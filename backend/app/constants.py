"""
Constantes centralizadas para valores mágicos del sistema.

Agrupa timeouts, TTLs, límites operativos, umbrales técnicos y configuraciones
de instrumentos en un único lugar para facilitar mantenimiento y auditoría.
"""

# ─────────────────────────────────────────────────────────────────────────────
# HTTP & Timeouts (segundos)
# ─────────────────────────────────────────────────────────────────────────────

HTTP_TIMEOUT_DEFAULT = 15
HTTP_TIMEOUT_AI = 20
HTTP_TIMEOUT_NEWS = 15

# ─────────────────────────────────────────────────────────────────────────────
# Cache TTLs (segundos)
# ─────────────────────────────────────────────────────────────────────────────

# Stocks client
CACHE_TTL_INTRADAY = 300        # 5 min (15min, 1h, 4h)
CACHE_TTL_DAILY = 3600          # 1 h (1day)
CACHE_TTL_QUOTE = 300           # 5 min
CACHE_TTL_SEARCH = 86400        # 24 h

# Scanner (OHLC crudo compartido con radar)
CACHE_TTL_OHLC_SCANNER = 900    # 15 min

# Radar
CACHE_TTL_RADAR = 900           # 15 min

# News
CACHE_TTL_NEWS_CALENDAR = 3600  # 1 h

# ─────────────────────────────────────────────────────────────────────────────
# Indicadores técnicos — períodos estándar
# ─────────────────────────────────────────────────────────────────────────────

SMA_PERIOD_20 = 20
SMA_PERIOD_50 = 50
SMA_PERIOD_200 = 200

EMA_PERIOD_9 = 9
EMA_PERIOD_20 = 20
EMA_PERIOD_21 = 21
EMA_PERIOD_50 = 50
EMA_PERIOD_200 = 200

RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
MACD_HIST_LOOKBACK = 5

BBANDS_PERIOD = 20
BBANDS_MULT = 2.0

ADX_PERIOD = 14
ATR_PERIOD = 14

# ─────────────────────────────────────────────────────────────────────────────
# Scanner — configuración de pares y scoring
# ─────────────────────────────────────────────────────────────────────────────

SCANNER_INTERVAL = "15min"
SCANNER_OUTPUTSIZE = 200
SCANNER_MIN_CANDLES = 60

# Umbrales de confluencia para clasificación de bloques
SCANNER_CONFLUENCE_THRESHOLD_TREND = 4
SCANNER_CONFLUENCE_THRESHOLD_NEUTRAL = 3

# Umbrales de rango para clasificación
SCANNER_RANGE_DISCOUNT = 0.30   # 30% — zona de descuento (parte baja)
SCANNER_RANGE_PREMIUM = 0.70    # 70% — zona premium (parte alta)
SCANNER_RANGE_EXTREME_LOW = 0.15   # 15% — extremo bajo (reversión potencial LONG)
SCANNER_RANGE_EXTREME_HIGH = 0.85  # 85% — extremo alto (reversión potencial SHORT)

# Umbrales de RSI para agotamiento
SCANNER_RSI_OVERBOUGHT_EXTREME = 72
SCANNER_RSI_OVERSOLD_EXTREME = 28

# Impulso mínimo detectable (5 velas)
SCANNER_MOMENTUM_THRESHOLD = 0.001  # 0.1%

# ─────────────────────────────────────────────────────────────────────────────
# Radar — configuración de reversiones
# ─────────────────────────────────────────────────────────────────────────────

RADAR_INTERVAL = "15min"
RADAR_OUTPUTSIZE = 200
RADAR_MIN_CANDLES = 20

# Detección de key levels
RADAR_KEY_LEVELS_LOOKBACK = 100
RADAR_KEY_LEVELS_TOLERANCE_PCT = 0.002  # 0.2%

# Detección de vela de rechazo
RADAR_REJECTION_WICK_RATIO = 2.0        # wick ≥ 2× body
RADAR_REJECTION_WICK_PCT = 0.60         # wick ≥ 60% del rango

# Detección de divergencia RSI
RADAR_DIVERGENCE_LOOKBACK = 10

# Posición en rango para clasificación
RADAR_RANGE_SUPPORT_ZONE = 0.35         # < 35% = zona de soporte
RADAR_RANGE_RESISTANCE_ZONE = 0.65      # > 65% = zona de resistencia

# Extremos de rango para reversión
RADAR_RANGE_EXTREME_LOW = 0.15          # < 15% = extremo bajo
RADAR_RANGE_EXTREME_HIGH = 0.85         # > 85% = extremo alto

# Edad de vela para considerar mercado cerrado (fin de semana, caída de feed)
RADAR_CANDLE_INTERVAL_MIN = 15
RADAR_MARKET_STALE_THRESHOLD_MIN = 30

# RRR mínimo para que un setup sea operable
RADAR_MIN_RRR = 2.0

# Pares que reciben enriquecimiento SMC vía IA (los que el usuario opera).
# El radar sigue escaneando los DEFAULT_PAIRS del scanner para tener contexto
# de MTF LOCK; solo estos 6 mayores forex disparan la llamada a OpenRouter.
RADAR_SMC_PAIRS = {
    "GBPUSD",
    "AUDUSD",
    "EURUSD",
    "USDCHF",
    "USDCAD",
    "USDJPY",
}

# SMC — agregación M15 → M30 y prompt
RADAR_SMC_M30_CANDLES = 40             # 40 velas M30 = 20h de contexto
RADAR_SMC_HTTP_TIMEOUT = 25            # OpenRouter puede tardar más que /analyze
RADAR_SMC_MAX_PARALLEL = 6             # 6 pares como mucho — un worker por par

# ─────────────────────────────────────────────────────────────────────────────
# Instrumentos — configuración por símbolo
# ─────────────────────────────────────────────────────────────────────────────

# Tamaño de pip (unidades de precio)
PIP_SIZES = {
    "XAUUSD": 0.01,
    "XAGUSD": 0.001,
    "USDJPY": 0.01,
    "EURJPY": 0.01,
    "GBPJPY": 0.01,
    "CHFJPY": 0.01,
    "AUDJPY": 0.01,
    "NZDJPY": 0.01,
    "CADJPY": 0.01,
    "default": 0.0001,
}

# Stop loss máximo en pips (cap operativo del sistema)
SL_MAX_PIPS = {
    "XAUUSD": 40,   # 40 pips × $0.25 (0.25 lotes) = $10
    "EURUSD": 25,   # 25 pips × $1.00 (1 lote)    = $25
    "default": 20,
}

# Rango mínimo entre soporte y resistencia (% del precio)
MIN_RANGE_PCT = {
    "XAUUSD": 0.15,
    "EURUSD": 0.10,
    "default": 0.12,
}

# ─────────────────────────────────────────────────────────────────────────────
# Zonas S/R — detector de niveles con bias M30 (zones.py)
# ─────────────────────────────────────────────────────────────────────────────

# Swing window: N velas a cada lado para considerar un pivot
ZONES_PIVOT_WINDOW = 3

# Distancia máxima entre pivots para fundirlos en un mismo nivel (pips)
ZONES_MERGE_DISTANCE_PIPS = 8.0

# Mínimo de velas entre pivots del mismo tipo (evita ruido en consolidación)
ZONES_MIN_BARS_BETWEEN_PEAKS = 3

# Rango activo: niveles dentro de X pips del precio actual son operables (scalp M5)
ZONES_ACTIVE_RANGE_PIPS = 25.0

# Tolerancia para contar un "toque" en un nivel (pips)
ZONES_TOUCH_TOLERANCE_PIPS = 3.0

# 'median' (Recommended): robusto a outliers · 'mean': promedio simple
ZONES_LEVEL_SELECTOR_DEFAULT = "median"

# Pares por defecto del módulo de zonas (los que el usuario opera)
ZONES_DEFAULT_PAIRS = ["AUDUSD", "USDCAD"]

# ─────────────────────────────────────────────────────────────────────────────
# News — ventanas de warning
# ─────────────────────────────────────────────────────────────────────────────

NEWS_WINDOW_BEFORE_MIN_DEFAULT = 30
NEWS_WINDOW_AFTER_MIN_DEFAULT = 5

# ─────────────────────────────────────────────────────────────────────────────
# AI — configuración de refinamiento
# ─────────────────────────────────────────────────────────────────────────────

AI_TEMPERATURE = 0.2

# ─────────────────────────────────────────────────────────────────────────────
# Stocks — validación de entrada
# ─────────────────────────────────────────────────────────────────────────────

STOCK_SYMBOL_MAX_LENGTH = 16

# Intervalos válidos para análisis de stocks
VALID_STOCK_INTERVALS = {"15min", "1h", "4h", "1day"}

# Horizontes de inversión válidos
VALID_HORIZONS = {"day_trader", "swing", "long_term"}

# Rangos de capital válidos
VALID_CAPITAL = {"<1k", "1k-10k", "10k-50k", "50k+"}

# Niveles de experiencia válidos
VALID_EXPERIENCE = {"novice", "intermediate", "advanced"}

# Decisiones válidas
VALID_DECISIONS = {"BUY", "SELL", "HOLD"}

# Rango de tolerancia de riesgo (1-5)
RISK_TOLERANCE_MIN = 1
RISK_TOLERANCE_MAX = 5

# Rango de confianza (0-1)
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0

# ─────────────────────────────────────────────────────────────────────────────
# Twelve Data — configuración
# ─────────────────────────────────────────────────────────────────────────────

TWELVEDATA_FREE_TIER_CREDITS_PER_DAY = 800
TWELVEDATA_FREE_TIER_REQUESTS_PER_MIN = 8
TWELVEDATA_CONCURRENT_WORKERS = 4

# ─────────────────────────────────────────────────────────────────────────────
# HTTP Status Codes
# ─────────────────────────────────────────────────────────────────────────────

HTTP_STATUS_OK = 200
HTTP_STATUS_BAD_REQUEST = 400
HTTP_STATUS_NOT_FOUND = 404
HTTP_STATUS_RATE_LIMIT = 429
HTTP_STATUS_SERVER_ERROR = 500
HTTP_STATUS_BAD_GATEWAY = 502
