"""Replay de los trades reales del bridge (bridge/trades.csv) contra el OHLC M15.

Sirve de test de regresión del motor de simulación: en modo continuation (sin
parcial) el resultado simulado con el SL/TP real debe coincidir con el del broker.
Además da el contrafactual por trade: lado del detector vs lado invertido con
12/24 fijo, y la comparación contra entradas aleatorias emparejadas.

Uso (desde backend/, tras `python -m scripts.bt_data`):
    python -m scripts.bt_trades
    python -m scripts.bt_trades --csv ../bridge/trades.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import bt_data
from scripts.bt_sim import (COST_PIPS, PIP, RandomBaseline, fmt, index_at, r_multiple,
                            sim, summarize)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CHANGE = datetime(2026, 9, 1, tzinfo=timezone.utc)  # reversion → continuation
HORIZON_DAYS = 5
OPP = {"LONG": "SHORT", "SHORT": "LONG"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(Path(__file__).resolve().parents[2] / "bridge" / "trades.csv"))
    a = ap.parse_args()
    rows = [r for r in csv.DictReader(open(a.csv, encoding="utf-8")) if r["dry_run"] == "0"]
    series = {p: bt_data.load(p) for p in {r["symbol"] for r in rows}}
    base = {p: RandomBaseline(b, PIP[p]) for p, b in series.items()}

    print(f"{'fecha UTC':16} {'par':6} {'coh':4} {'lado':5} {'real':5} {'sim':4} {'match':5} "
          f"{'det12/24':>8} {'inv12/24':>8}")
    match = total = 0
    by_coh: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        p, side, e = r["symbol"], r["side"], float(r["entry_price"])
        bars, pip, cost = series[p], PIP[p], COST_PIPS[p]
        t0 = datetime.fromisoformat(r["opened_at"])
        coh = "REV" if t0 < CHANGE else "CONT"
        det = side if coh == "REV" else OPP[side]
        # Arranca en la vela siguiente a la que contiene la ejecución (no hay orden intrabar)
        i0 = index_at(bars, t0)
        t_end = t0 + timedelta(days=HORIZON_DAYS)
        sl, tp = float(r["sl_price"]), float(r["tp_price"])
        sp, _, so = sim(bars, i0, side, e, sl, tp, t_end, pip)
        res = {"SL": "LOSS", "TP": "WIN"}.get(so, "OPEN")
        ok = ""
        if r["result"] and r["tp1_price"] == "":  # sin parcial → comparable 1:1
            total += 1
            ok = "OK" if res == r["result"] else "DIFF"
            match += res == r["result"]
        risk = abs(e - sl) / pip
        out = {}
        for k, sd in (("exec", side), ("det", det), ("inv", OPP[det])):
            if k == "exec":
                pp = sp
            else:
                s = 1 if sd == "LONG" else -1
                pp, _, _ = sim(bars, i0, sd, e, e - s * 12 * pip, e + s * 24 * pip, t_end, pip)
            out[k] = r_multiple(pp, 12 if k != "exec" else risk, cost)
        rb = base[p].mean_r(t0, side, risk, abs(tp - e) / pip, cost)
        d = by_coh.setdefault(coh, {"exec": [], "det": [], "inv": [], "rand": []})
        for k in ("exec", "det", "inv"):
            d[k].append(out[k])
        if rb is not None:
            d["rand"].append(rb)
        print(f"{t0:%Y-%m-%d %H:%M} {p:6} {coh:4} {side:5} {r['result'] or 'OPEN':5} {res:4} {ok:5} "
              f"{out['det']:+8.2f} {out['inv']:+8.2f}")
    print(f"\nRegresión del motor: {match}/{total} cierres sin parcial coinciden con el broker")
    for coh, d in by_coh.items():
        print(f"\n{coh}")
        for k, lbl in (("exec", "ejecutado (SL/TP real)"), ("det", "lado detector 12/24"),
                       ("inv", "lado invertido 12/24"), ("rand", "aleatorio emparejado")):
            print(f"  {lbl:24} {fmt(summarize(d[k]))}")


if __name__ == "__main__":
    main()
