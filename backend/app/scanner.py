"""Scanner independiente: analiza pares en vivo desde Twelve Data.

No depende de las señales del Pine — hace su propia lectura técnica multi-factor
y devuelve los pares rankeados por confluencia.

Sobre M5 (configurable) para scalping 0-30 min.

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

from .constants import (
    CACHE_TTL_OHLC_SCANNER,
    HTTP_TIMEOUT_DEFAULT,
    SCANNER_INTERVAL,
    SCANNER_OUTPUTSIZE,
    SCANNER_MIN_CANDLES,
    SCANNER_CONFLUENCE_THRESHOLD_TREND,
    SCANNER_CONFLUENCE_THRESHOLD_NEUTRAL,
    SCANNER_RANGE_DISCOUNT,
    SCANNER_RANGE_PREMIUM,
    SCANNER_RANGE_EXTREME_LOW,
    SCANNER_RANGE_EXTREME_HIGH,
    SCANNER_RSI_OVERBOUGHT_EXTREME,
    SCANNER_RSI_OVERSOLD_EXTREME,
    SCANNER_RSI_PULLBACK_LOW,
    SCANNER_RSI_PULLBACK_HIGH,
    SCANNER_RSI_EXHAUSTION,
    SCANNER_EMA9_ATR_EXTENDED,
    SCANNER_EMA9_ATR_SKIP,
    SCANNER_STRUCT_LOOKBACK,
    SCANNER_MOMENTUM_THRESHOLD,
    EMA_PERIOD_9,
    EMA_PERIOD_21,
    EMA_PERIOD_50,
    RSI_PERIOD,
    ATR_PERIOD,
    TWELVEDATA_CONCURRENT_WORKERS,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_PAIRS = [
    "USDJPY", "USDCAD", "AUDUSD",
    "EURUSD", "USDCHF", "GBPUSD",
]

TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
TWELVEDATA_BASE = "https://api.twelvedata.com/time_series"

# Twelve Data usa slash: "EUR/USD"
def _td_symbol(pair: str) -> str:
    p = pair.upper().replace("/", "").replace("-", "")
    if len(p) == 6:
        return f"{p[:3]}/{p[3:]}"
    return p

# TTL alto para proteger el presupuesto del plan free (800 créditos/día).
# 15 min implica 2-3 ciclos de poll del frontend (5 min) sirviendo desde cache.
CACHE_TTL_SECONDS = CACHE_TTL_OHLC_SCANNER
_cache: dict[str, tuple[float, dict]] = {}          # scored cards (scan_pairs)
_ohlc_cache: dict[str, tuple[float, dict]] = {}     # raw OHLC (compartido con radar)
_last_error: str = ""


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_chart(pair: str, interval: str = SCANNER_INTERVAL, outputsize: int = SCANNER_OUTPUTSIZE) -> Optional[dict]:
    """Descarga OHLC de Twelve Data. None si falla. Cachea el crudo 5 min
    para que scanner y radar compartan la misma respuesta sin duplicar fetches."""
    global _last_error
    if not TWELVEDATA_API_KEY:
        _last_error = "TWELVEDATA_API_KEY no configurada"
        return None

    cache_key = f"{pair}:{interval}:{outputsize}"
    now = time.time()
    entry = _ohlc_cache.get(cache_key)
    if entry and (now - entry[0]) < CACHE_TTL_SECONDS:
        return entry[1]

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
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_DEFAULT) as r:
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

    _ohlc_cache[cache_key] = (now, data)
    return data


def _parse_ohlc(raw: dict) -> Optional[dict]:
    """Extrae listas opens/closes/highs/lows/timestamps del formato Twelve Data."""
    values = raw.get("values") if isinstance(raw, dict) else None
    if not values:
        return None

    out_ts, out_o, out_c, out_h, out_l = [], [], [], [], []
    for v in values:
        try:
            c = float(v["close"])
        except (TypeError, ValueError, KeyError):
            continue
        try:
            o = float(v.get("open", c))
        except (TypeError, ValueError):
            o = c
        try:
            h = float(v.get("high", c))
        except (TypeError, ValueError):
            h = c
        try:
            l = float(v.get("low", c))
        except (TypeError, ValueError):
            l = c
        out_ts.append(v.get("datetime"))
        out_o.append(o)
        out_c.append(c)
        out_h.append(h)
        out_l.append(l)

    if len(out_c) < SCANNER_MIN_CANDLES:
        return None

    return {"ts": out_ts, "open": out_o, "close": out_c, "high": out_h, "low": out_l}


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
    return out


def _rsi(values: list[float], period: int = RSI_PERIOD) -> Optional[float]:
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


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = ATR_PERIOD) -> Optional[float]:
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
# Estructura de mercado (HH/HL/LH/LL) sobre N últimas velas
# ---------------------------------------------------------------------------

def _detect_structure(closes: list[float], highs: list[float], lows: list[float], lookback: int = 50) -> dict:
    """Detecta estructura de mercado tipo Smart Money sobre las últimas `lookback` velas.

    Devuelve:
        - last_move: "HH" | "HL" | "LH" | "LL" | "RANGE"
        - description: texto explicativo
        - bullish: bool|null
    """
    n = len(closes)
    if n < lookback + 5:
        return {
            "last_move": "RANGE",
            "description": "Datos insuficientes para estructura",
            "bullish": None,
        }

    c = closes[-lookback:]
    h = highs[-lookback:]
    l = lows[-lookback:]

    # Detectar swings: pivot high / pivot low con ventana=2
    window = 2
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []

    for i in range(window, len(c) - window):
        if h[i] > max(h[i - window:i]) and h[i] > max(h[i + 1:i + window + 1]):
            swing_highs.append((i, h[i]))
        if l[i] < min(l[i - window:i]) and l[i] < min(l[i + 1:i + window + 1]):
            swing_lows.append((i, l[i]))

    if not swing_highs or not swing_lows:
        return {
            "last_move": "RANGE",
            "description": "Sin swings claros — consolidación",
            "bullish": None,
        }

    # Ordenar por índice
    all_swings = sorted([(i, p, "H") for i, p in swing_highs] + [(i, p, "L") for i, p in swing_lows])

    # Extraer últimos 3 swings significativos (evitar duplicados del mismo lado consecutivo)
    filtered: list[tuple[int, float, str]] = []
    for i, p, k in all_swings:
        if not filtered:
            filtered.append((i, p, k))
            continue
        if k != filtered[-1][2]:
            filtered.append((i, p, k))
    
    # Comparar últimos dos del mismo tipo
    if len(filtered) < 3:
        return {
            "last_move": "RANGE",
            "description": "Swings insuficientes",
            "bullish": None,
        }

    # Últimos 2 highs
    last_highs = [p for _, p, k in filtered if k == "H"][-2:]
    last_lows = [p for _, p, k in filtered if k == "L"][-2:]

    if len(last_highs) == 2 and len(last_lows) == 2:
        if last_highs[1] > last_highs[0] and last_lows[1] > last_lows[0]:
            return {"last_move": "HH", "description": "Highs más altos + lows más altos — tendencia alcista", "bullish": True}
        if last_highs[1] > last_highs[0] and last_lows[1] < last_lows[0]:
            return {"last_move": "HL", "description": "High más alto, low más bajo — posible acumulación", "bullish": True}
        if last_highs[1] < last_highs[0] and last_lows[1] < last_lows[0]:
            return {"last_move": "LL", "description": "Highs más bajos + lows más bajos — tendencia bajista", "bullish": False}
        if last_highs[1] < last_highs[0] and last_lows[1] > last_lows[0]:
            return {"last_move": "LH", "description": "High más bajo, low más alto — posible distribución", "bullish": False}

    return {"last_move": "RANGE", "description": "Sin patrón estructural claro", "bullish": None}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_pair(pair: str, ohlc: dict) -> dict:
    """Evalúa 7 factores direccionales + salud. Devuelve card completa.
    
    Diseñado para scalping M5 (0-30 min):
    - Estructura de mercado (HH/HL/LH/LL) reemplaza a EMA200 como factor macro
    - RSI optimizado para pullback en tendencia (40-60 cerca del EMA9 = +1)
    - Factor EXTENDED mide distancia al EMA9 en ×ATR → evita entradas tardías
    """
    closes = ohlc["close"]
    highs = ohlc["high"]
    lows = ohlc["low"]

    ema9 = _ema(closes, EMA_PERIOD_9)
    ema21 = _ema(closes, EMA_PERIOD_21)
    ema50 = _ema(closes, EMA_PERIOD_50)

    last_close = closes[-1]
    prev_close = closes[-2] if len(closes) > 1 else last_close
    # Para M5, 288 velas ≈ 24h. Usar primera del día si tenemos suficientes.
    day_ago_idx = -288 if len(closes) >= 288 else (-96 if len(closes) >= 96 else 0)
    day_open = closes[day_ago_idx] if day_ago_idx != 0 else closes[0]
    change_pct = ((last_close - day_open) / day_open) * 100 if day_open else 0.0

    rsi = _rsi(closes, RSI_PERIOD)
    atr = _atr(highs, lows, closes, ATR_PERIOD)

    # Posición en rango últimas 50 velas (~4h en M5 = contexto de sesión)
    lookback = closes[-50:]
    rng_hi = max(lookback)
    rng_lo = min(lookback)
    range_pos = (last_close - rng_lo) / (rng_hi - rng_lo) if rng_hi > rng_lo else 0.5

    # Impulso 5 velas (~25 min)
    mom_ret = (last_close - closes[-6]) / closes[-6] if len(closes) >= 6 and closes[-6] else 0.0
    mom_ret_threshold = SCANNER_MOMENTUM_THRESHOLD

    # Estructura de mercado (reemplaza EMA200)
    struct = _detect_structure(closes, highs, lows, lookback=SCANNER_STRUCT_LOOKBACK)

    # EXTENDED: distancia al EMA9 en multiplicadores de ATR
    ema9_dist_atr: Optional[float] = None
    extended_status = "normal"
    if atr is not None and atr > 0 and ema9:
        ema9_dist_atr = abs(last_close - ema9[-1]) / atr
        if ema9_dist_atr >= SCANNER_EMA9_ATR_SKIP:
            extended_status = "skip"
        elif ema9_dist_atr >= SCANNER_EMA9_ATR_EXTENDED:
            extended_status = "extended"

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

    # 4. Estructura de mercado (HH/HL/LH/LL) — reemplaza EMA200
    if struct["bullish"] is not None:
        val = 1 if struct["bullish"] else -1
        factors.append({
            "key": "structure",
            "label": f"Estructura ({struct['last_move']})",
            "desc": struct["description"],
            "value": val,
        })
    else:
        factors.append({
            "key": "structure",
            "label": "Estructura",
            "desc": struct["description"],
            "value": 0,
        })

    # 5. RSI momentum / pullback — LÓGICA CORREGIDA PARA SCALPING
    if rsi is not None:
        # En pullback al EMA9 con precio saludable: RSI 40-60 = zona de entrada
        in_pullback_zone = SCANNER_RSI_PULLBACK_LOW <= rsi <= SCANNER_RSI_PULLBACK_HIGH
        # Exhaustion: RSI extremo + precio extendido
        is_exhausted = rsi >= SCANNER_RSI_EXHAUSTION or rsi <= (100 - SCANNER_RSI_EXHAUSTION)
        # Agotamiento clásico
        is_overbought = rsi >= SCANNER_RSI_OVERBOUGHT_EXTREME
        is_oversold = rsi <= SCANNER_RSI_OVERSOLD_EXTREME

        if in_pullback_zone and extended_status != "skip":
            # RSI en zona de pullback + precio medio-sano = oportunidad
            val = 1 if ema9 and last_close > ema9[-1] else (-1 if ema9 and last_close < ema9[-1] else 0)
            desc = f"RSI {rsi:.0f} — pullback técnico en tendencia"
        elif is_overbought and extended_status in ("extended", "skip"):
            val = -1
            desc = f"RSI {rsi:.0f} — sobrecompra + extendido (agotamiento)"
        elif is_oversold and extended_status in ("extended", "skip"):
            val = 1
            desc = f"RSI {rsi:.0f} — sobreventa + extendido (rebote potencial)"
        elif is_exhausted:
            val = 0
            desc = f"RSI {rsi:.0f} — agotamiento (esperar pullback)"
        elif rsi > 50:
            val = 1
            desc = f"RSI {rsi:.0f} — momentum alcista"
        elif rsi < 50:
            val = -1
            desc = f"RSI {rsi:.0f} — momentum bajista"
        else:
            val = 0
            desc = f"RSI {rsi:.0f} — neutral"
        factors.append({"key": "rsi", "label": f"RSI {RSI_PERIOD}", "desc": desc, "value": val})
    else:
        factors.append({"key": "rsi", "label": f"RSI {RSI_PERIOD}", "desc": "Sin datos RSI", "value": 0})

    # 6. Posición en rango (50 velas)
    if range_pos < SCANNER_RANGE_DISCOUNT:
        val = 1
        desc = "Zona de descuento (parte baja del rango)"
    elif range_pos > SCANNER_RANGE_PREMIUM:
        val = -1
        desc = "Zona premium (parte alta del rango)"
    else:
        val = 0
        desc = "Precio en mitad del rango"
    factors.append({"key": "range_pos", "label": "Posición en rango", "desc": desc, "value": val})

    # 7. Impulso 5 velas
    if mom_ret > mom_ret_threshold:
        val = 1
        desc = f"Impulso reciente +{mom_ret*100:.2f}%"
    elif mom_ret < -mom_ret_threshold:
        val = -1
        desc = f"Impulso reciente {mom_ret*100:.2f}%"
    else:
        val = 0
        desc = "Sin impulso claro"
    factors.append({"key": "momentum", "label": "Impulso 5v", "desc": desc, "value": val})

    bias = sum(f["value"] for f in factors)
    total_weight = sum(abs(f["value"]) or 1 for f in factors) or len(factors)
    confluence = abs(bias)
    max_confluence = len(factors)

    if bias >= 3:
        side = "LONG"
    elif bias <= -3:
        side = "SHORT"
    else:
        side = "NEUTRAL"

    # Sparkline: últimos 20 closes (~100 min en M5 = ventana operativa)
    spark = closes[-20:]

    ema_aligned = (
        bool(ema9 and ema21 and ema50) and
        (
            (ema9[-1] > ema21[-1] > ema50[-1]) or
            (ema9[-1] < ema21[-1] < ema50[-1])
        )
    )
    bloque, bloque_reason = _classify_bloque(
        bias=bias,
        confluence=confluence,
        range_pos=range_pos,
        rsi=rsi,
        ema_aligned=ema_aligned,
        extended_status=extended_status,
    )

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
        "bloque": bloque,              # "1" | "2" | "3"
        "bloque_reason": bloque_reason,
        "factors": factors,
        "spark": [round(c, 5) for c in spark],
        # Nuevos campos para scalping
        "ema9_dist_atr": round(ema9_dist_atr, 2) if ema9_dist_atr is not None else None,
        "extended_status": extended_status,
        "structure": struct["last_move"],
        "struct_bullish": struct["bullish"],
    }


def _classify_bloque(
    bias: int,
    confluence: int,
    range_pos: float,
    rsi: Optional[float],
    ema_aligned: bool,
    extended_status: str,
) -> tuple[str, str]:
    """Clasifica un par en uno de tres bloques operativos.

    Bloque 1 — Trend-follow: |bias|>=4, EMAs alineadas, RSI no agotado, NO extended.
    Bloque 3 — Reversión en extremo: rango extremo (<15% o >85%) + RSI en exhaustion + extended.
    Bloque 2 — Sin edge: resto (lateral, EMAs mixtas, bias bajo, extended sin confirmación).
    
    extended_status: "normal" | "extended" | "skip"
      - "skip" fuerza Bloque 2 siempre (precio demasiado extendido)
    """
    at_extreme = range_pos <= SCANNER_RANGE_EXTREME_LOW or range_pos >= SCANNER_RANGE_EXTREME_HIGH
    rsi_exhausted = rsi is not None and (rsi <= SCANNER_RSI_OVERSOLD_EXTREME or rsi >= SCANNER_RSI_OVERBOUGHT_EXTREME)

    # Si está majormente extendido (>2.5×ATR del EMA9) → Bloque 2, el pullback no es accionable
    if extended_status == "skip":
        return "2", "Precio muy extendido del EMA9 — esperar pullback antes de entrar"

    # Bloque 3 — reversión: precio en extremo + RSI agotado + extendido
    # Requiere sweep de extremo + RSI exhaustion para ser válido en scalping
    if at_extreme and rsi_exhausted and extended_status == "extended":
        if range_pos <= SCANNER_RANGE_EXTREME_LOW and rsi is not None and rsi <= SCANNER_RSI_OVERSOLD_EXTREME:
            return "3", "Reversión potencial LONG — sweep low + RSI sobrevendido + extendido"
        if range_pos >= SCANNER_RANGE_EXTREME_HIGH and rsi is not None and rsi >= SCANNER_RSI_OVERBOUGHT_EXTREME:
            return "3", "Reversión potencial SHORT — sweep high + RSI sobrecomprado + extendido"

    # Bloque 1 — tendencia limpia: bias alto, EMAs alineadas, RSI sano, NO extended
    if confluence >= SCANNER_CONFLUENCE_THRESHOLD_TREND and ema_aligned and extended_status == "normal":
        # excluir si precio está pegado al extremo contrario al bias
        exhausted_against = (
            (bias > 0 and range_pos >= 0.9 and rsi is not None and rsi >= SCANNER_RSI_OVERBOUGHT_EXTREME) or
            (bias < 0 and range_pos <= 0.1 and rsi is not None and rsi <= SCANNER_RSI_OVERSOLD_EXTREME)
        )
        if not exhausted_against:
            direction = "alcista" if bias > 0 else "bajista"
            return "1", f"Tendencia {direction} limpia — EMAs alineadas, estructura {direction}, confluencia {confluence}/7"

    # Bloque 2 — excluido: razón más específica posible
    if extended_status == "extended":
        return "2", "Precio extendido del EMA9 — esperar pullback al nivel antes de entrar"
    if confluence < SCANNER_CONFLUENCE_THRESHOLD_NEUTRAL:
        return "2", "Sin dirección clara — bias bajo"
    if not ema_aligned:
        return "2", "EMAs mixtas — estructura no definida"
    if at_extreme and not rsi_exhausted:
        return "2", "Precio en extremo sin confirmación de agotamiento"
    return "2", "Sin edge — contexto ambiguo"


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
# Daily brief — síntesis estilo analista
# ---------------------------------------------------------------------------

def _macro_theme(by_pair: dict[str, dict]) -> str:
    """Heurística simple: correlación dominante del día."""
    # USD strength score: + significa USD fuerte
    usd_score = 0
    for p, d in by_pair.items():
        b = d.get("bias", 0)
        if p in ("EURUSD", "GBPUSD", "AUDUSD"):
            usd_score -= b          # SHORT de XXXUSD = USD fuerte
        elif p in ("USDCAD", "USDCHF", "USDJPY"):
            usd_score += b          # LONG de USDXXX = USD fuerte

    usdjpy = by_pair.get("USDJPY", {}).get("bias", 0)
    usdchf = by_pair.get("USDCHF", {}).get("bias", 0)
    aud = by_pair.get("AUDUSD", {}).get("bias", 0)

    # Safe-haven proxy: yen y franco fuertes (USDJPY/USDCHF bajistas)
    if usdjpy <= -3 and usdchf <= -3:
        return "Risk-off / refugio — yen y franco bid, evita riesgo cíclico"
    # Risk-on: AUD fuerte + yen débil
    if aud >= 3 and usdjpy >= 2:
        return "Risk-on — divisas cíclicas al alza, debilidad de refugios"
    if usd_score >= 10:
        return "Dólar fuerte transversalmente — vendedor de todo lo demás"
    if usd_score <= -10:
        return "Dólar débil transversalmente — comprador de todo lo demás"
    if usd_score >= 5:
        return "Sesgo favorable al dólar, no extremo"
    if usd_score <= -5:
        return "Sesgo contrario al dólar, no extremo"
    return "Sin tema macro dominante — mercado mixto / lateral"


def _sesgo_dia(items: list[dict]) -> str:
    """Resumen one-liner del sesgo general."""
    longs = sum(1 for x in items if x["side"] == "LONG")
    shorts = sum(1 for x in items if x["side"] == "SHORT")
    neutrals = sum(1 for x in items if x["side"] == "NEUTRAL")
    total = len(items) or 1

    high_conf = [x for x in items if x["confluence"] >= 5]
    n_hc = len(high_conf)

    if longs > shorts and longs >= total * 0.5:
        tone = "sesgo alcista general"
    elif shorts > longs and shorts >= total * 0.5:
        tone = "sesgo bajista general"
    elif neutrals >= total * 0.6:
        tone = "mercado lateral — mayoría sin dirección"
    else:
        tone = "mercado mixto sin sesgo único"

    hc_note = f", {n_hc} par{'es' if n_hc != 1 else ''} con confluencia >=5/7" if n_hc else ""
    return f"{tone} ({longs} LONG · {shorts} SHORT · {neutrals} neutral){hc_note}"


def _mejor_setup(operables: list[dict]) -> str:
    """Top pick entre Bloque 1 y Bloque 3, máx 15 palabras."""
    if not operables:
        return "Sin setup operable hoy — todo en Bloque 2"
    top = max(operables, key=lambda x: (x["confluence"], abs(x.get("change_pct", 0))))
    pair = top["pair"]
    side = top["side"] if top["side"] != "NEUTRAL" else ("LONG" if top["bias"] > 0 else "SHORT")
    bloq = top["bloque"]
    razon = top["bloque_reason"]
    # Compact: "EURUSD LONG [B1] bias 5, estructura HH, conf 5/7"
    return f"{pair} {side} [B{bloq}] — {razon.split(' — ')[-1] if ' — ' in razon else razon}"[:140]


def build_daily_brief(items: list[dict]) -> dict:
    """Aggrega los resultados en formato brief estilo analista."""
    by_pair = {x["pair"]: x for x in items}
    operables = [x for x in items if x["bloque"] in ("1", "3")]
    excluidos = [x for x in items if x["bloque"] == "2"]

    # Orden: operables por confluencia desc, excluidos por bias absoluto desc
    operables.sort(key=lambda x: -x["confluence"])
    excluidos.sort(key=lambda x: -abs(x["bias"]))

    return {
        "sesgo_dia": _sesgo_dia(items),
        "pares_operables": [
            f"{x['pair']} {x['side']} [B{x['bloque']}] conf {x['confluence']}/{x['max']}"
            for x in operables
        ],
        "pares_excluidos": [
            f"{x['pair']} — {x['bloque_reason']}"
            for x in excluidos
        ],
        "mejor_setup": _mejor_setup(operables),
        "correlacion_dominante": _macro_theme(by_pair),
    }


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
        # Free tier: 8 req/min. Concurrencia configurable para dejar holgura.
        with ThreadPoolExecutor(max_workers=TWELVEDATA_CONCURRENT_WORKERS) as ex:
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
