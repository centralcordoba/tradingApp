"""
geometry_detector.py
Detecta canales y triángulos con regresión lineal sobre pivots M30.
Sin IA, sin costo, determinístico.
"""

import numpy as np
from typing import Optional


# ─── Pivots ──────────────────────────────────────────────────────────────────

def _find_pivots(highs: list, lows: list, n: int = 3) -> tuple:
    """
    Retorna pivot highs y pivot lows como lista de (índice, precio).
    Requiere n velas a cada lado siendo menores/mayores.
    """
    pivot_highs = []
    pivot_lows  = []
    length = len(highs)

    for i in range(n, length - n):
        if all(highs[i] > highs[i - j] and highs[i] > highs[i + j] for j in range(1, n + 1)):
            pivot_highs.append((i, highs[i]))
        if all(lows[i] < lows[i - j] and lows[i] < lows[i + j] for j in range(1, n + 1)):
            pivot_lows.append((i, lows[i]))

    return pivot_highs, pivot_lows


# ─── Regresión lineal ─────────────────────────────────────────────────────────

def _linear_regression(points: list) -> tuple:
    """
    Regresión lineal sobre lista de (índice, precio).
    Retorna (slope, intercept, r_squared).
    """
    if len(points) < 2:
        return 0.0, 0.0, 0.0

    x = np.array([p[0] for p in points], dtype=float)
    y = np.array([p[1] for p in points], dtype=float)

    slope, intercept = np.polyfit(x, y, 1)

    y_pred = slope * x + intercept
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 1e-10 else 0.0

    return float(slope), float(intercept), float(r_squared)


# ─── Canal ────────────────────────────────────────────────────────────────────

def _detect_channel(
    pivot_highs: list,
    pivot_lows: list,
    current_price: float,
    pip_size: float,
    min_touches: int = 3,
) -> dict:
    """
    Detecta canal alcista, bajista o lateral.
    Requiere mínimo min_touches pivots en cada línea.
    Confianza basada en R² promedio de ambas regresiones.
    """
    empty = {
        "detectado": False,
        "tipo": "NINGUNO",
        "estado": "NINGUNO",
        "linea_superior": None,
        "linea_inferior": None,
        "confianza": "BAJA",
        "r_squared_sup": 0.0,
        "r_squared_inf": 0.0,
    }

    if len(pivot_highs) < min_touches or len(pivot_lows) < min_touches:
        return empty

    slope_h, intercept_h, r2_h = _linear_regression(pivot_highs)
    slope_l, intercept_l, r2_l = _linear_regression(pivot_lows)

    # Umbral mínimo de calidad
    if r2_h < 0.80 or r2_l < 0.80:
        return empty

    # Proyección al índice actual
    last_idx  = max(pivot_highs[-1][0], pivot_lows[-1][0])
    precio_sup = slope_h * last_idx + intercept_h
    precio_inf = slope_l * last_idx + intercept_l

    # Tipo por pendiente promedio
    avg_slope       = (slope_h + slope_l) / 2
    slope_threshold = pip_size * 0.5

    if avg_slope > slope_threshold:
        tipo = "ALCISTA"
    elif avg_slope < -slope_threshold:
        tipo = "BAJISTA"
    else:
        tipo = "LATERAL"

    # Estado del precio respecto al canal
    tolerance = pip_size * 3

    if current_price > precio_sup + tolerance:
        estado = "RUPTURA_ALCISTA"
    elif current_price < precio_inf - tolerance:
        estado = "RUPTURA_BAJISTA"
    elif abs(current_price - precio_sup) <= tolerance:
        estado = "RETESTEO_SUPERIOR"
    elif abs(current_price - precio_inf) <= tolerance:
        estado = "RETESTEO_INFERIOR"
    else:
        estado = "DENTRO"

    # Confianza
    avg_r2    = (r2_h + r2_l) / 2
    confianza = "ALTA" if avg_r2 >= 0.92 else "MEDIA" if avg_r2 >= 0.85 else "BAJA"

    return {
        "detectado":    True,
        "tipo":         tipo,
        "estado":       estado,
        "linea_superior": round(precio_sup, 5),
        "linea_inferior": round(precio_inf, 5),
        "confianza":    confianza,
        "r_squared_sup": round(r2_h, 3),
        "r_squared_inf": round(r2_l, 3),
    }


# ─── Triángulo ────────────────────────────────────────────────────────────────

def _detect_triangle(
    pivot_highs: list,
    pivot_lows: list,
    current_price: float,
    pip_size: float,
    min_touches: int = 3,
) -> dict:
    """
    Detecta triángulo simétrico, ascendente o descendente.
    Calcula vértice estimado e indica si el precio está llegando a él.
    """
    empty = {
        "detectado":        False,
        "tipo":             "NINGUNO",
        "estado":           "NINGUNO",
        "vertice_estimado": None,
        "confianza":        "BAJA",
    }

    if len(pivot_highs) < min_touches or len(pivot_lows) < min_touches:
        return empty

    slope_h, intercept_h, r2_h = _linear_regression(pivot_highs)
    slope_l, intercept_l, r2_l = _linear_regression(pivot_lows)

    if r2_h < 0.80 or r2_l < 0.80:
        return empty

    flat_threshold = pip_size * 0.3
    highs_falling  = slope_h < -flat_threshold
    highs_flat     = abs(slope_h) <= flat_threshold
    lows_rising    = slope_l > flat_threshold
    lows_flat      = abs(slope_l) <= flat_threshold

    # Clasificación — las líneas deben converger
    if highs_falling and lows_rising:
        tipo = "SIMETRICO"
    elif highs_flat and lows_rising:
        tipo = "ASCENDENTE"
    elif highs_falling and lows_flat:
        tipo = "DESCENDENTE"
    else:
        return empty  # Líneas divergen o son paralelas → no es triángulo

    # Vértice: intersección de las dos líneas de regresión
    vertice_x: Optional[float] = None
    vertice_y: Optional[float] = None

    if abs(slope_h - slope_l) > 1e-10:
        vertice_x = (intercept_l - intercept_h) / (slope_h - slope_l)
        vertice_y = slope_h * vertice_x + intercept_h

    # Estado
    last_idx  = max(pivot_highs[-1][0], pivot_lows[-1][0])
    precio_h  = slope_h * last_idx + intercept_h
    precio_l  = slope_l * last_idx + intercept_l
    tolerance = pip_size * 3

    if current_price > precio_h + tolerance:
        estado = "RUPTURA_ALCISTA"
    elif current_price < precio_l - tolerance:
        estado = "RUPTURA_BAJISTA"
    elif vertice_x is not None and last_idx >= vertice_x * 0.92:
        estado = "EN_VERTICE"   # Ruptura inminente
    else:
        estado = "FORMANDO"

    avg_r2    = (r2_h + r2_l) / 2
    confianza = "ALTA" if avg_r2 >= 0.92 else "MEDIA" if avg_r2 >= 0.85 else "BAJA"

    return {
        "detectado":        True,
        "tipo":             tipo,
        "estado":           estado,
        "vertice_estimado": round(float(vertice_y), 5) if vertice_y is not None else None,
        "confianza":        confianza,
    }


# ─── Entry point ──────────────────────────────────────────────────────────────

def _detect_geometry(
    candles: list,
    current_price: float,
    pip_size: float,
    lookback: int = 60,
) -> dict:
    """
    Entry point principal.

    Parámetros:
        candles       : lista de dicts con keys 'high', 'low', 'close'
        current_price : precio actual del par
        pip_size      : PIP_SIZES.get(symbol, PIP_SIZES["default"])
        lookback      : velas M30 a analizar (60 = ~30h)

    Retorna campo 'geometria' listo para agregar al JSON del radar:
    {
        "canal":     {...},
        "triangulo": {...},
        "ruptura":   {"confirmada": bool, "direccion": str, "figura": str}
    }

    Integración en _analyze_symbol:
        geometria = _detect_geometry(ohlc_data, price_now, pip_size)
        result["geometria"] = geometria
    """
    slice_  = candles[-lookback:]
    highs   = [c["high"]  for c in slice_]
    lows    = [c["low"]   for c in slice_]

    pivot_highs, pivot_lows = _find_pivots(highs, lows, n=3)

    canal     = _detect_channel(pivot_highs, pivot_lows, current_price, pip_size)
    triangulo = _detect_triangle(pivot_highs, pivot_lows, current_price, pip_size)

    # Ruptura consolidada — triángulo tiene prioridad si ambos detectados
    ruptura = {"confirmada": False, "direccion": "NINGUNA", "figura": "NINGUNA"}

    figura_activa = triangulo if triangulo["detectado"] else canal if canal["detectado"] else None

    if figura_activa:
        estado = figura_activa.get("estado", "NINGUNO")
        if "RUPTURA_ALCISTA" in estado:
            ruptura = {
                "confirmada": True,
                "direccion":  "BULLISH",
                "figura":     "TRIANGULO" if triangulo["detectado"] else "CANAL",
            }
        elif "RUPTURA_BAJISTA" in estado:
            ruptura = {
                "confirmada": True,
                "direccion":  "BEARISH",
                "figura":     "TRIANGULO" if triangulo["detectado"] else "CANAL",
            }

    return {
        "canal":     canal,
        "triangulo": triangulo,
        "ruptura":   ruptura,
    }
