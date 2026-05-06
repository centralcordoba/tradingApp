"""Radar de setups — detector de reversiones en soporte/resistencia (M15).

Segunda capa de análisis que convive con el escáner existente. Mientras el
escáner da sesgo macro / tendencia por confluencia de indicadores, el radar
busca puntos concretos de entrada en zonas clave usando price action:

  - Detección de soportes/resistencias por pivots + clustering
  - Vela de rechazo (pin bar / envolvente) sobre las últimas 3 velas
  - Divergencia RSI/precio sobre las últimas 10 velas
  - SL estimado con caps por pips configurables por instrumento
  - Cross-check con sesgo del escáner → reclasificación a trampa si hay conflicto

Los resultados se clasifican en 5 bloques operativos (0=sin setup, 1/3=compra/
venta válida, 2/4=trampa long/short). Los bloques STRONG añaden divergencia
como confluencia máxima.

Reutiliza `scanner._fetch_chart` (y su cache de 5 min) — no hace peticiones
propias a Twelve Data. El cache de OHLC crudo es compartido.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from concurrent.futures import ThreadPoolExecutor, as_completed

from . import scanner, radar_smc
from .geometry_detector import _detect_geometry
from .constants import (
    CACHE_TTL_RADAR,
    RADAR_INTERVAL,
    RADAR_OUTPUTSIZE,
    RADAR_MIN_CANDLES,
    RADAR_KEY_LEVELS_LOOKBACK,
    RADAR_KEY_LEVELS_TOLERANCE_PCT,
    RADAR_REJECTION_WICK_RATIO,
    RADAR_REJECTION_WICK_PCT,
    RADAR_DIVERGENCE_LOOKBACK,
    RADAR_RANGE_SUPPORT_ZONE,
    RADAR_RANGE_RESISTANCE_ZONE,
    RADAR_RANGE_EXTREME_LOW,
    RADAR_RANGE_EXTREME_HIGH,
    RADAR_CANDLE_INTERVAL_MIN,
    RADAR_MARKET_STALE_THRESHOLD_MIN,
    RADAR_MIN_RRR,
    RADAR_SMC_PAIRS,
    RADAR_SMC_M30_CANDLES,
    RADAR_SMC_MAX_PARALLEL,
    PIP_SIZES,
    SL_MAX_PIPS,
    MIN_RANGE_PCT,
    RSI_PERIOD,
    ATR_PERIOD,
)

logger = logging.getLogger(__name__)

# Cache del endpoint /api/radar (mismo TTL que el escáner subyacente).
_RADAR_CACHE_TTL = CACHE_TTL_RADAR
_radar_cache: dict[str, tuple[float, dict]] = {}

# Alias usado por main.py y por el chequeo de mercado cerrado en este módulo.
MARKET_STALE_THRESHOLD_MIN = RADAR_MARKET_STALE_THRESHOLD_MIN

# Pares por defecto del radar — comparte la lista del scanner (sin XAUUSD).
DEFAULT_PAIRS = list(scanner.DEFAULT_PAIRS)


def _pip_size(symbol: str) -> float:
    return PIP_SIZES.get(symbol.upper(), PIP_SIZES["default"])


def _sl_cap_pips(symbol: str) -> float:
    return SL_MAX_PIPS.get(symbol.upper(), SL_MAX_PIPS["default"])


def _min_range_pct(symbol: str) -> float:
    return MIN_RANGE_PCT.get(symbol.upper(), MIN_RANGE_PCT["default"])


def _is_compressed_range(
    symbol: str, price: float, support: Optional[float], resistance: Optional[float]
) -> tuple[bool, float]:
    """True si el gap S/R es menor al mínimo operable del instrumento.

    Devuelve (compressed, gap_pct). Si falta S o R, no es compresión — aún hay
    espacio hacia el lado no definido.
    """
    if support is None or resistance is None or price <= 0:
        return False, 0.0
    gap_pct = (resistance - support) / price * 100
    return gap_pct < _min_range_pct(symbol), gap_pct


def _normalize_ts(raw: Optional[str]) -> Optional[str]:
    """Twelve Data devuelve 'YYYY-MM-DD HH:MM:SS' en UTC — normalizamos a ISO 8601."""
    if not raw:
        return None
    s = str(raw).replace(" ", "T")
    if not s.endswith("Z") and "+" not in s:
        s += "Z"
    return s


def _parse_candle_ts(raw: Optional[str]) -> Optional[datetime]:
    """Parsea el timestamp de una vela (formato Twelve Data o ISO) a datetime UTC."""
    if not raw:
        return None
    s = str(raw)
    try:
        if "T" in s:
            iso = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _minutes_since_candle_close(
    raw_ts: Optional[str], now: Optional[datetime] = None
) -> Optional[float]:
    """Minutos desde que se cerró la vela cuyo `ts` (start) se pasa.

    Valor negativo → vela aún formándose (now está dentro del intervalo).
    Valor grande positivo → mercado probablemente cerrado o feed detenido.
    """
    dt = _parse_candle_ts(raw_ts)
    if dt is None:
        return None
    close_dt = dt + timedelta(minutes=RADAR_CANDLE_INTERVAL_MIN)
    ref = now or datetime.now(timezone.utc)
    return (ref - close_dt).total_seconds() / 60.0


def _aggregate_to_m30(ohlc: dict, n: int = 40) -> list[dict]:
    """Agrega velas M15 a M30 (2:1) y devuelve las últimas `n` velas M30.

    open=primer M15, close=segundo M15, high=max, low=min, ts=primer M15.
    Si el total de M15 es impar, descarta la última (vela en formación).
    Devuelve lista vacía si no hay datos suficientes.
    """
    ts_list = ohlc.get("ts", [])
    opens = ohlc.get("open", [])
    highs = ohlc.get("high", [])
    lows = ohlc.get("low", [])
    closes = ohlc.get("close", [])

    total = len(closes)
    if total < 4 or len(opens) != total or len(highs) != total or len(lows) != total:
        return []

    # Truncar a número par para que cada par de M15 forme un M30 completo.
    if total % 2 == 1:
        total -= 1

    m30: list[dict] = []
    for i in range(0, total, 2):
        m30.append({
            "ts": _normalize_ts(ts_list[i]) if i < len(ts_list) else None,
            "open": opens[i],
            "high": max(highs[i], highs[i + 1]),
            "low": min(lows[i], lows[i + 1]),
            "close": closes[i + 1],
        })

    return m30[-n:] if len(m30) > n else m30


def _build_candles(ohlc: dict, n: int = 20) -> list[dict]:
    """Devuelve las últimas `n` velas en formato dict para el minigráfico del
    frontend. Reutiliza el OHLC ya cacheado — no hace llamadas nuevas."""
    ts_list = ohlc.get("ts", [])
    opens = ohlc.get("open", [])
    highs = ohlc.get("high", [])
    lows = ohlc.get("low", [])
    closes = ohlc.get("close", [])
    if not opens or len(ts_list) < n or len(opens) < n or len(closes) < n:
        return []
    start = len(ts_list) - n
    return [
        {
            "ts": _normalize_ts(ts_list[i]),
            "open": opens[i],
            "high": highs[i],
            "low": lows[i],
            "close": closes[i],
        }
        for i in range(start, len(ts_list))
    ]


# ---------------------------------------------------------------------------
# Helpers indicadores (reutilizan o extienden scanner)
# ---------------------------------------------------------------------------

def _rsi_series(closes: list[float], period: int = RSI_PERIOD) -> list[Optional[float]]:
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


def _range_position(closes: list[float], lookback: int = 50) -> float:  # 50 velas estándar
    window = closes[-lookback:]
    hi = max(window)
    lo = min(window)
    if hi <= lo:
        return 0.5
    return (closes[-1] - lo) / (hi - lo)


# ---------------------------------------------------------------------------
# Paso 2 — Detección de key levels
# ---------------------------------------------------------------------------

def _find_key_levels(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    lookback: int = RADAR_KEY_LEVELS_LOOKBACK,
    tolerance_pct: float = RADAR_KEY_LEVELS_TOLERANCE_PCT,
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
    """Analiza la última vela de las listas pasadas. Envolventes requieren [-2]."""
    empty = {"rejection": False, "type": None, "wick_ratio": 0.0, "direction": None}

    if not opens:
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

    if lower_wick >= RADAR_REJECTION_WICK_RATIO * body and (c - l) / rng >= RADAR_REJECTION_WICK_PCT:
        return {
            "rejection": True,
            "type": "pin_bar_bull",
            "wick_ratio": round(lower_wick / body, 2),
            "direction": "LONG",
        }

    if upper_wick >= RADAR_REJECTION_WICK_RATIO * body and (h - c) / rng >= RADAR_REJECTION_WICK_PCT:
        return {
            "rejection": True,
            "type": "pin_bar_bear",
            "wick_ratio": round(upper_wick / body, 2),
            "direction": "SHORT",
        }

    if len(opens) >= 2:
        o2 = opens[-2]
        c2 = closes[-2]
        body_prev = abs(c2 - o2)
        hi_prev = max(o2, c2)
        lo_prev = min(o2, c2)

        if c > o and o < lo_prev and c > hi_prev:
            return {
                "rejection": True,
                "type": "engulf_bull",
                "wick_ratio": round(body / body_prev, 2) if body_prev > _EPS else 0.0,
                "direction": "LONG",
            }

        if c < o and o > hi_prev and c < lo_prev:
            return {
                "rejection": True,
                "type": "engulf_bear",
                "wick_ratio": round(body / body_prev, 2) if body_prev > _EPS else 0.0,
                "direction": "SHORT",
            }

    return empty


def _detect_recent_rejection(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    ts: list,
    max_age: int = 3,  # Máximo 3 velas atrás
) -> dict:
    """Escanea las últimas `max_age` velas y devuelve el rechazo más reciente.

    age=1 → última vela cerrada. age=3 → 3 velas atrás → setup EXPIRADO.
    """
    empty = {
        "rejection": False, "type": None, "wick_ratio": 0.0, "direction": None,
        "candle_age": None, "candle_ts": None, "expired": False,
    }
    n = len(closes)
    if n == 0:
        return empty

    for age in range(1, max_age + 1):
        end = n - age + 1  # slice end (exclusivo) para truncar a esta posición
        if end < 1:
            continue
        res = _detect_rejection_candle(
            opens[:end], highs[:end], lows[:end], closes[:end]
        )
        if res["rejection"]:
            target_idx = end - 1  # índice absoluto de la vela analizada
            return {
                **res,
                "candle_age": age,
                "candle_ts": ts[target_idx] if ts and target_idx < len(ts) else None,
                "expired": age >= 3,
            }
    return empty


# ---------------------------------------------------------------------------
# Paso 4 — Divergencia RSI / precio
# ---------------------------------------------------------------------------

def _detect_rsi_divergence(
    closes: list[float],
    rsi: list[Optional[float]],
    lookback: int = RADAR_DIVERGENCE_LOOKBACK,
) -> dict:
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

    min_idx = min(range(len(window_closes)), key=lambda i: window_closes[i])
    max_idx = max(range(len(window_closes)), key=lambda i: window_closes[i])

    min_price = window_closes[min_idx]
    max_price = window_closes[max_idx]
    rsi_at_min = window_rsi[min_idx]
    rsi_at_max = window_rsi[max_idx]

    if (
        rsi_at_min is not None
        and price_now < min_price
        and rsi_now > rsi_at_min
        and rsi_now < 50
    ):
        return {"divergence": True, "type": "bullish", "direction": "LONG"}

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

    if (
        near_support
        and has_rejection and rejection_dir == "LONG"
        and range_pos < RADAR_RANGE_SUPPORT_ZONE
        and has_divergence and divergence_dir == "LONG"
    ):
        return {"bloque": 1, "side": "LONG", "strength": "STRONG", "quality": quality}

    if (
        near_resistance
        and has_rejection and rejection_dir == "SHORT"
        and range_pos > RADAR_RANGE_RESISTANCE_ZONE
        and has_divergence and divergence_dir == "SHORT"
    ):
        return {"bloque": 3, "side": "SHORT", "strength": "STRONG", "quality": quality}

    if (
        near_support
        and has_rejection and rejection_dir == "LONG"
        and range_pos < RADAR_RANGE_SUPPORT_ZONE
    ):
        return {"bloque": 1, "side": "LONG", "strength": "NORMAL", "quality": quality}

    if (
        near_resistance
        and has_rejection and rejection_dir == "SHORT"
        and range_pos > RADAR_RANGE_RESISTANCE_ZONE
    ):
        return {"bloque": 3, "side": "SHORT", "strength": "NORMAL", "quality": quality}

    if (
        near_resistance
        and has_rejection and rejection_dir == "LONG"
        and range_pos > RADAR_RANGE_RESISTANCE_ZONE
    ):
        return {"bloque": 4, "side": "TRAP_SHORT", "strength": "WARN", "quality": quality}

    if (
        near_support
        and has_rejection and rejection_dir == "SHORT"
        and range_pos < RADAR_RANGE_SUPPORT_ZONE
    ):
        return {"bloque": 2, "side": "TRAP_LONG", "strength": "WARN", "quality": quality}

    return default


# ---------------------------------------------------------------------------
# SL estimado
# ---------------------------------------------------------------------------

def _estimate_sl(
    symbol: str,
    side: str,
    price: float,
    support: Optional[float],
    resistance: Optional[float],
    atr: Optional[float],
) -> Optional[dict]:
    """SL = nivel ± 0.5·ATR. Solo para setups direccionales (B1/B3).

    Devuelve None si faltan datos. `too_wide=True` si distance_pips > cap del
    instrumento. Incluye RRR calculado contra el nivel opuesto (TP natural del
    reverse-to-level): `rrr` y `rrr_below_min` — frontend dimea y tacha la
    card si `rrr_below_min`.
    """
    if atr is None:
        return None
    buffer = 0.5 * atr

    if side == "LONG" and support is not None:
        sl_price = support - buffer
        distance_price = price - sl_price
        tp_price = resistance
        reward_price = (resistance - price) if resistance is not None else None
    elif side == "SHORT" and resistance is not None:
        sl_price = resistance + buffer
        distance_price = sl_price - price
        tp_price = support
        reward_price = (price - support) if support is not None else None
    else:
        return None

    if distance_price <= 0:
        return None

    pip = _pip_size(symbol)
    cap = _sl_cap_pips(symbol)
    distance_pips = distance_price / pip

    rrr: Optional[float] = None
    if reward_price is not None and reward_price > 0:
        rrr = reward_price / distance_price

    return {
        "price": round(sl_price, 5),
        "distance_pips": round(distance_pips, 1),
        "distance_price": round(distance_price, 5),
        "cap_pips": cap,
        "too_wide": distance_pips > cap,
        "tp_price": round(tp_price, 5) if tp_price is not None else None,
        "reward_pips": round(reward_price / pip, 1) if reward_price and reward_price > 0 else None,
        "rrr": round(rrr, 2) if rrr is not None else None,
        "rrr_below_min": (rrr is not None and rrr < RADAR_MIN_RRR),
        "rrr_min": RADAR_MIN_RRR,
    }


# ---------------------------------------------------------------------------
# Paso 6 — Función principal del radar
# ---------------------------------------------------------------------------

def _analyze_symbol(symbol: str) -> Optional[dict]:
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
        ts = ohlc["ts"]

        if len(closes) < RADAR_MIN_CANDLES:
            return None

        rsi = _rsi_series(closes, RSI_PERIOD)
        atr = scanner._atr(highs, lows, closes, ATR_PERIOD)
        range_pos = _range_position(closes, 50)

        key_levels = _find_key_levels(highs, lows, closes)

        # Filtro de rango comprimido — antes de clasificar.
        price = closes[-1]
        compressed, gap_pct = _is_compressed_range(
            symbol, price, key_levels["support"], key_levels["resistance"]
        )
        if compressed:
            logger.debug(
                "[RADAR] %s COMPRESSED_RANGE — S/R gap %.3f%% < %s%% — omitido",
                symbol, gap_pct, _min_range_pct(symbol),
            )
            return None

        rejection = _detect_recent_rejection(opens, highs, lows, closes, ts)
        divergence = _detect_rsi_divergence(closes, rsi)

        # Si la última vela se cerró hace mucho (fin de semana, feed caído),
        # fuerza el rechazo como expirado — no queremos mostrar "vela recién
        # cerrada" con datos del viernes el lunes por la mañana.
        data_age = _minutes_since_candle_close(ts[-1] if ts else None)
        is_stale = data_age is not None and data_age > RADAR_MARKET_STALE_THRESHOLD_MIN
        if is_stale and rejection.get("rejection") and not rejection.get("expired"):
            logger.debug(
                "[RADAR] %s STALE_DATA age=%.0fmin — forzando rejection.expired",
                symbol, data_age,
            )
            rejection = {**rejection, "expired": True}

        classification = _classify_reversal_setup(
            key_levels, rejection, divergence, rsi[-1], range_pos
        )

        if classification["bloque"] == 0:
            return None

        sl = _estimate_sl(
            symbol,
            classification["side"],
            price,
            key_levels["support"],
            key_levels["resistance"],
            atr,
        )

        # Normalizar candle_ts del rejection para que coincida con los ts de candles
        if rejection.get("candle_ts"):
            rejection = {**rejection, "candle_ts": _normalize_ts(rejection["candle_ts"])}

        candles = _build_candles(ohlc, n=20)
        if candles:
            logger.debug("[RADAR] %s candles=%d velas OK", symbol, len(candles))
        else:
            logger.warning("[RADAR] %s candles insuficientes — devolviendo []", symbol)

        # Geometría (canales / triángulos) sobre M30 — determinístico, sin IA.
        geometria: Optional[dict] = None
        try:
            m30_for_geom = _aggregate_to_m30(ohlc, n=80)
            if m30_for_geom and len(m30_for_geom) >= 20:
                geometria = _detect_geometry(
                    m30_for_geom, price, _pip_size(symbol), lookback=60
                )
        except Exception as e:
            logger.debug("[RADAR] %s geometría falló: %s", symbol, e)

        logger.debug(
            "[RADAR] %s B%d %s Q%d age=%s",
            symbol,
            classification["bloque"],
            classification["side"],
            classification["quality"],
            rejection.get("candle_age"),
        )

        return {
            "symbol": symbol,
            "price": round(price, 5),
            "bloque": classification["bloque"],
            "side": classification["side"],
            "strength": classification["strength"],
            "quality": classification["quality"],
            "range_pos": round(range_pos, 2),
            "rsi": round(rsi[-1], 1) if rsi[-1] is not None else None,
            "atr": round(atr, 5) if atr is not None else None,
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
            "sl": sl,
            "alignment": None,  # se completa en _cross_check_alignment
            "candles": candles,
            "geometria": geometria,
        }
    except Exception as e:
        logger.warning("[RADAR] fallo analizando %s: %s", symbol, e)
        return None


def build_radar_setups(symbols: list[str]) -> list[dict]:
    """Ejecuta el radar sobre la lista de símbolos. No hace cross-check con
    el escáner — eso lo hace `get_radar_response` que es la API real."""
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
# Cross-check con escáner: alineación macro + reclasificación
# ---------------------------------------------------------------------------

def _cross_check_alignment(setups: list[dict], scanner_items: list[dict]) -> list[dict]:
    """Muta cada setup con `alignment`. NO reclasifica — el bloque original se
    preserva para que el frontend pueda mostrar una etiqueta explícita
    "NO CUMPLE MTF LOCK" cuando el sesgo del escáner contradice el setup.

    `mtf_lock_passed`:
      - True  → setup alineado con sesgo macro (o trampa confirmada por el macro)
      - False → setup contra el sesgo macro (no tomar)
      - None  → escáner neutral o sin data (indeterminado, no bloquea)
    """
    bias_by_pair = {x["pair"]: x for x in scanner_items}

    for s in setups:
        scan = bias_by_pair.get(s["symbol"])
        if not scan:
            s["alignment"] = {
                "status": "unknown",
                "scanner_bias": None,
                "scanner_confluence": None,
                "mtf_lock_passed": None,
                "mtf_lock_failed": False,
                "reclassified": False,
            }
            continue

        sb_side = scan.get("side")          # "LONG" | "SHORT" | "NEUTRAL"
        sb_conf = scan.get("confluence")
        sb_bias = scan.get("bias")

        # Escáner sin sesgo claro — no contradice ni respalda.
        if sb_side == "NEUTRAL":
            s["alignment"] = {
                "status": "neutral",
                "scanner_bias": "NEUTRAL",
                "scanner_confluence": sb_conf,
                "scanner_bias_value": sb_bias,
                "mtf_lock_passed": None,
                "mtf_lock_failed": False,
                "reclassified": False,
            }
            continue

        # Trampas ya existentes (B2/B4): la dirección implícita es la opuesta.
        if s["bloque"] in (2, 4):
            radar_implied = "SHORT" if s["side"] == "TRAP_LONG" else "LONG"
            status = "aligned" if sb_side == radar_implied else "conflict"
            s["alignment"] = {
                "status": status,
                "scanner_bias": sb_side,
                "scanner_confluence": sb_conf,
                "scanner_bias_value": sb_bias,
                "mtf_lock_passed": status == "aligned",
                "mtf_lock_failed": status == "conflict",
                "reclassified": False,
            }
            continue

        # B1 LONG o B3 SHORT: comparar dirección con sesgo macro.
        aligned = (s["side"] == sb_side)
        s["alignment"] = {
            "status": "aligned" if aligned else "conflict",
            "scanner_bias": sb_side,
            "scanner_confluence": sb_conf,
            "scanner_bias_value": sb_bias,
            "mtf_lock_passed": aligned,
            "mtf_lock_failed": not aligned,
            "reclassified": False,
        }

    return setups


# ---------------------------------------------------------------------------
# Paso 7 — Respuesta del endpoint (con cache)
# ---------------------------------------------------------------------------

def _probe_market_age_minutes(symbols: list[str]) -> Optional[float]:
    """Lee el cache de OHLC crudo para los símbolos dados y devuelve la edad
    (min) de la vela más reciente entre todos. None si no hay cache.
    """
    ages: list[float] = []
    for sym in symbols:
        key = f"{sym.strip().upper()}:15min:200"
        entry = scanner._ohlc_cache.get(key)
        if not entry:
            continue
        raw = entry[1]
        values = raw.get("values") if isinstance(raw, dict) else None
        if not values:
            continue
        age = _minutes_since_candle_close(values[-1].get("datetime"))
        if age is not None:
            ages.append(age)
    return min(ages) if ages else None


def _enrich_with_smc(active_setups: list[dict]) -> None:
    """Para cada setup activo cuyo símbolo está en RADAR_SMC_PAIRS, agrega M30
    desde el cache OHLC compartido y llama a OpenRouter en paralelo. Adjunta
    el resultado a `setup['smc']` (None si no aplica o si falla).

    Mutación in-place — no devuelve nada. Si OpenRouter no está configurado o
    el símbolo no es operable por el usuario, deja `smc=None` (frontend lo
    ignora).
    """
    for s in active_setups:
        s.setdefault("smc", None)

    if not radar_smc.is_enabled():
        return

    targets: list[tuple[dict, list[dict]]] = []
    for s in active_setups:
        sym = s.get("symbol", "").upper()
        if sym not in RADAR_SMC_PAIRS:
            continue
        # Reutiliza el cache de OHLC del scanner — sin créditos extra.
        raw = scanner._fetch_chart(sym)
        if raw is None:
            continue
        ohlc = scanner._parse_ohlc(raw)
        if ohlc is None:
            continue
        m30 = _aggregate_to_m30(ohlc, n=RADAR_SMC_M30_CANDLES)
        if not m30:
            continue
        targets.append((s, m30))

    if not targets:
        return

    workers = min(len(targets), RADAR_SMC_MAX_PARALLEL)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(radar_smc.analyze_setup_smc, s["symbol"], m30): s
            for s, m30 in targets
        }
        for fut in as_completed(futures):
            setup = futures[fut]
            try:
                result = fut.result()
            except Exception as e:
                logger.warning("[RADAR] SMC %s falló: %s", setup.get("symbol"), e)
                continue
            if result is not None:
                setup["smc"] = result


def get_radar_response(symbols: Optional[list[str]] = None) -> dict:
    """Respuesta cacheada del radar (TTL 15 min). Incluye cross-check con el
    escáner para reclasificar conflictos de sesgo macro."""
    selected = symbols or DEFAULT_PAIRS
    cache_key = ",".join(sorted(s.strip().upper() for s in selected if s.strip()))

    now = time.time()
    entry = _radar_cache.get(cache_key)
    if entry and (now - entry[0]) < _RADAR_CACHE_TTL:
        return entry[1]

    # Precargar el escáner para tener bias por par — comparte cache de OHLC.
    scanner_items: list[dict] = []
    try:
        scanner_items = scanner.scan_pairs(selected)
    except Exception as e:
        logger.warning("[RADAR] fallo escáner para cross-check: %s", e)

    setups = build_radar_setups(selected)
    setups = _cross_check_alignment(setups, scanner_items)

    # Reordenar tras posible reclasificación
    setups.sort(key=lambda s: -s["quality"])

    # Separar activos (age ≤ 2) de expirados (age = 3). Los expirados NO llevan
    # candles en el payload para ahorrar bytes — no se van a graficar.
    active_setups: list[dict] = []
    expired_setups: list[dict] = []
    for s in setups:
        rej = s.get("rejection") or {}
        if rej.get("expired"):
            age = rej.get("candle_age")
            logger.debug("[RADAR] %s EXPIRED — age=%s", s.get("symbol"), age)
            stripped = {k: v for k, v in s.items() if k != "candles"}
            expired_setups.append(stripped)
        else:
            active_setups.append(s)

    # Enriquecimiento SMC vía IA — solo pares operables del usuario, en paralelo.
    # Si OpenRouter no está configurado o falla, los setups quedan con smc=None.
    _enrich_with_smc(active_setups)

    # `total_setups` cuenta sólo activos y descarta too_wide — coherente con el
    # frontend que los pinta atenuados y no los considera operables.
    valid_active = [
        s for s in active_setups
        if not (s.get("sl") and s["sl"].get("too_wide"))
    ]

    # Estado del mercado: lee la vela más reciente del cache tras el scan.
    freshest_age = _probe_market_age_minutes(selected)
    market_closed = (
        freshest_age is not None and freshest_age > MARKET_STALE_THRESHOLD_MIN
    )
    last_candle_ts = None
    if freshest_age is not None:
        # Buscar el ts efectivo de la vela más reciente (para mostrar en UI).
        for sym in selected:
            key = f"{sym.strip().upper()}:15min:200"
            ent = scanner._ohlc_cache.get(key)
            if not ent:
                continue
            vals = ent[1].get("values") if isinstance(ent[1], dict) else None
            if not vals:
                continue
            age = _minutes_since_candle_close(vals[-1].get("datetime"))
            if age is not None and abs(age - freshest_age) < 1e-6:
                last_candle_ts = _normalize_ts(vals[-1].get("datetime"))
                break

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "active_setups": active_setups,
        "expired_setups": expired_setups,
        "total_setups": len(valid_active),
        "strong_setups": sum(1 for s in valid_active if s["strength"] == "STRONG"),
        "total_expired": len(expired_setups),
        "market_closed": market_closed,
        "data_age_minutes": round(freshest_age) if freshest_age is not None else None,
        "last_candle_ts": last_candle_ts,
    }
    _radar_cache[cache_key] = (now, payload)
    return payload
