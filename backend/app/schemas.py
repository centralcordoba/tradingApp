from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from datetime import datetime

SignalType = Literal["LONG", "SHORT", "BUY", "SELL"]
DecisionType = Literal["ENTER", "WAIT", "AVOID"]
QualityType = Literal["PREMIUM", "STRONG", "NORMAL", "LOW"]
MTFType = Literal["BULL", "BEAR", "MIX"]
ZoneType = Literal["COMPRA YA", "COMPRA", "VENDE", "VENDE YA"]


class TVSignal(BaseModel):
    """Payload emitido por el script Pine SMS_XAUUSD_v8.9.1 (formato JSON)."""
    signal: SignalType
    symbol: str = "XAUUSD"
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
    vol_high: bool = False
    vol_ratio: float = 1.0
    rsi: float = 50.0
    kz: str = "24H"
    mtf: MTFType = "MIX"
    zona: ZoneType = "COMPRA"
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
    time: Optional[str] = None


class EntryPlan(BaseModel):
    trigger_type: str   # PULLBACK_EMA9 | RETEST | MOMENTUM_CONFIRM | SWEEP_REVERSAL | EXTENDED_SKIP
    wait_zone: List[float]   # [min, max] precio donde esperar la entrada
    trigger_price: float     # precio que confirma la entrada
    invalidation: float      # si se cruza, cancelar la operación
    instructions: str        # texto operativo claro


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
