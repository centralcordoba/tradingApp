"""FastAPI app — ingesta + motor de decisión + historial."""
from dotenv import load_dotenv
load_dotenv()  # carga backend/.env si existe

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import os
from .schemas import TVSignal, AnalyzeResponse
from .decision_engine import analyze
from .tv_parser import parse_payload
from . import storage, ai_client

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
def list_signals(limit: int = 100, symbol: str | None = None):
    return storage.list_signals(limit=limit, symbol=symbol)


@app.get("/symbols")
def list_symbols():
    """Devuelve los símbolos únicos vistos hasta ahora (para el filtro del frontend)."""
    return storage.distinct_symbols()


@app.post("/signals/{signal_id}/result")
def set_result(signal_id: int, payload: dict):
    """Marca el resultado real de una señal: WIN | LOSS | BE.
    Body: {"result": "WIN", "exit_price": 2350.5}  (exit_price opcional)
    """
    result = (payload.get("result") or "").upper()
    exit_price = payload.get("exit_price")
    try:
        updated = storage.set_result(signal_id, result, exit_price)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if updated is None:
        raise HTTPException(status_code=404, detail="Señal no encontrada")
    return updated


@app.get("/stats")
def get_stats():
    return storage.stats()
