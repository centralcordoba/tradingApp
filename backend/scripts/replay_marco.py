"""Replay histórico del marco de Zonas S/R (AUDUSD/USDCAD) sobre OHLC de Twelve Data.

Corre el MISMO pipeline que /api/zones en vivo (analyze_zones → cross_verdict →
scanner M5 → generate_zone_marco) barra por barra sobre historia real, inyectando
los slices OHLC en scanner._ohlc_cache (el motor lee esa caché antes de la red).
Para cada decisión OPERAR, resuelve WIN/LOSS caminando el precio M5 hacia adelante
(qué toca primero: TP o SL). Reporta oportunidades, win-rate y expectancy en R.

Uso (desde backend/, con TWELVEDATA_API_KEY en backend/.env):
    python -m scripts.replay_marco
    python -m scripts.replay_marco --days 7 --pairs AUDUSD,USDCAD

NOTA: noticias = gate blando desactivado en el replay (no hay histórico de FF).
El madrid_hour se parchea al timestamp de la barra para fidelidad de la sesión.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    _MADRID = ZoneInfo("Europe/Madrid")
except Exception:
    _MADRID = None

# ── .env → os.environ ANTES de importar app (scanner captura la key al import) ──
_ENV = Path(__file__).resolve().parent.parent / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # consola Windows (cp1252) no traga ═ ⚠ ✓ — forzar UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import urllib.parse
import urllib.request
import json

from app import scanner, zones, cross_verdict, zone_signal_engine  # noqa: E402
from app.constants import ZONES_OUTPUTSIZE  # 600 M15  # noqa: E402

# Por si el import capturó "" antes de cargar .env
scanner.TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY", scanner.TWELVEDATA_API_KEY)

M15_KEY = "15min"
M5_KEY = "5min"
SCANNER_M5_OUTPUT = 200
COOLDOWN_MIN = 15          # mismo cooldown que el bridge/frontend (dedup de entradas)
WALKFWD_M5_BARS = 96       # 8 h de horizonte para resolver TP/SL


# ─────────────────────────────────────────────────────────────────────────────
# Fetch histórico (una vez por par/intervalo)
# ─────────────────────────────────────────────────────────────────────────────
_CACHE_DIR = Path(os.environ.get("TEMP", ".")) / "replay_cache"


def _fetch_td(pair: str, interval: str, outputsize: int, use_cache: bool = True) -> list[dict]:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cf = _CACHE_DIR / f"{pair}_{interval}_{outputsize}.json"
    if use_cache and cf.exists():
        return json.loads(cf.read_text(encoding="utf-8"))
    params = {
        "symbol": scanner._td_symbol(pair),
        "interval": interval,
        "outputsize": str(outputsize),
        "order": "ASC",
        "timezone": "UTC",   # igual que prod (sin esto TD devuelve ~UTC+10)
        "apikey": scanner.TWELVEDATA_API_KEY,
    }
    url = f"{scanner.TWELVEDATA_BASE}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    if isinstance(data, dict) and data.get("status") == "error":
        raise RuntimeError(f"TD error {pair} {interval}: {data.get('message')}")
    vals = data.get("values") or []
    cf.write_text(json.dumps(vals), encoding="utf-8")
    return vals


def _parse_dt(s: str) -> datetime:
    # TD: "2026-07-22 21:45:00" (naive) — se trata como UTC
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _madrid_hour_of(dt: datetime) -> int:
    if _MADRID is None:
        return dt.hour
    return dt.astimezone(_MADRID).hour


# ─────────────────────────────────────────────────────────────────────────────
# Un paso del replay: inyecta slices, corre el pipeline real, devuelve marco
# ─────────────────────────────────────────────────────────────────────────────
def _inject(pair: str, m15_slice: list[dict], m5_slice: list[dict]):
    now = time.time()
    # sin "meta" → _parse_ohlc no aplica la exclusión de vela en formación
    scanner._ohlc_cache[f"{pair}:{M15_KEY}:{ZONES_OUTPUTSIZE}"] = (now, {"values": m15_slice, "status": "ok"})
    scanner._ohlc_cache[f"{pair}:{M5_KEY}:{SCANNER_M5_OUTPUT}"] = (now, {"values": m5_slice, "status": "ok"})
    # limpia cachés SCORED (si no, devuelven el resultado de la barra anterior)
    scanner._cache.clear()
    zones._zones_cache.clear()


def _run_marco(pair: str, t_close: datetime) -> dict:
    # parcha la hora Madrid al timestamp de la barra (sesión = gate blando pero puntúa)
    zone_signal_engine._madrid_hour = lambda: _madrid_hour_of(t_close)

    params: dict = {}
    zres = zones.get_zones_response([pair], params)
    items = zres.get("items", [])
    if not items:
        return {"decision": "NO_DATA"}
    it = items[0]
    # La barra ES el presente durante su evaluación: analyze_zones marca
    # market_closed comparando la última vela contra el reloj real (now), lo que
    # en un replay siempre daría "mercado cerrado". Se neutraliza.
    it["market_closed"] = False
    it["data_age_minutes"] = 0.0
    cross = cross_verdict.build_cross_map([pair], zones_params=params)
    it["cross"] = cross.get(pair)
    scan_map = {x["pair"]: x for x in scanner.scan_pairs([pair])}
    marco = zone_signal_engine.generate_zone_marco(
        it, scan_map.get(pair), news_active=False,
    )
    marco["_cross"] = (it.get("cross") or {}).get("label", "?")
    marco["_atr_m15"] = it.get("atr_m15")
    return marco


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward: resuelve TP/SL sobre M5 desde la vela siguiente a la señal
# ─────────────────────────────────────────────────────────────────────────────
def _resolve(side: str, entry: float, sl: float, tp: float,
             m5: list[dict], start_idx: int) -> dict:
    """Devuelve {result, R, mfe_R, mae_R}. SL prioritario si una vela cruza ambos.
    mfe_R = máxima excursión FAVORABLE en R (cuánto se acercó al TP);
    mae_R = máxima excursión ADVERSA en R (cuánto se acercó al SL)."""
    risk = abs(entry - sl)
    if risk <= 0 or tp is None:
        return {"result": "OPEN", "R": 0.0, "mfe_R": 0.0, "mae_R": 0.0}
    rr = abs(tp - entry) / risk
    end = min(len(m5), start_idx + WALKFWD_M5_BARS)
    mfe = mae = 0.0
    for j in range(start_idx, end):
        hi = float(m5[j]["high"]); lo = float(m5[j]["low"])
        if side == "LONG":
            mfe = max(mfe, (hi - entry) / risk)
            mae = max(mae, (entry - lo) / risk)
            if lo <= sl:   return {"result": "LOSS", "R": -1.0, "mfe_R": mfe, "mae_R": mae}
            if hi >= tp:   return {"result": "WIN", "R": rr, "mfe_R": mfe, "mae_R": mae}
        else:
            mfe = max(mfe, (entry - lo) / risk)
            mae = max(mae, (hi - entry) / risk)
            if hi >= sl:   return {"result": "LOSS", "R": -1.0, "mfe_R": mfe, "mae_R": mae}
            if lo <= tp:   return {"result": "WIN", "R": rr, "mfe_R": mfe, "mae_R": mae}
    return {"result": "OPEN", "R": 0.0, "mfe_R": mfe, "mae_R": mae}


# ─────────────────────────────────────────────────────────────────────────────
# A/B de reglas de salida sobre las MISMAS entradas (ordenado barra a barra)
# ─────────────────────────────────────────────────────────────────────────────
EXIT_RULES = [
    ("nivel (actual)",   {"kind": "level"}),
    ("TP 1R",            {"kind": "R", "r": 1.0}),
    ("TP 1.5R",          {"kind": "R", "r": 1.5}),
    ("BE@1R · TP 1.5R",  {"kind": "be_runner", "arm": 1.0, "tp": 1.5}),
    ("BE@1R · TP 2R",    {"kind": "be_runner", "arm": 1.0, "tp": 2.0}),
]


def _simulate(side: str, entry: float, sl0: float, tp_level, m5: list[dict],
              start_idx: int, rule: dict) -> tuple[str, float]:
    """(result, R) de una entrada bajo una regla de salida. SL prioritario en
    cruce del mismo bar; en be_runner el SL sube a BE una vez armado."""
    risk = abs(entry - sl0)
    if risk <= 0:
        return "OPEN", 0.0
    kind = rule["kind"]
    if kind == "level":
        tp = tp_level
    elif kind == "R":
        tp = entry + rule["r"] * risk if side == "LONG" else entry - rule["r"] * risk
    else:  # be_runner
        tp = entry + rule["tp"] * risk if side == "LONG" else entry - rule["tp"] * risk
    if tp is None:
        return "OPEN", 0.0
    sl = sl0
    armed = False
    end = min(len(m5), start_idx + WALKFWD_M5_BARS)
    for j in range(start_idx, end):
        hi = float(m5[j]["high"]); lo = float(m5[j]["low"])
        if side == "LONG":
            if kind == "be_runner" and not armed and hi >= entry + rule["arm"] * risk:
                armed = True; sl = entry
            if lo <= sl:
                return ("BE", 0.0) if (armed and sl == entry) else ("LOSS", -1.0)
            if hi >= tp:
                return "WIN", (tp - entry) / risk
        else:
            if kind == "be_runner" and not armed and lo <= entry - rule["arm"] * risk:
                armed = True; sl = entry
            if hi >= sl:
                return ("BE", 0.0) if (armed and sl == entry) else ("LOSS", -1.0)
            if lo <= tp:
                return "WIN", (entry - tp) / risk
    return "OPEN", 0.0


def _ab_exit_rules(entries: list[dict], m5: list[dict]) -> dict:
    out = {}
    for name, rule in EXIT_RULES:
        W = L = BE = O = 0; sumR = 0.0
        for e in entries:
            res, R = _simulate(e["side"], e["entry"], e["sl"], e["tp"], m5, e["start_idx"], rule)
            sumR += R
            W += res == "WIN"; L += res == "LOSS"; BE += res == "BE"; O += res == "OPEN"
        out[name] = {"W": W, "L": L, "BE": BE, "O": O, "sumR": sumR}
    return out


# ─────────────────────────────────────────────────────────────────────────────
# A/B de ENTRADA: a mercado vs límite en el nivel (pullback), ambas con TP 1R
# ─────────────────────────────────────────────────────────────────────────────
def _simulate_limit(side: str, level, atr, sl_struct: float, m5: list[dict],
                    start_idx: int, tp_r: float = 1.0,
                    buffer_atr: float = 0.10, fill_window: int = 24) -> tuple[str, float]:
    """Entrada LÍMITE en el nivel (± buffer·ATR) esperando el pullback. NOFILL si
    el precio no vuelve al nivel en `fill_window` velas M5. SL estructural (no se
    mueve). TP a tp_r·riesgo. SL prioritario en cruce del mismo bar."""
    if level is None or not atr:
        return "NODATA", 0.0
    buf = buffer_atr * atr
    limit = level + buf if side == "LONG" else level - buf
    if side == "LONG" and not sl_struct < limit:
        return "BADSL", 0.0
    if side == "SHORT" and not sl_struct > limit:
        return "BADSL", 0.0
    fill = None
    fend = min(len(m5), start_idx + fill_window)
    for j in range(start_idx, fend):
        hi = float(m5[j]["high"]); lo = float(m5[j]["low"])
        if side == "LONG" and lo <= limit:
            fill = j; break
        if side == "SHORT" and hi >= limit:
            fill = j; break
    if fill is None:
        return "NOFILL", 0.0
    entry = limit
    risk = abs(entry - sl_struct)
    if risk <= 0:
        return "NOFILL", 0.0
    tp = entry + tp_r * risk if side == "LONG" else entry - tp_r * risk
    end = min(len(m5), fill + WALKFWD_M5_BARS)
    for j in range(fill, end):
        hi = float(m5[j]["high"]); lo = float(m5[j]["low"])
        if side == "LONG":
            if lo <= sl_struct: return "LOSS", -1.0
            if hi >= tp:        return "WIN", tp_r
        else:
            if hi >= sl_struct: return "LOSS", -1.0
            if lo <= tp:        return "WIN", tp_r
    return "OPEN", 0.0


def _ab_entry(entries: list[dict], m5: list[dict], tp_r: float = 1.0) -> dict:
    def blank():
        return {"W": 0, "L": 0, "O": 0, "NF": 0, "sumR": 0.0}

    def cat(e):
        c = e.get("cross") or ""
        return "favor" if "FAVOR" in c else ("fade" if "FADE" in c else "otros")

    out = {"market": {"all": blank(), "favor": blank(), "fade": blank()},
           "limit":  {"all": blank(), "favor": blank(), "fade": blank()}}
    for e in entries:
        c = cat(e)
        # mercado + TP1R
        rm, Rm = _simulate(e["side"], e["entry"], e["sl"], e["tp"], m5, e["start_idx"],
                           {"kind": "R", "r": tp_r})
        # límite en el nivel + TP1R
        rl, Rl = _simulate_limit(e["side"], e["level"], e["atr"], e["sl"], m5,
                                 e["start_idx"], tp_r)
        for tag, r, R in (("market", rm, Rm), ("limit", rl, Rl)):
            for bucket in ("all", c) if c in ("favor", "fade") else ("all",):
                d = out[tag][bucket]
                d["sumR"] += R
                d["W"] += r == "WIN"; d["L"] += r == "LOSS"
                d["O"] += r == "OPEN"; d["NF"] += r in ("NOFILL", "NODATA", "BADSL")
    return out


# ─────────────────────────────────────────────────────────────────────────────
def replay_pair(pair: str, days: int, use_cache: bool = True) -> dict:
    # M15: replay de `days` + warm-up de 600 velas (lo que el motor mira atrás)
    m15_needed = days * 96 + ZONES_OUTPUTSIZE + 10
    m5_needed = min(5000, days * 288 + 4 * ZONES_OUTPUTSIZE + 200)
    src = "caché" if use_cache else "TD"
    print(f"[{pair}] fetch M15({m15_needed}) + M5({m5_needed})  [{src}]...", flush=True)
    m15 = _fetch_td(pair, M15_KEY, m15_needed, use_cache)
    m5 = _fetch_td(pair, M5_KEY, m5_needed, use_cache)
    if not m15 or not m5:
        return {"pair": pair, "error": "sin datos"}

    # ── Diagnóstico del anomaly de timestamps ──
    m15_last_open = _parse_dt(m15[-1]["datetime"])
    now_utc = datetime.now(timezone.utc)
    age_min = (now_utc - (m15_last_open + timedelta(minutes=15))).total_seconds() / 60
    print(f"[{pair}] M15 [{m15[0]['datetime']} .. {m15[-1]['datetime']}]  "
          f"now={now_utc:%Y-%m-%d %H:%M}Z  data_age={age_min:.0f}min "
          f"{'⚠ FUTURO' if age_min < -30 else ''}", flush=True)

    # precomputa M5 open datetimes
    m5_open = [_parse_dt(v["datetime"]) for v in m5]

    # reset de estados con histéresis para un replay limpio
    zones._BIAS_STATE.clear() if hasattr(zones, "_BIAS_STATE") else None
    zone_signal_engine._STRENGTH_STATE.clear()

    warmup = ZONES_OUTPUTSIZE
    rows = []
    for i in range(warmup, len(m15)):
        t_close = _parse_dt(m15[i]["datetime"]) + timedelta(minutes=15)
        m15_slice = m15[max(0, i + 1 - ZONES_OUTPUTSIZE): i + 1]
        # M5 cerradas a t_close: open + 5min <= t_close
        m5_upto = [v for v, od in zip(m5, m5_open) if od + timedelta(minutes=5) <= t_close]
        if len(m5_upto) < 60:
            continue
        m5_slice = m5_upto[-SCANNER_M5_OUTPUT:]
        _inject(pair, m15_slice, m5_slice)
        try:
            marco = _run_marco(pair, t_close)
        except Exception as e:
            marco = {"decision": "ERR", "reason": str(e)}
        rows.append((i, t_close, marco))

    # ── dedup de entradas (transición + cooldown, como el bridge) ──
    entries = []
    last_side = None
    last_at: dict[str, datetime] = {}
    for i, t_close, m in rows:
        op = m.get("decision") == "OPERAR" and m.get("side") in ("LONG", "SHORT")
        cur = m.get("side") if op else None
        if cur and cur != last_side:
            prev_at = last_at.get(cur)
            if not (prev_at and (t_close - prev_at) < timedelta(minutes=COOLDOWN_MIN)):
                # índice M5 de la vela siguiente a la señal
                start_idx = next((k for k, od in enumerate(m5_open) if od >= t_close), len(m5))
                r = _resolve(cur, float(m.get("entry_price") or 0),
                             float(m.get("sl_price") or 0),
                             float(m["tp_price"]) if m.get("tp_price") is not None else None,
                             m5, start_idx)
                entries.append({
                    "t": t_close, "side": cur, "strength": m.get("strength"),
                    "score": (m.get("confluence") or {}).get("score"),
                    "entry": float(m.get("entry_price") or 0), "sl": float(m.get("sl_price") or 0),
                    "tp": float(m["tp_price"]) if m.get("tp_price") is not None else None,
                    "rrr": m.get("rrr"),
                    "level": (m.get("level_used") or {}).get("price"), "atr": m.get("_atr_m15"),
                    "cross": m.get("_cross", "?"),
                    "start_idx": start_idx,
                    "result": r["result"], "R": r["R"],
                    "mfe_R": r["mfe_R"], "mae_R": r["mae_R"],
                })
                last_at[cur] = t_close
        last_side = cur

    # ── agregados de decisiones (todas las barras) ──
    dec_counts: dict[str, int] = {}
    blocking: dict[str, int] = {}
    for _, _, m in rows:
        d = m.get("decision", "?")
        dec_counts[d] = dec_counts.get(d, 0) + 1
        if d == "NO_OPERAR":
            gate = m.get("reason", "?")
            blocking[gate] = blocking.get(gate, 0) + 1

    ab = _ab_exit_rules(entries, m5) if entries else {}
    ab_entry = _ab_entry(entries, m5) if entries else {}
    return {"pair": pair, "bars": len(rows), "dec_counts": dec_counts,
            "blocking": blocking, "entries": entries, "ab": ab, "ab_entry": ab_entry}


def _print_report(res: dict):
    pair = res["pair"]
    print("\n" + "═" * 70)
    print(f"  {pair}  —  {res.get('bars', 0)} barras evaluadas")
    print("═" * 70)
    if res.get("error"):
        print("  ERROR:", res["error"]); return
    print("  Decisiones:", ", ".join(f"{k}={v}" for k, v in sorted(res["dec_counts"].items())))
    if res["blocking"]:
        top = sorted(res["blocking"].items(), key=lambda kv: -kv[1])[:4]
        print("  Gates que más bloquearon:")
        for g, n in top:
            print(f"    {n:>4}×  {g}")
    ent = res["entries"]
    print(f"\n  Oportunidades OPERAR (dedup transición+cooldown): {len(ent)}")
    if not ent:
        print("    — ninguna entrada distinta —"); return
    def _stats(rows):
        w = sum(1 for e in rows if e["result"] == "WIN")
        l = sum(1 for e in rows if e["result"] == "LOSS")
        o = sum(1 for e in rows if e["result"] == "OPEN")
        res = w + l
        wr = (w / res * 100) if res else 0
        tR = sum(e["R"] for e in rows)
        return w, l, o, wr, tR

    w, l, o, wr, total_R = _stats(ent)
    print(f"    WIN {w} · LOSS {l} · OPEN {o}  "
          f"→ WR {wr:.0f}%  ·  Σ {total_R:+.2f}R  ·  exp/trade {total_R/max(1,w+l):+.2f}R")

    # Split por alineación con la tendencia M30 (cross)
    favor = [e for e in ent if "FAVOR" in (e.get("cross") or "")]
    fade = [e for e in ent if "FADE" in (e.get("cross") or "")]
    other = [e for e in ent if e not in favor and e not in fade]
    for name, rows in (("A FAVOR (tendencia)", favor), ("FADE EN RANGO", fade), ("otros", other)):
        if rows:
            ww, ll, oo, wwr, tR = _stats(rows)
            print(f"      · {name:<20} n={len(rows):<2} WIN {ww} LOSS {ll} OPEN {oo}  Σ {tR:+.2f}R")

    print("    ┌─ detalle (mfe=cuánto se acercó al TP · mae=cuánto al SL, en R) ──")
    for e in ent:
        icon = {"WIN": "✓", "LOSS": "✗", "OPEN": "·"}.get(e["result"], "?")
        rrr = f"{e['rrr']:.1f}" if e.get("rrr") else "—"
        sc = e.get("score")
        cross = (e.get("cross") or "?").split("·")[0].strip()[:14]
        print(f"    │ {icon} {e['t']:%m-%d %H:%M}Z {e['side']:<5} "
              f"{e.get('strength') or '?':<7} sc={sc} RRR={rrr} {cross:<14} "
              f"mfe={e['mfe_R']:.2f}R mae={e['mae_R']:.2f}R → {e['result']} {e['R']:+.2f}R")

    ab = res.get("ab") or {}
    if ab:
        print("\n    A/B de reglas de SALIDA (mismas entradas, ordenado barra a barra):")
        print(f"      {'regla':<18} {'W':>2} {'L':>2} {'BE':>2} {'OPEN':>4}  {'WR%':>4}  {'ΣR':>7}")
        for name, s in ab.items():
            wr = (s["W"] / (s["W"] + s["L"]) * 100) if (s["W"] + s["L"]) else 0
            print(f"      {name:<18} {s['W']:>2} {s['L']:>2} {s['BE']:>2} {s['O']:>4}  "
                  f"{wr:>3.0f}%  {s['sumR']:>+7.2f}")

    abe = res.get("ab_entry") or {}
    if abe:
        print("\n    A/B de ENTRADA (ambas con TP 1R): mercado vs LÍMITE en el nivel (pullback)")
        print(f"      {'entrada / grupo':<22} {'W':>2} {'L':>2} {'OPEN':>4} {'NoFill':>6}  {'WR%':>4}  {'ΣR':>7}")
        for tag, label in (("market", "MERCADO"), ("limit", "LÍMITE nivel")):
            for bucket in ("all", "favor", "fade"):
                s = abe[tag][bucket]
                gl = {"all": "todos", "favor": "  · A FAVOR", "fade": "  · FADE"}[bucket]
                wr = (s["W"] / (s["W"] + s["L"]) * 100) if (s["W"] + s["L"]) else 0
                print(f"      {label if bucket=='all' else '':<8}{gl:<14} "
                      f"{s['W']:>2} {s['L']:>2} {s['O']:>4} {s['NF']:>6}  {wr:>3.0f}%  {s['sumR']:>+7.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="AUDUSD,USDCAD")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--refresh", action="store_true", help="ignora la caché a disco y re-fetchea TD")
    args = ap.parse_args()

    if not scanner.TWELVEDATA_API_KEY:
        print("ERROR: TWELVEDATA_API_KEY no está en backend/.env ni en el entorno.")
        sys.exit(1)

    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    print(f"Replay del marco · pares={pairs} · días={args.days} · "
          f"key={scanner.TWELVEDATA_API_KEY[:4]}…", flush=True)
    results = [replay_pair(p, args.days, use_cache=not args.refresh) for p in pairs]
    for r in results:
        _print_report(r)
    print("\n" + "═" * 70)
    print("  Nota: noticias desactivadas (gate blando); sesión parcheada a la barra.")
    print("  SL tiene prioridad si una vela M5 cruza TP y SL a la vez (conservador).")
    print("═" * 70)


if __name__ == "__main__":
    main()
