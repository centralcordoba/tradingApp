"""Tests de las reglas puras del bridge. Sin dependencias: python test_bridge.py
(también los recoge pytest si se corre desde bridge/).
"""
from risk import classify_result, guard_reason, in_window, lots_for_risk


def test_lots_for_risk_eurusd():
    # 50k equity, 0.5% = 250 USD, SL 15 pips (0.0015), tick 1 USD/0.00001
    # → 150 USD por lote → 1.66 lotes (floor a step 0.01)
    lots = lots_for_risk(50_000, 0.5, 0.0015, 1.0, 0.00001, 0.01, 100.0, 0.01)
    assert lots == 1.66, lots


def test_lots_zero_si_minimo_excede_riesgo():
    # SL enorme: ni el lote mínimo cabe en el presupuesto → 0 (no operar)
    lots = lots_for_risk(1_000, 0.5, 0.0500, 1.0, 0.00001, 0.01, 100.0, 0.01)
    assert lots == 0.0, lots


def test_lots_clamp_al_maximo():
    lots = lots_for_risk(10_000_000, 1.0, 0.0010, 1.0, 0.00001, 0.01, 100.0, 0.01)
    assert lots == 100.0, lots


def test_lots_inputs_invalidos():
    assert lots_for_risk(50_000, 0.5, 0.0, 1.0, 0.00001, 0.01, 100.0, 0.01) == 0.0
    assert lots_for_risk(50_000, 0.5, 0.0015, 0.0, 0.00001, 0.01, 100.0, 0.01) == 0.0


def test_in_window():
    assert in_window(9, (9, 14)) is True
    assert in_window(13, (9, 14)) is True
    assert in_window(14, (9, 14)) is False   # [start, end)
    assert in_window(2, (22, 5)) is True     # cruza medianoche
    assert in_window(12, (22, 5)) is False
    assert in_window(10, None) is False      # sin ventana = no operar


def test_classify_result():
    assert classify_result(120.0, 5.0) == "WIN"
    assert classify_result(-80.0, 5.0) == "LOSS"
    assert classify_result(3.2, 5.0) == "BE"
    assert classify_result(-4.9, 5.0) == "BE"


def _guards(**over):
    base = dict(kill_switch=False, trades_today=0, max_trades=2,
                pnl_today_usd=0.0, next_trade_risk_usd=250.0,
                max_daily_loss=2500.0, drawdown_total_usd=0.0,
                max_total_loss=5000.0)
    base.update(over)
    return guard_reason(**base)


def test_guards_ok():
    assert _guards() is None


def test_guard_kill_switch_primero():
    assert "kill switch" in _guards(kill_switch=True, trades_today=99)


def test_guard_max_trades():
    assert "trades/dia" in _guards(trades_today=2)


def test_guard_daily_loss_incluye_sl_del_nuevo_trade():
    # PnL hoy -2300, riesgo nuevo 250 → peor caso -2550 < -2500 → bloquear
    assert "diario" in _guards(pnl_today_usd=-2300.0)
    # PnL hoy -2200, peor caso -2450 → pasa
    assert _guards(pnl_today_usd=-2200.0) is None


def test_guard_total_loss():
    assert "total" in _guards(drawdown_total_usd=4800.0)
    assert _guards(drawdown_total_usd=4500.0) is None


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} tests passed")
