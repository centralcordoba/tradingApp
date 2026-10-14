"""Núcleo del backtester: simulación walk-forward de una orden SL/TP + baselines.

Convenciones (comunes a bt_trades y bt_auction):
  - Velas M15 (t, o, h, l, c) en UTC, ts = APERTURA de la vela (como Twelve Data).
  - La simulación arranca en la vela `i0` y no ve nada antes. Si una vela toca SL y
    TP a la vez, gana el SL (no hay orden intrabar conocido → conservador).
  - Si al llegar a `t_end` no tocó nada, cierra al close de la última vela previa.
  - R = (resultado en pips − coste ida y vuelta) / riesgo en pips.
"""
from __future__ import annotations

import random
from bisect import bisect_left
from datetime import datetime, timedelta, timezone

PIP = {"AUDUSD": 0.0001, "USDCAD": 0.0001, "EURUSD": 0.0001, "GBPUSD": 0.0001,
       "USDJPY": 0.01, "EURJPY": 0.01, "XAUUSD": 0.1}
# Coste ida y vuelta aprox. FTMO. AUD/CAD = zone_signal_engine.cost_pips; el resto, estimado
COST_PIPS = {"AUDUSD": 1.4, "USDCAD": 1.8, "EURUSD": 1.0, "GBPUSD": 1.5,
             "USDJPY": 1.2, "EURJPY": 1.8, "XAUUSD": 3.0}


def day_end(t: datetime) -> datetime:
    """Siguiente 22:00 UTC (cierre del día forex) estrictamente posterior a t."""
    e = t.replace(hour=22, minute=0, second=0, microsecond=0)
    return e if e > t else e + timedelta(days=1)


def sim(bars, i0: int, side: str, entry: float, sl: float, tp: float,
        t_end: datetime, pip: float):
    """Devuelve (pips con signo, índice de salida, 'SL'|'TP'|'EOD')."""
    s = 1 if side == "LONG" else -1
    last = None
    for i in range(i0, len(bars)):
        t, _, h, l, c = bars[i]
        if t >= t_end:
            break
        if (l <= sl) if s == 1 else (h >= sl):
            return s * (sl - entry) / pip, i, "SL"
        if (h >= tp) if s == 1 else (l <= tp):
            return s * (tp - entry) / pip, i, "TP"
        last = i
    if last is None:
        return 0.0, i0, "EOD"
    return s * (bars[last][4] - entry) / pip, last, "EOD"


def r_multiple(pips: float, risk_pips: float, cost: float) -> float:
    return (pips - cost) / risk_pips


class RandomBaseline:
    """Entradas aleatorias emparejadas: mismo año, misma hora UTC, mismo lado y
    misma distancia SL/TP en pips que el trade real; entrada al close de la vela
    elegida, salida en SL/TP o fin del día forex (o `horizon` si se pasa). Aísla si el CUÁNDO aporta algo
    más allá del lado y la geometría."""

    def __init__(self, bars, pip: float, seed: int = 7):
        self.bars, self.pip = bars, pip
        self.rng = random.Random(seed)
        self.pool: dict[tuple[int, int], list[int]] = {}
        for i, (t, *_ ) in enumerate(bars[:-1]):
            if t.weekday() >= 5:  # TD trae velas de fin de semana desde 2026
                continue
            self.pool.setdefault((t.year, t.hour), []).append(i)

    def mean_r(self, t: datetime, side: str, risk_pips: float, reward_pips: float,
               cost: float, draws: int = 20, horizon: timedelta | None = None) -> float | None:
        pool = self.pool.get((t.year, t.hour))
        if not pool:
            return None
        s = 1 if side == "LONG" else -1
        acc = []
        for _ in range(draws):
            i = self.rng.choice(pool)
            e = self.bars[i][4]
            sl = e - s * risk_pips * self.pip
            tp = e + s * reward_pips * self.pip
            t_end = self.bars[i][0] + horizon if horizon else day_end(self.bars[i][0])
            p, _, _ = sim(self.bars, i + 1, side, e, sl, tp, t_end, self.pip)
            acc.append(r_multiple(p, risk_pips, cost))
        return sum(acc) / len(acc)


def index_at(bars, t: datetime) -> int:
    """Índice de la primera vela con apertura >= t."""
    return bisect_left(bars, (t,))


def bootstrap_ci(xs: list[float], n: int = 2000, seed: int = 11) -> tuple[float, float]:
    if len(xs) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    m = sorted(sum(rng.choice(xs) for _ in xs) / len(xs) for _ in range(n))
    return m[int(0.025 * n)], m[int(0.975 * n)]


def summarize(rs: list[float]) -> dict:
    if not rs:
        return {"n": 0}
    lo, hi = bootstrap_ci(rs)
    return {"n": len(rs), "wr": sum(r > 0 for r in rs) / len(rs),
            "r": sum(rs) / len(rs), "tot": sum(rs), "lo": lo, "hi": hi}


def fmt(s: dict) -> str:
    if not s.get("n"):
        return "n=0"
    return (f"n={s['n']:>4}  WR {s['wr']:4.0%}  R/trade {s['r']:+.3f}  "
            f"[{s['lo']:+.3f}, {s['hi']:+.3f}]  total {s['tot']:+7.1f}R")


UTC = timezone.utc
