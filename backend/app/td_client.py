"""Gate único hacia Twelve Data — rate limit, single-flight y métricas.

El free tier tiene DOS presupuestos que antes nadie coordinaba entre módulos
(scanner, zones, radar y stocks los gastaban a ciegas, cada uno con su cliente):

- 8 req/min  → token bucket global (`acquire_slot`, cap en 7 para dejar margen)
- 800 cr/día → contador (`note_credit` / `metrics`), expuesto en /scanner/debug

Además:
- `key_lock(key)`: single-flight por cache key — dos requests concurrentes con
  cache frío ya no disparan fetches duplicados (el escenario exacto del 429 de
  cold start documentado en CLAUDE.md).
- `get_json(url)`: GET con retry único respetando `Retry-After` en 429.

Este módulo NO cachea — el caching es de cada consumidor (scanner._ohlc_cache,
stocks_client._cache). Aquí solo vive lo que es global: el presupuesto.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from .constants import HTTP_TIMEOUT_DEFAULT

logger = logging.getLogger(__name__)

# Cap real del free tier: 8 req/min. Reservamos 1 de margen para bursts de
# reloj desalineado entre nuestro bucket y el contador de TD.
RATE_LIMIT_PER_MIN = 7
RETRY_AFTER_MAX_S = 30.0

_lock = threading.Lock()
_request_times: deque[float] = deque()
_key_locks: dict[str, threading.Lock] = {}
_credits = {"date": "", "count": 0, "requests": 0}


def acquire_slot() -> None:
    """Bloquea hasta que haya hueco en la ventana de 60s. Nunca lanza."""
    while True:
        with _lock:
            now = time.time()
            while _request_times and now - _request_times[0] > 60.0:
                _request_times.popleft()
            if len(_request_times) < RATE_LIMIT_PER_MIN:
                _request_times.append(now)
                return
            wait = 60.0 - (now - _request_times[0]) + 0.05
        time.sleep(min(max(wait, 0.05), 5.0))


def note_credit(n: int = 1) -> None:
    """Registra créditos consumidos (search es gratis: n=0 cuenta solo el request)."""
    today = datetime.now(timezone.utc).date().isoformat()
    with _lock:
        if _credits["date"] != today:
            _credits["date"] = today
            _credits["count"] = 0
            _credits["requests"] = 0
        _credits["count"] += n
        _credits["requests"] += 1


def key_lock(key: str) -> threading.Lock:
    """Lock por cache key para single-flight (patrón double-checked del caller)."""
    with _lock:
        lock = _key_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _key_locks[key] = lock
        return lock


def metrics() -> dict:
    with _lock:
        now = time.time()
        recent = sum(1 for t in _request_times if now - t <= 60.0)
        return {
            "credits_today": _credits["count"],
            "requests_today": _credits["requests"],
            "credits_date": _credits["date"],
            "requests_last_minute": recent,
            "rate_limit_per_minute": RATE_LIMIT_PER_MIN,
        }


def get_json(url: str, headers: Optional[dict] = None,
             timeout: int = HTTP_TIMEOUT_DEFAULT, credits: int = 1) -> tuple[Optional[dict], Optional[str]]:
    """GET con rate limit + contador + un retry respetando Retry-After en 429.

    Devuelve (data, None) o (None, error_str). No interpreta el body más allá
    de parsear JSON — los contratos de error son de cada consumidor.
    """
    hdrs = headers or {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (AI Trading Assistant)",
    }
    for attempt in (0, 1):
        acquire_slot()
        note_credit(credits)
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:250]
            except Exception:
                pass
            if e.code == 429 and attempt == 0:
                retry_after = 2.0
                try:
                    retry_after = float(e.headers.get("Retry-After", "2"))
                except (TypeError, ValueError):
                    pass
                if retry_after <= RETRY_AFTER_MAX_S:
                    logger.warning("TD 429 — reintentando en %.1fs", retry_after)
                    time.sleep(retry_after)
                    continue
            return None, f"HTTP {e.code} — {body or e.reason}"
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"
    return None, "HTTP 429 — rate limit tras retry"
