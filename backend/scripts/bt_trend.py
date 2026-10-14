"""Seguimiento de tendencia en diario (reglas Turtle, Dennis/Eckhardt vía Curtis Faith)
sobre una cartera de 7 majors. NO es el producto del bridge: posiciones de días o
semanas, swaps y gestión de salida por canal.

REGLAS PRE-REGISTRADAS (versión fijada sin piramidar ni regla de skip — ambas
varían entre fuentes; se declaran fuera):
  N = ATR20 de Wilder (diario). Sistema 1: entrada al romper el máximo/mínimo de
  los 20 días previos, salida al tocar el mínimo/máximo de 10 días. Sistema 2:
  55/20. Stop de protección 2N desde la entrada. Una posición por par y sistema.
  - Llenado al nivel de ruptura (o a la apertura si abre más allá).
  - Salida al nivel del canal o del stop, el que esté más cerca de la entrada (el
    precio toca primero ese); si abre más allá, a la apertura.
  - El día de entrada, si el rango del día toca el stop, cuenta como stop
    (no se conoce el orden intradía → conservador).
  - Coste ida y vuelta 1.5 pips (JPY: pip 0.01). Swaps NO modelados.
  R = resultado en pips / (2N en pips al entrar).
Base aleatoria: misma cartera, días de entrada al azar con lado al azar y las
mismas reglas de stop/salida (20 sorteos) — aísla el valor de la señal de ruptura.

Criterio (pre-registrado), DESARROLLO 2000 → 2025-06, Sistema 2 por defecto:
  IC95% bootstrap del R/trade de la cartera > 0, >= +0.10R sobre la base aleatoria,
  y R de la cartera positivo en >= 60% de los años. Holdout 2025-07 → hoy sellado.

Uso (desde backend/, tras `python -m scripts.bt_data --interval 1day --start 2000-01-03
--pairs EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,USDCAD,NZDUSD`):
    python -m scripts.bt_trend
"""
from __future__ import annotations

import random
import sys
from collections import defaultdict
from datetime import date

from scripts import bt_data
from scripts.bt_sim import fmt, summarize

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]
DEV_END = date(2025, 6, 30)
COST = 1.5
SYSTEMS = {"S1 20/10": (20, 10), "S2 55/20": (55, 20)}
DEFAULT = "S2 55/20"


def pip_of(pair):
    return 0.01 if pair.endswith("JPY") else 0.0001


def atr20(d):
    out, a = [], None
    for i, (_, o, h, l, c) in enumerate(d):
        tr = h - l if i == 0 else max(h - l, abs(h - d[i - 1][4]), abs(l - d[i - 1][4]))
        a = tr if a is None else a + (tr - a) / 20
        out.append(a)
    return out


def run_trade(d, i, side, entry, n_val, exit_len, pip):
    """Gestiona una posición abierta el día i. Devuelve (R, índice de salida)."""
    s = 1 if side == "LONG" else -1
    stop = entry - s * 2 * n_val
    risk = 2 * n_val / pip
    _, o, h, l, c = d[i]
    if (l <= stop) if s == 1 else (h >= stop):
        return (-risk - COST) / risk, i
    for j in range(i + 1, len(d)):
        _, o, h, l, c = d[j]
        ch = (min if s == 1 else max)(x[3] if s == 1 else x[2] for x in d[max(0, j - exit_len):j])
        level = max(stop, ch) if s == 1 else min(stop, ch)
        if (o <= level) if s == 1 else (o >= level):
            px = o
        elif (l <= level) if s == 1 else (h >= level):
            px = level
        else:
            continue
        return (s * (px - entry) / pip - COST) / risk, j
    return (s * (d[-1][4] - entry) / pip - COST) / risk, len(d) - 1


def signals(d, a, entry_len, exit_len, pip):
    trades, i = [], max(entry_len, 21)
    while i < len(d):
        hi = max(x[2] for x in d[i - entry_len:i])
        lo = min(x[3] for x in d[i - entry_len:i])
        _, o, h, l, c = d[i]
        side = "LONG" if h > hi else ("SHORT" if l < lo else None)
        if side is None or (h > hi and l < lo):
            i += 1
            continue
        lvl = hi if side == "LONG" else lo
        entry = max(o, lvl) if side == "LONG" else min(o, lvl)
        r, j = run_trade(d, i, side, entry, a[i - 1], exit_len, pip)
        trades.append({"t": d[i][0], "year": d[i][0].year, "side": side, "R": r, "i": i, "days": j - i})
        i = j + 1
    return trades


def random_trades(d, a, n_trades, exit_len, pip, rng):
    out = []
    for _ in range(n_trades):
        i = rng.randrange(60, len(d) - 1)
        side = rng.choice(("LONG", "SHORT"))
        r, _ = run_trade(d, i, side, d[i][1], a[i - 1], exit_len, pip)
        out.append(r)
    return out


def main() -> None:
    rng = random.Random(5)
    by_sys = defaultdict(list)
    rand_by_sys = defaultdict(list)
    per_pair = defaultdict(dict)
    for pair in PAIRS:
        d = [b for b in bt_data.load(pair, "1day") if b[0].date() <= DEV_END]
        if len(d) < 300:
            print(f"{pair}: sin datos diarios")
            continue
        a, pip = atr20(d), pip_of(pair)
        for name, (en, ex) in SYSTEMS.items():
            tr = signals(d, a, en, ex, pip)
            for t in tr:
                t["pair"] = pair
            by_sys[name] += tr
            rand_by_sys[name] += [r for _ in range(20) for r in random_trades(d, a, max(1, len(tr) // 20 + 1), ex, pip, rng)]
            per_pair[name][pair] = tr
    print(f"\n══════ CARTERA {len(per_pair[DEFAULT])} majors · DESARROLLO → 2025-06 ══════")
    verdict = {}
    for name in SYSTEMS:
        tr = by_sys[name]
        s, sr = summarize([t["R"] for t in tr]), summarize(rand_by_sys[name])
        years = sorted({t["year"] for t in tr})
        yr = {y: sum(t["R"] for t in tr if t["year"] == y) for y in years}
        print(f"\n▌{name}{'  ← por defecto' if name == DEFAULT else ''}")
        print(f"  cartera            {fmt(s)}   duración media {sum(t['days'] for t in tr) / len(tr):.0f} días")
        print(f"  aleatorio          {fmt(sr)}")
        for pair, ptr in per_pair[name].items():
            print(f"  {pair}  {fmt(summarize([t['R'] for t in ptr]))}")
        print("  R total por año: " + "  ".join(f"{y}: {v:+.1f}" for y, v in yr.items()))
        pos = sum(v > 0 for v in yr.values())
        print(f"  años positivos: {pos}/{len(yr)}")
        verdict[name] = (s.get("lo", -1) > 0 and s["r"] - sr["r"] >= 0.10 and pos >= 0.6 * len(yr), s, sr, pos, len(yr))
    ok, s, sr, pos, ny = verdict[DEFAULT]
    print("\n══════ CRITERIO PRE-REGISTRADO (S2 55/20) ══════")
    print(f"  {'APRUEBA' if ok else 'NO APRUEBA'} — R/trade {s['r']:+.3f} [{s['lo']:+.3f}, {s['hi']:+.3f}], "
          f"{s['r'] - sr['r']:+.3f}R vs azar, {pos}/{ny} años positivos")


if __name__ == "__main__":
    main()
