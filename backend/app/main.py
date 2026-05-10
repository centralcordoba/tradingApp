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
from . import storage, ai_client, news_client, scanner, radar, stocks_client, correlations
from .correlations import CorrelationsAIDisabled
from .stocks_client import StocksUpstreamError
from .constants import (
    HTTP_STATUS_BAD_REQUEST,
    HTTP_STATUS_NOT_FOUND,
    HTTP_STATUS_RATE_LIMIT,
    HTTP_STATUS_BAD_GATEWAY,
    VALID_STOCK_INTERVALS,
    VALID_HORIZONS,
    VALID_CAPITAL,
    VALID_EXPERIENCE,
    VALID_DECISIONS,
    RISK_TOLERANCE_MIN,
    RISK_TOLERANCE_MAX,
    CONFIDENCE_MIN,
    CONFIDENCE_MAX,
    STOCK_SYMBOL_MAX_LENGTH,
)

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


def _record_decision(final: AnalyzeResponse, heuristic: AnalyzeResponse | None, sig: TVSignal) -> dict:
    """Prepara el registro de decisión con source e heuristic si aplica."""
    record = final.model_dump()
    if heuristic is not None:
        record["heuristic"] = heuristic.model_dump()
        record["source"] = "ai"
    else:
        record["source"] = "heuristic"
    return record


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze_endpoint(sig: TVSignal, ai: int | None = None):
    use_ai = USE_AI_DEFAULT if ai is None else bool(ai)
    final, heuristic = _decide(sig, use_ai)
    record = _record_decision(final, heuristic, sig)
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
    record = _record_decision(final, heuristic, sig)
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


@app.get("/scanner/debug")
def scanner_debug():
    """Diagnóstico: confirma que la TWELVEDATA_API_KEY llega al servidor.
    No revela el valor — solo longitud y prefijo de 4 chars.
    """
    key = os.getenv("TWELVEDATA_API_KEY", "")
    return {
        "key_present": bool(key),
        "key_length": len(key),
        "key_prefix": (key[:4] + "…") if key else "",
        "last_error": scanner.last_error(),
    }


@app.get("/scanner/pairs")
def scan_pairs(pairs: str = ""):
    """Escanea pares en vivo (Twelve Data) y devuelve rankeados por confluencia.

    `pairs` opcional: lista separada por comas (ej: "EURUSD,GBPUSD"). Si vacío,
    usa la lista por defecto (majors + cruces).
    """
    selected = [p.strip().upper() for p in pairs.split(",") if p.strip()] or None
    results = scanner.scan_pairs(selected)
    probe_list = selected or scanner.DEFAULT_PAIRS
    age_min = radar._probe_market_age_minutes(probe_list)
    market_closed = age_min is not None and age_min > radar.MARKET_STALE_THRESHOLD_MIN
    return {
        "items": results,
        "count": len(results),
        "brief": scanner.build_daily_brief(results) if results else None,
        "last_error": scanner.last_error() if len(results) == 0 else "",
        "market_closed": market_closed,
        "data_age_minutes": round(age_min) if age_min is not None else None,
    }


@app.get("/api/radar")
def radar_setups(pairs: str = ""):
    """Radar de setups de reversión sobre soporte/resistencia (M15).

    Segunda capa de análisis — complementa el escáner existente. Detecta por
    símbolo: vela de rechazo, divergencia RSI/precio y proximidad a niveles
    clave, y los clasifica en 5 bloques (1/3 válidos, 2/4 trampas).

    `pairs` opcional: lista separada por comas (ej: "EURUSD,GBPUSD"). Si vacío,
    usa la lista por defecto del escáner.
    """
    selected = [p.strip().upper() for p in pairs.split(",") if p.strip()] or None
    return radar.get_radar_response(selected)


@app.get("/correlations")
def correlations_matrix():
    """Matriz estática de correlaciones entre los 6 pares operables.

    No consume Twelve Data. Datos memorizados en `correlations.py`.
    """
    return correlations.build_matrix()


@app.post("/correlations/query")
def correlations_query(payload: dict):
    """Consulta en lenguaje natural sobre correlaciones.

    Body: {"question": "..."}. Usa OpenRouter con el system prompt del
    Correlation Checker. Si OPENROUTER_API_KEY no está configurada → 503.
    """
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Falta 'question'")
    try:
        answer = correlations.query(question)
    except CorrelationsAIDisabled:
        raise HTTPException(
            status_code=503,
            detail="OpenRouter no configurado: falta OPENROUTER_API_KEY",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenRouter falló: {e}")
    return {"answer": answer}


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


@app.delete("/signals")
def delete_all_signals(symbol: str | None = None):
    """Elimina todas las señales, opcionalmente filtradas por símbolo."""
    n = storage.delete_all_signals(symbol)
    return {"ok": True, "deleted": n, "symbol": symbol}


@app.get("/stats")
def get_stats():
    return storage.stats()


@app.get("/news")
def get_news(symbol: str = "EURUSD", hours: int = 24):
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


# ---------------------------------------------------------------------------
# Stocks — proxy a Twelve Data + perfil + watchlist
# ---------------------------------------------------------------------------

VALID_STOCK_INTERVALS = {"15min", "1h", "4h", "1day"}
VALID_HORIZONS = {"day_trader", "swing", "long_term"}
VALID_CAPITAL = {"<1k", "1k-10k", "10k-50k", "50k+"}
VALID_EXPERIENCE = {"novice", "intermediate", "advanced"}
VALID_DECISIONS = {"BUY", "SELL", "HOLD"}


def _raise_upstream(e: StocksUpstreamError) -> None:
    """Mapea StocksUpstreamError → HTTPException con status equivalente."""
    if e.status == 404:
        raise HTTPException(status_code=404, detail=str(e))
    if e.status == 429:
        raise HTTPException(status_code=429, detail=str(e))
    if e.status == 402:
        raise HTTPException(status_code=402, detail=str(e))
    if e.status == 400:
        raise HTTPException(status_code=400, detail=str(e))
    if 500 <= e.status < 600:
        raise HTTPException(status_code=502, detail=f"Twelve Data: {e}")
    raise HTTPException(status_code=502, detail=f"Twelve Data: {e}")


@app.get("/stocks/search")
def stocks_search(q: str):
    """Búsqueda de tickers (TD symbol_search — gratis, no consume créditos)."""
    if not q or not q.strip():
        return {"matches": []}
    try:
        matches = stocks_client.search(q.strip())
        return {"matches": matches}
    except StocksUpstreamError as e:
        _raise_upstream(e)


@app.get("/stocks/quote")
def stocks_quote(symbol: str):
    sym = (symbol or "").upper().strip()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol requerido")
    try:
        return stocks_client.quote(sym)
    except StocksUpstreamError as e:
        _raise_upstream(e)


@app.get("/stocks/indicators")
def stocks_indicators(symbol: str, interval: str = "1day"):
    """Devuelve el IndicatorBundle listo para signalEngine.

    El cálculo (SMA/EMA/RSI/MACD/BBANDS/ADX) se hace acá en Python para
    minimizar créditos (1 fetch a /time_series + 1 a /quote = 2 créditos).
    """
    sym = (symbol or "").upper().strip()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol requerido")
    if interval not in VALID_STOCK_INTERVALS:
        raise HTTPException(
            status_code=400,
            detail=f"interval inválido (use {sorted(VALID_STOCK_INTERVALS)})",
        )
    try:
        return stocks_client.indicator_bundle(sym, interval)
    except StocksUpstreamError as e:
        _raise_upstream(e)


# ─── Profile ──────────────────────────────────────────────────

@app.get("/stocks/profile")
def stocks_get_profile():
    return storage.get_investor_profile()


@app.post("/stocks/profile")
def stocks_save_profile(payload: dict):
    horizon = payload.get("horizon")
    risk = payload.get("riskTolerance")
    cap = payload.get("capitalRange")
    exp = payload.get("experience")
    sectors = payload.get("sectors", [])
    if horizon not in VALID_HORIZONS:
        raise HTTPException(status_code=400, detail="horizon inválido")
    try:
        risk_int = int(risk)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="riskTolerance debe ser entero 1-5")
    if risk_int < 1 or risk_int > 5:
        raise HTTPException(status_code=400, detail="riskTolerance fuera de rango (1-5)")
    if cap not in VALID_CAPITAL:
        raise HTTPException(status_code=400, detail="capitalRange inválido")
    if exp not in VALID_EXPERIENCE:
        raise HTTPException(status_code=400, detail="experience inválido")
    if not isinstance(sectors, list) or not all(isinstance(s, str) for s in sectors):
        raise HTTPException(status_code=400, detail="sectors debe ser lista de strings")
    return storage.save_investor_profile({
        "horizon": horizon,
        "riskTolerance": risk_int,
        "capitalRange": cap,
        "experience": exp,
        "sectors": sectors,
    })


@app.delete("/stocks/profile")
def stocks_clear_profile():
    storage.clear_investor_profile()
    return {"ok": True}


# ─── Watchlist ────────────────────────────────────────────────

@app.get("/stocks/watchlist")
def stocks_get_watchlist():
    return {"items": storage.get_stocks_watchlist()}


@app.post("/stocks/watchlist")
def stocks_add_watchlist(payload: dict):
    sym = (payload.get("symbol") or "").upper().strip()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol requerido")
    if len(sym) > 16:
        raise HTTPException(status_code=400, detail="symbol demasiado largo")
    return {"items": storage.add_to_stocks_watchlist(sym)}


@app.delete("/stocks/watchlist/{symbol}")
def stocks_remove_watchlist(symbol: str):
    return {"items": storage.remove_from_stocks_watchlist(symbol)}


@app.patch("/stocks/watchlist/{symbol}")
def stocks_patch_watchlist(symbol: str, payload: dict):
    last_decision = payload.get("lastDecision")
    last_confidence = payload.get("lastConfidence")
    if last_decision is not None and last_decision not in VALID_DECISIONS:
        raise HTTPException(status_code=400, detail="lastDecision inválido")
    if last_confidence is not None:
        try:
            last_confidence = float(last_confidence)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="lastConfidence debe ser número")
        if last_confidence < 0 or last_confidence > 1:
            raise HTTPException(status_code=400, detail="lastConfidence fuera de rango (0-1)")
    return {"items": storage.update_stocks_watchlist_item(symbol, last_decision, last_confidence)}
