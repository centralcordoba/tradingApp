"""Suite del pipeline marco → orden (la cadena que estuvo 2 semanas en 0 trades).

Cubre los tres eslabones que fallaron en producción y todo lo que hay entre medio:
  - Frescura del dato: edad calculada desde el CIERRE de la vela con last_candle_ts
    (regresión del bug jul-2026: el data_age_minutes del backend mide desde la
    APERTURA y con umbral 10/18 descartaba el 100% de los OPERAR).
  - Semántica de transición + cooldown: un skip por dato viejo NO quema la señal.
  - Guardas de _execute: whitelist, ventana, posición abierta, sizing, FTMO.

Corre en frío: sin MT5 conectado, sin red, sin tocar bridge_state.json real.
    cd bridge && python -m pytest -q test_marco_pipeline.py
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import main
import trade_log

_REAL_REPORT = main._report_trade_open  # referencia antes de que el fixture lo stubbee


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def env(monkeypatch, tmp_path):
    """Bridge aislado: cfg de test, estado limpio, MT5 stubbeado, sin red ni disco real."""
    cfg = replace(
        main.cfg,
        dry_run=True,
        allowed_symbols=("AUDUSD", "USDCAD"),
        marco_min_strength="normal",
        zones_max_age_min=30.0,
        cooldown_min=15,
        risk_pct=0.5,
        max_trades_per_day=2,
        max_daily_loss_usd=2500.0,
        max_total_loss_usd=5000.0,
        initial_balance=50000.0,
        symbol_windows={"AUDUSD": (0, 24), "USDCAD": (0, 24)},
    )
    monkeypatch.setattr(main, "cfg", cfg)

    monkeypatch.setattr(main, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(main, "STOP_FILE", tmp_path / "STOP")
    monkeypatch.setattr(main, "_state", {
        "last_signal_id": None, "marco": {},
        "trades": {"date": "", "count": 0}, "open_map": {}, "managed": {},
    })
    monkeypatch.setattr(main, "_prev_strong", {})
    monkeypatch.setattr(main, "_stale_logged", {})

    executed = []
    reported = []
    monkeypatch.setattr(main, "_report_trade_open", reported.append)
    monkeypatch.setattr(trade_log, "log_open", executed.append)

    monkeypatch.setattr(main.mt5c, "our_positions", lambda s: 0)
    monkeypatch.setattr(main.mt5c, "symbol_specs",
                        lambda s: (1.0, 0.00001, 0.01, 100.0, 0.01))
    monkeypatch.setattr(main.mt5c, "equity", lambda: 50000.0)
    monkeypatch.setattr(main.mt5c, "current_price", lambda s, side: None)
    monkeypatch.setattr(main.mt5c, "pnl_today", lambda: 0.0)

    class Env:
        pass

    e = Env()
    e.cfg = cfg
    e.executed = executed          # filas CSV → una por orden colocada
    e.reported = reported          # POST /bridge/trades (best-effort)
    e.tmp = tmp_path
    e.monkeypatch = monkeypatch
    return e


def zone_item(pair="AUDUSD", decision="OPERAR", side="SHORT", strength="normal",
              closed_min_ago=5.0, data_age_minutes=None, with_last_ts=True,
              sl=0.65850, entry=0.65700, tp=0.65400):
    """Item de /api/zones con la forma real que emite zone_signal_engine."""
    now = datetime.now(timezone.utc)
    opened = now - timedelta(minutes=closed_min_ago + 15)  # ts de TD = APERTURA
    item = {
        "pair": pair,
        "price": entry,
        "cross": {"state": "A", "summary": "A FAVOR M30"},
        "data_age_minutes": (data_age_minutes if data_age_minutes is not None
                             else round(closed_min_ago + 15, 1)),
        "marco": {
            "decision": decision,
            "side": side,
            "strength": strength,
            "entry_price": entry,
            "sl_price": sl,
            "tp_price": tp,
            "tp1_price": round(2 * entry - sl, 5),
            "rrr": 2.0,
            "confluence": {"score": 12, "max": 18, "pct": 67},
            "level_used": {"price": 0.6580, "type": "resistance", "strength": 4,
                           "touches": 3, "distance_pips": 8.0},
            "session_status": "ok",
            "reason": "Setup normal SHORT — 12/18 de confluencia, gates superados.",
        },
    }
    if with_last_ts:
        item["last_candle_ts"] = opened.strftime("%Y-%m-%dT%H:%M:%SZ")
    return item


# ─── _zone_age_min: la edad se mide desde el CIERRE, con el reloj del bridge ─

def test_edad_desde_cierre_con_last_candle_ts(env):
    item = zone_item(closed_min_ago=5.0)
    age = main._zone_age_min(item)
    assert age == pytest.approx(5.0, abs=0.5)


def test_regresion_bug_data_age_desde_apertura(env):
    """El caso real medido en vivo el 29-jul: backend reporta 28.8 min (desde la
    APERTURA) pero la vela cerró hace 13.8. Con el umbral 18 de antes se descartaba;
    la edad real tiene que salir ~13.8 y pasar el umbral 30."""
    item = zone_item(closed_min_ago=13.8, data_age_minutes=28.8)
    age = main._zone_age_min(item)
    assert age == pytest.approx(13.8, abs=0.5)
    assert not main._stale_zone_data("AUDUSD", item)


def test_fallback_sin_last_candle_ts_resta_el_intervalo(env):
    item = zone_item(with_last_ts=False, data_age_minutes=28.8)
    assert main._zone_age_min(item) == pytest.approx(13.8, abs=0.01)


def test_ts_invalido_cae_al_fallback(env):
    item = zone_item(data_age_minutes=28.8)
    item["last_candle_ts"] = "no-es-una-fecha"
    assert main._zone_age_min(item) == pytest.approx(13.8, abs=0.01)


def test_sin_ninguna_edad_no_bloquea(env):
    item = zone_item(with_last_ts=False)
    item["data_age_minutes"] = None
    assert main._zone_age_min(item) is None
    assert not main._stale_zone_data("AUDUSD", item)


def test_dato_realmente_viejo_si_bloquea(env):
    item = zone_item(closed_min_ago=40.0)
    assert main._stale_zone_data("AUDUSD", item)


def test_log_de_stale_dedupea_por_racha(env, caplog):
    item = zone_item(closed_min_ago=40.0)
    with caplog.at_level("INFO", logger="bridge"):
        main._stale_zone_data("AUDUSD", item)
        main._stale_zone_data("AUDUSD", item)
        main._stale_zone_data("AUDUSD", item)
    assert sum("aplazado" in r.message for r in caplog.records) == 1
    # Al refrescarse el dato la racha se corta y un futuro stale vuelve a loguear
    main._stale_zone_data("AUDUSD", zone_item(closed_min_ago=5.0))
    with caplog.at_level("INFO", logger="bridge"):
        main._stale_zone_data("AUDUSD", item)
    assert sum("aplazado" in r.message for r in caplog.records) == 2


# ─── Pipeline completo: _process_zone_item → _execute (dry-run) ──────────────

def test_operar_fresco_ejecuta(env):
    main._process_zone_item(zone_item(), now=1000.0)
    assert len(env.executed) == 1
    row = env.executed[0]
    assert row["symbol"] == "AUDUSD" and row["side"] == "SHORT"
    assert row["sl_price"] == 0.65850 and row["tp1_price"] == pytest.approx(0.6555)
    assert row["lots"] == pytest.approx(1.66, abs=0.01)  # 0.5% de 50k / 15 pips
    assert main._state["trades"]["count"] == 1
    assert main._state["marco"]["AUDUSD"] == {"side": "SHORT", "at": 1000.0}
    assert len(env.reported) == 1 and env.reported[0]["dry_run"] is True


def test_tp1_se_recalcula_desde_el_fill(env):
    """TP1 = 1R desde el FILL real, no desde el entry teórico del marco (que es
    el precio de la última vela M15 cacheada y puede diferir varios pips)."""
    env.monkeypatch.setattr(main.mt5c, "current_price", lambda s, side: 0.65740)
    main._process_zone_item(zone_item(), now=1000.0)
    row = env.executed[0]
    # SHORT: fill 0.65740, SL 0.65850 → riesgo 0.0011 → TP1 = 0.65740 − 0.0011
    assert row["entry_price"] == pytest.approx(0.65740)
    assert row["tp1_price"] == pytest.approx(0.65630)


def test_stale_no_quema_la_senal_y_ejecuta_al_refrescar(env):
    """La propiedad clave del fix: OPERAR con dato viejo se APLAZA (no se registra
    la transición) y en cuanto el cache refresca, ese mismo OPERAR ejecuta."""
    main._process_zone_item(zone_item(closed_min_ago=40.0), now=1000.0)
    assert env.executed == []
    assert main._prev_strong.get("AUDUSD") is None      # transición intacta
    assert main._state["marco"] == {}                   # cooldown intacto
    main._process_zone_item(zone_item(closed_min_ago=3.0), now=1300.0)
    assert len(env.executed) == 1


def test_mismo_operar_sostenido_no_reentra(env):
    main._process_zone_item(zone_item(), now=1000.0)
    main._process_zone_item(zone_item(), now=1300.0)
    main._process_zone_item(zone_item(), now=1600.0)
    assert len(env.executed) == 1


def test_no_operar_y_esperar_no_ejecutan(env):
    main._process_zone_item(zone_item(decision="NO_OPERAR"), now=1000.0)
    main._process_zone_item(zone_item(decision="ESPERAR", strength=None), now=1300.0)
    assert env.executed == []


def test_barra_fuerte_exige_fuerte(env):
    env.monkeypatch.setattr(main, "cfg", replace(env.cfg, marco_min_strength="fuerte"))
    main._process_zone_item(zone_item(strength="normal"), now=1000.0)
    assert env.executed == []
    main._process_zone_item(zone_item(strength="fuerte"), now=1300.0)
    assert len(env.executed) == 1


def test_cooldown_mismo_lado_15min(env):
    main._process_zone_item(zone_item(), now=1000.0)
    # cae la señal y reaparece a los 5 min: cooldown
    main._process_zone_item(zone_item(decision="NO_OPERAR"), now=1150.0)
    main._process_zone_item(zone_item(), now=1300.0)
    assert len(env.executed) == 1
    # reaparece pasados los 15 min: ejecuta de nuevo
    main._process_zone_item(zone_item(decision="NO_OPERAR"), now=1500.0)
    main._process_zone_item(zone_item(), now=1000.0 + 16 * 60)
    assert len(env.executed) == 2


def test_flip_de_lado_no_tiene_cooldown(env):
    main._process_zone_item(zone_item(side="SHORT"), now=1000.0)
    main._process_zone_item(
        zone_item(side="LONG", sl=0.65550, entry=0.65700, tp=0.66000), now=1300.0)
    assert [r["side"] for r in env.executed] == ["SHORT", "LONG"]


def test_operar_sin_sl_no_crashea_ni_ejecuta(env):
    item = zone_item()
    item["marco"]["sl_price"] = None
    main._process_zone_item(item, now=1000.0)
    assert env.executed == []


def test_item_sin_marco_no_crashea(env):
    main._process_zone_item({"pair": "AUDUSD"}, now=1000.0)
    main._process_zone_item({"pair": "AUDUSD", "marco": None}, now=1000.0)
    assert env.executed == []


def test_payload_operar_al_arrancar_ejecuta_sin_baseline(env):
    """A diferencia de las alertas del frontend (baseline al montar), el bridge
    SÍ debe ejecutar un OPERAR ya activo en su primer poll tras arrancar."""
    assert main._prev_strong == {}
    main._process_zone_item(zone_item(), now=1000.0)
    assert len(env.executed) == 1


# ─── Guardas de _execute ─────────────────────────────────────────────────────

def test_fuera_de_whitelist_skip(env):
    main._process_zone_item(zone_item(pair="EURUSD"), now=1000.0)
    assert env.executed == []


def test_fuera_de_ventana_skip(env):
    env.cfg.symbol_windows["AUDUSD"] = (3, 3)  # ventana vacía: ninguna hora pasa
    main._process_zone_item(zone_item(), now=1000.0)
    assert env.executed == []


def test_posicion_ya_abierta_skip(env):
    env.monkeypatch.setattr(main.mt5c, "our_positions", lambda s: 1)
    main._process_zone_item(zone_item(), now=1000.0)
    assert env.executed == []


def test_limite_trades_diario(env):
    main._state["trades"] = {"date": datetime.now(main.MADRID).strftime("%Y-%m-%d"),
                             "count": 2}
    main._process_zone_item(zone_item(), now=1000.0)
    assert env.executed == []


def test_kill_switch_stop_file(env):
    main.STOP_FILE.write_text("")
    main._process_zone_item(zone_item(), now=1000.0)
    assert env.executed == []


def test_lote_minimo_excede_riesgo_skip(env):
    # vol_min 10 lots → 15 pips arriesgan 1500 USD > presupuesto 250 → no opera
    env.monkeypatch.setattr(main.mt5c, "symbol_specs",
                            lambda s: (1.0, 0.00001, 10.0, 100.0, 0.01))
    main._process_zone_item(zone_item(), now=1000.0)
    assert env.executed == []


def test_limite_diario_ftmo_peor_caso(env):
    # PnL de hoy -2300: el SL completo (-250) breachearía el límite diario de 2500
    env.monkeypatch.setattr(main.mt5c, "pnl_today", lambda: -2300.0)
    main._process_zone_item(zone_item(), now=1000.0)
    assert env.executed == []


def test_fallo_del_reporte_a_db_no_frena_la_orden(env):
    # Restaurar el _report_trade_open real (best-effort) y hacer fallar el POST
    env.monkeypatch.setattr(main, "_report_trade_open", _REAL_REPORT)

    def boom(*a, **k):
        raise RuntimeError("Render caido")
    env.monkeypatch.setattr(main, "_post_json", boom)
    main._process_zone_item(zone_item(), now=1000.0)
    assert len(env.executed) == 1


# ─── Geometría desde el FILL (fix 28-sep) ────────────────────────────────────
# El marco calcula SL/TP y valida RRR sobre su entry teórico (cierre de la última
# M15 cacheada); el fill llega hasta 30 min después. En vivo esto dio SL reales de
# 9.5-14.8p y RRR 1.43-2.79 con el log diciendo 2.00.

def test_continuation_desplaza_sl_tp_con_el_fill(env):
    item = zone_item()  # SHORT entry 0.65700, SL +15p, TP −30p
    item["marco"]["strategy"] = "continuation"
    env.monkeypatch.setattr(main.mt5c, "current_price", lambda s, side: 0.65730)
    main._process_zone_item(item, now=1000.0)
    row = env.executed[0]
    assert row["sl_price"] == pytest.approx(0.65880)
    assert row["tp_price"] == pytest.approx(0.65430)
    assert row["rrr"] == pytest.approx(2.0)


def test_reversion_no_desplaza_sl_estructural(env):
    # SHORT con fill 2p mejor: SL/TP anclados se mantienen, RRR = 32/13
    env.monkeypatch.setattr(main.mt5c, "current_price", lambda s, side: 0.65720)
    main._process_zone_item(zone_item(), now=1000.0)
    row = env.executed[0]
    assert row["sl_price"] == 0.65850 and row["tp_price"] == 0.65400
    assert row["rrr"] == pytest.approx(2.46, abs=0.01)


def test_rrr_real_bajo_minimo_no_ejecuta(env):
    # SHORT: el precio ya bajó 5p hacia el TP → riesgo 20p, beneficio 25p → 1.25
    env.monkeypatch.setattr(main.mt5c, "current_price", lambda s, side: 0.65650)
    main._process_zone_item(zone_item(), now=1000.0)
    assert env.executed == []


def test_rrr_neto_real_bajo_minimo_no_ejecuta(env):
    item = zone_item()
    item["marco"]["cost_pips"] = 4.0  # (30−4)/(15+4) = 1.37 < 1.6
    main._process_zone_item(item, now=1000.0)
    assert env.executed == []


def test_precio_ya_supero_el_sl_no_ejecuta(env):
    env.monkeypatch.setattr(main.mt5c, "current_price", lambda s, side: 0.65900)
    main._process_zone_item(zone_item(), now=1000.0)
    assert env.executed == []


# ─── Reporter: cierre por ticket, sin ventana de 7 días (fix 28-sep) ────────

class _Deal:
    def __init__(self, price, profit, commission=0.0, swap=0.0):
        self.price, self.profit, self.commission, self.swap = price, profit, commission, swap


@pytest.fixture
def rep(env):
    posts, closes = [], []
    env.monkeypatch.setattr(main, "_post_json", lambda path, body: posts.append((path, body)))
    env.monkeypatch.setattr(trade_log, "log_close", lambda *a: closes.append(a))
    env.monkeypatch.setattr(main, "_unresolved_logged", set())
    env.monkeypatch.setattr(main.mt5c, "account_login", lambda: 111)
    env.monkeypatch.setattr(main.mt5c, "position_by_ticket", lambda t: None)
    env.posts, env.closes = posts, closes
    return env


def test_reporter_cierra_por_ticket_y_suma_comision_de_entrada(rep):
    main._state["open_map"] = {"538310180": None}
    main._state["open_accounts"] = {"538310180": 111}
    rep.monkeypatch.setattr(main.mt5c, "closed_position_deals",
                            lambda t: [_Deal(0.72252, 0.0, -3.3), _Deal(0.71987, 352.45, -3.3)])
    main._report_closes()
    path, body = rep.posts[0]
    assert path == "/bridge/trades/538310180/close"
    assert body == {"result": "WIN", "exit_price": 0.71987, "pnl_usd": 345.85}
    assert main._state["open_map"] == {} and main._state["open_accounts"] == {}


def test_reporter_posicion_de_otra_cuenta_queda_pendiente(rep):
    main._state["open_map"] = {"539445240": None}
    main._state["open_accounts"] = {"539445240": 999}
    rep.monkeypatch.setattr(main.mt5c, "closed_position_deals",
                            lambda t: pytest.fail("no debe consultar otra cuenta"))
    main._report_closes()
    assert rep.posts == [] and "539445240" in main._state["open_map"]


def test_reporter_sin_historial_no_descarta_y_loguea_una_vez(rep, caplog):
    main._state["open_map"] = {"1": None}
    rep.monkeypatch.setattr(main.mt5c, "closed_position_deals", lambda t: [])
    with caplog.at_level("WARNING", logger="bridge"):
        main._report_closes()
        main._report_closes()
    assert rep.posts == [] and "1" in main._state["open_map"]
    assert sum("queda pendiente" in r.message for r in caplog.records) == 1


def test_reporter_posicion_abierta_no_se_cierra(rep):
    main._state["open_map"] = {"2": None}
    rep.monkeypatch.setattr(main.mt5c, "position_by_ticket", lambda t: object())
    rep.monkeypatch.setattr(main.mt5c, "closed_position_deals",
                            lambda t: pytest.fail("no debe buscar cierre de una abierta"))
    main._report_closes()
    assert rep.posts == []
