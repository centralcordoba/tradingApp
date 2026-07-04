"""Indicadores técnicos — implementación única para todo el backend.

Antes había 3 copias (scanner puro-Python, zones numpy, stocks_client) con las
mismas matemáticas: cualquier fix había que aplicarlo 3 veces y podían divergir
en silencio. scanner/zones/radar/stocks_client importan de aquí.

Convenciones:
- Series cronológicas (más viejo primero), como las entrega _parse_ohlc.
- Wilder smoothing en RSI/ATR/ADX (estándar de la industria).
- `*_last` devuelve el último valor (float | None); `*_series` la serie completa.
"""
from __future__ import annotations

from typing import Optional, Sequence


# ─── Medias ──────────────────────────────────────────────────────────────────

def sma_last(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values: Sequence[float], period: int) -> list[float]:
    """EMA con seed SMA. La serie arranca en el índice period-1 del input."""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(float(v) * k + out[-1] * (1 - k))
    return out


def ema_last(values: Sequence[float], period: int) -> Optional[float]:
    s = ema_series(values, period)
    return s[-1] if s else None


# ─── RSI (Wilder) ────────────────────────────────────────────────────────────

def rsi_series(closes: Sequence[float], period: int = 14) -> list[Optional[float]]:
    """RSI alineado con `closes` (None durante el warm-up)."""
    n = len(closes)
    out: list[Optional[float]] = [None] * n
    if n < period + 1:
        return out
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    for i in range(period + 1, n):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    return out


def rsi_last(closes: Sequence[float], period: int = 14) -> Optional[float]:
    s = rsi_series(closes, period)
    return s[-1] if s else None


# ─── ATR (Wilder) ────────────────────────────────────────────────────────────

def atr_last(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return float(atr)


# ─── MACD ────────────────────────────────────────────────────────────────────

def macd_hist(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9,
    n_last: int = 5,
) -> list[float]:
    """Histograma MACD = MACD - señal. Devuelve los últimos `n_last` puntos."""
    if len(values) < slow + signal:
        return []
    e_fast = ema_series(values, fast)
    e_slow = ema_series(values, slow)
    offset = slow - fast
    e_fast_aligned = e_fast[offset:]
    n = min(len(e_fast_aligned), len(e_slow))
    macd = [e_fast_aligned[i] - e_slow[i] for i in range(n)]
    if len(macd) < signal:
        return []
    signal_line = ema_series(macd, signal)
    macd_aligned = macd[signal - 1:]
    m = min(len(signal_line), len(macd_aligned))
    if m == 0:
        return []
    hist = [macd_aligned[-m + i] - signal_line[-m + i] for i in range(m)]
    return hist[-n_last:] if hist else []


# ─── Bollinger ───────────────────────────────────────────────────────────────

def bbands(
    values: Sequence[float], period: int = 20, mult: float = 2.0
) -> tuple[Optional[float], Optional[float]]:
    if len(values) < period:
        return None, None
    seg = values[-period:]
    mean = sum(seg) / period
    variance = sum((v - mean) ** 2 for v in seg) / period
    std = variance ** 0.5
    return mean + mult * std, mean - mult * std


# ─── ADX ─────────────────────────────────────────────────────────────────────

def adx(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Devuelve (adx, +DI, -DI). None si no hay datos suficientes."""
    n = len(closes)
    if n < period * 2 + 1:
        return None, None, None
    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    if len(tr) < period:
        return None, None, None

    def wilder(arr: list[float]) -> list[float]:
        seed = sum(arr[:period])
        out = [seed]
        for v in arr[period:]:
            out.append(out[-1] - (out[-1] / period) + v)
        return out

    s_plus_dm = wilder(plus_dm)
    s_minus_dm = wilder(minus_dm)
    s_tr = wilder(tr)
    plus_di = [100 * pdm / t if t else 0.0 for pdm, t in zip(s_plus_dm, s_tr)]
    minus_di = [100 * mdm / t if t else 0.0 for mdm, t in zip(s_minus_dm, s_tr)]
    dx = []
    for pdi, mdi in zip(plus_di, minus_di):
        denom = pdi + mdi
        dx.append(100 * abs(pdi - mdi) / denom if denom else 0.0)
    if len(dx) < period:
        return None, plus_di[-1] if plus_di else None, minus_di[-1] if minus_di else None
    adx_val = sum(dx[:period]) / period
    for v in dx[period:]:
        adx_val = (adx_val * (period - 1) + v) / period
    return adx_val, plus_di[-1], minus_di[-1]
