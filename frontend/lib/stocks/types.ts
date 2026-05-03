/* ──────────────────────────────────────────────────────────────────
   Stocks module — tipos compartidos entre lib, hooks y componentes.
   ────────────────────────────────────────────────────────────────── */

// ─── Investor profile ──────────────────────────────────────────

export type Horizon = "day_trader" | "swing" | "long_term";
export type RiskTolerance = 1 | 2 | 3 | 4 | 5;
export type CapitalRange = "<1k" | "1k-10k" | "10k-50k" | "50k+";
export type Experience = "novice" | "intermediate" | "advanced";

export type InvestorProfile = {
  horizon: Horizon;
  riskTolerance: RiskTolerance;
  capitalRange: CapitalRange;
  experience: Experience;
  /** Lista de sectores GICS de interés (ej: "Technology", "Healthcare"). */
  sectors: string[];
};

// ─── Signal engine ─────────────────────────────────────────────

/** -1 = vender, 0 = neutral, +1 = comprar. */
export type Vote = -1 | 0 | 1;

export type IndicatorKey =
  | "ma_short"
  | "ma_long"
  | "rsi"
  | "macd"
  | "bbands"
  | "adx";

export type IndicatorVote = {
  indicator: IndicatorKey;
  /** Valor numérico representativo del indicador (e.g. RSI=28). */
  value: number;
  vote: Vote;
  /** Texto humano corto (e.g. "RSI(14)=28 → sobreventa"). */
  reason: string;
};

export type Decision = "BUY" | "SELL" | "HOLD";
export type Interval = "15min" | "1h" | "4h" | "1day";
export type MarketStatus = "open" | "closed" | "pre" | "post";

export type Signal = {
  symbol: string;
  decision: Decision;
  /** 0–1 (conf alta = score lejos de 0). */
  confidence: number;
  /** -1 a 1, antes del threshold de decisión. */
  score: number;
  votes: IndicatorVote[];
  /** Top 3 razones ordenadas por |vote * weight|. */
  topReasons: string[];
  /** ISO UTC. */
  generatedAt: string;
  interval: Interval;
  marketStatus: MarketStatus;
};

// ─── Twelve Data (frontend-side, después de proxy backend) ─────

export type SymbolMatch = {
  symbol: string;
  /** Razón social ("Microsoft Corporation"). */
  instrument_name: string;
  exchange: string;
  /** Código ISO 3166 (US, ES, etc.). */
  country: string;
  /** "Common Stock", "ETF", etc. */
  type: string;
};

export type Quote = {
  symbol: string;
  /** Precio actual (último close). */
  price: number;
  /** Cambio absoluto vs apertura del día. */
  change: number;
  /** Cambio % vs apertura del día. */
  percent_change: number;
  /** Timestamp ISO de la última vela. */
  timestamp: string;
  /** Mercado actual según TwelveData (open/closed/pre/post). */
  marketStatus: MarketStatus;
};

/**
 * Bundle de indicadores que consume signalEngine.calculateSignal.
 * Todos los campos son los últimos valores; los indicadores con histórico
 * (e.g. macdHist) traen los últimos N puntos.
 */
export type IndicatorBundle = {
  symbol: string;
  interval: Interval;
  generatedAt: string;
  price: number;
  ma20: number | null;
  ma50: number | null;
  ma200: number | null;
  ema20: number | null;
  ema50: number | null;
  rsi14: number | null;
  /** Histórico del histograma MACD — últimos 5 puntos. Mayor = positivo. */
  macdHist: number[];
  bbandsUpper: number | null;
  bbandsLower: number | null;
  adx: number | null;
  plusDI: number | null;
  minusDI: number | null;
  marketStatus: MarketStatus;
};

// ─── Watchlist ─────────────────────────────────────────────────

export type WatchlistItem = {
  symbol: string;
  /** Última señal cacheada (puede ser null si nunca se evaluó). */
  lastDecision: Decision | null;
  /** Confianza de la última evaluación. */
  lastConfidence: number | null;
  /** ISO UTC. */
  addedAt: string;
};
