from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from datetime import datetime

SignalType = Literal["LONG", "SHORT", "BUY", "SELL"]
DecisionType = Literal["ENTER", "WAIT", "AVOID"]
QualityType = Literal["PREMIUM", "STRONG", "NORMAL", "LOW"]
MTFType = Literal["BULL", "BEAR", "MIX"]
ZoneType = Literal["COMPRA YA", "COMPRA", "VENDE", "VENDE YA"]


class TVSignal(BaseModel):
    """Payload emitido por el script Pine SMS_EURUSD_v8.10.1 (formato JSON)."""
    signal: SignalType
    symbol: str = "EURUSD"
    timeframe: str = "5"
    price: float
    sl: float
    be: float
    tp: float
    conf: int = Field(..., ge=0, le=19)
    conf_max: int = 19
    quality: QualityType
    pattern: str = "---"
    fvg: bool = False
    ifvg: bool = False  # retest de FVG invertido (zona rota actuando de oferta/demanda)
    vol_high: bool = False
    vol_ratio: float = 1.0
    rsi: float = 50.0
    kz: str = "24H"
    mtf: MTFType = "MIX"
    # Sin default direccional: un payload sin zona no debe regalar puntos de
    # "zona favorable" al score.
    zona: Optional[ZoneType] = None
    overhead: bool = False
    congestion: bool = False
    # Contexto adicional para el entry planner (opcional, default None)
    ema9: Optional[float] = None
    ema21: Optional[float] = None
    atr: Optional[float] = None
    swing_high: Optional[float] = None
    swing_low: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    # Timestamp de cierre de la barra de señal (epoch ms del Pine — llega como
    # número JSON — o ISO 8601). Lo usa el veto de staleness del decision_engine.
    time: Optional[str | int | float] = None
    # Sweep de liquidez detectado por el Pine en la vela de señal
    sweep_low: bool = False
    sweep_high: bool = False


class EntryPlan(BaseModel):
    trigger_type: str   # PULLBACK_EMA9 | RETEST | IMMEDIATE | SWEEP_REVERSAL | EXTENDED_SKIP
    wait_zone: List[float]   # [min, max] precio donde esperar la entrada
    trigger_price: float     # precio que confirma la entrada
    invalidation: float      # si se cruza, cancelar la operación
    instructions: str        # texto operativo claro
    expires_after: Optional[int] = None  # velas M5 de validez del plan (0 = no operar, None = sin límite)


class AnalyzeResponse(BaseModel):
    decision: DecisionType
    confidence: float
    entry_zone: List[float]
    stop_loss: float
    take_profit: List[float]
    reason: str
    score: int = 0
    signal_id: Optional[int] = None
    plan: Optional[EntryPlan] = None


class StoredSignal(BaseModel):
    id: int
    received_at: datetime
    signal: TVSignal
    response: AnalyzeResponse
