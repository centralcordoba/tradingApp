"""¿Mejora el marco si solo opera a favor de la tendencia diaria?

Hipótesis (de los trades en vivo: los LONG de sep-oct perdieron porque AUDUSD caía).
Usa la fase 1 cacheada de bt_marco (no recalcula el marco).

REGLAS PRE-REGISTRADAS:
  Tendencia D1 = cierre del último día COMPLETO (D1 de TD, día anterior a la señal)
  respecto a su EMA200 diaria: por encima → solo LONG, por debajo → solo SHORT.
  Variante (se reporta entera): pendiente de la EMA50 diaria (EMA50 hoy vs hace 5 días).
  Se filtran las decisiones OPERAR ANTES de aplicar las reglas del bridge (transición,
  cooldown, 2/día, una posición) y se ejecuta igual que bt_marco (fill +15 min, 12/24).
  Se evalúa el lado ejecutado (continuation) y el lado del detector, cada uno con el
  filtro aplicado a SU lado.
  Base aleatoria: entradas al azar en el mismo año y hora, con el mismo lado y SOLO en
  días en que el filtro permite ese lado → mide si el marco aporta algo más allá del
  propio filtro de tendencia.
  Criterio (el de siempre) en 2020-07 → 2025-06: R/trade > 0 en >= 5/6 años en ambos
  pares, IC95% conjunto > 0 y >= +0.10R sobre esa base aleatoria.

Uso (desde backend/, tras bt_marco y `bt_data --interval 1day --start 2000-01-03`):
    python -m scripts.bt_marco_d1
"""
from __future__ import annotations

import json
import random
import sys
from datetime import timedelta

from scripts import bt_data, bt_marco
from scripts.bt_sim import COST_PIPS, PIP, fmt, r_multiple, sim, summarize

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PAIRS = ["AUDUSD", "USDCAD"]
OPP = {"LONG": "SHORT", "SHORT": "LONG"}


def ema(xs, n):
    out, e = [], None
    for x in xs:
        e = x if e is None else e + 2 / (n + 1) * (x - e)
        out.append(e)
    return out


def trend_maps(pair):
    d = bt_data.load(pair, "1day")
    closes = [b[4] for b in d]
    e200, e50 = ema(closes, 200), ema(closes, 50)
    ema200 = {b[0].date(): ("LONG" if c > e else "SHORT") for b, c, e in zip(d, closes, e200)}
    slope = {d[i][0].date(): ("LONG" if e50[i] > e50[i - 5] else "SHORT") for i in range(5, len(d))}
    return {"EMA200": ema200, "pendiente EMA50": slope}


def state_at(m, t):
    """Estado del último día completo antes de t."""
    for k in range(1, 6):
        s = m.get((t - timedelta(days=k)).date())
        if s:
            return s
    return None


def filtered_random(m5, pip, cost, trades, tmap, rng, draws=20):
    pool = {}
    for i, (t, *_ ) in enumerate(m5[:-1]):
        if t.weekday() < 5:
            pool.setdefault((t.year, t.hour), []).append(i)
    out = []
    for tr in trades:
        cand = pool.get((tr["t"].year, tr["t"].hour), [])
        acc = []
        for _ in range(draws * 5):
            if len(acc) == draws or not cand:
                break
            i = rng.choice(cand)
            if state_at(tmap, m5[i][0]) != tr["side"]:
                continue
            s = 1 if tr["side"] == "LONG" else -1
            e = m5[i][4]
            p, _, _ = sim(m5, i + 1, tr["side"], e, e - s * 12 * pip, e + s * 24 * pip,
                          m5[i][0] + bt_marco.HORIZON, pip)
            acc.append(r_multiple(p, 12, cost))
        if acc:
            out.append(sum(acc) / len(acc))
    return out


def main() -> None:
    rng = random.Random(3)
    results = {}
    for pair in PAIRS:
        p1 = json.loads(bt_marco._phase1_path(pair).read_text(encoding="utf-8"))
        m5 = bt_data.load(pair, "5min")
        pip, cost = PIP[pair], COST_PIPS[pair]
        maps = trend_maps(pair)
        base = bt_marco.execute(pair, p1, False)
        print(f"\n══════ {pair} · 2020-07 → 2025-06 ══════")
        print(f"  sin filtro (bt_marco)            {fmt(summarize([t['R'] for t in base]))}")
        for fname, tmap in maps.items():
            for which in ("ejecutado", "detector"):
                rows = []
                for r in p1["operar"]:
                    t = bt_marco.datetime.fromisoformat(r["t"])
                    side = r["side"] if which == "ejecutado" else (r.get("signal_side") or OPP[r["side"]])
                    if state_at(tmap, t) == side:
                        rows.append({**r, "side": side, "signal_side": OPP[side]})
                tr = bt_marco.execute(pair, {**p1, "operar": rows}, False)
                rs = [t["R"] for t in tr]
                rnd = filtered_random(m5, pip, cost, tr, tmap, rng)
                s, sr = summarize(rs), summarize(rnd)
                years = sorted({t["year"] for t in tr})
                ys = {y: summarize([t["R"] for t in tr if t["year"] == y])["r"] for y in years}
                default = fname == "EMA200" and which == "ejecutado"
                print(f"\n  {fname} · lado {which}{'  ← por defecto' if default else ''}")
                print(f"    marco + filtro                 {fmt(s)}")
                print(f"    azar + mismo filtro            {fmt(sr)}")
                print("    por año: " + "  ".join(f"{y}: {v:+.2f}" for y, v in ys.items()))
                results[(pair, fname, which)] = {
                    "s": s, "edge": s.get("r", 0) - (sr.get("r") or 0), "R": rs,
                    "pos": sum(v > 0 for v in ys.values()), "years": len(ys)}
    print("\n══════ CRITERIO PRE-REGISTRADO (EMA200, lado ejecutado) ══════")
    rows = [results[(p, "EMA200", "ejecutado")] for p in PAIRS]
    pooled = summarize([r for row in rows for r in row["R"]])
    ok = all(r["pos"] >= 5 for r in rows) and pooled.get("lo", -1) > 0 and all(r["edge"] >= 0.10 for r in rows)
    print(f"  {'APRUEBA' if ok else 'NO APRUEBA'} — " + ", ".join(
        f"{p} {r['pos']}/{r['years']} años+, {r['edge']:+.3f}R vs azar filtrado" for p, r in zip(PAIRS, rows))
          + f"; conjunto {fmt(pooled)}")


if __name__ == "__main__":
    main()
