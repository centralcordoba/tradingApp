"""Tests de Fase 3: td_client (rate limit, single-flight, créditos),
indicators (implementación única) y persistencia OHLC."""
import threading
import time

import pytest

from app import indicators, scanner, storage, td_client


# ─── td_client: token bucket ────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_td_state():
    with td_client._lock:
        td_client._request_times.clear()
        td_client._credits.update({"date": "", "count": 0, "requests": 0})
    yield
    with td_client._lock:
        td_client._request_times.clear()


def test_acquire_slot_instant_under_limit():
    start = time.time()
    for _ in range(td_client.RATE_LIMIT_PER_MIN):
        td_client.acquire_slot()
    assert time.time() - start < 0.5
    assert len(td_client._request_times) == td_client.RATE_LIMIT_PER_MIN


def test_acquire_slot_purges_old_timestamps():
    old = time.time() - 120
    with td_client._lock:
        for _ in range(td_client.RATE_LIMIT_PER_MIN):
            td_client._request_times.append(old)
    start = time.time()
    td_client.acquire_slot()  # los viejos se purgan → instantáneo
    assert time.time() - start < 0.5


def test_acquire_slot_blocks_when_window_full():
    # Ventana llena con timestamps que expiran en ~0.15s → debe esperar
    almost_expired = time.time() - 59.85
    with td_client._lock:
        for _ in range(td_client.RATE_LIMIT_PER_MIN):
            td_client._request_times.append(almost_expired)
    start = time.time()
    td_client.acquire_slot()
    assert time.time() - start >= 0.05  # esperó a que expirara el más viejo


def test_credit_counter_and_metrics():
    td_client.note_credit(1)
    td_client.note_credit(2)
    td_client.note_credit(0)  # search: request sin crédito
    m = td_client.metrics()
    assert m["credits_today"] == 3
    assert m["requests_today"] == 3


def test_key_lock_same_instance_per_key():
    a = td_client.key_lock("EURUSD:15min:200")
    b = td_client.key_lock("EURUSD:15min:200")
    c = td_client.key_lock("AUDUSD:15min:200")
    assert a is b
    assert a is not c


# ─── scanner: single-flight sobre _fetch_chart ──────────────────────────────

def test_fetch_chart_single_flight(monkeypatch):
    calls = {"n": 0}

    def slow_fake_get_json(url, headers=None, timeout=None, credits=1):
        calls["n"] += 1
        time.sleep(0.1)
        return {"meta": {"interval": "5min"}, "values": []}, None

    monkeypatch.setattr(scanner, "TWELVEDATA_API_KEY", "test-key")
    monkeypatch.setattr(scanner.td_client, "get_json", slow_fake_get_json)
    monkeypatch.setattr(scanner.storage, "get_ohlc_cache", lambda key: None)
    monkeypatch.setattr(scanner.storage, "save_ohlc_cache", lambda *a, **k: None)
    scanner._ohlc_cache.pop("TESTSF:5min:200", None)

    results = []
    threads = [
        threading.Thread(target=lambda: results.append(scanner._fetch_chart("TESTSF")))
        for _ in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls["n"] == 1  # 5 llamadas concurrentes → 1 solo fetch real
    assert len(results) == 5 and all(r is not None for r in results)
    scanner._ohlc_cache.pop("TESTSF:5min:200", None)


def test_fetch_chart_rehydrates_from_db(monkeypatch):
    calls = {"n": 0}

    def fake_get_json(url, headers=None, timeout=None, credits=1):
        calls["n"] += 1
        return {"values": []}, None

    payload = {"meta": {"interval": "15min"}, "values": [{"close": "1.0"}]}
    monkeypatch.setattr(scanner, "TWELVEDATA_API_KEY", "test-key")
    monkeypatch.setattr(scanner.td_client, "get_json", fake_get_json)
    monkeypatch.setattr(scanner.storage, "get_ohlc_cache", lambda key: (time.time(), payload))
    scanner._ohlc_cache.pop("TESTDB:15min:200", None)

    out = scanner._fetch_chart("TESTDB", interval="15min", outputsize=200)
    assert out == payload
    assert calls["n"] == 0  # rehidratado de DB, sin fetch real
    scanner._ohlc_cache.pop("TESTDB:15min:200", None)


# ─── storage: roundtrip de ohlc_cache ────────────────────────────────────────

def test_ohlc_cache_roundtrip():
    storage.init_db()
    payload = {"meta": {"interval": "5min"}, "values": [{"close": "1.2345"}]}
    ts = time.time()
    storage.save_ohlc_cache("TESTRT:5min:200", ts, payload)
    row = storage.get_ohlc_cache("TESTRT:5min:200")
    assert row is not None
    assert row[0] == pytest.approx(ts, abs=0.01)
    assert row[1] == payload


# ─── storage: historial de trades del bridge MT5 ─────────────────────────────

def test_bridge_trades_roundtrip():
    storage.init_db()
    ticket = f"T{int(time.time() * 1000)}"  # único por corrida
    tid = storage.add_bridge_trade({
        "symbol": "AUDUSD", "side": "SHORT", "source": "marco",
        "lots": 1.5, "entry_price": 0.695, "sl_price": 0.697, "tp_price": 0.691,
        "risk_usd": 250.0, "rrr": 2.0, "mt5_ticket": ticket, "dry_run": False,
        "context": {"score": 11, "session_status": "fire"},
    })
    assert isinstance(tid, int) and tid > 0

    abierto = storage.get_bridge_trade(tid)
    assert abierto["result"] is None and abierto["closed_at"] is None
    assert abierto["context"]["score"] == 11
    assert abierto["dry_run"] is False

    cerrado = storage.close_bridge_trade(ticket, "WIN", exit_price=0.691, pnl_usd=498.5)
    assert cerrado is not None and cerrado["result"] == "WIN"
    assert cerrado["pnl_usd"] == pytest.approx(498.5)
    assert cerrado["closed_at"] is not None

    # Cerrar dos veces el mismo ticket no matchea (closed_at ya está set)
    assert storage.close_bridge_trade(ticket, "LOSS") is None

    items = storage.list_bridge_trades(limit=5)
    assert any(it["id"] == tid for it in items)


# ─── indicators: implementación única ────────────────────────────────────────

def test_ema_series_seed_and_length():
    values = [1.0] * 10 + [2.0] * 10
    s = indicators.ema_series(values, 5)
    assert len(s) == 16  # n - period + 1
    assert s[0] == pytest.approx(1.0)  # seed = SMA de los primeros 5
    assert s[-1] > s[0]


def test_rsi_series_warmup_and_bounds():
    closes = [100 + i * 0.5 for i in range(30)]  # subida constante
    s = indicators.rsi_series(closes, 14)
    assert all(v is None for v in s[:14])
    assert s[-1] == pytest.approx(100.0)  # sin pérdidas → RSI 100


def test_atr_last_known_value():
    # Velas de rango constante 1.0 sin gaps → ATR = 1.0
    n = 30
    highs = [10.5] * n
    lows = [9.5] * n
    closes = [10.0] * n
    assert indicators.atr_last(highs, lows, closes, 14) == pytest.approx(1.0)


def test_scanner_aliases_point_to_indicators():
    assert scanner._atr is indicators.atr_last
    assert scanner._ema is indicators.ema_series
    assert scanner._rsi is indicators.rsi_last
