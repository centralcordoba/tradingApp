"""Stocks — cliente de Twelve Data + cálculo de indicadores en Python puro.

Diseñado para consumir el mismo TWELVEDATA_API_KEY que ya usa el scanner
de forex. Cache propio (memoria) con TTL por intervalo. Sin dependencias
nuevas — solo `urllib` (igual que `scanner.py`).
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from .constants import (
    CACHE_TTL_INTRADAY,
    CACHE_TTL_DAILY,
    CACHE_TTL_QUOTE,
    CACHE_TTL_SEARCH,
    HTTP_TIMEOUT_DEFAULT,
    SMA_PERIOD_20,
    SMA_PERIOD_50,
    SMA_PERIOD_200,
    EMA_PERIOD_20,
    EMA_PERIOD_50,
    RSI_PERIOD,
    MACD_FAST,
    MACD_SLOW,
    MACD_SIGNAL,
    MACD_HIST_LOOKBACK,
    BBANDS_PERIOD,
    BBANDS_MULT,
    ADX_PERIOD,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TD_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
TD_BASE = "https://api.twelvedata.com"

# TTL por intervalo (segundos). Intraday = 5 min para coincidir con la
# frecuencia de polling del frontend; daily = 1 h porque la vela cierra
# una vez por día.
CACHE_TTL = {
    "15min": CACHE_TTL_INTRADAY,
    "1h": CACHE_TTL_INTRADAY,
    "4h": CACHE_TTL_INTRADAY,
    "1day": CACHE_TTL_DAILY,
}
DEFAULT_TTL = CACHE_TTL_INTRADAY
QUOTE_TTL = CACHE_TTL_QUOTE
SEARCH_TTL = CACHE_TTL_SEARCH

VALID_INTERVALS = ("15min", "1h", "4h", "1day")

# ---------------------------------------------------------------------------
# Cache en memoria
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, dict]] = {}


def _cache_get(key: str, ttl: int) -> Optional[dict]:
    entry = _cache.get(key)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > ttl:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: dict) -> None:
    _cache[key] = (time.time(), value)


def clear_cache(prefix: Optional[str] = None) -> None:
    if prefix is None:
        _cache.clear()
        return
    for k in list(_cache.keys()):
        if k.startswith(prefix):
            _cache.pop(k, None)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class StocksUpstreamError(Exception):
    """Error al hablar con Twelve Data (404 símbolo, 429 rate limit, etc.)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _http_get(path: str, params: dict, timeout: int = HTTP_TIMEOUT_DEFAULT) -> dict:
    if not TD_API_KEY:
        raise StocksUpstreamError(500, "TWELVEDATA_API_KEY no configurada")
    full_params = {**params, "apikey": TD_API_KEY}
    url = f"{TD_BASE}{path}?{urllib.parse.urlencode(full_params)}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (AI Trading Assistant Stocks)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:250]
        except Exception:
            pass
        raise StocksUpstreamError(e.code, f"HTTP {e.code} — {body or e.reason}")
    except Exception as e:
        raise StocksUpstreamError(0, f"{type(e).__name__}: {e}")

    if isinstance(data, dict) and data.get("status") == "error":
        msg = data.get("message", "error desconocido")
        # Heurística: TD devuelve mensajes como "**symbol** not found ..."
        # cuando el ticker no existe.
        if "not found" in msg.lower() or "could not be located" in msg.lower():
            raise StocksUpstreamError(404, msg)
        if "rate limit" in msg.lower() or data.get("code") == 429:
            raise StocksUpstreamError(429, msg)
        raise StocksUpstreamError(502, msg)

    return data


# ---------------------------------------------------------------------------
# Endpoints públicos: search / quote / time_series
# ---------------------------------------------------------------------------

def search(query: str, limit: int = 12) -> list[dict]:
    """Symbol search de Twelve Data — gratis, no consume créditos."""
    q = (query or "").strip()
    if not q:
        return []
    cache_key = f"search:{q.lower()}:{limit}"
    cached = _cache_get(cache_key, SEARCH_TTL)
    if cached:
        return cached["matches"]
    data = _http_get("/symbol_search", {"symbol": q, "outputsize": str(limit)})
    raw = data.get("data") or []
    matches = []
    for m in raw:
        matches.append({
            "symbol": m.get("symbol", ""),
            "instrument_name": m.get("instrument_name", ""),
            "exchange": m.get("exchange", ""),
            "country": m.get("country", ""),
            "type": m.get("instrument_type") or m.get("type", ""),
        })
    _cache_set(cache_key, {"matches": matches})
    return matches


def quote(symbol: str) -> dict:
    """Quote en tiempo real (1 crédito). Cache 5 min."""
    sym = symbol.upper().strip()
    if not sym:
        raise StocksUpstreamError(400, "symbol vacío")
    cache_key = f"quote:{sym}"
    cached = _cache_get(cache_key, QUOTE_TTL)
    if cached:
        return cached
    data = _http_get("/quote", {"symbol": sym})
    is_open = data.get("is_market_open")
    market_status = "open" if (is_open is True or is_open == "true") else "closed"
    out = {
        "symbol": sym,
        "price": _safe_float(data.get("close"), 0.0),
        "change": _safe_float(data.get("change"), 0.0),
        "percent_change": _safe_float(data.get("percent_change"), 0.0),
        "timestamp": data.get("datetime", ""),
        "marketStatus": market_status,
    }
    _cache_set(cache_key, out)
    return out


def time_series(symbol: str, interval: str, outputsize: int = 250) -> dict:
    """OHLC bruto (1 crédito). Cache según intervalo (5 min / 1 h)."""
    sym = symbol.upper().strip()
    if interval not in VALID_INTERVALS:
        raise StocksUpstreamError(400, f"interval inválido: {interval}")
    cache_key = f"ts:{sym}:{interval}:{outputsize}"
    ttl = CACHE_TTL.get(interval, DEFAULT_TTL)
    cached = _cache_get(cache_key, ttl)
    if cached:
        return cached
    data = _http_get("/time_series", {
        "symbol": sym,
        "interval": interval,
        "outputsize": str(outputsize),
        "order": "ASC",
    })
    values = data.get("values") or []
    closes, highs, lows, ts_list = [], [], [], []
    for v in values:
        c = _safe_float(v.get("close"), None)
        if c is None:
            continue
        closes.append(c)
        highs.append(_safe_float(v.get("high"), c))
        lows.append(_safe_float(v.get("low"), c))
        ts_list.append(v.get("datetime", ""))
    if len(closes) < 30:
        raise StocksUpstreamError(404, f"Sin suficientes datos para {sym}")
    out = {
        "symbol": sym,
        "interval": interval,
        "ts": ts_list,
        "close": closes,
        "high": highs,
        "low": lows,
    }
    _cache_set(cache_key, out)
    return out


def _safe_float(v, default):
    try:
        if v is None or v == "":
            return default
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Indicadores (Python puro, alineados con el frontend signalEngine)
# ---------------------------------------------------------------------------

def _sma(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema_series(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _ema_last(values: list[float], period: int) -> Optional[float]:
    s = _ema_series(values, period)
    return s[-1] if s else None


def _rsi_last(values: list[float], period: int = RSI_PERIOD) -> Optional[float]:
    if len(values) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(values)):
        diff = values[i] - values[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd_hist(
    values: list[float],
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
    n_last: int = MACD_HIST_LOOKBACK,
) -> list[float]:
    """Histograma MACD = MACD - señal. Devuelve los últimos `n_last` puntos."""
    if len(values) < slow + signal:
        return []
    ema_fast = _ema_series(values, fast)
    ema_slow = _ema_series(values, slow)
    # ema_fast indexa desde fast-1, ema_slow desde slow-1; alineamos al inicio
    # común recortando ema_fast por (slow - fast) puntos del frente.
    offset = slow - fast
    ema_fast_aligned = ema_fast[offset:]
    n = min(len(ema_fast_aligned), len(ema_slow))
    macd = [ema_fast_aligned[i] - ema_slow[i] for i in range(n)]
    if len(macd) < signal:
        return []
    signal_line = _ema_series(macd, signal)
    macd_aligned = macd[signal - 1:]
    m = min(len(signal_line), len(macd_aligned))
    if m == 0:
        return []
    hist = [macd_aligned[-m + i] - signal_line[-m + i] for i in range(m)]
    return hist[-n_last:] if hist else []


def _bbands(
    values: list[float],
    period: int = BBANDS_PERIOD,
    mult: float = BBANDS_MULT,
) -> tuple[Optional[float], Optional[float]]:
    if len(values) < period:
        return None, None
    seg = values[-period:]
    mean = sum(seg) / period
    variance = sum((v - mean) ** 2 for v in seg) / period
    std = variance ** 0.5
    return mean + mult * std, mean - mult * std


def _adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = ADX_PERIOD,
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
        tr.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
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


# ---------------------------------------------------------------------------
# Bundle público (lo que consume el frontend signalEngine)
# ---------------------------------------------------------------------------

def indicator_bundle(symbol: str, interval: str) -> dict:
    """Devuelve el IndicatorBundle listo para signalEngine.calculateSignal.

    Combina:
      - 1 crédito de /time_series (250 velas, intervalo según horizonte).
      - 1 crédito opcional de /quote (precio + market status). Si falla,
        usamos el último close de la serie y `marketStatus="closed"` por
        precaución.

    Total típico: 2 créditos por consulta. Cache TTL del time_series y
    quote evitan repetir si el frontend pega varias veces.
    """
    sym = symbol.upper().strip()
    ts = time_series(sym, interval, 250)
    closes = ts["close"]
    highs = ts["high"]
    lows = ts["low"]
    timestamps = ts["ts"]
    if not closes:
        raise StocksUpstreamError(404, f"Sin datos para {sym}")

    last_close = closes[-1]
    last_ts = timestamps[-1] if timestamps else ""

    # Indicadores
    upper, lower = _bbands(closes, 20, 2.0)
    adx, pdi, mdi = _adx(highs, lows, closes, 14)
    macd_hist = _macd_hist(closes, 12, 26, 9, 5)

    # Quote para precio en tiempo real + market status — si falla usamos
    # el último close y marcamos closed.
    market_status = "closed"
    price = last_close
    try:
        q = quote(sym)
        if q.get("price"):
            price = q["price"]
        market_status = q.get("marketStatus", "closed")
    except StocksUpstreamError:
        pass

    return {
        "symbol": sym,
        "interval": interval,
        "generatedAt": last_ts or datetime.now(timezone.utc).isoformat(),
        "price": price,
        "ma20": _sma(closes, SMA_PERIOD_20),
        "ma50": _sma(closes, SMA_PERIOD_50),
        "ma200": _sma(closes, SMA_PERIOD_200) if len(closes) >= SMA_PERIOD_200 else None,
        "ema20": _ema_last(closes, EMA_PERIOD_20),
        "ema50": _ema_last(closes, EMA_PERIOD_50),
        "rsi14": _rsi_last(closes, RSI_PERIOD),
        "macdHist": macd_hist,
        "bbandsUpper": upper,
        "bbandsLower": lower,
        "adx": adx,
        "plusDI": pdi,
        "minusDI": mdi,
        "marketStatus": market_status,
    }
