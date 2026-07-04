"""
Entry planner — convierte un WAIT genérico en un plan operativo concreto.

Filosofía (lo que hacen los scalpers profesionales rentables):
  - No entrar en la vela de señal si está extendida del EMA9 (>1×ATR).
  - Esperar pullback a EMA9/EMA21 o al nivel roto (retest).
  - Confirmar con cuerpo de vela siguiente cerrando más allá del high/low.
  - En zonas extremas, esperar sweep + reversión (trampa de retail).

Tipos de plan (en orden de precedencia):
  SWEEP_REVERSAL    — en zona extrema, esperar barrida de liquidez y vuelta dentro.
  RETEST            — viene de romper estructura, esperar retest del nivel roto.
                      (Va ANTES que el chequeo de extensión: una ruptura casi
                      siempre está >1×ATR del EMA9 y el plan correcto es el
                      retest del nivel, no un pullback genérico a la EMA.)
  PULLBACK_EMA9     — precio extendido del EMA9, esperar retroceso a la EMA.
  EXTENDED_SKIP     — demasiado lejos del EMA9 (>2.5×ATR): skip.
  IMMEDIATE         — cerca del EMA9 con cierre fuerte (el Pine solo señala con
                      isStrongBull/Bear): entrada a mercado válida ya.

Cada plan lleva `expires_after` (velas M5): los triggers usan referencias del
momento de la señal (EMA9, swings) que caducan rápido en M5.
"""
from typing import Optional
from .schemas import TVSignal, EntryPlan


def _round(symbol: str, value: float) -> float:
    """Redondea con la precisión típica del símbolo."""
    s = (symbol or "").upper().replace("/", "").replace("-", "")
    if "XAU" in s or "XAG" in s or "BTC" in s:
        return round(value, 2)
    if "JPY" in s:
        return round(value, 3)
    return round(value, 5)


def plan_entry(sig: TVSignal) -> Optional[EntryPlan]:
    """Devuelve un plan de entrada concreto, o None si no hay datos suficientes."""
    if sig.ema9 is None or sig.atr is None or sig.atr <= 0:
        return None

    is_long = sig.signal.upper() in ("LONG", "BUY")
    price = sig.price
    ema9 = sig.ema9
    ema21 = sig.ema21 or ema9
    atr = sig.atr
    R = lambda v: _round(sig.symbol, v)

    # Distancia del precio al EMA9, en ATRs
    dist_ema9_atr = abs(price - ema9) / atr

    # ─── Caso 0: SWEEP_CONFIRMED (la vela de señal ES la reversión) ──────
    # El Pine detecta el sweep en la propia vela de señal (mecha barre el
    # swing + cierre de vuelta dentro con volumen). No hay que "esperar la
    # barrida": ya ocurrió y el cierre fuerte la confirmó.
    if is_long and sig.sweep_low and sig.swing_low is not None:
        invalid = R(sig.low if sig.low is not None else sig.swing_low - atr * 0.3)
        return EntryPlan(
            trigger_type="SWEEP_CONFIRMED",
            wait_zone=[R(price - atr * 0.15), R(price + atr * 0.15)],
            trigger_price=R(price),
            invalidation=invalid,
            instructions=(
                f"Sweep del swing low {R(sig.swing_low)} ya ejecutado y recuperado con cierre "
                f"fuerte — la reversión confirmó en esta vela. Entrada LONG a mercado válida. "
                f"Cancela si una vela cierra debajo de {invalid} (el low del sweep)."
            ),
            expires_after=2,
        )
    if (not is_long) and sig.sweep_high and sig.swing_high is not None:
        invalid = R(sig.high if sig.high is not None else sig.swing_high + atr * 0.3)
        return EntryPlan(
            trigger_type="SWEEP_CONFIRMED",
            wait_zone=[R(price - atr * 0.15), R(price + atr * 0.15)],
            trigger_price=R(price),
            invalidation=invalid,
            instructions=(
                f"Sweep del swing high {R(sig.swing_high)} ya ejecutado y rechazado con cierre "
                f"fuerte — la reversión confirmó en esta vela. Entrada SHORT a mercado válida. "
                f"Cancela si una vela cierra arriba de {invalid} (el high del sweep)."
            ),
            expires_after=2,
        )

    # ─── Caso 1: SWEEP_REVERSAL (zona extrema, sweep aún NO ocurrió) ─────
    if sig.zona in ("VENDE YA", "COMPRA YA"):
        if is_long and sig.swing_low is not None:
            # Esperar que barra el swing low y vuelva arriba
            sweep_target = sig.swing_low - atr * 0.2
            return EntryPlan(
                trigger_type="SWEEP_REVERSAL",
                wait_zone=[R(sweep_target), R(sig.swing_low)],
                trigger_price=R(sig.swing_low + atr * 0.3),
                invalidation=R(sweep_target - atr * 0.5),
                instructions=(
                    f"Zona extrema. Espera que el precio barra el swing low en {R(sig.swing_low)} "
                    f"y vuelva arriba. Entra LONG cuando cierre vela por encima de {R(sig.swing_low + atr * 0.3)}. "
                    f"Cancela si cierra debajo de {R(sweep_target - atr * 0.5)}."
                ),
                expires_after=6,
            )
        if (not is_long) and sig.swing_high is not None:
            sweep_target = sig.swing_high + atr * 0.2
            return EntryPlan(
                trigger_type="SWEEP_REVERSAL",
                wait_zone=[R(sig.swing_high), R(sweep_target)],
                trigger_price=R(sig.swing_high - atr * 0.3),
                invalidation=R(sweep_target + atr * 0.5),
                instructions=(
                    f"Zona extrema. Espera que el precio barra el swing high en {R(sig.swing_high)} "
                    f"y vuelva abajo. Entra SHORT cuando cierre vela por debajo de {R(sig.swing_high - atr * 0.3)}. "
                    f"Cancela si cierra arriba de {R(sweep_target + atr * 0.5)}."
                ),
                expires_after=6,
            )

    # ─── Caso 2: RETEST (viene de romper estructura) ─────────────────────
    # Antes del chequeo de extensión: la vela de ruptura casi siempre está
    # >1×ATR del EMA9 y la respuesta correcta es el retest del nivel roto.
    if is_long and sig.swing_high is not None and price > sig.swing_high:
        level = sig.swing_high
        return EntryPlan(
            trigger_type="RETEST",
            wait_zone=[R(level - atr * 0.15), R(level + atr * 0.15)],
            trigger_price=R(level + atr * 0.2),
            invalidation=R(level - atr * 0.6),
            instructions=(
                f"Ruptura del swing high {R(level)}. NO compres en la ruptura. "
                f"Espera retest del nivel ({R(level - atr * 0.15)}-{R(level + atr * 0.15)}). "
                f"Entra LONG cuando una vela rebote y cierre arriba de {R(level + atr * 0.2)}. "
                f"Cancela si cierra debajo de {R(level - atr * 0.6)}."
            ),
            expires_after=8,
        )
    if (not is_long) and sig.swing_low is not None and price < sig.swing_low:
        level = sig.swing_low
        return EntryPlan(
            trigger_type="RETEST",
            wait_zone=[R(level - atr * 0.15), R(level + atr * 0.15)],
            trigger_price=R(level - atr * 0.2),
            invalidation=R(level + atr * 0.6),
            instructions=(
                f"Ruptura del swing low {R(level)}. NO vendas en la ruptura. "
                f"Espera retest del nivel ({R(level - atr * 0.15)}-{R(level + atr * 0.15)}). "
                f"Entra SHORT cuando una vela rechace y cierre debajo de {R(level - atr * 0.2)}. "
                f"Cancela si cierra arriba de {R(level + atr * 0.6)}."
            ),
            expires_after=8,
        )

    # ─── Caso 3: PULLBACK_EMA9 (precio extendido del EMA9) ───────────────
    if dist_ema9_atr > 1.0:
        # Demasiado lejos: si está a más de 2.5 ATRs, skip
        if dist_ema9_atr > 2.5:
            return EntryPlan(
                trigger_type="EXTENDED_SKIP",
                wait_zone=[R(ema9), R(ema21)],
                trigger_price=R(ema9),
                invalidation=R(price + atr * (1.5 if not is_long else -1.5)),
                instructions=(
                    f"Precio a {dist_ema9_atr:.1f}× ATR del EMA9 ({R(ema9)}). "
                    f"Demasiado extendido para scalp — alta probabilidad de retroceso profundo. "
                    f"Mejor saltar esta señal o esperar nuevo setup tras la corrección."
                ),
                expires_after=0,
            )
        # Pullback razonable a EMA9
        zone_min = R(min(ema9, ema21) - atr * 0.15)
        zone_max = R(max(ema9, ema21) + atr * 0.15)
        if is_long:
            trigger = R(ema9 + atr * 0.2)
            invalid = R(min(ema9, ema21) - atr * 0.6)
            return EntryPlan(
                trigger_type="PULLBACK_EMA9",
                wait_zone=[zone_min, zone_max],
                trigger_price=trigger,
                invalidation=invalid,
                instructions=(
                    f"Vela de señal extendida ({dist_ema9_atr:.1f}× ATR del EMA9). "
                    f"NO entres a {R(price)}. Espera retroceso a la zona {zone_min}-{zone_max} (EMA9/EMA21). "
                    f"Entra LONG cuando una vela cierre arriba de {trigger} con cuerpo >50% del rango. "
                    f"Cancela si cierra debajo de {invalid}."
                ),
                expires_after=6,
            )
        else:
            trigger = R(ema9 - atr * 0.2)
            invalid = R(max(ema9, ema21) + atr * 0.6)
            return EntryPlan(
                trigger_type="PULLBACK_EMA9",
                wait_zone=[zone_min, zone_max],
                trigger_price=trigger,
                invalidation=invalid,
                instructions=(
                    f"Vela de señal extendida ({dist_ema9_atr:.1f}× ATR del EMA9). "
                    f"NO entres a {R(price)}. Espera rebote a la zona {zone_min}-{zone_max} (EMA9/EMA21). "
                    f"Entra SHORT cuando una vela cierre debajo de {trigger} con cuerpo >50% del rango. "
                    f"Cancela si cierra arriba de {invalid}."
                ),
                expires_after=6,
            )

    # ─── Caso 5: IMMEDIATE (cerca del EMA9 con cierre fuerte) ────────────
    # El Pine solo señala con isStrongBull/isStrongBear: la vela de señal YA es
    # un cierre fuerte. Si además no está extendida, la entrada a mercado es
    # válida — pedir "otra confirmación" era una premisa falsa que contradecía
    # el ENTER del motor.
    if is_long:
        invalid = R(ema9 - atr * 0.5)
        return EntryPlan(
            trigger_type="IMMEDIATE",
            wait_zone=[R(price - atr * 0.1), R(price + atr * 0.1)],
            trigger_price=R(price),
            invalidation=invalid,
            instructions=(
                f"Cierre fuerte cerca del EMA9 sin extensión. Entrada LONG a mercado válida "
                f"en la zona {R(price - atr * 0.1)}-{R(price + atr * 0.1)}. "
                f"Cancela si una vela cierra debajo de {invalid}."
            ),
            expires_after=1,
        )
    else:
        invalid = R(ema9 + atr * 0.5)
        return EntryPlan(
            trigger_type="IMMEDIATE",
            wait_zone=[R(price - atr * 0.1), R(price + atr * 0.1)],
            trigger_price=R(price),
            invalidation=invalid,
            instructions=(
                f"Cierre fuerte cerca del EMA9 sin extensión. Entrada SHORT a mercado válida "
                f"en la zona {R(price - atr * 0.1)}-{R(price + atr * 0.1)}. "
                f"Cancela si una vela cierra arriba de {invalid}."
            ),
            expires_after=1,
        )
