"""Tests unitarios del radar de setups.

Ejecutables con pytest o como script:
    cd backend && .venv/Scripts/python -m pytest tests/test_radar.py -v
    cd backend && .venv/Scripts/python tests/test_radar.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Permite `python tests/test_radar.py` sin instalar el paquete
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.radar import (  # noqa: E402
    _classify_reversal_setup,
    _detect_rejection_candle,
    _detect_rsi_divergence,
    _find_key_levels,
    _rsi_series,
    build_radar_setups,
)


# ---------------------------------------------------------------------------
# 1. _find_key_levels: detecta un pivot claro
# ---------------------------------------------------------------------------

def test_find_key_levels_detects_clear_pivot():
    highs = [1.1005] * 100
    lows = [1.0995] * 100
    closes = [1.1000] * 100

    highs[30] = 1.1500  # pivot high claro
    lows[60] = 1.0500   # pivot low claro

    result = _find_key_levels(highs, lows, closes)

    assert result["resistance"] is not None
    assert abs(result["resistance"] - 1.1500) < 1e-6
    assert result["support"] is not None
    assert abs(result["support"] - 1.0500) < 1e-6
    assert 1.1500 in [round(x, 4) for x in result["all_resistances"]]
    assert 1.0500 in [round(x, 4) for x in result["all_supports"]]


def test_find_key_levels_near_flags_when_within_threshold():
    highs = [1.1001] * 100
    lows = [1.0999] * 100
    closes = [1.1000] * 100
    highs[30] = 1.1003  # pivot resistencia ~0.027% sobre el precio
    lows[60] = 1.0997   # pivot soporte ~0.027% bajo el precio

    result = _find_key_levels(highs, lows, closes)
    assert result["near_resistance"] is True
    assert result["near_support"] is True


# ---------------------------------------------------------------------------
# 2. _detect_rejection_candle: pin bar alcista con mecha = 3x cuerpo
# ---------------------------------------------------------------------------

def test_pin_bar_bull_with_three_times_body_wick():
    # body = 0.0010, lower_wick = 0.003 (3x body), close arriba
    opens = [1.0000]
    highs = [1.0015]
    lows = [0.9970]
    closes = [1.0010]

    res = _detect_rejection_candle(opens, highs, lows, closes)
    assert res["rejection"] is True
    assert res["type"] == "pin_bar_bull"
    assert res["direction"] == "LONG"
    assert res["wick_ratio"] == 3.0


def test_pin_bar_bear_detected():
    # body = 0.0010, upper_wick = 0.003 (3x body), close abajo
    opens = [1.0010]
    highs = [1.0040]
    lows = [0.9995]
    closes = [1.0000]

    res = _detect_rejection_candle(opens, highs, lows, closes)
    assert res["rejection"] is True
    assert res["type"] == "pin_bar_bear"
    assert res["direction"] == "SHORT"


def test_engulfing_bull_detected():
    opens = [1.0050, 1.0020]
    closes = [1.0030, 1.0060]
    highs = [1.0055, 1.0065]
    lows = [1.0025, 1.0015]

    res = _detect_rejection_candle(opens, highs, lows, closes)
    assert res["rejection"] is True
    assert res["type"] == "engulf_bull"
    assert res["direction"] == "LONG"


# ---------------------------------------------------------------------------
# 3. _detect_rejection_candle: cuerpo = 0 no debe romper
# ---------------------------------------------------------------------------

def test_zero_body_candle_returns_false_without_error():
    opens = [1.0000]
    closes = [1.0000]  # body = 0
    highs = [1.0010]
    lows = [0.9990]

    res = _detect_rejection_candle(opens, highs, lows, closes)
    assert res["rejection"] is False
    assert res["type"] is None


def test_zero_range_candle_returns_false():
    opens = [1.0000]
    closes = [1.0001]
    highs = [1.0001]
    lows = [1.0001]  # (high-low) ~ 0

    res = _detect_rejection_candle(opens, highs, lows, closes)
    assert res["rejection"] is False


# ---------------------------------------------------------------------------
# 4. _detect_rsi_divergence: precio nuevo mínimo con RSI más alto
# ---------------------------------------------------------------------------

def test_bullish_divergence_new_low_higher_rsi():
    closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 92.0, 91.0, 90.0]
    # RSI: el mínimo en la ventana está en el último índice de window (close=91 → rsi=30)
    # El rsi actual (40) es mayor pero sigue en zona bajista (<50)
    rsi = [None, 60.0, 55.0, 50.0, 45.0, 40.0, 38.0, 35.0, 33.0, 30.0, 40.0]

    res = _detect_rsi_divergence(closes, rsi, lookback=10)
    assert res["divergence"] is True
    assert res["type"] == "bullish"
    assert res["direction"] == "LONG"


def test_no_divergence_when_rsi_still_falling():
    closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 92.0, 91.0, 90.0]
    rsi = [None, 60.0, 55.0, 50.0, 45.0, 40.0, 38.0, 35.0, 33.0, 30.0, 25.0]

    res = _detect_rsi_divergence(closes, rsi, lookback=10)
    assert res["divergence"] is False


# ---------------------------------------------------------------------------
# 5. _classify_reversal_setup: B1 NORMAL con soporte + rechazo LONG + range_pos<0.35
# ---------------------------------------------------------------------------

def test_classifier_returns_b1_normal():
    key_levels = {"near_support": True, "near_resistance": False}
    rejection = {"rejection": True, "direction": "LONG"}
    divergence = {"divergence": False, "direction": None}

    res = _classify_reversal_setup(key_levels, rejection, divergence, rsi_current=40, range_pos=0.2)

    assert res["bloque"] == 1
    assert res["side"] == "LONG"
    assert res["strength"] == "NORMAL"
    assert res["quality"] == 2  # near_support + rejection


def test_classifier_returns_b1_strong_with_divergence():
    key_levels = {"near_support": True, "near_resistance": False}
    rejection = {"rejection": True, "direction": "LONG"}
    divergence = {"divergence": True, "direction": "LONG"}

    res = _classify_reversal_setup(key_levels, rejection, divergence, rsi_current=40, range_pos=0.2)
    assert res["bloque"] == 1
    assert res["strength"] == "STRONG"
    assert res["quality"] == 3


def test_classifier_b4_trap_when_long_rejection_at_resistance():
    key_levels = {"near_support": False, "near_resistance": True}
    rejection = {"rejection": True, "direction": "LONG"}
    divergence = {"divergence": False, "direction": None}

    res = _classify_reversal_setup(key_levels, rejection, divergence, rsi_current=65, range_pos=0.8)
    assert res["bloque"] == 4
    assert res["side"] == "TRAP_SHORT"
    assert res["strength"] == "WARN"


def test_classifier_returns_zero_when_no_setup():
    key_levels = {"near_support": False, "near_resistance": False}
    rejection = {"rejection": False, "direction": None}
    divergence = {"divergence": False, "direction": None}

    res = _classify_reversal_setup(key_levels, rejection, divergence, rsi_current=50, range_pos=0.5)
    assert res["bloque"] == 0


# ---------------------------------------------------------------------------
# 6. build_radar_setups: lista vacía no rompe
# ---------------------------------------------------------------------------

def test_build_radar_setups_empty_list():
    assert build_radar_setups([]) == []


def test_build_radar_setups_skips_blank_symbols():
    # Sin TWELVEDATA_API_KEY configurada _fetch_chart devuelve None → ningún setup.
    # El test verifica que strings vacíos/espacios no rompen la función.
    assert build_radar_setups(["", "   "]) == []


# ---------------------------------------------------------------------------
# Helper _rsi_series: sanity check básico
# ---------------------------------------------------------------------------

def test_rsi_series_length_matches_closes():
    closes = [100.0 + i * 0.1 for i in range(30)]
    rsi = _rsi_series(closes, period=14)
    assert len(rsi) == len(closes)
    # Los primeros 14 son warm-up (None), el resto son floats válidos
    assert all(v is None for v in rsi[:14])
    assert all(isinstance(v, float) and 0.0 <= v <= 100.0 for v in rsi[14:])


# ---------------------------------------------------------------------------
# Ejecutable standalone
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    tests = [obj for name, obj in list(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"OK   {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
