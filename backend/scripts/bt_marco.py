"""Backtest multi-año del MARCO REAL (el motor que opera el bridge) sobre la cache de bt_data.

Corre el mismo pipeline que /api/zones (zones → cross_verdict → scanner M5 →
generate_zone_marco) al cierre de cada vela M15, reutilizando `_inject`/`_run_marco`
de replay_marco.py, y aplica encima las reglas de ejecución del bridge.

Fase 1 (cara, ~40 ms por vela ≈ 2 h por par): evalúa el marco y guarda las
decisiones OPERAR + conteo de decisiones/gates en scripts/.bt_cache/marco_<PAR>_<modo>.json.
Se reaprovecha en las siguientes corridas (--recompute para rehacerla).
Fase 2 (barata): simula la ejecución y reporta.

REGLAS DE EJECUCIÓN (fijadas antes de ver resultados, espejo del bridge):
  - Ejecuta OPERAR de cualquier strength (MARCO_MIN_STRENGTH=normal), solo en la
    TRANSICIÓN (el lado cambia respecto a la vela anterior), cooldown 15 min por
    par+lado, máx. 2 trades por día UTC, y nunca con una posición abierta en el par.
  - Latencia: entrada al close de la vela M5 que cierra 15 min después del cierre
    de la vela M15 de la señal (el bridge entra 10-30 min tarde). Variante sin
    latencia: entrada al precio teórico del marco (close de la vela de señal).
  - Geometría continuation: SL 12p / TP 24p desde el fill (risk.rebase_to_fill).
    Se compara con el lado del DETECTOR (signal_side) con la misma geometría.
  - Salida: SL o TP sobre velas M5 (SL primero si una vela toca ambos), sin cierre
    por fin de día (el bridge no lo tiene); horizonte máx. 5 días, luego a mercado.
  - Coste ida y vuelta: AUDUSD 1.4p, USDCAD 1.8p.
  - Noticias desactivadas (no hay histórico de ForexFactory); sesión parcheada a la vela.
  - Sin volumen (TD no da volumen en forex, igual que en vivo → VWAP cae a TWAP).

Criterio (pre-registrado, el mismo que bt_auction) sobre 2020-07 → 2025-06:
  R/trade > 0 en >= 5 de 6 años en AMBOS pares, IC95% bootstrap del conjunto > 0,
  y supera a las entradas aleatorias emparejadas en >= 0.10 R/trade.
  Nota: el marco se diseñó y ajustó con datos de jul-sep 2026, así que el periodo
  2020-07 → 2025-06 es fuera de muestra para él; el tramo 2025-07 → hoy (--holdout)
  incluye el periodo de ajuste y NO sirve como validación.

Uso (desde backend/, tras `python -m scripts.bt_data` y `--interval 5min`):
    python -m scripts.bt_marco --pairs AUDUSD       # un proceso por par para paralelizar
    python -m scripts.bt_marco                      # informe (usa la fase 1 cacheada)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from scripts import bt_data, replay_marco as rm
from scripts.bt_sim import COST_PIPS, PIP, RandomBaseline, fmt, r_multiple, sim, summarize
from app import zone_signal_engine, zones
from app.constants import ZONES_OUTPUTSIZE

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

START = date(2020, 7, 1)
DEV_END = date(2025, 6, 30)
WARMUP_DAYS = 10  # el bias M30 (EMA100 sobre M30) necesita ~600 M15 de historia
COOLDOWN = timedelta(minutes=15)
MAX_PER_DAY = 2
LATENCY = timedelta(minutes=15)
SL_PIPS, TP_PIPS = 12, 24
HORIZON = timedelta(days=5)
M5_SLICE = rm.SCANNER_M5_OUTPUT


def _td(rows) -> list[dict]:
    return [{"datetime": t.strftime("%Y-%m-%d %H:%M:%S"), "open": str(o), "high": str(h),
             "low": str(l), "close": str(c)} for t, o, h, l, c in rows]


def _phase1_path(pair: str):
    return bt_data.CACHE / f"marco_{pair}_{zone_signal_engine.STRATEGY_MODE}.json"


def evaluate(pair: str) -> dict:
    """Fase 1: marco al cierre de cada vela M15 con dato M5 disponible."""
    m15, m5 = bt_data.load(pair), bt_data.load(pair, "5min")
    if not m5:
        raise SystemExit(f"{pair}: no hay M5 en cache — `python -m scripts.bt_data --interval 5min`")
    zones._BIAS_STATE.clear() if hasattr(zones, "_BIAS_STATE") else None
    zone_signal_engine._STRENGTH_STATE.clear()
    first = datetime.combine(START, datetime.min.time(), timezone.utc) + timedelta(days=WARMUP_DAYS)
    i0 = max(ZONES_OUTPUTSIZE, bisect_left(m15, (first,)))
    decisions, gates, operar = Counter(), Counter(), []
    t_start = time.time()
    for i in range(i0, len(m15)):
        if m15[i][0].weekday() >= 5:
            continue
        t_close = m15[i][0] + timedelta(minutes=15)
        j = bisect_left(m5, (t_close - timedelta(minutes=4),))  # M5 cerradas a t_close
        if j < 60 or j >= len(m5) or m5[j - 1][0] < t_close - timedelta(minutes=30):
            continue  # hueco en M5
        rm._inject(pair, _td(m15[i + 1 - ZONES_OUTPUTSIZE: i + 1]), _td(m5[j - M5_SLICE: j]))
        try:
            m = rm._run_marco(pair, t_close)
        except Exception as e:
            m = {"decision": "ERR", "reason": type(e).__name__}
        d = m.get("decision", "?")
        decisions[d] += 1
        if d == "NO_OPERAR":
            gates[(m.get("reason") or "?").split(" — ")[0][:60]] += 1
        if d == "OPERAR" and m.get("side") in ("LONG", "SHORT"):
            operar.append({
                "t": t_close.isoformat(), "side": m["side"], "signal_side": m.get("signal_side"),
                "strength": m.get("strength"), "score": (m.get("confluence") or {}).get("score"),
                "cross": (m.get("_cross") or "?").split("·")[0].strip()[:16],
                "session": m.get("session_status"),
                "entry": m.get("entry_price"), "sl": m.get("sl_price"), "tp": m.get("tp_price"),
            })
        n = i - i0 + 1
        if n % 5000 == 0:
            el = time.time() - t_start
            print(f"  {pair} {m15[i][0]:%Y-%m-%d}: {n}/{len(m15) - i0} velas · "
                  f"{len(operar)} OPERAR · {el / 60:.0f} min (quedan ~{el / n * (len(m15) - i0 - n) / 60:.0f})",
                  flush=True)
    out = {"pair": pair, "strategy": zone_signal_engine.STRATEGY_MODE, "decisions": dict(decisions),
           "gates": dict(gates.most_common(15)), "operar": operar}
    _phase1_path(pair).write_text(json.dumps(out), encoding="utf-8")
    return out


def _enter(m5, t_sig: datetime, side: str, pip: float):
    """Fill tardío + SL/TP 12/24 desde el fill. Devuelve (i0, entry, sl, tp) o None."""
    j = bisect_left(m5, (t_sig + LATENCY - timedelta(minutes=5),))
    if j >= len(m5) or m5[j][0] > t_sig + LATENCY + timedelta(minutes=30):
        return None
    s = 1 if side == "LONG" else -1
    e = m5[j][4]
    return j + 1, e, e - s * SL_PIPS * pip, e + s * TP_PIPS * pip


def execute(pair: str, phase1: dict, holdout: bool) -> list[dict]:
    m5 = bt_data.load(pair, "5min")
    pip, cost = PIP[pair], COST_PIPS[pair]
    base = RandomBaseline(m5, pip)
    trades, last_side, last_t = [], None, None
    seen: dict[str, datetime] = {}
    per_day: Counter = Counter()
    busy_until = datetime.min.replace(tzinfo=timezone.utc)
    rows = sorted(phase1["operar"], key=lambda r: r["t"])
    for r in rows:
        t = datetime.fromisoformat(r["t"])
        side = r["side"]
        # transición: vela anterior sin OPERAR en este lado (rows solo trae OPERAR)
        contiguous = last_t is not None and t - last_t <= timedelta(minutes=15) and last_side == side
        last_side, last_t = side, t
        if contiguous:
            continue
        if holdout != (t.date() > DEV_END):
            continue
        if seen.get(side) and t - seen[side] < COOLDOWN:
            continue
        if per_day[t.date()] >= MAX_PER_DAY or t < busy_until:
            continue
        got = _enter(m5, t, side, pip)
        if not got:
            continue
        i0, e, sl, tp = got
        pips, k, out = sim(m5, i0, side, e, sl, tp, t + HORIZON, pip)
        det = r.get("signal_side") or ("SHORT" if side == "LONG" else "LONG")
        sd = 1 if det == "LONG" else -1
        dpips, _, _ = sim(m5, i0, det, e, e - sd * SL_PIPS * pip, e + sd * TP_PIPS * pip, t + HORIZON, pip)
        z = None
        if r.get("entry") and r.get("sl") and r.get("tp"):
            ze, zsl, ztp = float(r["entry"]), float(r["sl"]), float(r["tp"])
            zi = bisect_left(m5, (t,))
            zp, _, _ = sim(m5, zi, side, ze, zsl, ztp, t + HORIZON, pip)
            z = r_multiple(zp, abs(ze - zsl) / pip, cost)
        seen[side] = t
        per_day[t.date()] += 1
        busy_until = m5[k][0] + timedelta(minutes=5)
        trades.append({**r, "t": t, "year": t.year, "out": out,
                       "R": r_multiple(pips, SL_PIPS, cost), "R_det": r_multiple(dpips, SL_PIPS, cost),
                       "R_nolat": z, "rand": base.mean_r(t, side, SL_PIPS, TP_PIPS, cost, horizon=HORIZON)})
    return trades


def report(pair: str, p1: dict, trades: list[dict], holdout: bool) -> dict:
    split = "HOLDOUT 2025-07 → hoy (incluye el periodo de ajuste: NO valida)" if holdout \
        else "2020-07 → 2025-06 (fuera de muestra para el marco)"
    print(f"\n══════ {pair} · marco {p1['strategy']} · {split} ══════")
    tot = sum(p1["decisions"].values())
    print("  Decisiones por vela: " + ", ".join(f"{k} {v} ({v / tot:.1%})" for k, v in
                                               sorted(p1["decisions"].items(), key=lambda kv: -kv[1])))
    print("  Gates que más bloquean: " + "; ".join(f"{g} ×{n}" for g, n in list(p1["gates"].items())[:5]))
    rs = [t["R"] for t in trades]
    s_main, s_rand = summarize(rs), summarize([t["rand"] for t in trades if t["rand"] is not None])
    print(f"\n  Ejecutado (lado del marco, fill +15 min, 12/24)  {fmt(s_main)}")
    print(f"  Lado del detector, misma entrada y geometría     {fmt(summarize([t['R_det'] for t in trades]))}")
    print(f"  Sin latencia (precio y SL/TP teóricos del marco) {fmt(summarize([t['R_nolat'] for t in trades if t['R_nolat'] is not None]))}")
    print(f"  Aleatorio emparejado (año, hora, lado, 12/24)    {fmt(s_rand)}")
    years = sorted({t["year"] for t in trades})
    print("  Por año: " + "  ".join(f"{y}: {summarize([t['R'] for t in trades if t['year'] == y])['r']:+.2f} "
                                    f"(n={sum(t['year'] == y for t in trades)})" for y in years))
    for key in ("strength", "cross", "side", "session"):
        groups = defaultdict(list)
        for t in trades:
            groups[t.get(key)].append(t["R"])
        print(f"  por {key:8} " + " | ".join(f"{k}: n={len(v)} {sum(v) / len(v):+.2f}R" for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))))
    pos = sum(summarize([t["R"] for t in trades if t["year"] == y])["r"] > 0 for y in years)
    return {"pair": pair, "pos_years": pos, "years": len(years), "R": rs,
            "edge": s_main.get("r", 0) - (s_rand.get("r") or 0)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="AUDUSD,USDCAD")
    ap.add_argument("--recompute", action="store_true", help="rehace la fase 1 aunque exista")
    ap.add_argument("--holdout", action="store_true")
    a = ap.parse_args()
    rows = []
    for pair in a.pairs.split(","):
        path = _phase1_path(pair)
        p1 = json.loads(path.read_text(encoding="utf-8")) if path.exists() and not a.recompute else evaluate(pair)
        rows.append(report(pair, p1, execute(pair, p1, a.holdout), a.holdout))
    if len(rows) == 2 and not a.holdout:
        pooled = summarize([r for row in rows for r in row["R"]])
        ok = (all(r["pos_years"] >= 5 for r in rows) and pooled.get("lo", -1) > 0
              and all(r["edge"] >= 0.10 for r in rows))
        print("\n══════ CRITERIO PRE-REGISTRADO ══════")
        print(f"  Marco: {'APRUEBA' if ok else 'NO APRUEBA'} — " + ", ".join(
            f"{r['pair']} {r['pos_years']}/{r['years']} años+, {r['edge']:+.3f}R vs azar" for r in rows)
              + f"; conjunto {fmt(pooled)}")


if __name__ == "__main__":
    main()
