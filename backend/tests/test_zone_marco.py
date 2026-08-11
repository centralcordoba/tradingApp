"""Tests del marco teórico de Zonas S/R (gates + confluencia → OPERAR/ESPERAR/NO_OPERAR).

Ejecutables con pytest o como script:
    cd backend && .venv/Scripts/python -m pytest tests/test_zone_marco.py -v
    cd backend && .venv/Scripts/python tests/test_zone_marco.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import zone_signal_engine as zse  # noqa: E402
from app.zone_signal_engine import generate_zone_marco  # noqa: E402


# ─── Factories ──────────────────────────────────────────────────────────────

def _level(price, kind, *, strength=5, touches=4, dist=5.0, wick_ratio=2.0,
           wick_dir="bull", active=True, within=True):
    return {
        "price": price,
        "type": kind,
        "strength": strength,
        "touches": touches,
        "distance_pips": dist,
        "within_range": within,
        "coherent_with_bias": True,
        "active": active,
        "last_touch_wick": (
            {"ratio": wick_ratio, "direction": wick_dir, "top": 0, "bottom": 0, "body": 0}
            if wick_ratio else None
        ),
    }


def _zone_item(*, pair="AUDUSD", price=0.71700, cross_state="A", market_closed=False,
               levels=None, atr_m15=0.0010, asia_range=None, vwap=None):
    if levels is None:
        levels = [
            _level(0.71650, "support"),       # mejor nivel LONG, 5 pips abajo
            _level(0.71900, "resistance", strength=4, dist=20.0, wick_ratio=0),  # objetivo TP
        ]
    return {
        "pair": pair,
        "price": price,
        "pip_size": 0.0001,
        "levels": levels,
        "market_closed": market_closed,
        "atr_m15": atr_m15,
        "cross": {"state": cross_state},
        "asia_range": asia_range,
        "vwap": vwap,
    }


def _scanner_item(*, side="LONG", confluence=5, extended="normal", rsi=40.0,
                  structure="HH", bloque="1", range_pos=0.3, struct_bullish=True,
                  change_pct=0.1):
    return {
        "side": side,
        "confluence": confluence,
        "extended_status": extended,
        "rsi": rsi,
        "structure": structure,
        "struct_bullish": struct_bullish,
        "bloque": bloque,
        "range_pos": range_pos,
        "change_pct": change_pct,
        "atr": 0.0009,
    }


def setup_function(_):
    # Hora Madrid fija (10h = London, AUDUSD en fire) para determinismo.
    zse._madrid_hour = lambda: 10  # type: ignore[assignment]
    zse._STRENGTH_STATE.clear()


# ─── Casos ──────────────────────────────────────────────────────────────────

def test_operar_tendencia_a_favor():
    m = generate_zone_marco(_zone_item(), _scanner_item())
    assert m["decision"] == "OPERAR"
    assert m["side"] == "LONG"
    assert m["confluence"]["score"] >= 10
    assert m["entry_price"] is not None and m["rrr"] is not None
    assert all(g["passed"] for g in m["gates"] if g["hard"])


def test_no_operar_conflicto_mtf():
    m = generate_zone_marco(_zone_item(cross_state="C"), _scanner_item())
    assert m["decision"] == "NO_OPERAR"
    mtf = next(g for g in m["gates"] if g["key"] == "mtf_coherente")
    assert mtf["passed"] is False


def test_no_operar_scanner_neutral():
    m = generate_zone_marco(_zone_item(cross_state="D"), _scanner_item(side="NEUTRAL"))
    assert m["decision"] == "NO_OPERAR"
    mtf = next(g for g in m["gates"] if g["key"] == "mtf_coherente")
    assert mtf["passed"] is False


def test_no_operar_precio_extendido():
    m = generate_zone_marco(_zone_item(), _scanner_item(extended="skip"))
    assert m["decision"] == "NO_OPERAR"
    ext = next(g for g in m["gates"] if g["key"] == "no_extendido")
    assert ext["passed"] is False


def test_no_operar_mercado_cerrado():
    m = generate_zone_marco(_zone_item(market_closed=True), _scanner_item())
    assert m["decision"] == "NO_OPERAR"
    assert next(g for g in m["gates"] if g["key"] == "mercado_abierto")["passed"] is False


def test_esperar_confluencia_floja():
    # Cross B (fade en rango) evita el veto de estructura; nivel/score mínimos.
    levels = [
        _level(0.71650, "support", strength=2, touches=1, wick_ratio=0),
        _level(0.71900, "resistance", strength=4, dist=20.0, wick_ratio=0),
    ]
    m = generate_zone_marco(
        _zone_item(cross_state="B", levels=levels),
        _scanner_item(confluence=3, rsi=50.0, structure="RANGE", bloque="3"),
    )
    assert m["decision"] == "ESPERAR"
    assert m["confluence"]["score"] < zse.PAIR_CONFIG["AUDUSD"]["min_score_normal"]


def test_noticia_degrada_operar_a_esperar():
    base = _zone_item()
    scan = _scanner_item()
    sin = generate_zone_marco(base, scan)
    assert sin["decision"] == "OPERAR"

    con = generate_zone_marco(
        base, scan,
        news_active=True,
        news_event={"title": "US NFP", "minutes_until": 12},
    )
    assert con["decision"] == "ESPERAR"
    assert con["news_warning"] is not None
    assert con["news_warning"]["title"] == "US NFP"
    # La noticia es gate blando: no aparece como fallo duro.
    noticia = next(g for g in con["gates"] if g["key"] == "noticia")
    assert noticia["hard"] is False and noticia["passed"] is False


def test_histeresis_strength_en_frontera():
    # AUDUSD: min_score_strong=10. Un score oscilando 10↔9 no debe hacer
    # flip-flop fuerte↔normal (re-dispararía la alerta sonora en cada poll):
    # una vez fuerte, se mantiene mientras score >= min_strong - 1.
    real = zse._score_signal
    scores = iter([10, 9, 8, 9])
    zse._score_signal = lambda **kw: (next(scores), [], [])  # type: ignore[assignment]
    try:
        args = (_zone_item(), _scanner_item())
        assert generate_zone_marco(*args)["strength"] == "fuerte"   # 10 → entra en fuerte
        assert generate_zone_marco(*args)["strength"] == "fuerte"   # 9 → histéresis: sigue fuerte
        assert generate_zone_marco(*args)["strength"] == "normal"   # 8 → pierde fuerte
        assert generate_zone_marco(*args)["strength"] == "normal"   # 9 sin estado previo → normal
    finally:
        zse._score_signal = real  # type: ignore[assignment]


def test_histeresis_se_resetea_con_gate_duro():
    real = zse._score_signal
    scores = iter([10, 9])
    zse._score_signal = lambda **kw: (next(scores), [], [])  # type: ignore[assignment]
    try:
        assert generate_zone_marco(_zone_item(), _scanner_item())["strength"] == "fuerte"
        # Un gate duro fallado (mercado cerrado) limpia el estado del par...
        m = generate_zone_marco(_zone_item(market_closed=True), _scanner_item())
        assert m["decision"] == "NO_OPERAR"
        # ...así que un 9 posterior ya no hereda el "fuerte".
        assert generate_zone_marco(_zone_item(), _scanner_item())["strength"] == "normal"
    finally:
        zse._score_signal = real  # type: ignore[assignment]


def test_bloque2_en_tendencia_ya_no_veta():
    # Cross A FAVOR + scanner Bloque 2: antes era veto duro (estructura_impulso);
    # ahora el gate pasa — la tendencia de 2 timeframes ya confirma.
    m = generate_zone_marco(_zone_item(), _scanner_item(bloque="2"))
    est = next(g for g in m["gates"] if g["key"] == "estructura_impulso")
    assert est["passed"] is True
    assert m["decision"] in ("OPERAR", "ESPERAR")


def test_nivel_operable_sin_flag_active():
    # Nivel de pullback en tendencia: active=False y fuera del rango de 12p viejo,
    # pero dentro de los 20p nuevos y con fuerza suficiente → ahora es operable.
    levels = [
        _level(0.71550, "support", strength=3, dist=15.0, active=False, within=False),
        _level(0.71900, "resistance", strength=4, dist=20.0, wick_ratio=0),
    ]
    m = generate_zone_marco(_zone_item(levels=levels), _scanner_item())
    nivel = next(g for g in m["gates"] if g["key"] == "nivel_operable")
    # El gate de nivel selecciona el soporte pese a active=False (antes lo excluía).
    assert nivel["passed"] is True
    assert "support 0.7155" in nivel["detail"]


def test_sesion_avoid_no_veta_usdcad():
    # USDCAD a las 10h Madrid (fuera de NY = sesión avoid). Antes era veto duro;
    # ahora la sesión solo puntúa: el gate pasa y es blando.
    m = generate_zone_marco(
        _zone_item(pair="USDCAD", price=1.36000,
                   levels=[_level(1.35950, "support", strength=3, wick_ratio=2.5),
                           _level(1.36300, "resistance", strength=4, dist=30.0, wick_ratio=0)]),
        _scanner_item(),
    )
    ses = next(g for g in m["gates"] if g["key"] == "sesion_operable")
    assert m["session_status"] == "avoid"     # 10h Madrid, fuera de NY
    assert ses["hard"] is False               # ya no es gate duro
    assert not (ses["hard"] and not ses["passed"])  # avoid ya no bloquea
    # La sesión avoid no aparece entre los gates duros que causarían NO_OPERAR.
    hard_blockers = [g["key"] for g in m["gates"] if g["hard"] and not g["passed"]]
    assert "sesion_operable" not in hard_blockers


def test_fade_exige_nivel_en_el_nivel():
    # Cross B: el nivel a 9p queda fuera del límite de fade (5p) aunque esté
    # dentro de los 20p generales — el patrón perdedor de ago-2026 era entrar
    # a media distancia persiguiendo el precio.
    levels = [
        _level(0.71610, "support", dist=9.0),
        _level(0.71900, "resistance", strength=4, dist=20.0, wick_ratio=0),
    ]
    m = generate_zone_marco(_zone_item(cross_state="B", levels=levels), _scanner_item())
    nivel = next(g for g in m["gates"] if g["key"] == "nivel_operable")
    assert nivel["passed"] is False
    assert "límite de fade" in nivel["detail"]
    assert m["decision"] == "NO_OPERAR"
    # El mismo nivel bajo cross A (tendencia) sí es operable (límite 20p).
    m2 = generate_zone_marco(_zone_item(cross_state="A", levels=levels), _scanner_item())
    nivel2 = next(g for g in m2["gates"] if g["key"] == "nivel_operable")
    assert nivel2["passed"] is True


def test_fade_veta_sweep_asiatico():
    # Réplica del trade LOSS del 11-ago: LONG en rango comprando exactamente
    # el high asiático recién barrido.
    asia = {"high": 0.71705, "low": 0.71400, "swept_high": True, "swept_low": False}
    m = generate_zone_marco(
        _zone_item(cross_state="B", asia_range=asia), _scanner_item())
    sweep = next(g for g in m["gates"] if g["key"] == "sweep_asiatico")
    assert sweep["passed"] is False
    assert m["decision"] == "NO_OPERAR"
    # En tendencia (cross A) romper el high asiático es continuación — no aplica.
    m2 = generate_zone_marco(
        _zone_item(cross_state="A", asia_range=asia), _scanner_item())
    assert next(g for g in m2["gates"] if g["key"] == "sweep_asiatico")["passed"] is True
    # Fade lejos del extremo barrido (>5p) tampoco veta.
    asia_far = {"high": 0.71800, "low": 0.71400, "swept_high": True, "swept_low": False}
    m3 = generate_zone_marco(
        _zone_item(cross_state="B", asia_range=asia_far), _scanner_item())
    assert next(g for g in m3["gates"] if g["key"] == "sweep_asiatico")["passed"] is True


def test_fade_veta_long_sobre_vwap():
    # Fade LONG con el precio SOBRE el VWAP de sesión = comprar caro contra la media.
    vwap_bajo = {"value": 0.71600, "upper": 0.71680, "lower": 0.71520,
                 "distance_pips": 10.0, "beyond_upper": True, "beyond_lower": False}
    m = generate_zone_marco(_zone_item(cross_state="B", vwap=vwap_bajo), _scanner_item())
    g = next(x for x in m["gates"] if x["key"] == "vwap_fade")
    assert g["passed"] is False
    assert m["decision"] == "NO_OPERAR"
    # Precio bajo el VWAP → fade LONG comprando barato: pasa.
    vwap_alto = {"value": 0.71800, "upper": 0.71880, "lower": 0.71720,
                 "distance_pips": -10.0, "beyond_upper": False, "beyond_lower": True}
    m2 = generate_zone_marco(_zone_item(cross_state="B", vwap=vwap_alto), _scanner_item())
    assert next(x for x in m2["gates"] if x["key"] == "vwap_fade")["passed"] is True
    # En tendencia no aplica (precio sobre VWAP es lo normal en un LONG de tendencia).
    m3 = generate_zone_marco(_zone_item(cross_state="A", vwap=vwap_bajo), _scanner_item())
    assert next(x for x in m3["gates"] if x["key"] == "vwap_fade")["passed"] is True


def test_sl_floor_extiende_sl_corto():
    # Entrada pegada al nivel: SL estructural de 3p (buffer mínimo) se extiende
    # al floor de 6p — con SL de 2-3p el spread domina (trade 06-ago, −32% extra).
    cfg = zse.PAIR_CONFIG["AUDUSD"]
    r = zse._calculate_sl_tp(
        pair="AUDUSD", pip_size=0.0001, scanner_side="LONG",
        entry_price=0.70346, best_level={"price": 0.70346},
        opposite_level=None, atr_m15=0.0003, cfg=cfg,
    )
    assert r["sl_floored"] is True
    assert r["risk_pips"] == 6.0
    assert r["sl_price"] == 0.70286  # entry − 6p


def test_rrr_neto_bloquea_trade_dominado_por_spread():
    # RRR bruto 2:1 con SL corto: el neto cae bajo 1.6 y el gate falla.
    cfg = {"sl_max_pips": 20.0, "sl_min_pips": 0.0, "cost_pips": 1.4}
    r = zse._calculate_sl_tp(
        pair="AUDUSD", pip_size=0.0001, scanner_side="LONG",
        entry_price=0.70330, best_level={"price": 0.70345},
        opposite_level={"price": 0.70370}, atr_m15=0.0002, cfg=cfg,
    )
    # risk = |0.70330 − (0.70345−0.0003)| = 1.5p · reward = 4p → bruto 2.67 pero
    # neto = (4−1.4)/(1.5+1.4) = 0.9 → bloqueado
    assert r["rrr"] is not None and r["rrr"] >= 2.0
    assert r["rrr_net"] is not None and r["rrr_net"] < zse.MIN_RRR_NET
    assert r["rrr_ok"] is False


def test_sesion_avoid_exige_fuerte():
    # 20h Madrid = AVOID para AUDUSD. Un OPERAR normal degrada a ESPERAR;
    # un OPERAR fuerte pasa.
    zse._madrid_hour = lambda: 20  # type: ignore[assignment]
    real = zse._score_signal
    try:
        zse._score_signal = lambda **kw: (8, [], [])  # type: ignore[assignment]
        m = generate_zone_marco(_zone_item(), _scanner_item())
        assert m["session_status"] == "avoid"
        assert m["decision"] == "ESPERAR"
        assert "AVOID" in m["reason"]

        zse._score_signal = lambda **kw: (10, [], [])  # type: ignore[assignment]
        m2 = generate_zone_marco(_zone_item(), _scanner_item())
        assert m2["decision"] == "OPERAR"
        assert m2["strength"] == "fuerte"
    finally:
        zse._score_signal = real  # type: ignore[assignment]


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        setup_function(fn)
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} tests passed")
