"""Detector de Zonas S/R activas para scalp M5/M15 con bias M30.

Tercera capa de análisis (independiente del scanner y del radar). Lee las 200
velas M15 ya cacheadas por scanner._fetch_chart, las resamplea a M30 para
calcular el bias direccional (EMA50 vs EMA100 — 100 es la EMA larga máxima
viable con 200 velas M15 ≈ 100 velas M30) y detecta niveles de soporte/
resistencia por pivots + clustering aglomerativo single-linkage.

Cada nivel se etiqueta con:
- precio, tipo (soporte/resistencia relativo al precio actual)
- fuerza (toques + antigüedad) sin opiniones
- distancia al precio en pips
- estado ACTIVO/LEJANO según rango operativo y coherencia con bias M30

La salida es estrictamente descriptiva — el lenguaje es neutro, sin
"comprar/vender". La app marca el terreno; la decisión es del trader.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from . import scanner
from .constants import (
    ATR_PERIOD,
    CACHE_TTL_OHLC_SCANNER,
    EMA_PERIOD_50,
    EMA_PERIOD_100,
    PIP_SIZES,
    ZONES_RANGO_ATR_MULT_DEFAULT,
    ZONES_PIVOT_WINDOW,
    ZONES_MERGE_DISTANCE_PIPS,
    ZONES_ACTIVE_RANGE_PIPS,
    ZONES_MIN_BARS_BETWEEN_PEAKS,
    ZONES_TOUCH_TOLERANCE_PIPS,
    ZONES_LEVEL_SELECTOR_DEFAULT,
    ZONES_DEFAULT_PAIRS,
    RADAR_MARKET_STALE_THRESHOLD_MIN,
)

logger = logging.getLogger(__name__)

# Cache del endpoint /api/zones (mismo TTL que el OHLC subyacente).
_ZONES_CACHE_TTL = CACHE_TTL_OHLC_SCANNER
_zones_cache: dict[str, tuple[float, dict]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pip_size(symbol: str) -> float:
    return PIP_SIZES.get(symbol.upper(), PIP_SIZES["default"])


def _normalize_ts(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).replace(" ", "T")
    if not s.endswith("Z") and "+" not in s:
        s += "Z"
    return s


def _parse_candle_ts(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    s = str(raw)
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Resample M15 → M30
# ---------------------------------------------------------------------------

def _resample_m15_to_m30(ohlc: dict) -> Optional[pd.DataFrame]:
    """Agrupa las velas M15 en velas M30 alineadas a :00 y :30.

    pandas resample con label='right' y closed='right' coloca la vela final
    en el timestamp del último M15 incluido. Para nuestras EMAs lo único que
    importa es la secuencia ordenada por tiempo.
    """
    if not ohlc.get("ts") or not ohlc.get("close"):
        return None
    try:
        idx = pd.to_datetime(ohlc["ts"], utc=True)
    except Exception:
        return None
    df = pd.DataFrame(
        {
            "open": ohlc["open"],
            "high": ohlc["high"],
            "low": ohlc["low"],
            "close": ohlc["close"],
        },
        index=idx,
    ).sort_index()
    if df.empty:
        return None
    m30 = (
        df.resample("30min", label="right", closed="right")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
    )
    return m30


def _ema_last(values: np.ndarray, period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    ema = float(values[:period].mean())
    for v in values[period:]:
        ema = float(v) * k + ema * (1 - k)
    return ema


def _atr_m30(m30: pd.DataFrame, period: int = ATR_PERIOD) -> Optional[float]:
    """ATR Wilder sobre las velas M30 ya resampleadas. None si no hay datos."""
    if m30 is None or len(m30) < period + 1:
        return None
    highs = m30["high"].to_numpy(dtype=float)
    lows = m30["low"].to_numpy(dtype=float)
    closes = m30["close"].to_numpy(dtype=float)
    trs: list[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return float(atr)


def _compute_m30_bias(
    m30: pd.DataFrame,
    pip: float,
    atr_mult: float = ZONES_RANGO_ATR_MULT_DEFAULT,
) -> dict:
    """Bias direccional M30: EMA50 vs EMA100 con tercer estado RANGO.

    200 velas M15 ≈ 100 velas M30, así que la EMA larga máxima viable sin
    pedir más datos a Twelve Data es EMA100 (~50h de contexto = 2 días).

    Estados:
      - BULL: EMA50 > EMA100 Y separación ≥ atr_mult × ATR(M30)
      - BEAR: EMA50 < EMA100 Y separación ≥ atr_mult × ATR(M30)
      - RANGO: separación < atr_mult × ATR(M30) — sin sesgo direccional fiable

    Devuelve siempre el dict completo. Si no se puede calcular, `available`
    queda False y `reason` indica el motivo (no_ohlc, insufficient_m30_bars,
    ema_failed, atr_failed).
    """
    out: dict = {
        "label": "NEUTRAL",
        "ema50": None,
        "ema100": None,
        "atr_m30": None,
        "separation": None,
        "atr_pips": None,
        "separation_pips": None,
        "atr_mult_threshold": round(float(atr_mult), 3),
        "available": False,
        "reason": None,
        "m30_bars": 0,
        "m30_bars_required": EMA_PERIOD_100,
    }
    if m30 is None:
        out["reason"] = "no_ohlc"
        return out
    out["m30_bars"] = int(len(m30))
    if len(m30) < EMA_PERIOD_100:
        out["reason"] = "insufficient_m30_bars"
        return out
    closes = m30["close"].to_numpy(dtype=float)
    ema50 = _ema_last(closes, EMA_PERIOD_50)
    ema100 = _ema_last(closes, EMA_PERIOD_100)
    if ema50 is None or ema100 is None:
        out["reason"] = "ema_failed"
        return out
    atr = _atr_m30(m30, ATR_PERIOD)
    if atr is None or atr <= 0:
        out["reason"] = "atr_failed"
        out["ema50"] = round(ema50, 5)
        out["ema100"] = round(ema100, 5)
        return out

    separation = abs(ema50 - ema100)
    threshold = atr_mult * atr

    if separation < threshold:
        label = "RANGO"
    elif ema50 > ema100:
        label = "BULL"
    else:
        label = "BEAR"

    return {
        "label": label,
        "ema50": round(ema50, 5),
        "ema100": round(ema100, 5),
        "atr_m30": round(atr, 5),
        "separation": round(separation, 5),
        "atr_pips": round(atr / pip, 1),
        "separation_pips": round(separation / pip, 1),
        "atr_mult_threshold": round(float(atr_mult), 3),
        "available": True,
        "reason": None,
        "m30_bars": int(len(m30)),
        "m30_bars_required": EMA_PERIOD_100,
    }


# ---------------------------------------------------------------------------
# Pivots
# ---------------------------------------------------------------------------

def _detect_pivots(
    highs: list[float], lows: list[float], window: int
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Swing detector: una vela es pivot high si su high es estrictamente mayor
    que los `window` highs a cada lado. Pivot low simétrico sobre lows.
    """
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    n = len(h)
    pivot_highs: list[tuple[int, float]] = []
    pivot_lows: list[tuple[int, float]] = []
    if n < 2 * window + 1:
        return pivot_highs, pivot_lows
    for i in range(window, n - window):
        center_h = h[i]
        center_l = l[i]
        is_high = True
        is_low = True
        for d in range(1, window + 1):
            if h[i - d] >= center_h or h[i + d] >= center_h:
                is_high = False
            if l[i - d] <= center_l or l[i + d] <= center_l:
                is_low = False
            if not is_high and not is_low:
                break
        if is_high:
            pivot_highs.append((i, float(center_h)))
        if is_low:
            pivot_lows.append((i, float(center_l)))
    return pivot_highs, pivot_lows


def _filter_min_bars(
    pivots: list[tuple[int, float]], min_bars: int, kind: str
) -> list[tuple[int, float]]:
    """Filtra pivots cuyo índice está a menos de `min_bars` del anterior.

    Cuando dos pivots colisionan en tiempo, conserva el extremo:
    - kind='high': el de mayor precio
    - kind='low':  el de menor precio
    """
    if not pivots or min_bars <= 1:
        return list(pivots)
    pivots = sorted(pivots, key=lambda p: p[0])
    out: list[tuple[int, float]] = [pivots[0]]
    for idx, price in pivots[1:]:
        prev_idx, prev_price = out[-1]
        if idx - prev_idx < min_bars:
            if kind == "high" and price > prev_price:
                out[-1] = (idx, price)
            elif kind == "low" and price < prev_price:
                out[-1] = (idx, price)
            continue
        out.append((idx, price))
    return out


# ---------------------------------------------------------------------------
# Clustering aglomerativo single-linkage 1D
# ---------------------------------------------------------------------------

def _cluster_single_linkage(
    pivots: list[tuple[int, float]], merge_distance: float
) -> list[list[tuple[int, float]]]:
    """Cluster aglomerativo 1D: dos puntos pertenecen al mismo cluster si el
    gap entre vecinos consecutivos (ordenados por precio) es ≤ merge_distance.

    Equivalente a single-linkage con corte por umbral — pero en O(N log N)
    sin construir matriz de distancias. Para 200 velas → ≤ 40 pivots → trivial.
    """
    if not pivots:
        return []
    ordered = sorted(pivots, key=lambda p: p[1])
    clusters: list[list[tuple[int, float]]] = [[ordered[0]]]
    for piv in ordered[1:]:
        if piv[1] - clusters[-1][-1][1] <= merge_distance:
            clusters[-1].append(piv)
        else:
            clusters.append([piv])
    return clusters


def _level_price(cluster: list[tuple[int, float]], selector: str) -> float:
    prices = [p[1] for p in cluster]
    if selector == "mean":
        return float(np.mean(prices))
    return float(np.median(prices))


# ---------------------------------------------------------------------------
# Toques y fuerza
# ---------------------------------------------------------------------------

def _count_touches(
    level_price: float, highs: list[float], lows: list[float], tolerance: float
) -> int:
    """Cuenta cuántas veces el precio ENTRÓ en la zona ± tolerance.

    No cuenta cada vela dentro de la zona — eso sobrevaloraría niveles
    visitados largo rato. Cuenta transiciones fuera→dentro (cada nuevo
    "test" del nivel).
    """
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    in_zone = (h >= level_price - tolerance) & (l <= level_price + tolerance)
    if len(in_zone) == 0:
        return 0
    transitions = int(np.diff(in_zone.astype(np.int8)).clip(min=0).sum())
    return transitions + (1 if in_zone[0] else 0)


def _strength_score(touches: int, age_bars: int, n_bars: int) -> int:
    """Score 1-5. Más toques + más antigüedad = más fuerte.

    Antigüedad mide HACE CUÁNTO tiempo se formó por primera vez el nivel
    (no cuánto lleva activo). Un nivel respetado 4 veces durante 100 velas
    tiene más peso que uno respetado 4 veces en las últimas 10 velas.
    """
    age_frac = age_bars / max(n_bars, 1)
    if touches >= 4 and age_frac >= 0.5:
        return 5
    if touches >= 3 and age_frac >= 0.3:
        return 4
    if touches >= 2 and age_frac >= 0.15:
        return 3
    if touches >= 2:
        return 2
    return 1


# ---------------------------------------------------------------------------
# Pipeline por par
# ---------------------------------------------------------------------------

def analyze_zones(pair: str, params: Optional[dict] = None) -> Optional[dict]:
    """Análisis completo de un par. None si falla la descarga / parseo."""
    params = params or {}
    window = int(params.get("window", ZONES_PIVOT_WINDOW))
    merge_distance_pips = float(params.get("merge_distance_pips", ZONES_MERGE_DISTANCE_PIPS))
    active_range_pips = float(params.get("active_range_pips", ZONES_ACTIVE_RANGE_PIPS))
    min_bars_between = int(params.get("min_bars_between", ZONES_MIN_BARS_BETWEEN_PEAKS))
    touch_tol_pips = float(params.get("touch_tolerance_pips", ZONES_TOUCH_TOLERANCE_PIPS))
    selector = str(params.get("level_selector", ZONES_LEVEL_SELECTOR_DEFAULT))
    if selector not in ("median", "mean"):
        selector = "median"
    rango_atr_mult = float(params.get("rango_atr_mult", ZONES_RANGO_ATR_MULT_DEFAULT))
    # Sanea: el multiplicador tiene que ser positivo y dentro de un rango razonable.
    rango_atr_mult = max(0.05, min(2.0, rango_atr_mult))

    raw = scanner._fetch_chart(pair)
    if raw is None:
        return None
    ohlc = scanner._parse_ohlc(raw)
    if ohlc is None:
        return None

    pip = _pip_size(pair)
    closes = ohlc["close"]
    highs = ohlc["high"]
    lows = ohlc["low"]
    n_bars = len(closes)
    last_close = closes[-1]

    last_ts = ohlc["ts"][-1] if ohlc["ts"] else None

    # Bias M30 (resample de las propias M15)
    m30 = _resample_m15_to_m30(ohlc)
    bias = _compute_m30_bias(m30, pip, atr_mult=rango_atr_mult)

    # Pivots
    p_highs, p_lows = _detect_pivots(highs, lows, window)
    p_highs = _filter_min_bars(p_highs, min_bars_between, "high")
    p_lows = _filter_min_bars(p_lows, min_bars_between, "low")

    merge_distance_price = merge_distance_pips * pip
    touch_tolerance_price = touch_tol_pips * pip

    # Cluster combinado: todos los pivots (highs + lows) en un único set.
    # Un cluster que mezcla highs y lows es un nivel con confluencia
    # bidireccional ("flip zone") — más relevante aún. La etiqueta final
    # support/resistance se decide por la posición vs precio actual.
    all_pivots = p_highs + p_lows
    clusters = _cluster_single_linkage(all_pivots, merge_distance_price)

    levels: list[dict] = []
    for cl in clusters:
        if not cl:
            continue
        price = _level_price(cl, selector)
        touches = _count_touches(price, highs, lows, touch_tolerance_price)
        first_idx = min(p[0] for p in cl)
        age_bars = n_bars - first_idx
        strength = _strength_score(touches, age_bars, n_bars)
        kind = "support" if price < last_close else "resistance"
        distance_pips = round(abs(price - last_close) / pip, 1)
        within_range = distance_pips <= active_range_pips

        # Coherencia con bias M30 (filtro híbrido):
        # BULL → priorizamos SOPORTES (potencial rebote a favor del bias)
        # BEAR → priorizamos RESISTENCIAS
        # RANGO / NEUTRAL / sin bias → DESACTIVAMOS el filtro direccional:
        #   en rango el scalper opera ambos lados (fade desde extremos), así que
        #   todos los niveles cercanos pasan a ACTIVO. La UI muestra el banner
        #   de "sin sesgo direccional" para que el trader cambie el modo mental.
        if bias["label"] == "BULL":
            coherent = (kind == "support")
        elif bias["label"] == "BEAR":
            coherent = (kind == "resistance")
        else:
            coherent = True

        active = within_range and coherent

        levels.append({
            "price": round(price, 5),
            "type": kind,
            "strength": strength,
            "touches": touches,
            "age_bars": int(age_bars),
            "pivots_in_cluster": len(cl),
            "distance_pips": distance_pips,
            "within_range": within_range,
            "coherent_with_bias": coherent,
            "active": active,
        })

    # Orden: activos primero (por distancia asc), luego dentro de rango pero
    # incoherentes con bias (informativos), luego lejanos (ordenados por fuerza desc).
    def _sort_key(lv: dict) -> tuple:
        if lv["active"]:
            return (0, lv["distance_pips"])
        if lv["within_range"]:
            return (1, lv["distance_pips"])
        return (2, -lv["strength"], lv["distance_pips"])

    levels.sort(key=_sort_key)

    # Mercado cerrado (mismo criterio que radar/scanner)
    market_closed = False
    data_age_minutes: Optional[float] = None
    if last_ts:
        last_dt = _parse_candle_ts(last_ts)
        if last_dt is not None:
            data_age_minutes = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
            market_closed = data_age_minutes > RADAR_MARKET_STALE_THRESHOLD_MIN

    return {
        "pair": pair,
        "price": round(last_close, 5),
        "pip_size": pip,
        "bias_m30": bias,
        "params": {
            "window": window,
            "merge_distance_pips": merge_distance_pips,
            "active_range_pips": active_range_pips,
            "min_bars_between": min_bars_between,
            "touch_tolerance_pips": touch_tol_pips,
            "level_selector": selector,
        },
        "levels": levels,
        "active_count": sum(1 for lv in levels if lv["active"]),
        "n_bars": n_bars,
        "last_candle_ts": _normalize_ts(last_ts),
        "data_age_minutes": round(data_age_minutes, 1) if data_age_minutes is not None else None,
        "market_closed": market_closed,
    }


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def get_zones_response(
    pairs: Optional[list[str]] = None, params: Optional[dict] = None
) -> dict:
    """Endpoint payload. Cachea por (pair, hash de params) durante TTL del OHLC."""
    pairs = pairs or list(ZONES_DEFAULT_PAIRS)
    params = params or {}
    cache_key = "|".join(sorted(pairs)) + ":" + ",".join(f"{k}={v}" for k, v in sorted(params.items()))
    now = time.time()
    cached = _zones_cache.get(cache_key)
    if cached and (now - cached[0]) < _ZONES_CACHE_TTL:
        return cached[1]

    items: list[dict] = []
    for p in pairs:
        try:
            r = analyze_zones(p, params)
        except Exception as e:
            logger.exception("zones.analyze_zones failed for %s: %s", p, e)
            r = None
        if r is not None:
            items.append(r)

    any_market_closed = any(it.get("market_closed") for it in items)
    response = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "items": items,
        "count": len(items),
        "market_closed": any_market_closed,
    }
    _zones_cache[cache_key] = (now, response)
    return response
