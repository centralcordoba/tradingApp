"""Calibración offline del motor de decisión contra resultados reales.

Lee la tabla `signals` (Supabase si DATABASE_URL, SQLite local si no) y cruza
cada factor del score con el resultado real (WIN/LOSS/BE). Es la respuesta a
"¿los umbrales 7/4 y los pesos +4/+2/+1 predicen algo?" — hasta ahora eran
constantes inventadas.

Uso:
    cd backend
    .venv\\Scripts\\python.exe -m scripts.calibrate            # todo
    .venv\\Scripts\\python.exe -m scripts.calibrate --taken    # solo operadas
    .venv\\Scripts\\python.exe -m scripts.calibrate --symbol EURUSD

Lectura:
- WR por bucket con n<20 es ruido — no recalibres con menos de ~50 cierres.
- El sweep de umbral muestra qué ENTER-threshold habría maximizado expectancy.
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# La consola de Windows usa cp1252 — sin esto los ⚠/─ del output revientan.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app import storage  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    MADRID = ZoneInfo("Europe/Madrid")
except Exception:
    MADRID = None


def wilson_low(wins: int, n: int, z: float = 1.96) -> float:
    """Límite inferior del intervalo de Wilson — WR pesimista para n pequeño."""
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def agg(rows: list[dict]) -> dict:
    wins = sum(1 for r in rows if r["result"] == "WIN")
    losses = sum(1 for r in rows if r["result"] == "LOSS")
    be = sum(1 for r in rows if r["result"] == "BE")
    pnl = sum((r.get("pnl") or 0) for r in rows)
    decided = wins + losses
    wr = wins / decided if decided else 0.0
    return {
        "n": len(rows), "wins": wins, "losses": losses, "be": be,
        "wr": wr, "wr_low": wilson_low(wins, decided), "pnl": pnl,
        "avg_pnl": pnl / len(rows) if rows else 0.0,
    }


def print_table(title: str, buckets: dict[str, list[dict]], sort_by_key: bool = False) -> None:
    print(f"\n── {title} " + "─" * max(0, 58 - len(title)))
    print(f"{'bucket':<18}{'n':>5}{'W/L/BE':>10}{'WR':>7}{'WR₉₅⁻':>7}{'PnL':>10}{'avg':>8}")
    items = sorted(buckets.items(), key=(lambda kv: kv[0]) if sort_by_key else (lambda kv: -len(kv[1])))
    for k, rows in items:
        a = agg(rows)
        flag = " ⚠n" if a["n"] < 20 else ""
        print(
            f"{k:<18}{a['n']:>5}{a['wins']:>4}/{a['losses']}/{a['be']:<3}"
            f"{a['wr']*100:>6.0f}%{a['wr_low']*100:>6.0f}%{a['pnl']:>10.1f}{a['avg_pnl']:>8.2f}{flag}"
        )


def is_aligned_zona(sig: dict) -> str:
    side = (sig.get("signal") or "").upper()
    zona = sig.get("zona") or ""
    is_long = side in ("LONG", "BUY")
    if not zona:
        return "sin_zona"
    if is_long and zona in ("COMPRA YA", "COMPRA"):
        return "alineada"
    if not is_long and zona in ("VENDE YA", "VENDE"):
        return "alineada"
    return "contraria"


def is_aligned_mtf(sig: dict) -> str:
    side = (sig.get("signal") or "").upper()
    mtf = sig.get("mtf") or ""
    is_long = side in ("LONG", "BUY")
    if mtf == "MIX" or not mtf:
        return "MIX"
    return "alineado" if ((is_long and mtf == "BULL") or (not is_long and mtf == "BEAR")) else "contrario"


def madrid_hour(received_at) -> str:
    try:
        dt = datetime.fromisoformat(str(received_at).replace("Z", "+00:00"))
        if MADRID is not None:
            dt = dt.astimezone(MADRID)
        return f"{dt.hour:02d}h"
    except Exception:
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--taken", action="store_true", help="solo señales operadas (taken=yes)")
    ap.add_argument("--symbol", default=None, help="filtrar por símbolo")
    args = ap.parse_args()

    rows = storage.list_signals(limit=100_000, offset=0, symbol=args.symbol)
    closed = [r for r in rows if r.get("result") in ("WIN", "LOSS", "BE")]
    if args.taken:
        closed = [r for r in closed if r.get("taken") == "yes"]

    print(f"Señales totales: {len(rows)} · cerradas{' (taken)' if args.taken else ''}: {len(closed)}")
    if len(closed) < 10:
        print("\n⚠ Menos de 10 señales cerradas — no hay nada que calibrar todavía.")
        print("  Sigue registrando resultados (W/L/BE) y vuelve a correr esto.")
        return

    a = agg(closed)
    print(f"Global: WR {a['wr']*100:.0f}% (Wilson₉₅⁻ {a['wr_low']*100:.0f}%) · PnL {a['pnl']:.1f}")

    def bucket(key_fn) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = defaultdict(list)
        for r in closed:
            out[str(key_fn(r))].append(r)
        return dict(out)

    print_table("Por decisión del motor", bucket(lambda r: r["response"].get("decision")))
    print_table("Por score del motor", bucket(lambda r: r["response"].get("score", "?")), sort_by_key=True)
    print_table("Por quality (tier de conf)", bucket(lambda r: r["signal"].get("quality")))
    print_table("Por conf bucket", bucket(lambda r: storage._conf_bucket(r["signal"].get("conf"))), sort_by_key=True)
    print_table("Por zona vs lado", bucket(lambda r: is_aligned_zona(r["signal"])))
    print_table("Por MTF vs lado", bucket(lambda r: is_aligned_mtf(r["signal"])))
    print_table("Por patrón", bucket(lambda r: r["signal"].get("pattern") or "---"))
    print_table("Por vol_high", bucket(lambda r: "sí" if r["signal"].get("vol_high") else "no"))
    print_table("Por FVG", bucket(lambda r: "sí" if r["signal"].get("fvg") else "no"))
    print_table("Por hora Madrid", bucket(lambda r: madrid_hour(r.get("received_at"))), sort_by_key=True)

    # Sweep de umbral ENTER: ¿qué threshold de score habría filtrado mejor?
    print("\n── Sweep de umbral ENTER (score >= t) " + "─" * 24)
    print(f"{'t':>3}{'n':>6}{'WR':>8}{'WR₉₅⁻':>8}{'PnL':>10}{'avg':>8}")
    scores = sorted({int(r["response"].get("score") or 0) for r in closed})
    for t in scores:
        sel = [r for r in closed if int(r["response"].get("score") or 0) >= t]
        if not sel:
            continue
        s = agg(sel)
        print(f"{t:>3}{s['n']:>6}{s['wr']*100:>7.0f}%{s['wr_low']*100:>7.0f}%{s['pnl']:>10.1f}{s['avg_pnl']:>8.2f}")

    print(
        "\nNota: los scores históricos se calcularon con la fórmula vigente en su momento\n"
        "(antes de quitar el double-counting conf/quality los scores eran ~1-2 pts más altos).\n"
        "Compara cohortes de la misma época del motor."
    )


if __name__ == "__main__":
    main()
