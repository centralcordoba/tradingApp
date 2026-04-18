"""Radar de setups — detector de reversiones en soporte/resistencia (M15).

Segunda capa de análisis que convive con el escáner existente. Mientras el
escáner da sesgo macro / tendencia por confluencia de indicadores, el radar
busca puntos concretos de entrada en zonas clave usando price action:

  - Detección de soportes/resistencias por pivots + clustering
  - Vela de rechazo (pin bar / envolvente) sobre la última vela cerrada
  - Divergencia RSI/precio sobre las últimas 10 velas

Los resultados se clasifican en 5 bloques operativos (0=sin setup, 1/3=compra/
venta válida, 2/4=trampa long/short). Los bloques STRONG añaden divergencia
como confluencia máxima.

Reutiliza `scanner._fetch_chart` (y su cache de 5 min) — no hace peticiones
propias a Twelve Data.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from . import scanner

logger = logging.getLogger(__name__)

# Cache del endpoint /api/radar (mismo TTL que el escáner subyacente).
_RADAR_CACHE_TTL = 300
_radar_cache: dict[str, tuple[float, dict]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rsi_series(closes: list[float], period: int = 14) -> list[Optional[float]]:
    """RSI alineado con `closes`. Devuelve None para las posiciones de warm-up."""
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
    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100 - (100 / (1 + rs))

    for i in range(period + 1, n):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100 - (100 / (1 + rs))
    return out


def _range_position(closes: list[float], lookback: int = 50) -> float:
    """Posición del último close en el rango de las N velas anteriores (0..1)."""
    window = closes[-lookback:]
    hi = max(window)
    lo = min(window)
    if hi <= lo:
        return 0.5
    return (closes[-1] - lo) / (hi - lo)


# ---------------------------------------------------------------------------
# Paso 2 — Detección de key levels (soportes / resistencias)
# ---------------------------------------------------------------------------

def _find_key_levels(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    lookback: int = 100,
    tolerance_pct: float = 0.002,
) -> dict:
    """Pivots fractales (2 velas a cada lado) + clustering por proximidad."""
    price = closes[-1]

    empty = {
        "resistance": None,
        "support": None,
        "dist_resistance": None,
        "dist_support": None,
        "near_resistance": False,
        "near_support": False,
        "all_resistances": [],
        "all_supports": [],
    }

    if len(highs) < 5 or len(lows) < 5:
        return empty

    hi_slice = highs[-lookback:]
    lo_slice = lows[-lookback:]
    n = len(hi_slice)

    pivot_highs: list[float] = []
    pivot_lows: list[float] = []
    for i in range(2, n - 2):
        h = hi_slice[i]
        if h > hi_slice[i - 1] and h > hi_slice[i - 2] and h > hi_slice[i + 1] and h > hi_slice[i + 2]:
            pivot_highs.append(h)
        l = lo_slice[i]
        if l < lo_slice[i - 1] and l < lo_slice[i - 2] and l < lo_slice[i + 1] and l < lo_slice[i + 2]:
            pivot_lows.append(l)

    def _cluster(levels: list[float]) -> list[float]:
        if not levels:
            return []
        levels = sorted(levels)
        clusters: list[list[float]] = [[levels[0]]]
        for lv in levels[1:]:
            ref = clusters[-1][-1]
            if ref > 0 and (lv - ref) / ref <= tolerance_pct:
                clusters[-1].append(lv)
            else:
                clusters.append([lv])
        return [sum(c) / len(c) for c in clusters]

    clustered_highs = _cluster(pivot_highs)
    clustered_lows = _cluster(pivot_lows)

    resistances_above = [lv for lv in clustered_highs if lv > price]
    supports_below = [lv for lv in clustered_lows if lv < price]

    resistance = min(resistances_above) if resistances_above else None
    support = max(supports_below) if supports_below else None

    dist_resistance = ((resistance - price) / price * 100) if resistance else None
    dist_support = ((price - support) / price * 100) if support else None

    near_resistance = dist_resistance is not None and dist_resistance < 0.3
    near_support = dist_support is not None and dist_support < 0.3

    return {
        "resistance": resistance,
        "support": support,
        "dist_resistance": round(dist_resistance, 3) if dist_resistance is not None else None,
        "dist_support": round(dist_support, 3) if dist_support is not None else None,
        "near_resistance": near_resistance,
        "near_support": near_support,
        "all_resistances": [round(x, 5) for x in clustered_highs],
        "all_supports": [round(x, 5) for x in clustered_lows],
    }


# ---------------------------------------------------------------------------
# Paso 3 — Vela de rechazo (pin bar / envolvente)
# ---------------------------------------------------------------------------

_EPS = 1e-10


def _detect_rejection_candle(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
) -> dict:
    """Analiza la última vela cerrada ([-1]). Envolventes requieren [-2]."""
    empty = {"rejection": False, "type": None, "wick_ratio": 0.0, "direction": None}

    if not opens or len(opens) < 1:
        return empty

    o = opens[-1]
    c = closes[-1]
    h = highs[-1]
    l = lows[-1]

    body = abs(c - o)
    rng = h - l

    if body < _EPS or rng < _EPS:
        return empty

    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    # Pin bar alcista: mecha inferior grande + cierre en parte alta del rango
    if lower_wick >= 2 * body and (c - l) / rng >= 0.6:
        return {
            "rejection": True,
            "type": "pin_bar_bull",
            "wick_ratio": round(lower_wick / body, 2),
            "direction": "LONG",
        }

    # Pin bar bajista: mecha superior grande + cierre en parte baja del rango
    if upper_wick >= 2 * body and (h - c) / rng >= 0.6:
        return {
            "rejection": True,
            "type": "pin_bar_bear",
            "wick_ratio": round(upper_wick / body, 2),
            "direction": "SHORT",
        }

    # Envolventes requieren vela previa
    if len(opens) >= 2:
        o2 = opens[-2]
        c2 = closes[-2]
        body_prev = abs(c2 - o2)
        hi_prev = max(o2, c2)
        lo_prev = min(o2, c2)

        # Envolvente alcista: verde, abre por debajo y cierra por encima del cuerpo previo
        if c > o and o < lo_prev and c > hi_prev:
            return {
                "rejection": True,
                "type": "engulf_bull",
                "wick_ratio": round(body / body_prev, 2) if body_prev > _EPS else 0.0,
                "direction": "LONG",
            }

        # Envolvente bajista: roja, abre por encima y cierra por debajo del cuerpo previo
        if c < o and o > hi_prev and c < lo_prev:
            return {
                "rejection": True,
                "type": "engulf_bear",
                "wick_ratio": round(body / body_prev, 2) if body_prev > _EPS else 0.0,
                "direction": "SHORT",
            }

    return empty


# ---------------------------------------------------------------------------
# Paso 4 — Divergencia RSI / precio
# ---------------------------------------------------------------------------

def _detect_rsi_divergence(
    closes: list[float],
    rsi: list[Optional[float]],
    lookback: int = 10,
) -> dict:
    """Divergencia sobre las últimas `lookback` velas (excluyendo la actual)."""
    empty = {"divergence": False, "type": None, "direction": None}

    if len(closes) < lookback + 1 or len(rsi) != len(closes):
        return empty

    rsi_now = rsi[-1]
    if rsi_now is None:
        return empty

    price_now = closes[-1]
    window_closes = closes[-(lookback + 1):-1]
    window_rsi = rsi[-(lookback + 1):-1]
    if not window_closes or not window_rsi:
        return empty

    # Índice (dentro de la ventana) del mínimo y máximo de precio
    min_idx = min(range(len(window_closes)), key=lambda i: window_closes[i])
    max_idx = max(range(len(window_closes)), key=lambda i: window_closes[i])

    min_price = window_closes[min_idx]
    max_price = window_closes[max_idx]
    rsi_at_min = window_rsi[min_idx]
    rsi_at_max = window_rsi[max_idx]

    # Alcista: precio hace nuevo mínimo pero RSI sube (y está en zona bajista)
    if (
        rsi_at_min is not None
        and price_now < min_price
        and rsi_now > rsi_at_min
        and rsi_now < 50
    ):
        return {"divergence": True, "type": "bullish", "direction": "LONG"}

    # Bajista: precio hace nuevo máximo pero RSI cae (y está en zona alcista)
    if (
        rsi_at_max is not None
        and price_now > max_price
        and rsi_now < rsi_at_max
        and rsi_now > 50
    ):
        return {"divergence": True, "type": "bearish", "direction": "SHORT"}

    return empty


# ---------------------------------------------------------------------------
# Paso 5 — Clasificador de bloque
# ---------------------------------------------------------------------------

def _classify_reversal_setup(
    key_levels: dict,
    rejection: dict,
    divergence: dict,
    rsi_current: Optional[float],
    range_pos: float,
) -> dict:
    """Clasifica el contexto actual en uno de los bloques de reversión."""
    near_support = bool(key_levels.get("near_support"))
    near_resistance = bool(key_levels.get("near_resistance"))
    has_rejection = bool(rejection.get("rejection"))
    rejection_dir = rejection.get("direction")
    has_divergence = bool(divergence.get("divergence"))
    divergence_dir = divergence.get("direction")

    quality = 0
    if near_support or near_resistance:
        quality += 1
    if has_rejection:
        quality += 1
    if has_divergence:
        quality += 1

    default = {"bloque": 0, "side": "NEUTRAL", "strength": None, "quality": quality}

    # B1 STRONG — soporte + rechazo LONG + parte baja de rango + divergencia alcista
    if (
        near_support
        and has_rejection and rejection_dir == "LONG"
        and range_pos < 0.35
        and has_divergence and divergence_dir == "LONG"
    ):
        return {"bloque": 1, "side": "LONG", "strength": "STRONG", "quality": quality}

    # B3 STRONG — resistencia + rechazo SHORT + parte alta de rango + divergencia bajista
    if (
        near_resistance
        and has_rejection and rejection_dir == "SHORT"
        and range_pos > 0.65
        and has_divergence and divergence_dir == "SHORT"
    ):
        return {"bloque": 3, "side": "SHORT", "strength": "STRONG", "quality": quality}

    # B1 NORMAL
    if (
        near_support
        and has_rejection and rejection_dir == "LONG"
        and range_pos < 0.35
    ):
        return {"bloque": 1, "side": "LONG", "strength": "NORMAL", "quality": quality}

    # B3 NORMAL
    if (
        near_resistance
        and has_rejection and rejection_dir == "SHORT"
        and range_pos > 0.65
    ):
        return {"bloque": 3, "side": "SHORT", "strength": "NORMAL", "quality": quality}

    # B4 TRAP — resistencia pero rechazo LONG: la resistencia podría no aguantar
    if (
        near_resistance
        and has_rejection and rejection_dir == "LONG"
        and range_pos > 0.65
    ):
        return {"bloque": 4, "side": "TRAP_SHORT", "strength": "WARN", "quality": quality}

    # B2 TRAP — soporte pero rechazo SHORT: el soporte podría ceder
    if (
        near_support
        and has_rejection and rejection_dir == "SHORT"
        and range_pos < 0.35
    ):
        return {"bloque": 2, "side": "TRAP_LONG", "strength": "WARN", "quality": quality}

    return default


# ---------------------------------------------------------------------------
# Paso 6 — Función principal del radar
# ---------------------------------------------------------------------------

def _analyze_symbol(symbol: str) -> Optional[dict]:
    """Analiza un símbolo y devuelve el setup si hay bloque activo (≥1)."""
    try:
        raw = scanner._fetch_chart(symbol)
        if raw is None:
            return None
        ohlc = scanner._parse_ohlc(raw)
        if ohlc is None:
            return None

        opens = ohlc["open"]
        highs = ohlc["high"]
        lows = ohlc["low"]
        closes = ohlc["close"]

        if len(closes) < 20:
            return None

        rsi = _rsi_series(closes, 14)
        range_pos = _range_position(closes, 50)

        key_levels = _find_key_levels(highs, lows, closes)
        rejection = _detect_rejection_candle(opens, highs, lows, closes)
        divergence = _detect_rsi_divergence(closes, rsi)

        classification = _classify_reversal_setup(
            key_levels, rejection, divergence, rsi[-1], range_pos
        )

        if classification["bloque"] == 0:
            return None

        logger.debug(
            "[RADAR] %s B%d %s Q%d",
            symbol,
            classification["bloque"],
            classification["side"],
            classification["quality"],
        )

        return {
            "symbol": symbol,
            "price": round(closes[-1], 5),
            "bloque": classification["bloque"],
            "side": classification["side"],
            "strength": classification["strength"],
            "quality": classification["quality"],
            "range_pos": round(range_pos, 2),
            "rsi": round(rsi[-1], 1) if rsi[-1] is not None else None,
            "key_levels": {
                "support": round(key_levels["support"], 5) if key_levels["support"] else None,
                "resistance": round(key_levels["resistance"], 5) if key_levels["resistance"] else None,
                "dist_support": key_levels["dist_support"],
                "dist_resistance": key_levels["dist_resistance"],
                "near_support": key_levels["near_support"],
                "near_resistance": key_levels["near_resistance"],
            },
            "rejection": rejection,
            "divergence": divergence,
        }
    except Exception as e:
        logger.warning("[RADAR] fallo analizando %s: %s", symbol, e)
        return None


def build_radar_setups(symbols: list[str]) -> list[dict]:
    """Ejecuta el radar sobre la lista de símbolos y devuelve sólo bloques 1-4."""
    if not symbols:
        return []

    results: list[dict] = []
    for sym in symbols:
        s = sym.strip().upper()
        if not s:
            continue
        setup = _analyze_symbol(s)
        if setup is not None:
            results.append(setup)

    results.sort(key=lambda s: -s["quality"])
    return results


# ---------------------------------------------------------------------------
# Paso 7 — Respuesta del endpoint (con cache)
# ---------------------------------------------------------------------------

def get_radar_response(symbols: Optional[list[str]] = None) -> dict:
    """Respuesta cacheada del radar (TTL 5 min). Lista por defecto = la del escáner."""
    selected = symbols or scanner.DEFAULT_PAIRS
    cache_key = ",".join(sorted(s.strip().upper() for s in selected if s.strip()))

    now = time.time()
    entry = _radar_cache.get(cache_key)
    if entry and (now - entry[0]) < _RADAR_CACHE_TTL:
        return entry[1]

    setups = build_radar_setups(selected)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_setups": len(setups),
        "strong_setups": sum(1 for s in setups if s["strength"] == "STRONG"),
        "setups": setups,
    }
    _radar_cache[cache_key] = (now, payload)
    return payload
