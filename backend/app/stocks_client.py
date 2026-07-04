"""Stocks — cliente de Twelve Data + cálculo de indicadores en Python puro.

Diseñado para consumir el mismo TWELVEDATA_API_KEY que ya usa el scanner
de forex. Cache propio (memoria) con TTL por intervalo. Sin dependencias
nuevas — solo `urllib` (igual que `scanner.py`).
"""
from __future__ import annotations

import math
import os
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

from . import td_client
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
    # Vía td_client: rate limit global 8/min compartido con el scanner forex
    # (antes eran dos clientes ciegos gastando la misma cuota) + contador de
    # créditos. symbol_search es gratis (credits=0, solo cuenta el request).
    credits = 0 if "symbol_search" in path else 1
    data, err = td_client.get_json(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (AI Trading Assistant Stocks)",
        },
        timeout=timeout,
        credits=credits,
    )
    if err is not None:
        if err.startswith("HTTP "):
            try:
                code = int(err.split()[1])
            except (ValueError, IndexError):
                code = 0
            raise StocksUpstreamError(code, err)
        raise StocksUpstreamError(0, err)

    if isinstance(data, dict) and data.get("status") == "error":
        msg = data.get("message", "error desconocido")
        msg_lower = msg.lower()
        # Símbolo restringido a plan pago de TD (Pro/Venture/Ultra).
        # Status 402 (Payment Required) — el frontend lo distingue de un 404
        # para mostrar mensaje accionable ("probá otro ticker").
        plan_gated_patterns = (
            "available starting with",
            "or venture plan",
            "or pro plan",
            "consider upgrading",
            "upgrade your plan",
        )
        if any(p in msg_lower for p in plan_gated_patterns):
            raise StocksUpstreamError(402, msg)
        # Heurística: TD devuelve mensajes con varias formas cuando el ticker
        # no existe, no está soportado por el plan free, o no hay data.
        # Todas estas las mapeamos a 404 — el frontend las muestra como
        # "Ticker no encontrado".
        not_found_patterns = (
            "not found",
            "could not be located",
            "not available",
            "not supported",
            "no data",
            "no historical data",
            "invalid symbol",
            "not subscribed",
            "is not a valid symbol",
        )
        if any(p in msg_lower for p in not_found_patterns):
            raise StocksUpstreamError(404, msg)
        if "rate limit" in msg_lower or data.get("code") == 429:
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
# Indicadores — implementación única en indicators.py (alineados con el
# frontend signalEngine). Aliases con defaults propios de stocks.
# ---------------------------------------------------------------------------

from .indicators import (  # noqa: E402
    adx as _indicators_adx,
    bbands as _indicators_bbands,
    ema_last as _ema_last,
    ema_series as _ema_series,
    macd_hist as _indicators_macd_hist,
    rsi_last as _rsi_last,
    sma_last as _sma,
)


def _macd_hist(
    values: list[float],
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
    n_last: int = MACD_HIST_LOOKBACK,
) -> list[float]:
    return _indicators_macd_hist(values, fast=fast, slow=slow, signal=signal, n_last=n_last)


def _bbands(
    values: list[float],
    period: int = BBANDS_PERIOD,
    mult: float = BBANDS_MULT,
) -> tuple[Optional[float], Optional[float]]:
    return _indicators_bbands(values, period=period, mult=mult)


def _adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = ADX_PERIOD,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    return _indicators_adx(highs, lows, closes, period=period)


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
