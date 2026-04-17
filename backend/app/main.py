"""FastAPI app — ingesta + motor de decisión + historial."""
from dotenv import load_dotenv
load_dotenv()  # carga backend/.env si existe

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import os
from datetime import datetime, timezone

from .schemas import TVSignal, AnalyzeResponse
from .decision_engine import analyze
from .tv_parser import parse_payload
from . import storage, ai_client, news_client, scanner

USE_AI_DEFAULT = os.getenv("USE_AI", "0") == "1"

app = FastAPI(title="AI Trading Assistant", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    storage.init_db()


@app.get("/health")
def health():
    return {"ok": True}


def _decide(sig: TVSignal, use_ai: bool) -> tuple[AnalyzeResponse, AnalyzeResponse | None]:
    """Devuelve (final, heuristic). Si AI activo y responde, final = AI; si no, heurística."""
    heuristic = analyze(sig)
    if use_ai and ai_client.is_enabled():
        refined = ai_client.refine(sig, heuristic)
        if refined is not None:
            return refined, heuristic
    return heuristic, None


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze_endpoint(sig: TVSignal, ai: int | None = None):
    use_ai = USE_AI_DEFAULT if ai is None else bool(ai)
    final, heuristic = _decide(sig, use_ai)
    record = final.model_dump()
    if heuristic is not None:
        record["heuristic"] = heuristic.model_dump()
        record["source"] = "ai"
    else:
        record["source"] = "heuristic"
    sid = storage.save_signal(sig.model_dump(), record)
    final.signal_id = sid
    return final


@app.post("/webhook/tradingview")
async def tv_webhook(request: Request, ai: int | None = None):
    body = await request.body()
    try:
        data = parse_payload(body)
        sig = TVSignal(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Payload inválido: {e}")

    use_ai = USE_AI_DEFAULT if ai is None else bool(ai)
    final, heuristic = _decide(sig, use_ai)
    record = final.model_dump()
    if heuristic is not None:
        record["heuristic"] = heuristic.model_dump()
        record["source"] = "ai"
    else:
        record["source"] = "heuristic"
    sid = storage.save_signal(sig.model_dump(), record)
    final.signal_id = sid
    return {"ok": True, "decision": final.decision, "id": sid, "result": record}


@app.get("/signals")
def list_signals(limit: int = 10, offset: int = 0, symbol: str | None = None):
    items = storage.list_signals(limit=limit, offset=offset, symbol=symbol)
    total = storage.count_signals(symbol=symbol)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/symbols")
def list_symbols():
    """Devuelve los símbolos únicos vistos hasta ahora (para el filtro del frontend)."""
    return storage.distinct_symbols()


@app.get("/scanner/pairs")
def scan_pairs(pairs: str = ""):
    """Escanea pares en vivo (Twelve Data) y devuelve rankeados por confluencia.

    `pairs` opcional: lista separada por comas (ej: "XAUUSD,EURUSD"). Si vacío,
    usa la lista por defecto (metales + majors + cruces).
    """
    selected = [p.strip().upper() for p in pairs.split(",") if p.strip()] or None
    results = scanner.scan_pairs(selected)
    return {
        "items": results,
        "count": len(results),
        "last_error": scanner.last_error() if len(results) == 0 else "",
    }


@app.post("/signals/{signal_id}/result")
def set_result(signal_id: int, payload: dict):
    """Marca el resultado real de una señal: WIN | LOSS | BE.
    Body: {
        "result": "WIN",
        "exit_price": 2350.5,                  # opcional
        "taken": "yes"|"no",                   # obligatorio desde el frontend
        "journal_respected_plan": "yes"|"no",  # solo si taken=yes
        "journal_closed_early": "yes"|"no",    # solo si taken=yes
        "journal_emotion": "confianza"|"miedo"|"fomo"|"venganza"  # solo si taken=yes
    }
    """
    result = (payload.get("result") or "").upper()
    exit_price = payload.get("exit_price")
    try:
        updated = storage.set_result(
            signal_id,
            result,
            exit_price,
            taken=payload.get("taken"),
            journal_respected_plan=payload.get("journal_respected_plan"),
            journal_closed_early=payload.get("journal_closed_early"),
            journal_emotion=payload.get("journal_emotion"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if updated is None:
        raise HTTPException(status_code=404, detail="Señal no encontrada")
    return updated


@app.delete("/signals/{signal_id}")
def delete_signal(signal_id: int):
    """Elimina una señal del historial (para corregir data sucia)."""
    deleted = storage.delete_signal(signal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Señal no encontrada")
    return {"ok": True, "deleted_id": signal_id}


@app.get("/stats")
def get_stats():
    return storage.stats()


@app.get("/news")
def get_news(symbol: str = "XAUUSD", hours: int = 24):
    """Próximas noticias high-impact que afectan al símbolo en las próximas N horas."""
    now = datetime.now(timezone.utc)
    horizon = now.timestamp() + hours * 3600
    currencies = {c.upper() for c in news_client.symbol_to_currencies(symbol)}
    events = []
    for ev in news_client.get_calendar():
        if (ev.get("impact") or "").lower() != "high":
            continue
        if (ev.get("country") or "").upper() not in currencies:
            continue
        when = news_client._parse_event_date(ev.get("date", ""))
        if when is None:
            continue
        if now.timestamp() <= when.timestamp() <= horizon:
            events.append({
                "title": ev.get("title"),
                "country": ev.get("country"),
                "impact": ev.get("impact"),
                "date_utc": when.isoformat(),
                "minutes_until": int((when.timestamp() - now.timestamp()) / 60),
            })
    events.sort(key=lambda e: e["date_utc"])
    return {
        "symbol": symbol,
        "currencies": sorted(currencies),
        "enabled": news_client.is_enabled(),
        "window_before_min": news_client._window_before(),
        "window_after_min": news_client._window_after(),
        "upcoming": events,
    }


@app.get("/news/calendar")
def get_news_calendar(date: str | None = None, impact: str = "high"):
    """Eventos del calendario económico para un día específico (filtrados por zona Madrid).

    Query:
      - `?date=2026-04-10` (default: hoy en Madrid)
      - `?impact=high|medium|low|all` (default: high)
    """
    from zoneinfo import ZoneInfo
    madrid_tz = ZoneInfo("Europe/Madrid")

    if date:
        try:
            target = datetime.fromisoformat(date).date()
        except ValueError:
            raise HTTPException(status_code=400, detail=f"date inválido: {date}")
    else:
        target = datetime.now(madrid_tz).date()

    events = []
    for ev in news_client.get_calendar():
        ev_impact = (ev.get("impact") or "").lower()
        if impact != "all" and ev_impact != impact.lower():
            continue
        when = news_client._parse_event_date(ev.get("date", ""))
        if when is None:
            continue
        when_madrid = when.astimezone(madrid_tz)
        if when_madrid.date() != target:
            continue
        events.append({
            "title": ev.get("title"),
            "country": ev.get("country"),
            "impact": ev.get("impact"),
            "date_utc": when.isoformat(),
            "time_madrid": when_madrid.strftime("%H:%M"),
            "forecast": ev.get("forecast"),
            "previous": ev.get("previous"),
        })
    events.sort(key=lambda e: e["date_utc"])
    return {
        "date": target.isoformat(),
        "timezone": "Europe/Madrid",
        "impact_filter": impact,
        "events": events,
    }


@app.get("/news/warnings")
def get_news_warnings(currencies: str | None = None, now: str | None = None):
    """Eventos high-impact actualmente en ventana de warning.

    Query opcional:
      - `?currencies=USD,EUR` filtra por monedas
      - `?now=2026-04-10T12:35:00Z` simula "ahora" en otro momento (para testing/preview)
    """
    filter_list = [c.strip() for c in currencies.split(",")] if currencies else None

    sim_now = None
    if now:
        try:
            sim_now = datetime.fromisoformat(now.replace("Z", "+00:00"))
            if sim_now.tzinfo is None:
                sim_now = sim_now.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"now inválido: {now}")

    warnings = news_client.get_active_warnings(currencies=filter_list, now=sim_now)
    return {
        "enabled": news_client.is_enabled(),
        "window_before_min": news_client._window_before(),
        "window_after_min": news_client._window_after(),
        "simulated_now": sim_now.isoformat() if sim_now else None,
        "warnings": warnings,
    }
