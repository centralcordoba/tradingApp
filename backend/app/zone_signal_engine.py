"""
Motor de señales para Zonas Activas — AUDUSD y USDCAD.

Capas de confirmación:
  1. Vetos duros — bloqueo total si falla cualquiera
  2. Sesión — ventana de liquidez por par
  3. Volatilidad — ATR dentro de rango útil para scalp
  4. Alineación M30/M5 — tendencia o fade confirmado
  5. Calidad del nivel S/R — fuerza, toques, distancia
  6. Price action — wick de rechazo en el nivel
  7. Estado técnico — RSI, EMA9, estructura, posición en rango

Reglas por par:
  AUDUSD — sigue bien confirmaciones técnicas; sesión Asian/London preferida;
            un wick moderado es suficiente si el resto confluye.
  USDCAD — más volátil; necesita wick fuerte + nivel probado + sesión NY;
            thresholds de score más exigentes.

Gestión de riesgo:
  $50.000 / x100 / 3 lotes / límite diario $2.500 / límite total $5.000
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _MADRID_TZ = _ZoneInfo("Europe/Madrid")
except Exception:
    _MADRID_TZ = None  # tzdata no disponible → fallback UTC

# ─── Cuenta ───────────────────────────────────────────────────────────────

ACCOUNT_CONFIG = {
    "size_usd":           50_000.0,
    "leverage":           100,
    "lot_size":           3.0,
    "max_daily_loss_usd": 2_500.0,
    "max_total_loss_usd": 5_000.0,
}

PIP_VALUE_PER_LOT: dict[str, float] = {
    "AUDUSD": 10.0,
    "USDCAD":  7.7,   # ≈ 10 / USDCAD (varía con el precio)
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "USDCHF":  9.2,
    "USDJPY":  9.0,
    "XAUUSD": 10.0,
    "default": 10.0,
}

# ─── Configuración por par ────────────────────────────────────────────────

PAIR_CONFIG: dict[str, dict] = {
    "AUDUSD": {
        # ── Umbrales de score ────────────────────────────────────────
        "min_score_strong":  10,   # ≥ 10/18 → FUERTE_COMPRA/VENTA
        "min_score_normal":   7,   # ≥  7/18 → COMPRA/VENTA
        "min_score_neutral":  4,   # ≥  4/18 → NEUTRAL (informacional)

        # ── SL cap ──────────────────────────────────────────────────
        "sl_max_pips": 20.0,

        # ── Volatilidad útil para scalp (ATR M15 en pips) ──────────
        # < min → mercado muerto, spread relativo alto → VETO
        # > max → choppy, gappy → VETO
        "atr_min_pips":  3.0,
        "atr_max_pips": 22.0,

        # ── Nivel cercano ────────────────────────────────────────────
        "max_entry_distance_pips": 12.0,
        "min_level_strength": 2,

        # ── Sesiones (hora Madrid, formato [start, end) 24h) ─────────
        # AUD opera bien en apertura Tokyo (02-09 Madrid) y London (09-13).
        # El overlap LDN-NY (14-17) también tiene buena liquidez.
        "sessions": {
            "fire":  [(9, 13), (14, 17)],   # London Open + overlap: +2 pts
            "ok":    [(2,  9), (13, 14), (17, 19)],   # Asian + pre-NY + NY mid: +1 pt
            "avoid": [(19, 24), (0, 2)],    # NY tarde + noche: sin puntos, no veto
        },
        "veto_avoid_session": False,        # AUDUSD: sesión desfavorable penaliza pero no bloquea

        # ── Wick ────────────────────────────────────────────────────
        "wick_min_for_normal": 1.2,         # umbral mínimo para señal normal
        "wick_min_for_strong": 1.8,         # umbral mínimo para señal fuerte
        "require_wick_for_normal": False,   # AUDUSD: sin wick puede emitir COMPRA con score alto
        "require_wick_for_strong": True,    # Para FUERTE siempre necesita wick

        # ── Estructura ───────────────────────────────────────────────
        # Si cross=A (tendencia) pero estructura M5 = RANGE → no operar tendencia
        "veto_range_in_trend": True,

        # ── Scanner bloque ───────────────────────────────────────────
        "veto_bloque2_in_trend": True,      # Bloque 2 = "sin edge" → veto en setup tendencia
    },

    "USDCAD": {
        # ── Umbrales de score (más exigentes) ────────────────────────
        "min_score_strong":  12,   # ≥ 12/18 → FUERTE_COMPRA/VENTA
        "min_score_normal":   8,   # ≥  8/18 → COMPRA/VENTA
        "min_score_neutral":  4,

        # ── SL cap ──────────────────────────────────────────────────
        "sl_max_pips": 20.0,

        # ── Volatilidad (USDCAD es más volátil, umbral más alto) ─────
        "atr_min_pips":  4.0,
        "atr_max_pips": 28.0,

        # ── Nivel cercano ────────────────────────────────────────────
        "max_entry_distance_pips": 10.0,   # Más estricto que AUDUSD
        "min_level_strength": 3,           # USDCAD: siempre necesita nivel ≥ 3★

        # ── Sesiones ─────────────────────────────────────────────────
        # USDCAD es más activo en la sesión NY (CAD data + USD flows).
        # Fuera de NY el spread es mayor y el movimiento menos predecible.
        "sessions": {
            "fire":  [(14, 21)],           # NY completa: +2 pts
            "ok":    [(13, 14), (21, 22)], # Pre-NY + cierre NY: +1 pt
            "avoid": [(0, 13), (22, 24)],  # Todo fuera de NY: veto
        },
        "veto_avoid_session": True,        # USDCAD: FUERA DE NY → VETO DURO

        # ── Wick ────────────────────────────────────────────────────
        "wick_min_for_normal": 1.5,        # Umbral más alto que AUDUSD
        "wick_min_for_strong": 2.2,
        "require_wick_for_normal": True,   # USDCAD: sin wick NO se emite señal normal
        "require_wick_for_strong": True,

        # ── Estructura ───────────────────────────────────────────────
        "veto_range_in_trend": True,

        # ── Scanner bloque ───────────────────────────────────────────
        "veto_bloque2_in_trend": True,     # Bloque 2 = veto duro en USDCAD
    },
}

# Configuración por defecto para pares no configurados específicamente
_DEFAULT_CONFIG = PAIR_CONFIG["AUDUSD"]

# Score máximo teórico (suma de todos los factores positivos)
MAX_SCORE = 18

# RRR mínimo global
MIN_RRR = 2.0


# ─── Helpers ──────────────────────────────────────────────────────────────

def _cfg(pair: str) -> dict:
    return PAIR_CONFIG.get(pair.upper(), _DEFAULT_CONFIG)


def _pip_value(pair: str) -> float:
    return PIP_VALUE_PER_LOT.get(pair.upper(), PIP_VALUE_PER_LOT["default"])


def _madrid_hour() -> int:
    """Hora actual en Madrid (0-23). Fallback a UTC si tzdata no disponible."""
    if _MADRID_TZ is not None:
        return datetime.now(_MADRID_TZ).hour
    return datetime.now(timezone.utc).hour


def _session_status(cfg: dict, hour: int) -> str:
    """Devuelve 'fire', 'ok' o 'avoid' para la hora Madrid dada."""
    for start, end in cfg["sessions"].get("fire", []):
        if start <= hour < end:
            return "fire"
    for start, end in cfg["sessions"].get("ok", []):
        if start <= hour < end:
            return "ok"
    return "avoid"


def _atr_pips(atr_value: Optional[float], pip_size: float) -> Optional[float]:
    if atr_value is None or pip_size <= 0:
        return None
    return atr_value / pip_size


# ─── Selección del mejor nivel ────────────────────────────────────────────

def _best_level_for_side(
    levels: list[dict],
    scanner_side: str,
    cfg: dict,
) -> Optional[dict]:
    """
    Selecciona el nivel activo más adecuado para el side dado.
    Filtra por distancia máxima y fuerza mínima del par.
    Prioriza: wick confirmado > fuerza > cercanía.
    """
    target_type = "support" if scanner_side == "LONG" else "resistance"
    max_dist = cfg["max_entry_distance_pips"]
    min_str  = cfg["min_level_strength"]

    candidates = [
        lv for lv in levels
        if lv.get("type") == target_type
        and lv.get("active")
        and lv.get("distance_pips", 999.0) <= max_dist
        and lv.get("strength", 0) >= min_str
    ]
    if not candidates:
        return None

    wick_min = cfg.get("wick_min_for_normal", 1.2)

    def _sort(lv: dict) -> tuple:
        wick = lv.get("last_touch_wick") or {}
        has_wick = wick.get("ratio", 0.0) >= wick_min
        return (0 if has_wick else 1, -lv.get("strength", 0), lv.get("distance_pips", 999.0))

    candidates.sort(key=_sort)
    return candidates[0]


def _opposite_level(levels: list[dict], scanner_side: str) -> Optional[dict]:
    """Nivel opuesto más cercano (activo o en rango) para el objetivo de TP."""
    target_type = "resistance" if scanner_side == "LONG" else "support"
    pool = [
        lv for lv in levels
        if lv.get("type") == target_type
        and (lv.get("active") or lv.get("within_range"))
    ]
    return min(pool, key=lambda lv: lv.get("distance_pips", 999.0)) if pool else None


# ─── Scoring de confirmación ──────────────────────────────────────────────

def _score_signal(
    *,
    cross_state: str,
    scanner_side: str,
    scanner_confluence: int,
    extended_status: str,
    rsi: Optional[float],
    level: dict,
    # Contexto extendido del scanner
    structure: str,
    struct_bullish: Optional[bool],
    scanner_bloque: str,
    range_pos: float,
    change_pct: float,
    # Contexto de sesión y volatilidad
    session_status: str,
    atr_m15_pips: Optional[float],
    cfg: dict,
) -> tuple[int, list[str], list[str]]:
    """
    Scoring multi-capa por par (max 18 puntos).

    Base (max 12):
      M30 A FAVOR          +3   Tendencia alineada M30 y M5
      M30 RANGO (fade)     +1   Mean-reversion válida
      Nivel fuerza ≥5★     +3   / ≥4★ +2 / ≥3★ +1
      Wick fuerte ≥ umbral +2   / wick normal +1
      Toques ≥ 4           +1
      Confluencia M5 ≥ 5   +1
      Precio no extendido  +1
      RSI alineado         +1

    Contexto (max 6):
      Sesión FIRE          +2   / OK +1 / AVOID 0
      Volatilidad en rango +1
      Estructura M5 HH/LL  +1   (confirma tendencia)
      Scanner Bloque 1     +1   (tendencia limpia)
      Posición en rango    +1   (precio en zona favorable, no en extremo opuesto)
    """
    met: list[str] = []
    failed: list[str] = []
    score = 0

    # ── 1. Alineación M30/M5 ─────────────────────────────────────────
    if cross_state == "A":
        score += 3
        met.append("M30 A FAVOR: tendencia alineada en ambos timeframes (+3)")
    elif cross_state == "B":
        score += 1
        met.append("FADE EN RANGO: mean-reversion en rango M30, objetivo extremo opuesto (+1)")
    else:
        failed.append(f"Cruce M30/M5 sin confluencia (estado {cross_state}) — sin puntos")

    # ── 2. Fuerza del nivel ──────────────────────────────────────────
    strength = level.get("strength", 0)
    if strength >= 5:
        score += 3
        met.append(f"Nivel {strength}★: el más probado históricamente (+3)")
    elif strength >= 4:
        score += 2
        met.append(f"Nivel {strength}★: muy fuerte (+2)")
    elif strength >= 3:
        score += 1
        met.append(f"Nivel {strength}★: moderado (+1)")
    else:
        failed.append(f"Nivel {strength}★: débil, pocos tests históricos (sin puntos)")

    # ── 3. Wick de rechazo en el nivel ───────────────────────────────
    wick = level.get("last_touch_wick") or {}
    ratio = wick.get("ratio", 0.0)
    direction = wick.get("direction", "neutral")
    wick_aligned = (
        (scanner_side == "LONG" and direction == "bull") or
        (scanner_side == "SHORT" and direction == "bear")
    )
    wick_strong_threshold = cfg.get("wick_min_for_strong", 2.2)
    wick_normal_threshold = cfg.get("wick_min_for_normal", 1.5)

    if ratio >= wick_strong_threshold and wick_aligned:
        score += 2
        met.append(f"Rechazo fuerte {ratio:.1f}x body — price action confirma el nivel (+2)")
    elif ratio >= wick_normal_threshold and wick_aligned:
        score += 1
        met.append(f"Rechazo {ratio:.1f}x body en dirección correcta (+1)")
    elif ratio >= wick_normal_threshold and not wick_aligned:
        failed.append(f"Wick {ratio:.1f}x pero dirección contraria al trade — señal mixta (sin puntos)")
    else:
        failed.append(f"Sin wick de rechazo claro en el nivel (ratio: {ratio:.1f}x) — sin puntos")

    # ── 4. Historial del nivel (toques) ──────────────────────────────
    touches = level.get("touches", 0)
    if touches >= 4:
        score += 1
        met.append(f"{touches} toques — nivel respetado múltiples veces (+1)")
    elif touches >= 2:
        met.append(f"{touches} toques — historial básico (sin puntos extra)")
    else:
        failed.append(f"{touches} toque(s) — nivel sin historial suficiente (sin puntos)")

    # ── 5. Confluencia del scanner M5 ────────────────────────────────
    if scanner_confluence >= 5:
        score += 1
        met.append(f"Scanner M5 {scanner_confluence}/7 — señal fuerte en M5 (+1)")
    elif scanner_confluence >= 3:
        met.append(f"Scanner M5 {scanner_confluence}/7 — señal moderada (sin puntos)")
    else:
        failed.append(f"Scanner M5 {scanner_confluence}/7 — confluencia baja (sin puntos)")

    # ── 6. Distancia al EMA9 ─────────────────────────────────────────
    if extended_status == "normal":
        score += 1
        met.append("Precio cerca del EMA9 — entrada técnica no tardía (+1)")
    elif extended_status == "extended":
        failed.append("Precio extendido 1-2.5×ATR del EMA9 — pullback esperado (sin puntos)")
    else:
        failed.append("Precio muy extendido >2.5×ATR del EMA9 — entrada tardía (sin puntos)")

    # ── 7. RSI alineado con el lado ──────────────────────────────────
    if rsi is not None:
        if scanner_side == "LONG":
            if rsi <= 42:
                score += 1
                met.append(f"RSI {rsi:.0f}: pullback o sobreventa — favorable para LONG (+1)")
            elif rsi >= 70:
                failed.append(f"RSI {rsi:.0f}: sobrecompra — entrar LONG aquí es tardío (sin puntos)")
            elif 42 < rsi <= 55:
                met.append(f"RSI {rsi:.0f}: zona neutra para LONG (sin puntos)")
            else:
                failed.append(f"RSI {rsi:.0f}: momentum alcista sin pullback — riesgo de reversión (sin puntos)")
        else:
            if rsi >= 58:
                score += 1
                met.append(f"RSI {rsi:.0f}: sobrecompra o pullback — favorable para SHORT (+1)")
            elif rsi <= 30:
                failed.append(f"RSI {rsi:.0f}: sobreventa — entrar SHORT aquí es tardío (sin puntos)")
            elif 45 <= rsi < 58:
                met.append(f"RSI {rsi:.0f}: zona neutra para SHORT (sin puntos)")
            else:
                failed.append(f"RSI {rsi:.0f}: momentum bajista sin pullback — riesgo de rebote (sin puntos)")
    else:
        failed.append("RSI no disponible (sin puntos)")

    # ── 8. Sesión de trading ──────────────────────────────────────────
    if session_status == "fire":
        score += 2
        met.append("Sesión FIRE: ventana de mayor liquidez para este par (+2)")
    elif session_status == "ok":
        score += 1
        met.append("Sesión OK: liquidez aceptable para operar (+1)")
    else:
        failed.append("Sesión AVOID: fuera de la ventana de liquidez óptima (sin puntos)")

    # ── 9. Volatilidad en rango útil ─────────────────────────────────
    atr_min = cfg.get("atr_min_pips", 3.0)
    atr_max = cfg.get("atr_max_pips", 22.0)
    if atr_m15_pips is not None:
        if atr_min <= atr_m15_pips <= atr_max:
            score += 1
            met.append(f"ATR M15 {atr_m15_pips:.1f} pips — volatilidad útil para scalp (+1)")
        elif atr_m15_pips < atr_min:
            failed.append(f"ATR M15 {atr_m15_pips:.1f} pips < {atr_min} mínimo — mercado demasiado tranquilo (sin puntos)")
        else:
            failed.append(f"ATR M15 {atr_m15_pips:.1f} pips > {atr_max} máximo — mercado demasiado volátil (sin puntos)")
    else:
        failed.append("ATR M15 no disponible — volatilidad no verificable (sin puntos)")

    # ── 10. Estructura de mercado M5 ─────────────────────────────────
    structure_bullish_types = {"HH", "HL"}
    structure_bearish_types = {"LL", "LH"}
    struct_ok = (
        (scanner_side == "LONG" and structure in structure_bullish_types) or
        (scanner_side == "SHORT" and structure in structure_bearish_types)
    )
    if struct_ok:
        score += 1
        met.append(f"Estructura M5 {structure} — confirma dirección del trade (+1)")
    elif structure == "RANGE":
        failed.append("Estructura M5 RANGE — mercado lateral sin dirección clara (sin puntos)")
    else:
        failed.append(f"Estructura M5 {structure} — no confirma dirección (sin puntos)")

    # ── 11. Scanner bloque 1 (tendencia limpia) ───────────────────────
    if scanner_bloque == "1":
        score += 1
        met.append("Scanner Bloque 1: tendencia limpia, EMAs alineadas (+1)")
    elif scanner_bloque == "3":
        met.append("Scanner Bloque 3: reversión en extremo — setup válido pero atípico (sin puntos)")
    else:
        failed.append("Scanner Bloque 2: sin edge claro en M5 (sin puntos)")

    # ── 12. Posición en rango (no en extremo contrario) ───────────────
    range_ok = (
        (scanner_side == "LONG" and range_pos <= 0.55) or
        (scanner_side == "SHORT" and range_pos >= 0.45)
    )
    if range_ok:
        score += 1
        met.append(f"Posición en rango {range_pos:.0%} — precio en zona favorable para el trade (+1)")
    else:
        failed.append(
            f"Posición en rango {range_pos:.0%} — precio en extremo contrario al trade (sin puntos)"
        )

    return score, met, failed


# ─── SL y TP ──────────────────────────────────────────────────────────────

def _calculate_sl_tp(
    *,
    pair: str,
    pip_size: float,
    scanner_side: str,
    entry_price: float,
    best_level: dict,
    opposite_level: Optional[dict],
    atr_m15: Optional[float],
    cfg: dict,
) -> dict:
    """
    SL: más allá del nivel ± max(0.5×ATR_M15, 3 pips).
    TP: nivel opuesto si RRR ≥ 2.0; sino automático a 2×risk.
    """
    atr_buffer = (atr_m15 * 0.5) if atr_m15 else (3 * pip_size)
    buffer = max(atr_buffer, 3 * pip_size)
    level_price = best_level["price"]
    max_sl_pips = cfg.get("sl_max_pips", 20.0)
    max_sl_price = max_sl_pips * pip_size

    if scanner_side == "LONG":
        sl_price = level_price - buffer
        if entry_price - sl_price > max_sl_price:
            sl_price = entry_price - max_sl_price
    else:
        sl_price = level_price + buffer
        if sl_price - entry_price > max_sl_price:
            sl_price = entry_price + max_sl_price

    risk_price = abs(entry_price - sl_price)
    risk_pips = round(risk_price / pip_size, 1)

    reward_pips = round(risk_pips * 2.0, 1)
    tp_source = "2:1_calculado"
    tp_price = (
        entry_price + risk_price * 2.0 if scanner_side == "LONG"
        else entry_price - risk_price * 2.0
    )

    if opposite_level:
        opp_price = opposite_level["price"]
        opp_reward = abs(opp_price - entry_price) / pip_size
        if opp_reward >= risk_pips * MIN_RRR:
            tp_price = opp_price
            reward_pips = round(opp_reward, 1)
            tp_source = "nivel_sr"
        else:
            tp_source = "2:1_fallback"

    rrr = round(reward_pips / risk_pips, 2) if risk_pips > 0 else None
    return {
        "sl_price": round(sl_price, 5),
        "tp_price": round(tp_price, 5),
        "risk_pips": risk_pips,
        "reward_pips": reward_pips,
        "rrr": rrr,
        "rrr_ok": rrr is not None and rrr >= MIN_RRR,
        "sl_within_cap": risk_pips <= max_sl_pips,
        "tp_source": tp_source,
    }


# ─── Gestión de riesgo ────────────────────────────────────────────────────

def _account_risk_check(
    *,
    pair: str,
    risk_pips: float,
    daily_loss_usd: float,
    total_loss_usd: float,
) -> dict:
    lot_size = ACCOUNT_CONFIG["lot_size"]
    pip_val = _pip_value(pair)
    risk_usd = round(risk_pips * pip_val * lot_size, 2)
    max_daily = ACCOUNT_CONFIG["max_daily_loss_usd"]
    max_total = ACCOUNT_CONFIG["max_total_loss_usd"]

    daily_blocked = (daily_loss_usd + risk_usd) > max_daily
    total_blocked = (total_loss_usd + risk_usd) > max_total
    blocked = daily_blocked or total_blocked

    reasons: list[str] = []
    if daily_blocked:
        remaining = max(0.0, max_daily - daily_loss_usd)
        reasons.append(
            f"Perdida diaria: ${daily_loss_usd:.0f} + ${risk_usd:.0f} > ${max_daily:.0f} max "
            f"(margen: ${remaining:.0f})"
        )
    if total_blocked:
        remaining = max(0.0, max_total - total_loss_usd)
        reasons.append(
            f"Perdida total: ${total_loss_usd:.0f} + ${risk_usd:.0f} > ${max_total:.0f} max "
            f"(margen: ${remaining:.0f})"
        )

    return {
        "risk_usd": risk_usd,
        "lot_size": lot_size,
        "pip_value": pip_val,
        "daily_loss_usd": daily_loss_usd,
        "total_loss_usd": total_loss_usd,
        "max_daily_loss_usd": max_daily,
        "max_total_loss_usd": max_total,
        "blocked": blocked,
        "block_reasons": reasons,
    }


# ─── API pública ──────────────────────────────────────────────────────────

def generate_zone_signal(
    zone_item: dict,
    scanner_item: Optional[dict],
    *,
    daily_loss_usd: float = 0.0,
    total_loss_usd: float = 0.0,
) -> dict:
    """
    Genera señal para el par. zone_item debe tener 'cross' ya inyectado.

    Retorna dict con has_signal, signal, confidence, entry/sl/tp,
    criteria_met/failed, rejection_reason, account_check, session_status.
    """
    pair = zone_item.get("pair", "")
    pip_size = zone_item.get("pip_size", 0.0001)
    levels = zone_item.get("levels", [])
    market_closed = zone_item.get("market_closed", False)
    cross = zone_item.get("cross") or {}
    cross_state = cross.get("state", "NA")
    atr_m15 = zone_item.get("atr_m15")

    cfg = _cfg(pair)
    hour = _madrid_hour()
    session_status = _session_status(cfg, hour)
    atr_m15_pips_val = _atr_pips(atr_m15, pip_size)

    # Datos del scanner
    scanner_side     = "NEUTRAL"
    scanner_confluence = 0
    extended_status  = "normal"
    rsi: Optional[float] = None
    structure        = "RANGE"
    struct_bullish: Optional[bool] = None
    scanner_bloque   = "2"
    range_pos        = 0.5
    change_pct       = 0.0
    atr_m5: Optional[float] = None

    if scanner_item:
        scanner_side       = scanner_item.get("side", "NEUTRAL")
        scanner_confluence = scanner_item.get("confluence", 0)
        extended_status    = scanner_item.get("extended_status", "normal")
        rsi                = scanner_item.get("rsi")
        structure          = scanner_item.get("structure", "RANGE")
        struct_bullish     = scanner_item.get("struct_bullish")
        scanner_bloque     = scanner_item.get("bloque", "2")
        range_pos          = scanner_item.get("range_pos", 0.5)
        change_pct         = scanner_item.get("change_pct", 0.0)
        atr_m5             = scanner_item.get("atr")

    # ═══════════════════════════════════════════════════════════════
    # CAPA 1: VETOS DUROS — orden de bloqueo más grave a menos
    # ═══════════════════════════════════════════════════════════════

    # V1. Mercado cerrado (datos > 30 min)
    if market_closed:
        return _no_signal("Mercado cerrado — ultima vela demasiado antigua para scalping")

    # V2. Scanner sin dirección (NEUTRAL = confluencia < 3/7)
    if scanner_side == "NEUTRAL":
        return _no_signal(
            f"Scanner M5 NEUTRAL (confluencia {scanner_confluence}/7) — "
            "sin direccion clara para entrada. Se necesita bias minimo 3/7."
        )

    # V3. Conflicto M30/M5 (el M5 va contra el bias director M30)
    if cross_state == "C":
        return _no_signal(
            "CONFLICTO M30/M5 — el M5 va en contra del bias director M30. "
            "No operar contra tendencia superior sin setup de alta probabilidad."
        )

    # V4. Sesión desfavorable (solo para pares que lo requieren — USDCAD)
    if session_status == "avoid" and cfg.get("veto_avoid_session", False):
        return _no_signal(
            f"Sesion desfavorable para {pair} a las {hour:02d}h Madrid — "
            "liquidez insuficiente fuera de la ventana NY. Esperar apertura NY (14h Madrid)."
        )

    # V5. Precio muy extendido del EMA9 (entrada tardía)
    if extended_status == "skip":
        return _no_signal(
            "Precio demasiado extendido del EMA9 (>2.5xATR) — entrada tardia. "
            "Esperar retroceso al EMA9 o al nivel S/R."
        )

    # V6. Volatilidad fuera del rango útil para scalping
    atr_min = cfg.get("atr_min_pips", 3.0)
    atr_max = cfg.get("atr_max_pips", 22.0)
    if atr_m15_pips_val is not None:
        if atr_m15_pips_val < atr_min:
            return _no_signal(
                f"ATR M15 {atr_m15_pips_val:.1f} pips < {atr_min} minimo — mercado demasiado tranquilo. "
                "Spread relativo alto; scalping no viable en este contexto."
            )
        if atr_m15_pips_val > atr_max:
            return _no_signal(
                f"ATR M15 {atr_m15_pips_val:.1f} pips > {atr_max} maximo — mercado demasiado volatil. "
                "Riesgo de slippage y gapping alto para scalp de 0-30 min."
            )

    # V7. Mercado lateral con setup de tendencia (cross A + structure RANGE)
    if cross_state == "A" and structure == "RANGE" and cfg.get("veto_range_in_trend", True):
        return _no_signal(
            "Conflicto tendencia/estructura — M30 marca tendencia (A FAVOR) pero M5 muestra "
            "estructura RANGE (sin HH/HL ni LL/LH claros). Tendencia sin impulso = trampa frecuente."
        )

    # V8. Scanner Bloque 2 en setup de tendencia (sin edge en M5)
    if cross_state == "A" and scanner_bloque == "2" and cfg.get("veto_bloque2_in_trend", True):
        return _no_signal(
            "Scanner Bloque 2 con cross A FAVOR — el M5 clasifica como 'sin edge' "
            "(EMAs mixtas, bias bajo, o precio extendido). No operar tendencia sin impulso limpio."
        )

    # V9. Buscar el mejor nivel activo en la dirección del scanner
    best_level = _best_level_for_side(levels, scanner_side, cfg)
    if best_level is None:
        max_dist = cfg["max_entry_distance_pips"]
        min_str  = cfg["min_level_strength"]
        dir_str  = "soporte" if scanner_side == "LONG" else "resistencia"
        return _no_signal(
            f"Sin {dir_str} activo a <= {max_dist} pips con fuerza >= {min_str}. "
            f"El precio no esta sobre una zona S/R operable para {scanner_side} en {pair} ahora."
        )

    # V10. Wick requerido para USDCAD (siempre) y para señal FUERTE en AUDUSD
    wick = best_level.get("last_touch_wick") or {}
    wick_ratio = wick.get("ratio", 0.0)
    wick_dir = wick.get("direction", "neutral")
    wick_aligned = (
        (scanner_side == "LONG" and wick_dir == "bull") or
        (scanner_side == "SHORT" and wick_dir == "bear")
    )
    wick_normal_min = cfg.get("wick_min_for_normal", 1.2)
    if cfg.get("require_wick_for_normal", False) and not (wick_ratio >= wick_normal_min and wick_aligned):
        return _no_signal(
            f"Sin rechazo claro en el nivel (wick {wick_ratio:.1f}x, se necesita >= {wick_normal_min}x "
            f"alineado con {scanner_side}). {pair} requiere confirmacion de price action en el nivel."
        )

    # V11. Nivel opuesto para TP
    opp_level = _opposite_level(levels, scanner_side)

    # V12. SL / TP
    entry_price = zone_item.get("price", best_level["price"])
    sl_tp = _calculate_sl_tp(
        pair=pair,
        pip_size=pip_size,
        scanner_side=scanner_side,
        entry_price=entry_price,
        best_level=best_level,
        opposite_level=opp_level,
        atr_m15=atr_m15,
        cfg=cfg,
    )

    if not sl_tp["sl_within_cap"]:
        max_sl = cfg.get("sl_max_pips", 20.0)
        return _no_signal(
            f"SL {sl_tp['risk_pips']:.1f} pips excede el cap de {max_sl:.0f} pips para {pair}. "
            "Nivel demasiado alejado del precio para scalp de 0-30 min."
        )

    if not sl_tp["rrr_ok"]:
        rrr_val = sl_tp.get("rrr")
        rrr_str = f"{rrr_val:.2f}" if rrr_val is not None else "N/A"
        return _no_signal(
            f"RRR {rrr_str} insuficiente (minimo {MIN_RRR:.1f}:1). "
            "Sin nivel opuesto suficientemente alejado para justificar el riesgo."
        )

    # V13. Gestión de cuenta
    account_check = _account_risk_check(
        pair=pair,
        risk_pips=sl_tp["risk_pips"],
        daily_loss_usd=daily_loss_usd,
        total_loss_usd=total_loss_usd,
    )
    if account_check["blocked"]:
        return _no_signal(
            "Sistema bloqueado — limite de perdida alcanzado. " +
            " | ".join(account_check["block_reasons"]),
            account_check=account_check,
            session_status=session_status,
        )

    # ═══════════════════════════════════════════════════════════════
    # CAPA 2: SCORING DE CONFIRMACIÓN
    # ═══════════════════════════════════════════════════════════════

    score, met, failed = _score_signal(
        cross_state=cross_state,
        scanner_side=scanner_side,
        scanner_confluence=scanner_confluence,
        extended_status=extended_status,
        rsi=rsi,
        level=best_level,
        structure=structure,
        struct_bullish=struct_bullish,
        scanner_bloque=scanner_bloque,
        range_pos=range_pos,
        change_pct=change_pct,
        session_status=session_status,
        atr_m15_pips=atr_m15_pips_val,
        cfg=cfg,
    )

    # ── Veto adicional para señal FUERTE: wick mínimo ────────────────
    if cfg.get("require_wick_for_strong", True):
        wick_strong_min = cfg.get("wick_min_for_strong", 2.0)
        strong_threshold = cfg["min_score_strong"]
        if score >= strong_threshold and not (wick_ratio >= wick_strong_min and wick_aligned):
            # Degradar a NORMAL si no hay wick fuerte suficiente
            score = min(score, cfg["min_score_normal"] + 1)
            failed.append(
                f"Señal degradada a COMPRA/VENTA — wick {wick_ratio:.1f}x no alcanza "
                f"{wick_strong_min}x requerido para FUERTE en {pair}"
            )

    # ═══════════════════════════════════════════════════════════════
    # CLASIFICACIÓN FINAL
    # ═══════════════════════════════════════════════════════════════

    is_long = scanner_side == "LONG"
    min_strong  = cfg["min_score_strong"]
    min_normal  = cfg["min_score_normal"]
    min_neutral = cfg["min_score_neutral"]

    if score >= min_strong:
        signal = "FUERTE_COMPRA" if is_long else "FUERTE_VENTA"
        confidence = round(min(0.95, 0.74 + (score - min_strong) * 0.04), 2)
    elif score >= min_normal:
        signal = "COMPRA" if is_long else "VENTA"
        confidence = round(0.56 + (score - min_normal) * 0.04, 2)
    elif score >= min_neutral:
        signal = "NEUTRAL"
        confidence = round(0.30 + (score - min_neutral) * 0.05, 2)
    else:
        top_fail = ", ".join(failed[:2]) if failed else "confirmaciones insuficientes"
        return _no_signal(
            f"Score {score}/{MAX_SCORE} — umbral minimo {min_neutral} no alcanzado. {top_fail}.",
            account_check=account_check,
            session_status=session_status,
        )

    return {
        "has_signal": True,
        "signal": signal,
        "confidence": confidence,
        "score": score,
        "max_score": MAX_SCORE,
        "side": scanner_side,
        "entry_price": round(entry_price, 5),
        "sl_price": sl_tp["sl_price"],
        "tp_price": sl_tp["tp_price"],
        "risk_pips": sl_tp["risk_pips"],
        "reward_pips": sl_tp["reward_pips"],
        "rrr": sl_tp["rrr"],
        "tp_source": sl_tp["tp_source"],
        "session_status": session_status,
        "session_hour_madrid": hour,
        "level_used": {
            "price": best_level["price"],
            "type": best_level["type"],
            "strength": best_level["strength"],
            "touches": best_level["touches"],
            "distance_pips": best_level["distance_pips"],
        },
        "criteria_met": met,
        "criteria_failed": failed,
        "rejection_reason": None,
        "account_check": account_check,
    }


def _no_signal(
    reason: str,
    account_check: Optional[dict] = None,
    session_status: str = "unknown",
) -> dict:
    return {
        "has_signal": False,
        "signal": "SIN_SEÑAL",
        "confidence": 0.0,
        "score": 0,
        "max_score": MAX_SCORE,
        "side": None,
        "entry_price": None,
        "sl_price": None,
        "tp_price": None,
        "risk_pips": None,
        "reward_pips": None,
        "rrr": None,
        "tp_source": None,
        "session_status": session_status,
        "session_hour_madrid": _madrid_hour(),
        "level_used": None,
        "criteria_met": [],
        "criteria_failed": [],
        "rejection_reason": reason,
        "account_check": account_check,
    }
