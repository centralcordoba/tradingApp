"""Scanner independiente: analiza pares en vivo desde Twelve Data.

No depende de las señales del Pine — hace su propia lectura técnica multi-factor
y devuelve los pares rankeados por confluencia.

Fuente: api.twelvedata.com (free tier 800 créditos/día, 8 req/min).
Requiere env var TWELVEDATA_API_KEY.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_PAIRS = [
    "XAUUSD",  # plata (XAGUSD) requiere plan Grow en Twelve Data, no incluida
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
    "AUDUSD", "NZDUSD", "USDCAD",
    "EURJPY", "GBPJPY", "EURGBP",
]

TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
TWELVEDATA_BASE = "https://api.twelvedata.com/time_series"

# Twelve Data usa slash: "EUR/USD", "XAU/USD"
def _td_symbol(pair: str) -> str:
    p = pair.upper().replace("/", "").replace("-", "")
    if p.startswith("XAU"):
        return "XAU/USD"
    if p.startswith("XAG"):
        return "XAG/USD"
    if len(p) == 6:
        return f"{p[:3]}/{p[3:]}"
    return p

# TTL alto para proteger el presupuesto del plan free (800 créditos/día)
CACHE_TTL_SECONDS = 300  # 5 min
_cache: dict[str, tuple[float, dict]] = {}
_last_error: str = ""


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_chart(pair: str, interval: str = "15min", outputsize: int = 200) -> Optional[dict]:
    """Descarga OHLC de Twelve Data. None si falla."""
    global _last_error
    if not TWELVEDATA_API_KEY:
        _last_error = "TWELVEDATA_API_KEY no configurada"
        return None

    params = {
        "symbol": _td_symbol(pair),
        "interval": interval,
        "outputsize": str(outputsize),
        "order": "ASC",  # oldest first, los indicadores calculan sobre series cronológicas
        "apikey": TWELVEDATA_API_KEY,
    }
    url = f"{TWELVEDATA_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (AI Trading Assistant Scanner)",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:250]
        except Exception:
            pass
        _last_error = f"{pair}: HTTP {e.code} — {body or e.reason}"
        return None
    except Exception as e:
        _last_error = f"{pair}: {type(e).__name__}: {e}"
        return None

    if isinstance(data, dict) and data.get("status") == "error":
        _last_error = f"{pair}: {data.get('message', 'error')}"
        return None
    return data


def _parse_ohlc(raw: dict) -> Optional[dict]:
    """Extrae listas closes/highs/lows/timestamps del formato Twelve Data."""
    values = raw.get("values") if isinstance(raw, dict) else None
    if not values:
        return None

    out_ts, out_c, out_h, out_l = [], [], [], []
    for v in values:
        try:
            c = float(v["close"])
        except (TypeError, ValueError, KeyError):
            continue
        try:
            h = float(v.get("high", c))
        except (TypeError, ValueError):
            h = c
        try:
            l = float(v.get("low", c))
        except (TypeError, ValueError):
            l = c
        out_ts.append(v.get("datetime"))
        out_c.append(c)
        out_h.append(h)
        out_l.append(l)

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
        "td_symbol": _td_symbol(pair),
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
    raw = _fetch_chart(pair)
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
        # Free tier: 8 req/min. Concurrencia 4 para dejar holgura.
        with ThreadPoolExecutor(max_workers=4) as ex:
            future_map = {ex.submit(_analyze_pair, p): p for p in to_fetch}
            for fut in as_completed(future_map):
                p = future_map[fut]
                data = fut.result()
                if data is not None:
                    _cache[p] = (now, data)
                    results.append(data)

    results.sort(key=lambda r: (-r["confluence"], -abs(r.get("change_pct", 0))))
    return results


def last_error() -> str:
    """Último mensaje de error para diagnóstico (vacío si todo OK)."""
    return _last_error
