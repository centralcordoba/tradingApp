"""Backtest de los dos modelos de subasta (estilo Fabio Valentini) sobre OHLC M15.

REGLAS PRE-REGISTRADAS (fijadas ANTES de ver un solo resultado — no se tocan
para "mejorar" el número; cualquier variante se reporta entera, nunca la mejor celda):

Perfil. Día forex = [22:00 UTC, 22:00 UTC). Días con < 60 velas o que terminan en fin de semana se descartan.
  El perfil de referencia es el del día válido anterior (el lunes usa el viernes).
  TPO por tiempo (sin volumen: TD no da volumen en forex): cada vela M15 suma 1 a
  cada bin de 1 pip entre su low y su high. POC = bin con más cuentas (empate → el
  más cercano al centro del rango). Área de valor (VA) = expansión desde el POC
  hacia el lado con más cuentas hasta cubrir el 70% → VAH / VAL.
  Perfil de un TRAMO (impulso o vuelta): bin = max(1 pip, rango/20); LVN = bin con
  menos cuentas cuyo centro esté entre el 20% y el 80% del tramo (empate → el más
  cercano al centro).

Modelo A — tendencia (desequilibrio). LONG (SHORT simétrico):
  1. Aceptación: 2 cierres M15 consecutivos > VAH del día anterior.
  2. Impulso: desde el mínimo del día hasta la vela de aceptación, extendido con
     cada nuevo máximo. Desplazamiento mínimo: rango del impulso >= 2×ATR14(M15).
  3. Disparo: una vela posterior al máximo del impulso cuyo low toca el LVN del
     impulso (una vela que hace nuevo máximo no dispara: extiende el tramo).
     Si antes de disparar una vela cierra de vuelta < VAH, el setup se cancela.
  4. Stop = LVN − 0.5×ATR (variante: 1.0×ATR).
     Objetivo = máximo del impulso (variante: 2R fijo).

Modelo B — reversión (ruptura fallida). SHORT tras ruptura del VAH (LONG simétrico en VAL):
  1. Ruptura: un cierre > VAH. Fallida si en <= 8 velas una vela cierra < VAH;
     si no vuelve en 8 velas = aceptación, no hay B en ese lado (se rearma si
     vuelve a salir más tarde).
  2. Tramo de vuelta: desde el máximo de la ruptura hasta la vela que vuelve a
     entrar. No se entra en esa vuelta: se espera un retroceso al LVN de ese tramo
     en las 8 velas siguientes (high >= LVN). Un cierre > máximo de la ruptura cancela.
  3. Stop = máximo de la ruptura + 0.2×ATR (variante: 0.5×ATR).
     Objetivo = POC del día anterior. Si la entrada ya está más allá del POC, no hay trade.

Común:
  - Disparos solo en velas con hora UTC en [07, 20). Máx. 1 trade por modelo,
    lado y día. Cierre forzado a las 22:00 UTC. SL primero si una vela toca ambos.
  - Entrada por defecto = TARDÍA: close de la vela siguiente a la de disparo
    (≈ la latencia real del bridge, 15-30 min tras el cierre). Si para entonces
    el precio ya tocó el stop o está más allá del objetivo, no hay trade.
    Variante TOQUE: entrada en el LVN dentro de la vela de disparo (la vela de
    disparo cuenta como perdedora si también toca el stop). NO es ejecutable con
    este pipeline, y la comparación con TARDÍA no mide el coste de la latencia:
    TARDÍA descarta los setups ya invalidados en las velas k/k+1 (filtro de
    selección), TOQUE los cuenta como pérdida.
  - Coste ida y vuelta: AUDUSD 1.4p, USDCAD 1.8p (y se imprime también +0.6p).
  - Lo que el sistema NO puede ver: el flujo de órdenes (la "agresión" de Fabio).
    Aquí la agresión no existe; el test mide si estado + zona + objetivo bastan.

Criterio de aprobación (pre-registrado), sobre la variante por defecto (tardía,
stop corto, objetivo estructural) en DESARROLLO (2020-07 → 2025-06):
  R/trade > 0 en >= 5 de los 6 años en AMBOS pares, IC95% bootstrap del conjunto
  > 0, y supera a las entradas aleatorias emparejadas en >= 0.10 R/trade.
  Solo si aprueba se corre UNA vez el holdout (2025-07 → hoy) con --holdout.

Uso (desde backend/, tras `python -m scripts.bt_data`):
    python -m scripts.bt_auction
    python -m scripts.bt_auction --holdout
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date, datetime

from scripts import bt_data
from scripts.bt_sim import (COST_PIPS, PIP, RandomBaseline, day_end, fmt, r_multiple,
                            sim, summarize)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DEV_END = date(2025, 6, 30)
MIN_DAY_BARS = 60
WINDOW = (7, 20)
VA_PCT = 0.70
ACCEPT_CLOSES = 2
DISPLACEMENT_ATR = 2.0
FAIL_BARS = 8
PULLBACK_BARS = 8
EXTRA_COST = 0.6

A_VARIANTS = [(e, m, tg) for e in ("tardia", "toque") for m in (0.5, 1.0) for tg in ("estructural", "2R")]
B_VARIANTS = [(e, m, "estructural") for e in ("tardia", "toque") for m in (0.2, 0.5)]
DEFAULT = {"A": ("tardia", 0.5, "estructural"), "B": ("tardia", 0.2, "estructural")}


# ── indicadores y perfiles ─────────────────────────────────────────────────────
def atr14(bars) -> list[float]:
    out, a = [], None
    for i, (_, _, h, l, c) in enumerate(bars):
        tr = h - l if i == 0 else max(h - l, abs(h - bars[i - 1][4]), abs(l - bars[i - 1][4]))
        a = tr if a is None else a + (tr - a) / 14
        out.append(a)
    return out


def day_profile(day_bars, pip: float):
    cnt: dict[int, int] = defaultdict(int)
    for _, _, h, l, _ in day_bars:
        for k in range(int(l / pip), int(h / pip) + 1):
            cnt[k] += 1
    kmin, kmax = min(cnt), max(cnt)
    mid = (kmin + kmax) / 2
    poc = max(cnt, key=lambda k: (cnt[k], -abs(k - mid)))
    total, acc, lo, hi = sum(cnt.values()), cnt[poc], poc, poc
    while acc < VA_PCT * total and (lo > kmin or hi < kmax):
        up = cnt.get(hi + 1, 0) if hi < kmax else -1
        dn = cnt.get(lo - 1, 0) if lo > kmin else -1
        if up >= dn:
            hi += 1; acc += up
        else:
            lo -= 1; acc += dn
    return {"poc": (poc + 0.5) * pip, "vah": (hi + 1) * pip, "val": lo * pip}


def leg_lvn(leg_bars, pip: float) -> float | None:
    lo = min(b[3] for b in leg_bars)
    hi = max(b[2] for b in leg_bars)
    rng = hi - lo
    if rng <= 0:
        return None
    w = max(pip, rng / 20)
    nb = int(rng / w) + 1
    cnt = [0] * nb
    for _, _, h, l, _ in leg_bars:
        for j in range(int((l - lo) / w), min(nb - 1, int((h - lo) / w)) + 1):
            cnt[j] += 1
    mid = lo + rng / 2
    cands = [j for j in range(nb) if 0.2 * rng <= (j + 0.5) * w <= 0.8 * rng]
    if not cands:
        return None
    j = min(cands, key=lambda j: (cnt[j], abs(lo + (j + 0.5) * w - mid)))
    return lo + (j + 0.5) * w


def split_days(bars):
    days, cur, cur_end = [], [], None
    for i, b in enumerate(bars):
        e = day_end(b[0])
        if e != cur_end:
            if cur:
                days.append((cur_end, cur))
            cur, cur_end = [], e
        cur.append(i)
    if cur:
        days.append((cur_end, cur))
    # TD devuelve velas de sábado/domingo desde 2026: los días forex válidos terminan lun-vie
    return [(e, idx) for e, idx in days if len(idx) >= MIN_DAY_BARS and e.weekday() < 5]


# ── disparos ───────────────────────────────────────────────────────────────────
def triggers_A(bars, idx, prof, atr, pip):
    """Devuelve disparos (k, lado, lvn, extremo_impulso, atr) del modelo A en el día."""
    out = []
    for s in (1, -1):
        edge = prof["vah"] if s == 1 else prof["val"]
        consec, acc_k, ext, ext_k = 0, None, None, None
        for n, k in enumerate(idx):
            _, _, h, l, c = bars[k]
            if acc_k is None:
                consec = consec + 1 if (c > edge if s == 1 else c < edge) else 0
                if consec >= ACCEPT_CLOSES:
                    acc_k = n
                    # origen = mínimo del día (LONG) / máximo (SHORT); extremo = máximo / mínimo desde ahí
                    if s == 1:
                        origin_n = min(range(n + 1), key=lambda j: bars[idx[j]][3])
                        ext_k = max(idx[origin_n:n + 1], key=lambda j: bars[j][2])
                        ext = bars[ext_k][2]
                    else:
                        origin_n = max(range(n + 1), key=lambda j: bars[idx[j]][2])
                        ext_k = min(idx[origin_n:n + 1], key=lambda j: bars[j][3])
                        ext = bars[ext_k][3]
                continue
            if (h > ext) if s == 1 else (l < ext):
                ext, ext_k = (h if s == 1 else l), k
                continue
            leg = [bars[j] for j in idx[origin_n:idx.index(ext_k) + 1]]
            rng = max(b[2] for b in leg) - min(b[3] for b in leg)
            lvn = leg_lvn(leg, pip)
            hour = bars[k][0].hour
            if (lvn is not None and rng >= DISPLACEMENT_ATR * atr[k - 1]
                    and WINDOW[0] <= hour < WINDOW[1]
                    and ((l <= lvn) if s == 1 else (h >= lvn))):
                out.append((k, "LONG" if s == 1 else "SHORT", lvn, ext, atr[k - 1]))
                break
            if (c < edge) if s == 1 else (c > edge):
                break
    return out


def triggers_B(bars, idx, prof, atr, pip):
    """Disparos (k, lado, lvn, extremo_ruptura, atr) del modelo B en el día."""
    out = []
    for s in (1, -1):  # s=1: ruptura del VAH → SHORT ; s=-1: ruptura del VAL → LONG
        edge = prof["vah"] if s == 1 else prof["val"]
        n, done = 0, False
        while n < len(idx) and not done:
            _, _, h, l, c = bars[idx[n]]
            if not ((c > edge) if s == 1 else (c < edge)):
                n += 1
                continue
            out_n, ext_n = n, n
            back_n = None
            for m in range(n, min(len(idx), n + FAIL_BARS + 1)):
                b = bars[idx[m]]
                if (b[2] > bars[idx[ext_n]][2]) if s == 1 else (b[3] < bars[idx[ext_n]][3]):
                    ext_n = m
                if m > out_n and ((b[4] < edge) if s == 1 else (b[4] > edge)):
                    back_n = m
                    break
            if back_n is None:
                n = out_n + FAIL_BARS + 1  # aceptación: se rearma si vuelve a salir
                while n < len(idx) and ((bars[idx[n]][4] > edge) if s == 1 else (bars[idx[n]][4] < edge)):
                    n += 1
                continue
            ext = bars[idx[ext_n]][2] if s == 1 else bars[idx[ext_n]][3]
            lvn = leg_lvn([bars[idx[j]] for j in range(ext_n, back_n + 1)], pip)
            for m in range(back_n + 1, min(len(idx), back_n + 1 + PULLBACK_BARS)):
                _, _, h, l, c = bars[idx[m]]
                if lvn is not None and WINDOW[0] <= bars[idx[m]][0].hour < WINDOW[1] \
                        and ((h >= lvn) if s == 1 else (l <= lvn)):
                    out.append((idx[m], "SHORT" if s == 1 else "LONG", lvn, ext, atr[idx[m] - 1]))
                    done = True
                    break
                if (c > ext) if s == 1 else (c < ext):
                    break
            n = back_n + 1
    return out


# ── ejecución de un disparo bajo una variante ──────────────────────────────────
def execute(bars, trig, model, variant, prof, pip, cost):
    k, side, lvn, ext, a = trig
    entry_mode, mult, target = variant
    s = 1 if side == "LONG" else -1
    # A: stop detrás del LVN · B: stop detrás del extremo de la ruptura fallida
    stop = (lvn if model == "A" else ext) - s * mult * a
    t_end = day_end(bars[k][0])
    if entry_mode == "toque":
        entry, i0 = lvn, k + 1
        if (bars[k][3] <= stop) if s == 1 else (bars[k][2] >= stop):
            risk = abs(entry - stop) / pip
            return None if risk <= 0 else _tp_and_result(None, side, entry, stop, risk, -risk, model, target, ext, prof, pip, cost)
    else:
        if k + 1 >= len(bars):
            return None
        nb = bars[k + 1]
        if ((min(bars[k][3], nb[3]) <= stop) if s == 1 else (max(bars[k][2], nb[2]) >= stop)):
            return None
        entry, i0 = nb[4], k + 2
    risk = s * (entry - stop) / pip
    if risk <= 0:
        return None
    tp = _target(side, entry, stop, model, target, ext, prof)
    if s * (tp - entry) <= 0:
        return None
    pips, _, _ = sim(bars, i0, side, entry, stop, tp, t_end, pip)
    return _tp_and_result(tp, side, entry, stop, risk, pips, model, target, ext, prof, pip, cost)


def _target(side, entry, stop, model, target, ext, prof):
    s = 1 if side == "LONG" else -1
    if model == "B":
        return prof["poc"]
    return ext if target == "estructural" else entry + s * 2 * abs(entry - stop)


def _tp_and_result(tp, side, entry, stop, risk, pips, model, target, ext, prof, pip, cost):
    if tp is None:
        tp = _target(side, entry, stop, model, target, ext, prof)
    s = 1 if side == "LONG" else -1
    reward = s * (tp - entry) / pip
    if reward <= 0:
        return None
    return {"side": side, "risk": risk, "reward": reward, "pips": pips,
            "R": r_multiple(pips, risk, cost), "R2": r_multiple(pips, risk, cost + EXTRA_COST)}


# ── informe ────────────────────────────────────────────────────────────────────
def run(pair: str, holdout: bool):
    bars = bt_data.load(pair)
    pip, cost = PIP[pair], COST_PIPS[pair]
    atr = atr14(bars)
    days = split_days(bars)
    base = RandomBaseline(bars, pip)
    trades = defaultdict(list)  # (modelo, variante) → trades
    for (prev_end, prev_idx), (end, idx) in zip(days, days[1:]):
        d = end.date()
        if holdout != (d > DEV_END) or d < date(2020, 7, 2):
            continue
        prof = day_profile([bars[i] for i in prev_idx], pip)
        for model, fn, variants in (("A", triggers_A, A_VARIANTS), ("B", triggers_B, B_VARIANTS)):
            for trig in fn(bars, idx, prof, atr, pip):
                for v in variants:
                    r = execute(bars, trig, model, v, prof, pip, cost)
                    if r is None:
                        continue
                    t = bars[trig[0]][0]
                    r.update(t=t, year=t.year, hour=t.hour)
                    if v == DEFAULT[model]:
                        r["rand"] = base.mean_r(t, r["side"], r["risk"], r["reward"], cost)
                    trades[(model, v)].append(r)
    return trades


def report(all_trades: dict, holdout: bool):
    split = "HOLDOUT 2025-07 → hoy" if holdout else "DESARROLLO 2020-07 → 2025-06"
    print(f"\n══════ {split} ══════")
    verdict = {}
    for model, variants in (("A", A_VARIANTS), ("B", B_VARIANTS)):
        name = "A — tendencia (LVN del impulso)" if model == "A" else "B — ruptura fallida → POC"
        print(f"\n▌Modelo {name}")
        for pair, trades in all_trades.items():
            print(f"\n  {pair}")
            for v in variants:
                rs = [t["R"] for t in trades[(model, v)]]
                tag = " ← por defecto" if v == DEFAULT[model] else ""
                print(f"    {v[0]:6} stop {v[1]:.1f}ATR {v[2]:11} {fmt(summarize(rs))}{tag}")
            dt = trades[(model, DEFAULT[model])]
            if not dt:
                continue
            years = sorted({t["year"] for t in dt})
            print("    por año (por defecto):  " + "  ".join(
                f"{y}: {summarize([t['R'] for t in dt if t['year'] == y])['r']:+.2f} "
                f"(n={sum(t['year'] == y for t in dt)})" for y in years))
            rand = [t["rand"] for t in dt if t.get("rand") is not None]
            s_def = summarize([t["R"] for t in dt])
            s_rand = summarize(rand)
            print(f"    aleatorio emparejado:   {fmt(s_rand)}")
            print(f"    con coste +{EXTRA_COST}p:       {fmt(summarize([t['R2'] for t in dt]))}")
            for lbl, f in (("riesgo <6p", lambda t: t["risk"] < 6), ("riesgo 6-10p", lambda t: 6 <= t["risk"] <= 10),
                           ("riesgo >10p", lambda t: t["risk"] > 10), ("07-12 UTC", lambda t: t["hour"] < 12),
                           ("12-16 UTC", lambda t: 12 <= t["hour"] < 16), ("16-20 UTC", lambda t: t["hour"] >= 16),
                           ("LONG", lambda t: t["side"] == "LONG"), ("SHORT", lambda t: t["side"] == "SHORT")):
                print(f"    {lbl:22} {fmt(summarize([t['R'] for t in dt if f(t)]))}")
            pos_years = sum(summarize([t['R'] for t in dt if t['year'] == y])['r'] > 0 for y in years)
            verdict.setdefault(model, []).append({
                "pair": pair, "pos_years": pos_years, "years": len(years),
                "edge_vs_rand": s_def["r"] - (s_rand.get("r") or 0), "R": [t["R"] for t in dt]})
    print("\n══════ CRITERIO PRE-REGISTRADO (variante por defecto) ══════")
    for model, rows in verdict.items():
        pooled = summarize([r for row in rows for r in row["R"]])
        years_ok = all(row["pos_years"] >= 5 for row in rows) and len(rows) == 2
        rand_ok = all(row["edge_vs_rand"] >= 0.10 for row in rows)
        ci_ok = pooled.get("lo", -1) > 0
        detail = ", ".join(f"{r['pair']} {r['pos_years']}/{r['years']} años+ , {r['edge_vs_rand']:+.3f}R vs azar" for r in rows)
        ok = years_ok and rand_ok and ci_ok if not holdout else ci_ok and rand_ok
        print(f"  Modelo {model}: {'APRUEBA' if ok else 'NO APRUEBA'} — {detail}; conjunto {fmt(pooled)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="AUDUSD,USDCAD")
    ap.add_argument("--holdout", action="store_true", help="corre SOLO el holdout 2025-07 → hoy (una vez)")
    a = ap.parse_args()
    all_trades = {p: run(p, a.holdout) for p in a.pairs.split(",")}
    report(all_trades, a.holdout)


if __name__ == "__main__":
    main()
