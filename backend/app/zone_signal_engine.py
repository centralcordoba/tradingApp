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


# ─── Marco teórico (gates + confluencia → OPERAR / ESPERAR / NO OPERAR) ─────
#
# El marco reusa las dos capas del motor: los gates son los vetos duros de la
# CAPA 1 reencuadrados como checklist; la confluencia es el scoring de la CAPA 2.
# El M30 manda, el M5 ejecuta; la decisión final es del usuario.

def _gate(key: str, label: str, passed: bool, hard: bool, detail: str = "") -> dict:
    return {"key": key, "label": label, "passed": passed, "hard": hard, "detail": detail}


def generate_zone_marco(
    zone_item: dict,
    scanner_item: Optional[dict],
    *,
    news_active: bool = False,
    news_event: Optional[dict] = None,
    daily_loss_usd: float = 0.0,
    total_loss_usd: float = 0.0,
) -> dict:
    """
    Evalúa el par bajo el marco teórico. zone_item debe tener 'cross' inyectado.

    Devuelve un veredicto OPERAR / ESPERAR / NO_OPERAR con:
      - gates[]: checklist de filtros (duros → NO_OPERAR si fallan; blandos → degradan)
      - confluence: score 0..MAX_SCORE cuando los gates duros pasan
      - entry/sl/tp/rrr/level_used cuando hay setup
      - news_warning: si hay high-impact en ventana (degrada OPERAR→ESPERAR, nunca veta)
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

    # Datos del scanner M5
    scanner_side       = "NEUTRAL"
    scanner_confluence = 0
    extended_status    = "normal"
    rsi: Optional[float] = None
    structure          = "RANGE"
    struct_bullish: Optional[bool] = None
    scanner_bloque     = "2"
    range_pos          = 0.5
    change_pct         = 0.0

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

    gates: list[dict] = []

    # GATE 1 — Mercado abierto (duro)
    gates.append(_gate(
        "mercado_abierto", "Mercado abierto", not market_closed, True,
        "" if not market_closed else "Última vela demasiado antigua (>30 min) para scalping",
    ))

    # GATE 2 — Coherencia MTF M30/M5 (duro): ni NEUTRAL ni CONFLICTO
    if scanner_side == "NEUTRAL":
        mtf_ok, mtf_detail = False, f"Scanner M5 sin dirección (NEUTRAL, confluencia {scanner_confluence}/7)"
    elif cross_state == "C":
        mtf_ok, mtf_detail = False, "CONFLICTO M30/M5 — el M5 va contra el bias director M30"
    else:
        mtf_ok, mtf_detail = True, (
            "A FAVOR del M30" if cross_state == "A"
            else "Fade en rango M30" if cross_state == "B"
            else "M5 con dirección"
        )
    gates.append(_gate("mtf_coherente", "Coherencia MTF M30/M5", mtf_ok, True, mtf_detail))

    # GATE 3 — Sesión operable (duro solo si el par lo exige, p.ej. USDCAD)
    session_hard = bool(cfg.get("veto_avoid_session", False))
    session_ok = session_status != "avoid"
    gates.append(_gate(
        "sesion_operable", "Sesión operable", session_ok, session_hard,
        f"{session_status.upper()} · {hour:02d}h Madrid" +
        ("" if session_ok else f" — fuera de la ventana de liquidez de {pair}"),
    ))

    # GATE 4 — Precio no extendido del EMA9 (duro)
    gates.append(_gate(
        "no_extendido", "Precio no extendido", extended_status != "skip", True,
        {"normal": "Cerca del EMA9", "extended": "Extendido 1–2.5×ATR — pullback esperado",
         "skip": "Muy extendido >2.5×ATR — entrada tardía"}.get(extended_status, extended_status),
    ))

    # GATE 5 — Volatilidad útil para scalp (duro)
    atr_min = cfg.get("atr_min_pips", 3.0)
    atr_max = cfg.get("atr_max_pips", 22.0)
    if atr_m15_pips_val is None:
        vol_ok, vol_detail = True, "ATR M15 no disponible"
    elif atr_m15_pips_val < atr_min:
        vol_ok, vol_detail = False, f"ATR M15 {atr_m15_pips_val:.1f}p < {atr_min}p — mercado muerto"
    elif atr_m15_pips_val > atr_max:
        vol_ok, vol_detail = False, f"ATR M15 {atr_m15_pips_val:.1f}p > {atr_max}p — demasiado volátil"
    else:
        vol_ok, vol_detail = True, f"ATR M15 {atr_m15_pips_val:.1f}p — útil para scalp"
    gates.append(_gate("volatilidad_util", "Volatilidad útil", vol_ok, True, vol_detail))

    # GATE 6 — Estructura con impulso (duro, solo relevante en tendencia cross A)
    if cross_state == "A" and structure == "RANGE" and cfg.get("veto_range_in_trend", True):
        struct_ok, struct_detail = False, "M30 marca tendencia pero M5 está en RANGE — trampa frecuente"
    elif cross_state == "A" and scanner_bloque == "2" and cfg.get("veto_bloque2_in_trend", True):
        struct_ok, struct_detail = False, "Scanner Bloque 2 (sin edge) bajo cross A FAVOR"
    else:
        struct_ok, struct_detail = True, f"Estructura M5 {structure}"
    gates.append(_gate("estructura_impulso", "Estructura con impulso", struct_ok, True, struct_detail))

    # GATE 7 — Nivel S/R operable en la dirección del trade (duro)
    best_level = (
        _best_level_for_side(levels, scanner_side, cfg)
        if scanner_side in ("LONG", "SHORT") else None
    )
    if best_level is not None:
        level_ok, level_detail = True, (
            f"{best_level['type']} {best_level['price']} · {best_level['strength']}★ · "
            f"{best_level['distance_pips']}p"
        )
    else:
        dir_str = "soporte" if scanner_side == "LONG" else "resistencia" if scanner_side == "SHORT" else "nivel"
        level_ok, level_detail = False, (
            f"Sin {dir_str} activo a ≤{cfg['max_entry_distance_pips']}p con fuerza "
            f"≥{cfg['min_level_strength']}★"
        )
    gates.append(_gate("nivel_operable", "Nivel S/R operable", level_ok, True, level_detail))

    # GATE 8 — Rechazo confirmado en el nivel (duro solo si el par lo exige)
    wick = (best_level or {}).get("last_touch_wick") or {}
    wick_ratio = wick.get("ratio", 0.0)
    wick_dir = wick.get("direction", "neutral")
    wick_aligned = (
        (scanner_side == "LONG" and wick_dir == "bull") or
        (scanner_side == "SHORT" and wick_dir == "bear")
    )
    wick_normal_min = cfg.get("wick_min_for_normal", 1.2)
    wick_required = bool(cfg.get("require_wick_for_normal", False))
    wick_present = best_level is not None and wick_ratio >= wick_normal_min and wick_aligned
    gates.append(_gate(
        "rechazo_confirmado", "Rechazo en el nivel",
        wick_present or not wick_required, wick_required,
        f"Wick {wick_ratio:.1f}× {'alineado' if wick_aligned else 'sin alinear'}"
        if best_level is not None else "—",
    ))

    # GATE 9 — SL dentro del cap + RRR ≥ mínimo (duro). Requiere nivel.
    sl_tp: Optional[dict] = None
    account_check: Optional[dict] = None
    if best_level is not None:
        opp_level = _opposite_level(levels, scanner_side)
        entry_price = zone_item.get("price", best_level["price"])
        sl_tp = _calculate_sl_tp(
            pair=pair, pip_size=pip_size, scanner_side=scanner_side,
            entry_price=entry_price, best_level=best_level,
            opposite_level=opp_level, atr_m15=atr_m15, cfg=cfg,
        )
        rrr_ok = sl_tp["sl_within_cap"] and sl_tp["rrr_ok"]
        if not sl_tp["sl_within_cap"]:
            rrr_detail = f"SL {sl_tp['risk_pips']:.1f}p excede cap {cfg.get('sl_max_pips', 20.0):.0f}p"
        elif not sl_tp["rrr_ok"]:
            rv = sl_tp.get("rrr")
            rrr_detail = f"RRR {rv:.2f}:1 < {MIN_RRR:.1f}:1" if rv is not None else "RRR no calculable"
        else:
            rrr_detail = f"RRR {sl_tp['rrr']:.2f}:1 · SL {sl_tp['risk_pips']:.1f}p"
    else:
        rrr_ok, rrr_detail = False, "Sin nivel para calcular SL/TP"
    gates.append(_gate("rrr_minimo", f"RRR ≥ {MIN_RRR:.0f}:1 y SL en cap", rrr_ok, True, rrr_detail))

    # GATE 10 — Riesgo de cuenta dentro de límite (duro). Hoy inerte (losses=0).
    if sl_tp is not None:
        account_check = _account_risk_check(
            pair=pair, risk_pips=sl_tp["risk_pips"],
            daily_loss_usd=daily_loss_usd, total_loss_usd=total_loss_usd,
        )
        acc_ok = not account_check["blocked"]
        acc_detail = (
            f"{account_check['lot_size']} lotes · ${account_check['risk_usd']:.0f} USD"
            if acc_ok else " | ".join(account_check["block_reasons"])
        )
        gates.append(_gate("cuenta", "Riesgo de cuenta", acc_ok, True, acc_detail))

    # GATE 11 — Sin noticia high-impact en ventana (blando — degrada, no veta)
    if news_active:
        ev = news_event or {}
        mins = ev.get("minutes_until")
        news_detail = (
            f"{ev.get('title', 'Evento high-impact')}"
            + (f" · ~{mins}min" if isinstance(mins, int) else "")
        )
    else:
        news_detail = "Sin eventos high-impact en ventana"
    gates.append(_gate("noticia", "Sin noticia en ventana", not news_active, False, news_detail))

    # ── Decisión ────────────────────────────────────────────────────
    hard_failed = [g for g in gates if g["hard"] and not g["passed"]]
    side = scanner_side if scanner_side in ("LONG", "SHORT") else None

    base = {
        "side": side,
        "gates": gates,
        "session_status": session_status,
        "session_hour_madrid": hour,
        "news_warning": (
            {"title": (news_event or {}).get("title"),
             "minutes_until": (news_event or {}).get("minutes_until")}
            if news_active else None
        ),
    }

    if hard_failed:
        return {
            **base,
            "decision": "NO_OPERAR",
            "confluence": {"score": 0, "max": MAX_SCORE, "pct": 0},
            "criteria_met": [],
            "criteria_failed": [],
            "entry_price": None, "sl_price": None, "tp_price": None,
            "rrr": None, "risk_pips": None, "reward_pips": None,
            "level_used": None,
            "account_check": account_check,
            "reason": hard_failed[0]["detail"] or f"No pasa el filtro '{hard_failed[0]['label']}'",
        }

    # Todos los gates duros pasan → confluencia (CAPA 2)
    score, met, failed = _score_signal(
        cross_state=cross_state, scanner_side=scanner_side,
        scanner_confluence=scanner_confluence, extended_status=extended_status,
        rsi=rsi, level=best_level, structure=structure, struct_bullish=struct_bullish,
        scanner_bloque=scanner_bloque, range_pos=range_pos, change_pct=change_pct,
        session_status=session_status, atr_m15_pips=atr_m15_pips_val, cfg=cfg,
    )

    min_strong = cfg["min_score_strong"]
    min_normal = cfg["min_score_normal"]
    if score >= min_normal:
        decision = "OPERAR"
        strength = "fuerte" if score >= min_strong else "normal"
        reason = (
            f"Setup {strength} {scanner_side} — {score}/{MAX_SCORE} de confluencia, "
            "gates superados."
        )
    else:
        decision = "ESPERAR"
        strength = None
        reason = (
            f"Dirección {scanner_side} válida pero confluencia floja ({score}/{MAX_SCORE}). "
            "Esperar mejor confirmación o precio en el nivel."
        )

    # Degradación blanda por noticia
    if news_active and decision == "OPERAR":
        decision = "ESPERAR"
        strength = None
        reason = "Noticia high-impact en ventana — esperar a que pase antes de entrar."

    return {
        **base,
        "decision": decision,
        "strength": strength,
        "confluence": {
            "score": score, "max": MAX_SCORE,
            "pct": round(score / MAX_SCORE * 100) if MAX_SCORE else 0,
        },
        "criteria_met": met,
        "criteria_failed": failed,
        "entry_price": round(zone_item.get("price", best_level["price"]), 5),
        "sl_price": sl_tp["sl_price"] if sl_tp else None,
        "tp_price": sl_tp["tp_price"] if sl_tp else None,
        "rrr": sl_tp["rrr"] if sl_tp else None,
        "risk_pips": sl_tp["risk_pips"] if sl_tp else None,
        "reward_pips": sl_tp["reward_pips"] if sl_tp else None,
        "tp_source": sl_tp["tp_source"] if sl_tp else None,
        "level_used": {
            "price": best_level["price"],
            "type": best_level["type"],
            "strength": best_level["strength"],
            "touches": best_level["touches"],
            "distance_pips": best_level["distance_pips"],
        } if best_level else None,
        "account_check": account_check,
        "reason": reason,
    }
