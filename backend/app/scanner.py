"""Scanner independiente: analiza pares en vivo desde Yahoo Finance.

No depende de las señales del Pine — hace su propia lectura técnica multi-factor
y devuelve los pares rankeados por confluencia.

Fuente: query1.finance.yahoo.com (público, sin API key, sólo urllib).
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_PAIRS = [
    "XAUUSD", "XAGUSD",
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
    "AUDUSD", "NZDUSD", "USDCAD",
    "EURJPY", "GBPJPY", "EURGBP",
]

# Yahoo usa sufijo "=X" para forex; metales son futuros
_YAHOO_OVERRIDE = {
    "XAUUSD": "GC=F",  # oro: contrato de futuros CME
    "XAGUSD": "SI=F",  # plata: contrato de futuros CME
}

def _yahoo_symbol(pair: str) -> str:
    p = pair.upper()
    return _YAHOO_OVERRIDE.get(p, f"{p}=X")

CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[float, dict]] = {}


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_chart(yahoo_symbol: str, interval: str = "15m", rng: str = "5d") -> Optional[dict]:
    """Descarga OHLC de Yahoo Finance. None si falla."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(yahoo_symbol)}?interval={interval}&range={rng}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (AI Trading Assistant Scanner)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _parse_ohlc(raw: dict) -> Optional[dict]:
    """Extrae listas closes/highs/lows/timestamps. Limpia None."""
    try:
        result = raw["chart"]["result"][0]
        ts = result.get("timestamp") or []
        q = result["indicators"]["quote"][0]
        closes = q.get("close") or []
        highs = q.get("high") or []
        lows = q.get("low") or []
    except Exception:
        return None

    # Filtra índices donde close sea None
    out_ts, out_c, out_h, out_l = [], [], [], []
    for i, c in enumerate(closes):
        if c is None:
            continue
        out_ts.append(ts[i] if i < len(ts) else None)
        out_c.append(float(c))
        h = highs[i] if i < len(highs) else None
        l = lows[i] if i < len(lows) else None
        out_h.append(float(h) if h is not None else float(c))
        out_l.append(float(l) if l is not None else float(c))

    if len(out_c) < 60:
        return None

    return {"ts": out_ts, "close": out_c, "high": out_h, "low": out_l}


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------

def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    # Prepend None-placeholder para alinear índices: longitud = len(values) - period + 1
    return out


def _rsi(values: list[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1:
        return None
    gains, losses = 0.0, 0.0
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


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_pair(pair: str, ohlc: dict) -> dict:
    """Evalúa 7 factores direccionales + salud. Devuelve card completa."""
    closes = ohlc["close"]
    highs = ohlc["high"]
    lows = ohlc["low"]

    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200) if len(closes) >= 200 else []

    last_close = closes[-1]
    prev_close = closes[-2] if len(closes) > 1 else last_close
    day_open = closes[-96] if len(closes) >= 96 else closes[0]
    change_pct = ((last_close - day_open) / day_open) * 100 if day_open else 0.0

    rsi = _rsi(closes, 14)
    atr = _atr(highs, lows, closes, 14)

    # Posición en rango últimas 50 velas
    lookback = closes[-50:]
    rng_hi = max(lookback)
    rng_lo = min(lookback)
    range_pos = (last_close - rng_lo) / (rng_hi - rng_lo) if rng_hi > rng_lo else 0.5

    # Impulso 5 velas
    mom_ret = (last_close - closes[-6]) / closes[-6] if len(closes) >= 6 and closes[-6] else 0.0

    factors = []

    # 1. EMA9 vs EMA21 (trend corto)
    if ema9 and ema21:
        val = 1 if ema9[-1] > ema21[-1] else -1
        factors.append({
            "key": "ema_short",
            "label": "EMA9 vs EMA21",
            "desc": "Tendencia corta alcista" if val > 0 else "Tendencia corta bajista",
            "value": val,
        })

    # 2. EMA21 vs EMA50 (trend medio)
    if ema21 and ema50:
        val = 1 if ema21[-1] > ema50[-1] else -1
        factors.append({
            "key": "ema_medium",
            "label": "EMA21 vs EMA50",
            "desc": "Tendencia media alcista" if val > 0 else "Tendencia media bajista",
            "value": val,
        })

    # 3. Precio vs EMA50 (sesgo estructural)
    if ema50:
        val = 1 if last_close > ema50[-1] else -1
        factors.append({
            "key": "price_ema50",
            "label": "Precio vs EMA50",
            "desc": "Precio sobre EMA50" if val > 0 else "Precio bajo EMA50",
            "value": val,
        })

    # 4. Precio vs EMA200 (macro)
    if ema200:
        val = 1 if last_close > ema200[-1] else -1
        factors.append({
            "key": "macro",
            "label": "Macro (EMA200)",
            "desc": "Sesgo macro alcista" if val > 0 else "Sesgo macro bajista",
            "value": val,
        })

    # 5. RSI momentum
    if rsi is not None:
        if 50 <= rsi < 70:
            val = 1
            desc = f"RSI {rsi:.0f} — momentum alcista sano"
        elif 30 < rsi < 50:
            val = -1
            desc = f"RSI {rsi:.0f} — momentum bajista sano"
        elif rsi >= 70:
            val = 0
            desc = f"RSI {rsi:.0f} — sobrecompra (agotamiento)"
        else:
            val = 0
            desc = f"RSI {rsi:.0f} — sobreventa (agotamiento)"
        factors.append({"key": "rsi", "label": "RSI 14", "desc": desc, "value": val})

    # 6. Posición en rango (50 velas)
    if range_pos < 0.3:
        val = 1
        desc = "Zona de descuento (parte baja del rango)"
    elif range_pos > 0.7:
        val = -1
        desc = "Zona premium (parte alta del rango)"
    else:
        val = 0
        desc = "Precio en mitad del rango"
    factors.append({"key": "range_pos", "label": "Posición en rango", "desc": desc, "value": val})

    # 7. Impulso 5 velas
    if mom_ret > 0.001:
        val = 1
        desc = f"Impulso reciente +{mom_ret*100:.2f}%"
    elif mom_ret < -0.001:
        val = -1
        desc = f"Impulso reciente {mom_ret*100:.2f}%"
    else:
        val = 0
        desc = "Sin impulso claro"
    factors.append({"key": "momentum", "label": "Impulso 5v", "desc": desc, "value": val})

    bias = sum(f["value"] for f in factors)
    total_weight = sum(abs(f["value"]) or 1 for f in factors) or len(factors)
    confluence = abs(bias)
    # max confluencia posible: cada factor puede aportar 1 en valor absoluto
    max_confluence = len(factors)

    if bias >= 3:
        side = "LONG"
    elif bias <= -3:
        side = "SHORT"
    else:
        side = "NEUTRAL"

    # Sparkline: últimos 60 closes normalizados
    spark = closes[-60:]

    return {
        "pair": pair,
        "yahoo_symbol": _yahoo_symbol(pair),
        "price": round(last_close, 5),
        "prev_close": round(prev_close, 5),
        "change_pct": round(change_pct, 2),
        "rsi": round(rsi, 1) if rsi is not None else None,
        "atr": round(atr, 5) if atr is not None else None,
        "range_pos": round(range_pos, 2),
        "bias": bias,
        "side": side,
        "confluence": confluence,
        "max": max_confluence,
        "factors": factors,
        "spark": [round(c, 5) for c in spark],
    }


def _analyze_pair(pair: str) -> Optional[dict]:
    """Descarga + scoring para un par. None si falla."""
    raw = _fetch_chart(_yahoo_symbol(pair))
    if raw is None:
        return None
    ohlc = _parse_ohlc(raw)
    if ohlc is None:
        return None
    try:
        return _score_pair(pair, ohlc)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def scan_pairs(pairs: Optional[list[str]] = None) -> list[dict]:
    """Escanea pares en paralelo. Devuelve lista rankeada por confluencia desc.

    Cachea cada par individualmente con TTL, para que recargas rápidas no
    machaquen Yahoo.
    """
    pairs = pairs or DEFAULT_PAIRS
    now = time.time()
    results: list[dict] = []
    to_fetch: list[str] = []

    for p in pairs:
        entry = _cache.get(p)
        if entry and (now - entry[0]) < CACHE_TTL_SECONDS:
            results.append(entry[1])
        else:
            to_fetch.append(p)

    if to_fetch:
        with ThreadPoolExecutor(max_workers=8) as ex:
            future_map = {ex.submit(_analyze_pair, p): p for p in to_fetch}
            for fut in as_completed(future_map):
                p = future_map[fut]
                data = fut.result()
                if data is not None:
                    _cache[p] = (now, data)
                    results.append(data)

    results.sort(key=lambda r: (-r["confluence"], -abs(r.get("change_pct", 0))))
    return results
