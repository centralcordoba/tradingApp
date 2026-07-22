"""Analiza bridge/trades.csv y resume WR / expectancy por corte (cross, strength,
sesión, símbolo, lado). Solo stdlib — no toca MT5 ni la red.

Uso (desde bridge/):
  python -m analyze_trades                 # trades reales (dry_run=0)
  python analyze_trades.py --include-dry   # incluye dry-run
  python analyze_trades.py --only-dry      # solo dry-run
  python analyze_trades.py --csv otro.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # consola Windows (cp1252) no traga ═ ✓
except Exception:
    pass

_CSV_DEFAULT = Path(__file__).parent / "trades.csv"

CROSS_LABEL = {"A": "A FAVOR", "B": "FADE", "C": "CONFLICTO",
               "D": "SIN SETUP", "NA": "sin bias", "OUT": "fuera"}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def summarize(rows: list[dict]) -> dict:
    wins = losses = be = partial = 0
    pnl = 0.0
    Rs = []
    for r in rows:
        res = r.get("result", "")
        if res == "WIN":
            wins += 1
        elif res == "LOSS":
            losses += 1
        elif res == "BE":
            be += 1
        p = _f(r.get("pnl_usd"))
        if p is not None:
            pnl += p
        risk = _f(r.get("risk_usd"))
        if p is not None and risk and risk > 0:
            Rs.append(p / risk)
        if r.get("partial_done") == "1":
            partial += 1
    decided = wins + losses
    return {
        "n": len(rows), "wins": wins, "losses": losses, "be": be, "partial": partial,
        "wr": (wins / decided * 100) if decided else 0.0,
        "pnl": pnl, "expR": (sum(Rs) / len(Rs)) if Rs else 0.0, "sumR": sum(Rs),
    }


def _line(label: str, s: dict, width: int = 18) -> str:
    return (f"  {label:<{width}} n={s['n']:<3} "
            f"W {s['wins']:<2} L {s['losses']:<2} BE {s['be']:<2}  "
            f"WR {s['wr']:>3.0f}%  ΣR {s['sumR']:>+6.2f}  "
            f"exp {s['expR']:>+5.2f}R  PnL {s['pnl']:>+8.2f}")


def _bucket(closed: list[dict], key: str, label_map=None) -> list[tuple]:
    groups: dict = {}
    for r in closed:
        k = r.get(key) or "(vacío)"
        groups.setdefault(k, []).append(r)
    out = []
    for k, rows in groups.items():
        disp = (label_map or {}).get(k, k)
        out.append((disp, summarize(rows)))
    return sorted(out, key=lambda t: -t[1]["sumR"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(_CSV_DEFAULT))
    ap.add_argument("--include-dry", action="store_true", help="incluye trades dry-run")
    ap.add_argument("--only-dry", action="store_true", help="solo trades dry-run")
    args = ap.parse_args()

    path = Path(args.csv)
    if not path.exists():
        print(f"No existe {path} — todavía no hay trades registrados.")
        return 0
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print(f"{path} está vacío (solo header).")
        return 0

    if args.only_dry:
        rows = [r for r in rows if r.get("dry_run") == "1"]
    elif not args.include_dry:
        rows = [r for r in rows if r.get("dry_run") != "1"]

    closed = [r for r in rows if r.get("result") in ("WIN", "LOSS", "BE")]
    open_n = len(rows) - len(closed)
    scope = ("dry-run" if args.only_dry else
             "todos (real+dry)" if args.include_dry else "reales (dry excluidos)")

    print("═" * 78)
    print(f"  Análisis de {path.name}  ·  scope: {scope}")
    print("═" * 78)
    print(f"  Trades: {len(rows)} · cerrados: {len(closed)} · abiertos: {open_n}")
    if not closed:
        print("\n  Ningún trade cerrado todavía — nada que analizar aún.")
        return 0

    g = summarize(closed)
    print(f"\n  GLOBAL (cerrados)")
    print(_line("total", g, width=10))
    print(f"  Parcial 1R tomado: {g['partial']}/{len(closed)}")

    for title, key, lbl in (("Por cross (M30/M5)", "cross_state", CROSS_LABEL),
                            ("Por fuerza", "strength", None),
                            ("Por sesión", "session", None),
                            ("Por símbolo", "symbol", None),
                            ("Por lado", "side", None),
                            ("Por fuente", "source", None)):
        buckets = _bucket(closed, key, lbl)
        if len(buckets) <= 1 and key in ("symbol", "side", "source"):
            continue  # no aporta si hay un solo valor
        print(f"\n  {title}")
        for disp, s in buckets:
            print(_line(disp, s))

    print("\n" + "═" * 78)
    print("  R = pnl_usd / risk_usd (múltiplo realizado). WR = W/(W+L), BE aparte.")
    print("  exp = expectancy en R por trade. Muestra chica → interpretá con cuidado.")
    print("═" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
