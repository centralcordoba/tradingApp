"""
News warnings — avisa (no bloquea) alrededor de noticias high-impact.

Fuente: ForexFactory (JSON gratis, semana completa).
Cache en memoria con TTL de 1 hora.

Variables de entorno:
  NEWS_FILTER_ENABLED    1 = activo (default), 0 = desactivado
  NEWS_WINDOW_BEFORE_MIN minutos antes del evento que el warning aparece (default 30)
  NEWS_WINDOW_AFTER_MIN  minutos después del evento que el warning sigue visible (default 5)
"""
import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Optional

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_TTL_SECONDS = 3600

_cache: dict = {"fetched_at": None, "data": None}


def is_enabled() -> bool:
    return os.getenv("NEWS_FILTER_ENABLED", "1") == "1"


def _window_before() -> int:
    try:
        return int(os.getenv("NEWS_WINDOW_BEFORE_MIN", "30"))
    except ValueError:
        return 30


def _window_after() -> int:
    try:
        return int(os.getenv("NEWS_WINDOW_AFTER_MIN", "5"))
    except ValueError:
        return 5


def symbol_to_currencies(symbol: str) -> list[str]:
    """Devuelve las monedas relevantes para un símbolo.

    XAUUSD → ["USD"] (oro cotiza en USD, todas las noticias USD afectan)
    EURUSD → ["EUR", "USD"]
    Generic: extrae códigos de 3 letras del símbolo.
    """
    s = symbol.upper().replace("/", "").replace("-", "")
    # Oro/plata → solo USD
    if s.startswith("XAU") or s.startswith("XAG"):
        return ["USD"]
    # Split en 2 códigos de 3 letras si es posible
    if len(s) == 6:
        return [s[:3], s[3:]]
    return [s]


def _fetch() -> list[dict]:
    """Descarga el calendario crudo de ForexFactory."""
    req = urllib.request.Request(
        FF_URL,
        headers={"User-Agent": "Mozilla/5.0 (AI Trading Assistant)"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def get_calendar() -> list[dict]:
    """Devuelve el calendario cacheado (TTL 1h). Lista vacía si falla."""
    now = datetime.now(timezone.utc)
    fetched_at = _cache["fetched_at"]
    if (
        _cache["data"] is not None
        and fetched_at is not None
        and (now - fetched_at).total_seconds() < CACHE_TTL_SECONDS
    ):
        return _cache["data"]

    try:
        data = _fetch()
        _cache["data"] = data
        _cache["fetched_at"] = now
        return data
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        print(f"[news_client] fetch error: {e}")
        # Mantener cache viejo si existe; si no, lista vacía
        return _cache["data"] or []


def _parse_event_date(raw: str) -> Optional[datetime]:
    """Convierte la fecha de ForexFactory a datetime UTC."""
    if not raw:
        return None
    try:
        # Formato típico: "2026-04-11T08:30:00-05:00" o similar ISO 8601
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def is_news_window(
    symbol: str,
    now: Optional[datetime] = None,
) -> tuple[bool, Optional[dict]]:
    """Indica si el símbolo está dentro de la ventana de warning por noticia.

    Devuelve (in_window, event_dict_or_None).
    """
    if not is_enabled():
        return False, None

    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    before = timedelta(minutes=_window_before())
    after = timedelta(minutes=_window_after())
    currencies = {c.upper() for c in symbol_to_currencies(symbol)}

    for ev in get_calendar():
        if (ev.get("impact") or "").lower() != "high":
            continue
        if (ev.get("country") or "").upper() not in currencies:
            continue
        when = _parse_event_date(ev.get("date", ""))
        if when is None:
            continue
        if (when - before) <= now_utc <= (when + after):
            return True, ev

    return False, None


def get_active_warnings(
    currencies: Optional[list[str]] = None,
    now: Optional[datetime] = None,
) -> list[dict]:
    """Devuelve todos los eventos high-impact actualmente en la ventana de warning.

    Si `currencies` se pasa, filtra solo por esas monedas. Si no, devuelve todos.
    Cada evento incluye `minutes_until` (negativo si ya pasó).
    Ordenado por minutes_until ascendente (los ya-pasados primero si están en ventana).
    """
    if not is_enabled():
        return []

    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    before = timedelta(minutes=_window_before())
    after = timedelta(minutes=_window_after())
    filter_set = {c.upper() for c in currencies} if currencies else None

    out: list[dict] = []
    for ev in get_calendar():
        if (ev.get("impact") or "").lower() != "high":
            continue
        country = (ev.get("country") or "").upper()
        if filter_set is not None and country not in filter_set:
            continue
        when = _parse_event_date(ev.get("date", ""))
        if when is None:
            continue
        if (when - before) <= now_utc <= (when + after):
            delta = int((when - now_utc).total_seconds() / 60)
            out.append({
                "title": ev.get("title"),
                "country": country,
                "impact": ev.get("impact"),
                "date_utc": when.isoformat(),
                "minutes_until": delta,
                "status": "past" if delta < 0 else ("imminent" if delta <= 5 else "upcoming"),
            })
    out.sort(key=lambda e: abs(e["minutes_until"]))
    return out
