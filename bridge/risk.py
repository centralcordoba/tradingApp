"""Reglas de riesgo puras del bridge (sin MT5, sin red) — testeables en frío."""
from __future__ import annotations

import math
from typing import Optional


def lots_for_risk(equity: float, risk_pct: float, sl_distance: float,
                  tick_value: float, tick_size: float,
                  vol_min: float, vol_max: float, vol_step: float) -> float:
    """Lotes para arriesgar risk_pct% del equity con el SL a sl_distance (en precio).

    Devuelve 0.0 si el lote mínimo del broker ya arriesga más que el presupuesto:
    mejor no operar que operar pasado de riesgo.
    """
    if sl_distance <= 0 or tick_value <= 0 or tick_size <= 0 or vol_step <= 0:
        return 0.0
    risk_usd = equity * risk_pct / 100.0
    loss_per_lot = sl_distance / tick_size * tick_value
    if loss_per_lot <= 0:
        return 0.0
    lots = math.floor(risk_usd / loss_per_lot / vol_step) * vol_step
    lots = round(lots, 8)  # limpiar residuo flotante del floor
    if lots < vol_min:
        return 0.0
    return min(lots, vol_max)


def in_window(hour_madrid: int, window: Optional[tuple]) -> bool:
    """[start, end) en hora Madrid; soporta ventanas que cruzan medianoche."""
    if window is None:
        return False
    start, end = window
    if start <= end:
        return start <= hour_madrid < end
    return hour_madrid >= start or hour_madrid < end


def classify_result(profit_usd: float, be_threshold_usd: float) -> str:
    if abs(profit_usd) <= be_threshold_usd:
        return "BE"
    return "WIN" if profit_usd > 0 else "LOSS"


def management_action(side: str, entry: float, tp1: Optional[float],
                      current_price: float, partial_done: bool) -> dict:
    """Decide la gestión de una posición abierta del marco: al alcanzar TP1 (1R),
    tomar parcial y mover el SL a break-even. Pura y testeable.

    {take_partial, move_be}. Una vez tomado el parcial no vuelve a disparar.
    """
    if partial_done or tp1 is None:
        return {"take_partial": False, "move_be": False}
    reached = (current_price >= tp1) if side == "LONG" else (current_price <= tp1)
    return {"take_partial": reached, "move_be": reached}


def half_volume(total: float, vol_min: float, vol_step: float) -> float:
    """Mitad del volumen redondeada al step, o 0.0 si la mitad no llega al mínimo
    (posición de lote mínimo: no se puede partir → se deja correr solo con BE)."""
    if vol_step <= 0:
        return 0.0
    half = math.floor((total / 2.0) / vol_step) * vol_step
    half = round(half, 8)
    return half if half >= vol_min else 0.0


def guard_reason(*, kill_switch: bool, trades_today: int, max_trades: int,
                 pnl_today_usd: float, next_trade_risk_usd: float,
                 max_daily_loss: float, drawdown_total_usd: float,
                 max_total_loss: float) -> Optional[str]:
    """None si se puede operar; si no, el primer motivo de bloqueo.

    Los límites de pérdida se evalúan asumiendo que el trade nuevo se va a SL
    completo: nunca colocar una orden cuyo peor caso breachearía la cuenta.
    """
    if kill_switch:
        return "kill switch activo (archivo STOP presente)"
    if trades_today >= max_trades:
        return f"limite de {max_trades} trades/dia alcanzado"
    if pnl_today_usd - next_trade_risk_usd <= -max_daily_loss:
        return (f"el SL de este trade ({next_trade_risk_usd:.0f} USD) podria breachear "
                f"el limite diario (PnL hoy {pnl_today_usd:.0f} USD, limite {max_daily_loss:.0f})")
    if drawdown_total_usd + next_trade_risk_usd >= max_total_loss:
        return (f"el SL de este trade podria breachear el limite total "
                f"(drawdown {drawdown_total_usd:.0f} USD, limite {max_total_loss:.0f})")
    return None
