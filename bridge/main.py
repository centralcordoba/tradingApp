"""Bridge señales → MT5 (FTMO).

Ejecuta en el terminal MT5 local las decisiones del backend:
  - Señales del Pine con decision ENTER (SSE /signals/stream + catch-up por id)
  - Marco de Zonas S/R en OPERAR + fuerte (poll /api/zones cada 5 min)
y reporta los cierres a POST /signals/{id}/result (auto-resolución W/L/BE).

DRY_RUN=1 (default): registra lo que habría ejecutado, no envía órdenes.
Kill switch: crear el archivo bridge/STOP bloquea nuevas órdenes al instante
(no toca las posiciones ya abiertas).

Uso:  cd bridge && python main.py
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from config import Config
from mt5_client import Mt5Client
from risk import classify_result, guard_reason, in_window, lots_for_risk

BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "bridge_state.json"
STOP_FILE = BASE_DIR / "STOP"
MADRID = ZoneInfo("Europe/Madrid")

log = logging.getLogger("bridge")
cfg = Config()
mt5c = Mt5Client(cfg)

_state_lock = threading.Lock()
_state: dict = {
    "last_signal_id": None,          # baseline: nunca ejecutar señales históricas
    "marco": {},                     # pair → {"side": .., "at": epoch} (cooldown)
    "trades": {"date": "", "count": 0},
    "open_map": {},                  # position_ticket → signal_id (para reportar cierre)
}
_prev_strong: dict = {}              # pair → side|None (transiciones del marco, en memoria)


# ─── Estado persistido ──────────────────────────────────────────────────────

def _load_state():
    global _state
    try:
        _state.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def _save_state():
    with _state_lock:
        STATE_FILE.write_text(json.dumps(_state, indent=2), encoding="utf-8")


def _trades_today() -> int:
    today = datetime.now(MADRID).strftime("%Y-%m-%d")
    if _state["trades"].get("date") != today:
        _state["trades"] = {"date": today, "count": 0}
    return _state["trades"]["count"]


def _bump_trades():
    _trades_today()  # asegura reset de fecha
    _state["trades"]["count"] += 1
    _save_state()


# ─── HTTP hacia el backend ──────────────────────────────────────────────────

def _get_json(path: str, timeout: float = 30) -> dict:
    req = urllib.request.Request(cfg.api_base + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(path: str, body: dict, timeout: float = 30) -> dict:
    if cfg.api_token:
        path += ("&" if "?" in path else "?") + "token=" + cfg.api_token
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(cfg.api_base + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _report_trade_open(trade: dict):
    """Registra la apertura (o simulación) en la DB del backend. Best-effort:
    un fallo aquí nunca debe frenar la operativa."""
    try:
        _post_json("/bridge/trades", trade)
    except Exception as e:
        log.warning("No se pudo registrar el trade en DB (%s) — sigue en bridge.log", e)


# ─── Ejecución con guardas ──────────────────────────────────────────────────

def _execute(symbol: str, side: str, sl: float, tp, comment: str,
             signal_id, source: str, entry_hint: float,
             context: dict | None = None, rrr=None):
    """Todas las guardas + sizing + orden (o log en DRY_RUN)."""
    if symbol not in cfg.allowed_symbols:
        log.info("[%s] %s fuera de whitelist — skip", source, symbol)
        return
    hour = datetime.now(MADRID).hour
    if not in_window(hour, cfg.symbol_windows.get(symbol)):
        log.info("[%s] %s %s fuera de ventana (hora Madrid %d) — skip", source, symbol, side, hour)
        return
    broker_symbol = symbol + cfg.symbol_suffix
    if mt5c.our_positions(broker_symbol) > 0:
        log.info("[%s] ya hay posicion nuestra en %s — skip", source, symbol)
        return

    specs = mt5c.symbol_specs(broker_symbol)
    if specs is None:
        log.warning("[%s] sin especificaciones para %s — skip", source, broker_symbol)
        return
    tick_value, tick_size, vol_min, vol_max, vol_step = specs

    equity = mt5c.equity() or cfg.initial_balance
    price = mt5c.current_price(broker_symbol, side) or entry_hint
    sl_distance = abs(price - sl)
    lots = lots_for_risk(equity, cfg.risk_pct, sl_distance,
                         tick_value, tick_size, vol_min, vol_max, vol_step)
    if lots <= 0:
        log.info("[%s] %s: el lote minimo del broker excede el presupuesto de riesgo "
                 "(SL a %.5f de %.5f) — skip", source, symbol, sl, price)
        return
    risk_usd = equity * cfg.risk_pct / 100.0

    reason = guard_reason(
        kill_switch=STOP_FILE.exists(),
        trades_today=_trades_today(), max_trades=cfg.max_trades_per_day,
        pnl_today_usd=mt5c.pnl_today(), next_trade_risk_usd=risk_usd,
        max_daily_loss=cfg.max_daily_loss_usd,
        drawdown_total_usd=max(0.0, cfg.initial_balance - equity),
        max_total_loss=cfg.max_total_loss_usd,
    )
    if reason:
        log.warning("[%s] %s %s BLOQUEADO: %s", source, symbol, side, reason)
        return

    desc = (f"{side} {symbol} {lots:.2f} lots @ ~{price:.5f} SL {sl:.5f}"
            + (f" TP {tp:.5f}" if tp else " sin TP")
            + f" (riesgo ~{risk_usd:.0f} USD, {source})")
    trade_record = {
        "symbol": symbol, "side": side, "source": source, "lots": lots,
        "entry_price": price, "sl_price": sl, "tp_price": tp,
        "risk_usd": round(risk_usd, 2), "rrr": rrr, "signal_id": signal_id,
        "dry_run": cfg.dry_run, "context": context,
    }
    if cfg.dry_run:
        log.info("[DRY-RUN] %s", desc)
        _bump_trades()  # simular también el contador diario
        _report_trade_open(trade_record)
        return

    ok, detail, ticket = mt5c.market_order(broker_symbol, side, lots, sl, tp, comment)
    if ok:
        log.info("EJECUTADO %s — %s", desc, detail)
        _bump_trades()
        if ticket is not None:
            # signal_id puede ser None (trades del marco): el reporter cierra
            # el registro en bridge_trades igualmente vía el ticket.
            _state["open_map"][str(ticket)] = signal_id
            _save_state()
            trade_record["mt5_ticket"] = str(ticket)
        _report_trade_open(trade_record)
    else:
        log.error("FALLO al ejecutar %s — %s", desc, detail)


# ─── Fuente A: señales del Pine (SSE + catch-up) ────────────────────────────

def _process_new_signals():
    data = _get_json("/signals?limit=10")
    items = sorted(data.get("items", []), key=lambda s: s["id"])
    for s in items:
        last = _state["last_signal_id"]
        if last is not None and s["id"] <= last:
            continue
        _state["last_signal_id"] = s["id"]
        _save_state()
        _handle_pine_signal(s)


def _handle_pine_signal(s: dict):
    resp = s.get("response") or {}
    sig = s.get("signal") or {}
    decision = resp.get("decision")
    symbol = str(sig.get("symbol", "")).upper()
    if decision != "ENTER":
        log.info("[pine] senal %s %s decision=%s — no se ejecuta", s["id"], symbol, decision)
        return
    # Staleness local: protege contra catch-up tras un rato caído
    try:
        received = datetime.fromisoformat(str(s["received_at"]).replace("Z", "+00:00"))
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        age_min = (datetime.now(timezone.utc) - received).total_seconds() / 60
    except (KeyError, ValueError):
        age_min = None
    if age_min is not None and age_min > cfg.signal_max_age_min:
        log.info("[pine] senal %s con %.1f min de edad — skip (catch-up)", s["id"], age_min)
        return

    side = "LONG" if sig.get("signal") in ("LONG", "BUY") else "SHORT"
    sl = resp.get("stop_loss")
    tps = resp.get("take_profit") or []
    tp = tps[-1] if tps else None
    if sl is None:
        log.warning("[pine] senal %s sin stop_loss — skip", s["id"])
        return
    context = {
        "score": resp.get("score"), "quality": sig.get("quality"),
        "conf": sig.get("conf"), "kz": sig.get("kz"),
        "plan": (resp.get("plan") or {}).get("trigger_type"),
    }
    _execute(symbol, side, float(sl), float(tp) if tp is not None else None,
             comment=f"sig:{s['id']}", signal_id=s["id"], source="pine",
             entry_hint=float(sig.get("price", 0.0)), context=context)


def _sse_loop():
    url = cfg.api_base + "/signals/stream"
    warned_missing = False
    while True:
        retry_sec = 10
        try:
            req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                log.info("SSE conectado a %s", url)
                warned_missing = False
                event = ""
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if line.startswith("event:"):
                        event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:") and event == "signal":
                        event = ""
                        try:
                            _process_new_signals()
                        except Exception as e:
                            log.warning("procesando senales: %s", e)
        except urllib.error.HTTPError as e:
            if e.code in (404, 405):
                # El backend desplegado no tiene la ruta SSE (deploy viejo):
                # degradar a polling de 30s sin spamear el log.
                retry_sec = 30
                if not warned_missing:
                    log.warning("SSE no disponible en el backend (%s) — polling cada 30s", e)
                    warned_missing = True
            else:
                log.warning("SSE caido (%s) — reintento en 10s", e)
        except Exception as e:
            log.warning("SSE caido (%s) — reintento en 10s", e)
        try:
            _process_new_signals()  # catch-up / fallback de polling
        except Exception:
            pass
        time.sleep(retry_sec)


# ─── Fuente B: marco de Zonas S/R (OPERAR fuerte) ───────────────────────────

def _zones_loop():
    while True:
        try:
            data = _get_json("/api/zones", timeout=60)
            now = time.time()
            for item in data.get("items", []):
                pair = str(item.get("pair", "")).upper()
                marco = item.get("marco") or {}
                # "normal" acepta cualquier OPERAR; "fuerte" exige strength fuerte.
                strength_ok = (
                    marco.get("strength") == "fuerte"
                    if cfg.marco_min_strength == "fuerte" else True
                )
                operable = (marco.get("decision") == "OPERAR"
                            and strength_ok
                            and marco.get("side") in ("LONG", "SHORT"))
                cur = marco.get("side") if operable else None
                last = _prev_strong.get(pair)
                _prev_strong[pair] = cur
                if not cur or cur == last:
                    continue  # solo transiciones (misma semántica que las alertas del frontend)
                seen = _state["marco"].get(pair) or {}
                if seen.get("side") == cur and now - seen.get("at", 0) < cfg.cooldown_min * 60:
                    log.info("[marco] %s %s en cooldown — skip", pair, cur)
                    continue
                _state["marco"][pair] = {"side": cur, "at": now}
                _save_state()
                _handle_marco(pair, item, marco)
        except Exception as e:
            log.warning("zones poll: %s", e)
        time.sleep(cfg.zones_poll_sec)


def _handle_marco(pair: str, item: dict, marco: dict):
    age = item.get("data_age_minutes")
    if age is not None and age > cfg.zones_max_age_min:
        log.info("[marco] %s con dato de %.1f min — skip (viejo)", pair, age)
        return
    sl = marco.get("sl_price")
    entry = marco.get("entry_price") or item.get("price")
    if sl is None or entry is None:
        log.warning("[marco] %s sin sl_price/entry_price — skip", pair)
        return
    tp = marco.get("tp_price")
    confluence = marco.get("confluence") or {}
    context = {
        "score": confluence.get("score"), "score_max": confluence.get("max"),
        "level_used": marco.get("level_used"),
        "session_status": marco.get("session_status"),
        "cross_state": (item.get("cross") or {}).get("state"),
        "reason": marco.get("reason"),
    }
    _execute(pair, marco["side"], float(sl), float(tp) if tp is not None else None,
             comment=f"marco:{pair}", signal_id=None, source="marco",
             entry_hint=float(entry), context=context, rrr=marco.get("rrr"))


# ─── Auto-resolución: cierres MT5 → /signals/{id}/result ────────────────────

def _reporter_loop():
    while True:
        time.sleep(cfg.reporter_poll_sec)
        if not mt5c.connected or not _state["open_map"]:
            continue
        try:
            since = datetime.now(timezone.utc) - timedelta(days=7)
            for d in mt5c.closed_deals_since(since):
                ticket = str(d.position_id)
                if ticket not in _state["open_map"]:
                    continue
                sid = _state["open_map"][ticket]  # None en trades del marco
                profit = d.profit + d.swap + d.commission
                result = classify_result(profit, cfg.be_threshold_usd)
                try:
                    _post_json(f"/bridge/trades/{ticket}/close",
                               {"result": result, "exit_price": d.price,
                                "pnl_usd": round(profit, 2)})
                except urllib.error.HTTPError as e:
                    if e.code != 404:  # 404 = fila inexistente; no reintentar para siempre
                        log.warning("POST close trade %s fallo: %s", ticket, e)
                        continue
                    log.warning("Trade %s sin fila en bridge_trades (404) — se descarta", ticket)
                if sid is not None:
                    try:
                        _post_json(f"/signals/{sid}/result",
                                   {"result": result, "exit_price": d.price})
                    except urllib.error.HTTPError as e:
                        log.warning("POST result senal %s fallo: %s", sid, e)
                        continue
                del _state["open_map"][ticket]
                _save_state()
                log.info("Cierre reportado: ticket %s → %s (%.2f USD)", ticket, result, profit)
        except Exception as e:
            log.warning("reporter: %s", e)


# ─── Arranque ───────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[logging.StreamHandler(),
                  logging.FileHandler(BASE_DIR / "bridge.log", encoding="utf-8")],
    )
    log.info("=" * 60)
    log.info("Bridge MT5 — DRY_RUN=%s  API=%s", cfg.dry_run, cfg.api_base)
    log.info("Riesgo: %.2f%%/trade, max %d trades/dia, limite diario %.0f USD, total %.0f USD",
             cfg.risk_pct, cfg.max_trades_per_day, cfg.max_daily_loss_usd, cfg.max_total_loss_usd)
    log.info("Simbolos: %s  Ventanas Madrid: %s", cfg.allowed_symbols, cfg.symbol_windows)
    if not cfg.dry_run:
        log.warning(">>> EJECUCION REAL ACTIVA <<<")

    _load_state()
    connected = mt5c.connect()
    if not connected and not cfg.dry_run:
        log.error("Sin conexion MT5 y DRY_RUN=0 — abortando por seguridad")
        return

    # Baseline: en el primer arranque no ejecutar nada histórico
    if _state["last_signal_id"] is None:
        try:
            data = _get_json("/signals?limit=1")
            items = data.get("items", [])
            _state["last_signal_id"] = items[0]["id"] if items else 0
            _save_state()
            log.info("Baseline de senales: id %s", _state["last_signal_id"])
        except Exception as e:
            log.error("No se pudo establecer baseline (%s) — abortando", e)
            return

    for target in (_sse_loop, _zones_loop, _reporter_loop):
        threading.Thread(target=target, daemon=True, name=target.__name__).start()

    try:
        while True:
            time.sleep(1800)
            log.info("heartbeat — trades hoy: %d, posiciones mapeadas: %d%s",
                     _trades_today(), len(_state["open_map"]),
                     " [STOP activo]" if STOP_FILE.exists() else "")
    except KeyboardInterrupt:
        log.info("Parando bridge (las posiciones abiertas no se tocan)")
    finally:
        mt5c.shutdown()


if __name__ == "__main__":
    main()
