"""Tests de los fixes de Fase 1 + Fase 2 (auditoría jul-2026).

Cubre exactamente los bugs encontrados: intervalo del radar, alineación del
resample M30, vela en formación, gate 9 fallable, reconcile(), estructura,
parser legacy, vetos nuevos del decision engine, histéresis RANGO, wick cap,
rango asiático y entry planner reformado.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app import decision_engine, radar, scanner, zones, zone_signal_engine
from app.cross_verdict import reconcile
from app.entry_planner import plan_entry
from app.schemas import TVSignal
from app.tv_parser import parse_payload


# ─── Radar: intervalo M15 (el bug de mayor impacto de la auditoría) ─────────

def test_radar_fetches_m15(monkeypatch):
    calls: dict = {}

    def fake_fetch(symbol, interval=None, outputsize=None):
        calls["interval"] = interval
        calls["outputsize"] = outputsize
        return None

    monkeypatch.setattr(radar.scanner, "_fetch_chart", fake_fetch)
    assert radar._analyze_symbol("EURUSD") is None
    assert calls["interval"] == "15min"
    assert calls["outputsize"] == 200


# ─── Zones: resample M15→M30 alineado + drop de vela incompleta ─────────────

def test_resample_m30_left_aligned_and_drops_partial():
    ts = ["2026-07-01 10:00:00", "2026-07-01 10:15:00", "2026-07-01 10:30:00",
          "2026-07-01 10:45:00", "2026-07-01 11:00:00"]
    ohlc = {"ts": ts, "open": [1, 2, 3, 4, 5], "high": [1.5, 2.5, 3.5, 4.5, 5.5],
            "low": [0.5, 1.5, 2.5, 3.5, 4.5], "close": [1.2, 2.2, 3.2, 4.2, 5.2]}
    m30 = zones._resample_m15_to_m30(ohlc)
    assert len(m30) == 2  # la M30 de las 11:00 tiene 1 sola hija → descartada
    assert str(m30.index[0]) == "2026-07-01 10:00:00+00:00"
    assert m30.iloc[0]["open"] == 1 and m30.iloc[0]["close"] == 2.2
    assert m30.iloc[1]["open"] == 3 and m30.iloc[1]["close"] == 4.2


# ─── Scanner: vela en formación excluida ────────────────────────────────────

def _build_raw(n_closed: int, interval_min: int = 5, with_forming: bool = True) -> dict:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    forming_open = now - timedelta(minutes=2)
    base = forming_open - timedelta(minutes=interval_min * n_closed)
    values = []
    for i in range(n_closed):
        t = base + timedelta(minutes=interval_min * i)
        values.append({"datetime": t.strftime("%Y-%m-%d %H:%M:%S"),
                       "open": "1.0", "high": "1.1", "low": "0.9", "close": "1.05"})
    if with_forming:
        values.append({"datetime": forming_open.strftime("%Y-%m-%d %H:%M:%S"),
                       "open": "1.0", "high": "1.2", "low": "0.8", "close": "1.15"})
    return {"meta": {"interval": f"{interval_min}min"}, "values": values}


def test_parse_ohlc_drops_forming_candle():
    parsed = scanner._parse_ohlc(_build_raw(99))
    assert len(parsed["close"]) == 99


def test_parse_ohlc_without_meta_keeps_all():
    raw = _build_raw(99)
    del raw["meta"]
    assert len(scanner._parse_ohlc(raw)["close"]) == 100


# ─── Gate 9 fallable (zone_signal_engine._calculate_sl_tp) ──────────────────

_G9 = dict(pair="EURUSD", pip_size=0.0001, cfg={"sl_max_pips": 20.0}, atr_m15=0.0010)


def test_gate9_sl_beyond_cap_fails_not_clamps():
    r = zone_signal_engine._calculate_sl_tp(
        scanner_side="LONG", entry_price=1.0850,
        best_level={"price": 1.0800}, opposite_level={"price": 1.0900}, **_G9,
    )
    # SL estructural = nivel - buffer(0.0005) = 1.0795 → 55 pips, NO recortado
    assert r["sl_price"] == pytest.approx(1.0795)
    assert r["risk_pips"] == pytest.approx(55.0)
    assert r["sl_within_cap"] is False


def test_gate9_insufficient_rrr_fails_not_fabricates():
    # Nivel opuesto a 50p con riesgo 15p → RRR 3.3 OK; opuesto a 20p → RRR 1.3 falla
    r = zone_signal_engine._calculate_sl_tp(
        scanner_side="LONG", entry_price=1.0810,
        best_level={"price": 1.0800}, opposite_level={"price": 1.0830}, **_G9,
    )
    assert r["tp_source"] == "nivel_sr"
    assert r["tp_price"] == pytest.approx(1.0830)  # el techo real, no un 2:1 inventado
    assert r["rrr"] is not None and r["rrr"] < 2.0
    assert r["rrr_ok"] is False


def test_gate9_no_opposite_level_uses_2to1():
    r = zone_signal_engine._calculate_sl_tp(
        scanner_side="LONG", entry_price=1.0810,
        best_level={"price": 1.0800}, opposite_level=None, **_G9,
    )
    assert r["tp_source"] == "2:1_sin_nivel_opuesto"
    assert r["rrr_ok"] is True
    assert r["sl_within_cap"] is True


# ─── cross_verdict.reconcile (función pura, síntesis de ambas pantallas) ────

def test_reconcile_states():
    assert reconcile("NEUTRAL", "BULL", True)["state"] == "D"
    assert reconcile("LONG", None, False)["state"] == "NA"
    assert reconcile("LONG", "BULL", True)["state"] == "A"
    assert reconcile("SHORT", "BEAR", True)["state"] == "A"
    assert reconcile("SHORT", "BULL", True)["state"] == "C"
    assert reconcile("LONG", "BEAR", True)["state"] == "C"
    b = reconcile("SHORT", "RANGO", True, opposite_price=1.0800)
    assert b["state"] == "B"
    assert b["target_side"] == "support"
    assert b["target_price"] == 1.0800


# ─── Scanner: estructura HH/LL + casos mixtos neutrales ─────────────────────

def _zigzag(peaks_troughs: list[float], step: int = 4) -> list[float]:
    """Serie que interpola linealmente entre extremos alternos."""
    out: list[float] = []
    for a, b in zip(peaks_troughs, peaks_troughs[1:]):
        for k in range(step):
            out.append(a + (b - a) * k / step)
    out.append(peaks_troughs[-1])
    return out


def test_structure_hh_uptrend():
    seq = _zigzag([1.0, 5.0, 2.5, 7.0, 4.5, 9.0, 7.5])
    struct = scanner._detect_structure(seq, seq, seq, lookback=len(seq) - 5)
    assert struct["last_move"] == "HH"
    assert struct["bullish"] is True


def test_structure_ll_downtrend():
    seq = _zigzag([9.0, 5.0, 7.5, 3.0, 5.5, 1.0, 2.5])
    struct = scanner._detect_structure(seq, seq, seq, lookback=len(seq) - 5)
    assert struct["last_move"] == "LL"
    assert struct["bullish"] is False


def test_structure_expansion_is_neutral():
    # Highs crecientes + lows decrecientes = expansión, NO señal direccional
    seq = _zigzag([3.0, 6.0, 2.0, 8.0, 1.0, 9.0, 4.0])
    struct = scanner._detect_structure(seq, seq, seq, lookback=len(seq) - 5)
    assert struct["last_move"] == "EXPANSION"
    assert struct["bullish"] is None


# ─── tv_parser legacy ───────────────────────────────────────────────────────

_LEGACY = """LONG EURUSD v8.10
Entrada: 1.08500
SL[OB]: 1.08300
BE 1:1: 1.08700
TP: 1.08900
RSI: 55
MTF30: BULL ✓
Zona: COMPRA
Calidad: STRONG
Confluencias: 12/19
Vol: HIGH 1.8x
FVG: SI"""


def test_parser_legacy_be_and_slob():
    out = parse_payload(_LEGACY)
    assert out["be"] == 1.087       # "BE 1:1" partía mal por el ':' del label
    assert out["sl"] == 1.083       # "SL[OB]" ahora matchea
    assert out["symbol"] == "EURUSD"
    assert out["mtf"] == "BULL"     # ✓ eliminado
    assert out["conf"] == 12


def test_parser_does_not_confuse_words_with_symbols():
    out = parse_payload("COMPRA FUERTE AHORA\nEntrada: 1.0850")
    assert "symbol" not in out  # "COMPRA"/"FUERTE" son 6 letras pero no divisas


# ─── decision_engine: vetos nuevos + score sin double-counting ──────────────

def _sig(**overrides) -> TVSignal:
    base = dict(
        signal="LONG", symbol="EURUSD", price=1.0850, sl=1.0835, be=1.0865,
        tp=1.0885, conf=14, quality="PREMIUM", mtf="BULL", zona="COMPRA",
        rsi=55.0, ema9=1.0848, ema21=1.0846, atr=0.0008,
        swing_high=1.0860, swing_low=1.0820, high=1.0852, low=1.0840,
    )
    base.update(overrides)
    return TVSignal(**base)


@pytest.fixture
def kz_ok(monkeypatch):
    monkeypatch.setattr(decision_engine, "_kill_zone_status", lambda now=None: "ok")


def test_veto_rr_below_floor(kz_ok):
    r = decision_engine.analyze(_sig(tp=1.0857))  # reward 7p vs risk 15p → RR 0.47
    assert r.decision == "AVOID"
    assert "R:R" in r.reason


def test_veto_sl_beyond_cap(kz_ok):
    r = decision_engine.analyze(_sig(sl=1.0810, tp=1.0950))  # 40p > cap 25 EURUSD
    assert r.decision == "AVOID"
    assert "cap" in r.reason


def test_veto_sl_wrong_side(kz_ok):
    r = decision_engine.analyze(_sig(sl=1.0860))  # SL encima de un LONG
    assert r.decision == "AVOID"


def test_veto_stale_signal(kz_ok):
    old_ms = int((datetime.now(timezone.utc) - timedelta(minutes=20)).timestamp() * 1000)
    r = decision_engine.analyze(_sig(time=old_ms))
    assert r.decision == "AVOID"
    assert "antigüedad" in r.reason


def test_stale_3min_degrades_enter_to_wait(kz_ok):
    ms = int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp() * 1000)
    r = decision_engine.analyze(_sig(time=ms))
    assert r.decision == "WAIT"
    assert "min" in r.reason


def test_fresh_signal_enters(kz_ok):
    ms = int((datetime.now(timezone.utc) - timedelta(seconds=30)).timestamp() * 1000)
    r = decision_engine.analyze(_sig(time=ms))
    assert r.decision == "ENTER"
    assert r.plan is not None and r.plan.trigger_type == "IMMEDIATE"


def test_ifvg_scores_plus_one(kz_ok):
    base = decision_engine.analyze(_sig()).score
    con = decision_engine.analyze(_sig(ifvg=True)).score
    assert con == base + 1


def test_parser_legacy_ifvg():
    out = parse_payload(_LEGACY + "\nIFVG: SI")
    assert out["ifvg"] is True


def test_conf_no_longer_double_counted(kz_ok):
    low_conf = decision_engine.analyze(_sig(conf=10))
    high_conf = decision_engine.analyze(_sig(conf=19))
    assert low_conf.score == high_conf.score  # quality ya representa el tier


def test_neutral_pattern_scores_nothing(kz_ok):
    without = decision_engine.analyze(_sig())
    nr7 = decision_engine.analyze(_sig(pattern="NR7"))
    directional = decision_engine.analyze(_sig(pattern="Envolvente"))
    assert nr7.score == without.score
    assert directional.score == without.score + 1


def test_kill_zone_avoid_blocks_enter(monkeypatch):
    monkeypatch.setattr(decision_engine, "_kill_zone_status", lambda now=None: "avoid")
    r = decision_engine.analyze(_sig())
    assert r.decision != "ENTER"


# ─── entry_planner reformado ────────────────────────────────────────────────

def test_planner_sweep_confirmed_is_immediate_entry(kz_ok):
    plan = plan_entry(_sig(sweep_low=True, zona="COMPRA YA"))
    assert plan.trigger_type == "SWEEP_CONFIRMED"
    r = decision_engine.analyze(_sig(sweep_low=True, zona="COMPRA YA"))
    assert r.decision == "ENTER"  # el sweep ya confirmó — no se degrada


def test_planner_retest_reachable_when_extended():
    # Ruptura del swing high con precio a >1×ATR del EMA9: antes caía en
    # PULLBACK_EMA9 y RETEST era inalcanzable.
    plan = plan_entry(_sig(price=1.0880, swing_high=1.0870, ema9=1.0850, atr=0.0008,
                           high=1.0882, low=1.0870))
    assert plan.trigger_type == "RETEST"
    assert plan.expires_after == 8


def test_planner_immediate_near_ema():
    plan = plan_entry(_sig())
    assert plan.trigger_type == "IMMEDIATE"
    assert plan.expires_after == 1


# ─── zones: wick cap + histéresis + rango asiático ──────────────────────────

def test_wick_ratio_capped_and_doji_neutral():
    ohlc = {"open": [1.08000], "close": [1.08001], "high": [1.08030], "low": [1.07990]}
    w = zones._wick_ratio(ohlc, 0)
    assert w["ratio"] <= 5.0
    assert w["direction"] == "neutral"  # cuerpo de 0.1 pips no confirma nada


def _linear_m30(slope: float, n: int = 400) -> pd.DataFrame:
    closes = np.arange(n, dtype=float) * slope + 100.0
    idx = pd.date_range("2026-06-01", periods=n, freq="30min", tz="UTC")
    return pd.DataFrame({"open": closes, "high": closes + 0.5,
                         "low": closes - 0.5, "close": closes}, index=idx)


def test_bias_hysteresis_prev_state_changes_label():
    # Separación EMA50/EMA100 ≈ 25×slope; ATR ≈ 1 → threshold = 0.3.
    # slope 0.0108 → sep ≈ 0.27: RANGO con umbral simple, BULL si venía de BULL
    # (entrar en RANGO exige < 0.24).
    m30 = _linear_m30(0.0108)
    fresh = zones._compute_m30_bias(m30, pip=0.0001, atr_mult=0.3)
    assert fresh["label"] == "RANGO"

    zones._BIAS_STATE["TESTPAIR:0.3"] = "BULL"
    sticky = zones._compute_m30_bias(m30, pip=0.0001, atr_mult=0.3, state_key="TESTPAIR:0.3")
    assert sticky["label"] == "BULL"

    zones._BIAS_STATE["TESTPAIR2:0.3"] = "RANGO"
    held = zones._compute_m30_bias(m30, pip=0.0001, atr_mult=0.3, state_key="TESTPAIR2:0.3")
    assert held["label"] == "RANGO"


def test_asia_range_detects_extremes_and_sweep():
    # Madrid en julio = UTC+2 → Asia (02–09h Madrid) = 00–07h UTC.
    ts, highs, lows, closes, opens = [], [], [], [], []
    base = datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc)
    for i in range(4 * 9):  # 00:00–09:00 UTC en M15
        t = base + timedelta(minutes=15 * i)
        ts.append(t.strftime("%Y-%m-%d %H:%M:%S"))
        in_asia = t.hour < 7
        if in_asia:
            highs.append(1.0850 if i == 10 else 1.0840)
            lows.append(1.0800 if i == 20 else 1.0810)
        else:
            highs.append(1.0860)  # barre el high asiático
            lows.append(1.0820)
        closes.append(1.0830)
        opens.append(1.0830)
    ohlc = {"ts": ts, "open": opens, "high": highs, "low": lows, "close": closes}
    ar = zones._asia_range(ohlc, 0.0001)
    assert ar is not None
    assert ar["high"] == pytest.approx(1.0850)
    assert ar["low"] == pytest.approx(1.0800)
    assert ar["swept_high"] is True
    assert ar["swept_low"] is False
