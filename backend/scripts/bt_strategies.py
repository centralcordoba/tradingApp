"""Estrategias publicadas de traders conocidos, backtest intradía sobre la cache M15.

REGLAS PRE-REGISTRADAS (fijadas antes de ver resultados; las fuentes secundarias
difieren en detalles — se fija UNA versión, citada, y no se cambia tras el run):

Día forex = [22:00, 22:00) UTC, lun-vie, >= 60 velas (mismo `split_days` que bt_auction).
Ejecución común: órdenes stop que se llenan al nivel exacto. Si la vela de llenado
también toca el stop de protección cuenta como pérdida (no hay orden intrabar
conocido → conservador). Si una vela toca las dos órdenes de un bracket, se cuenta
como pérdida del bracket completo. Coste ida y vuelta AUDUSD 1.4p / USDCAD 1.8p.
Máx. 1 trade por estrategia y día.

1. WILLIAMS — ruptura de volatilidad (Larry Williams; versión "open ± k×rango previo",
   LuxAlgo/TradingView). Al abrir el día: buy stop = open + k×rango(día anterior),
   sell stop = open − k×rango. La primera que se llena es la posición, la otra es
   el stop. Salida al cierre del día. k = 0.5 (variantes 0.25 / 0.75).
2. CRABEL — ORB con stretch (Toby Crabel, versión oxfordstrat). ruido = min(high−open,
   open−low) de cada día; stretch = SMA10(ruido) × 2 (variante ×1). Bracket open ±
   stretch, el otro lado es el stop, salida al cierre del día. Variante NR7: solo si
   el día anterior tuvo el rango más estrecho de los últimos 7.
   Prior declarado: oxfordstrat reporta que NO es operable tras costes.
3. LONDON BREAKOUT — ruptura del rango asiático (FX clásico). Rango = high/low de
   00:00–07:00 UTC. Entre 07:00 y 12:00 UTC: buy stop en el high, sell stop en el
   low; primera que se llena. Stop = lado opuesto del rango; TP = 1× rango desde
   la entrada; cierre forzado a las 22:00 UTC.
4. TURTLE SOUP — falsa ruptura de 20 días (Raschke/Connors, "Street Smarts";
   versión LuxAlgo/TradingView con mínimo previo >= 4 días). Si el día hace un
   mínimo por debajo del mínimo de los 20 días anteriores, y ese mínimo previo tiene
   >= 4 días de antigüedad: buy stop en el mínimo previo + 1 pip (la vuelta dentro
   del rango, mismo día). Stop = mínimo del día hasta la entrada − 1 pip. Salida al
   cierre del día SIGUIENTE (variante: TP 2R). SHORT simétrico en máximos.

Comparaciones primarias: 4 estrategias (variante por defecto) × 2 pares. Con 4
intentos, un solo "aprueba" marginal no es un descubrimiento.
Criterio (igual que bt_auction/bt_marco) en DESARROLLO 2020-07 → 2025-06:
R/trade > 0 en >= 5 de 6 años en AMBOS pares, IC95% conjunto > 0, y >= +0.10R
sobre entradas aleatorias emparejadas (misma hora, lado, stop y regla de salida).
La lista de estrategias queda cerrada con este run. Holdout 2025-07 → hoy sellado.

Uso (desde backend/):  python -m scripts.bt_strategies
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date, timedelta

from scripts import bt_data
from scripts.bt_auction import split_days
from scripts.bt_sim import COST_PIPS, PIP, RandomBaseline, fmt, r_multiple, sim, summarize

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DEV_END = date(2025, 6, 30)
NO_TP = 10_000  # pips: "sin take profit"

DEFAULTS = {"williams": "k=0.5", "crabel": "x2", "london": "base", "soup": "cierre D+1"}


def daily(bars, days):
    """OHLC diario a partir de los índices M15 de cada día."""
    return [(end, bars[idx[0]][1], max(bars[i][2] for i in idx), min(bars[i][3] for i in idx),
             bars[idx[-1]][4]) for end, idx in days]


def bracket(bars, idx, buy, sell):
    """Primer lado llenado de un bracket. Devuelve (k, lado, entrada, stop) o None."""
    for k in idx:
        _, _, h, l, _ = bars[k]
        up, dn = h >= buy, l <= sell
        if up and dn:
            return k, "LONG", buy, sell  # ambas en la misma vela → pérdida completa
        if up:
            return k, "LONG", buy, sell
        if dn:
            return k, "SHORT", sell, buy
    return None


def fill_and_run(bars, k, side, entry, stop, tp, t_end, pip):
    """Llenado en la vela k al nivel `entry`; SL primero en esa misma vela."""
    s = 1 if side == "LONG" else -1
    _, _, h, l, _ = bars[k]
    if (l <= stop) if s == 1 else (h >= stop):
        return s * (stop - entry) / pip, k
    p, j, _ = sim(bars, k + 1, side, entry, stop, tp, t_end, pip)
    return p, j


def run(pair: str, holdout: bool = False):
    bars = bt_data.load(pair)
    pip, cost = PIP[pair], COST_PIPS[pair]
    days = split_days(bars)
    d1 = daily(bars, days)
    base = RandomBaseline(bars, pip)
    out = defaultdict(list)  # (estrategia, variante) → trades

    def record(name, var, k, side, entry, stop, tp, t_end, is_default):
        if side is None:
            return
        risk = abs(entry - stop) / pip
        if risk <= 0:
            return
        p, _ = fill_and_run(bars, k, side, entry, stop, tp, t_end, pip)
        t = bars[k][0]
        tr = {"t": t, "year": t.year, "side": side, "risk": risk, "R": r_multiple(p, risk, cost)}
        if is_default:
            reward = abs(tp - entry) / pip
            tr["rand"] = base.mean_r(t, side, risk, reward, cost, horizon=t_end - t)
        out[(name, var)].append(tr)

    for n in range(1, len(days)):
        end, idx = days[n]
        if holdout != (end.date() > DEV_END) or end.date() < date(2020, 7, 2):
            continue
        t_end = end
        o = bars[idx[0]][1]
        _, _, ph, pl, _ = d1[n - 1]
        rng = ph - pl

        # 1. Williams
        for kk in (0.25, 0.5, 0.75):
            var = f"k={kk}"
            b = bracket(bars, idx, o + kk * rng, o - kk * rng)
            if b:
                k, side, e, st = b
                record("williams", var, k, side, e, st, e + (NO_TP if side == "LONG" else -NO_TP) * pip,
                       t_end, var == DEFAULTS["williams"])

        # 2. Crabel
        if n >= 10:
            noise = [min(d1[m][2] - d1[m][1], d1[m][1] - d1[m][3]) for m in range(n - 10, n)]
            avg = sum(noise) / 10
            nr7 = n >= 7 and (d1[n - 1][2] - d1[n - 1][3]) < min(d1[m][2] - d1[m][3] for m in range(n - 7, n - 1))
            for mult, var in ((2, "x2"), (1, "x1"), (2, "x2 + NR7")):
                if var.endswith("NR7") and not nr7:
                    continue
                b = bracket(bars, idx, o + mult * avg, o - mult * avg)
                if b:
                    k, side, e, st = b
                    record("crabel", var, k, side, e, st, e + (NO_TP if side == "LONG" else -NO_TP) * pip,
                           t_end, var == DEFAULTS["crabel"])

        # 3. London breakout
        asia = [k for k in idx if bars[k][0].hour < 7 and bars[k][0].date() == end.date()]
        london = [k for k in idx if 7 <= bars[k][0].hour < 12 and bars[k][0].date() == end.date()]
        if len(asia) >= 20 and london:
            ah, al = max(bars[k][2] for k in asia), min(bars[k][3] for k in asia)
            b = bracket(bars, london, ah, al)
            if b:
                k, side, e, st = b
                r = ah - al
                record("london", "base", k, side, e, st, e + (r if side == "LONG" else -r), t_end, True)

        # 4. Turtle Soup (necesita el día siguiente para la salida)
        if n >= 21 and n + 1 < len(days):
            prev = d1[n - 20:n]
            for side in ("LONG", "SHORT"):
                s = 1 if side == "LONG" else -1
                ext_i = (min if s == 1 else max)(range(20), key=lambda i: prev[i][3] if s == 1 else prev[i][2])
                ext = prev[ext_i][3] if s == 1 else prev[ext_i][2]
                if 20 - ext_i < 4:  # el extremo previo debe tener >= 4 días
                    continue
                broke, day_ext, fill = False, None, None
                for k in idx:
                    _, _, h, l, _ = bars[k]
                    x = l if s == 1 else h  # mínimo del día (LONG) / máximo (SHORT) hasta la entrada
                    day_ext = x if day_ext is None else (min(day_ext, x) if s == 1 else max(day_ext, x))
                    if broke and ((h >= ext + pip) if s == 1 else (l <= ext - pip)):
                        fill = k
                        break
                    if (l < ext) if s == 1 else (h > ext):
                        broke = True
                if fill is None:
                    continue
                e = ext + s * pip
                st = day_ext - s * pip
                t_exit = days[n + 1][0]
                risk = abs(e - st)
                record("soup", "cierre D+1", fill, side, e, st, e + s * NO_TP * pip, t_exit, True)
                record("soup", "TP 2R", fill, side, e, st, e + s * 2 * risk, t_exit, False)
    return out


def report(res: dict):
    names = {"williams": "Williams · ruptura de volatilidad", "crabel": "Crabel · ORB stretch",
             "london": "London breakout (rango asiático)", "soup": "Turtle Soup (Raschke/Connors)"}
    exe = {"williams": "necesita cierre a fin de día (el bridge solo tiene SL/TP)",
           "crabel": "necesita cierre a fin de día + órdenes stop",
           "london": "órdenes stop + cierre a las 22 UTC",
           "soup": "mantiene overnight + salida por tiempo"}
    print("\n══════ DESARROLLO 2020-07 → 2025-06 ══════")
    verdict = []
    for name in names:
        print(f"\n▌{names[name]}")
        rows = []
        for pair, out in res.items():
            print(f"  {pair}")
            for (nm, var), trades in sorted(out.items()):
                if nm != name:
                    continue
                tag = " ← por defecto" if var == DEFAULTS[name] else ""
                print(f"    {var:12} {fmt(summarize([t['R'] for t in trades]))}{tag}")
            dt = out.get((name, DEFAULTS[name]), [])
            years = sorted({t["year"] for t in dt})
            ys = {y: summarize([t["R"] for t in dt if t["year"] == y])["r"] for y in years}
            print("    por año: " + "  ".join(f"{y}: {v:+.2f}" for y, v in ys.items()))
            sr = summarize([t["rand"] for t in dt if t.get("rand") is not None])
            sd = summarize([t["R"] for t in dt])
            print(f"    aleatorio emparejado: {fmt(sr)}")
            rows.append({"pair": pair, "pos": sum(v > 0 for v in ys.values()), "years": len(ys),
                         "edge": sd.get("r", 0) - (sr.get("r") or 0), "R": [t["R"] for t in dt],
                         "r": sd.get("r", 0), "n": sd.get("n", 0)})
        verdict.append((name, rows))
    print("\n══════ TABLA COMPARATIVA (variante por defecto) ══════")
    print(f"  {'estrategia':34} {'n':>5} {'R/trade':>8} {'vs azar':>8} {'años+ AUD/CAD':>14}  veredicto · ejecutable con el bridge actual")
    for name, rows in verdict:
        pooled = summarize([r for row in rows for r in row["R"]])
        ok = (len(rows) == 2 and all(r["pos"] >= 5 for r in rows) and pooled.get("lo", -1) > 0
              and all(r["edge"] >= 0.10 for r in rows))
        edge = sum(r["edge"] * r["n"] for r in rows) / max(1, sum(r["n"] for r in rows))
        print(f"  {names[name]:34} {pooled.get('n', 0):>5} {pooled.get('r', 0):>+8.3f} {edge:>+8.3f} "
              f"{'/'.join(f'{r['pos']}/{r['years']}' for r in rows):>14}  "
              f"{'APRUEBA' if ok else 'NO APRUEBA'} · {exe[name]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="AUDUSD,USDCAD")
    a = ap.parse_args()
    report({p: run(p) for p in a.pairs.split(",")})


if __name__ == "__main__":
    main()
