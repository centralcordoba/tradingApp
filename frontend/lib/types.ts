/* ──────────────────────────────────────────────────────────────────
   Tipos compartidos extraídos de app/page.tsx.
   El page.tsx legacy todavía mantiene copias inline; cuando los
   componentes de Fases 4-8 consuman desde aquí, las copias se
   eliminan.
   ────────────────────────────────────────────────────────────────── */

export type View = "dashboard" | "zones" | "radar" | "stocks" | "correlations" | "playbook" | "sr";

// ─── Zonas S/R ──────────────────────────────────────────────────

export type ZoneBiasM30 = {
  label: "BULL" | "BEAR" | "RANGO" | "NEUTRAL";
  ema50: number | null;
  ema100: number | null;
  atr_m30: number | null;
  separation: number | null;
  atr_pips: number | null;
  separation_pips: number | null;
  atr_mult_threshold: number;
  available: boolean;
  reason: "no_ohlc" | "insufficient_m30_bars" | "ema_failed" | "atr_failed" | null;
  m30_bars: number;
  m30_bars_required: number;
};

export type ZoneLevel = {
  price: number;
  type: "support" | "resistance";
  strength: number;        // 1-5 ★
  touches: number;
  age_bars: number;
  pivots_in_cluster: number;
  distance_pips: number;
  within_range: boolean;
  coherent_with_bias: boolean;
  active: boolean;
  last_touch_wick?: {
    top: number;
    bottom: number;
    body: number;
    ratio: number;
    direction: "bull" | "bear" | "neutral";
    at_bar: number;
  } | null;
};

export type ZonesPairResponse = {
  pair: string;
  price: number;
  pip_size: number;
  bias_m30: ZoneBiasM30;
  recent_wicks: Array<{
    top: number;
    bottom: number;
    body: number;
    ratio: number;
    direction: "bull" | "bear" | "neutral";
  }>;
  params: {
    window: number;
    merge_distance_pips: number;
    active_range_pips: number;
    min_bars_between: number;
    touch_tolerance_pips: number;
    level_selector: "median" | "mean";
  };
  levels: ZoneLevel[];
  active_count: number;
  n_bars: number;
  last_candle_ts: string | null;
  data_age_minutes: number | null;
  market_closed: boolean;
};

export type ZonesResponse = {
  timestamp: string;
  items: ZonesPairResponse[];
  count: number;
  market_closed: boolean;
};

// ─── Signals & journal ──────────────────────────────────────────

export type Signal = {
  id: number;
  received_at: string;
  signal: {
    signal: string;
    symbol: string;
    price: number;
    sl?: number;
    tp?: number;
    conf: number;
    quality: string;
    mtf: string;
    zona: string;
    pattern: string;
    rsi: number;
    fvg?: boolean;
    vol_high?: boolean;
    overhead?: boolean;
    congestion?: boolean;
  };
  response: {
    decision: "ENTER" | "WAIT" | "AVOID";
    confidence: number;
    score: number;
    reason: string;
    stop_loss: number;
    take_profit: number[];
    plan?: {
      trigger_type: string;
      wait_zone: number[];
      trigger_price: number;
      invalidation: number;
      instructions: string;
    } | null;
  };
  result: "WIN" | "LOSS" | "BE" | null;
  pnl: number | null;
  source: string | null;
  taken?: "yes" | "no" | null;
  journal_respected_plan?: string | null;
  journal_closed_early?: string | null;
  journal_emotion?: string | null;
};

export type Emotion = "confianza" | "miedo" | "fomo" | "venganza";

export type JournalDraft = {
  signalId: number;
  result: "WIN" | "LOSS" | "BE";
  taken: "yes" | "no" | null;
  respected_plan: "yes" | "no" | null;
  closed_early: "yes" | "no" | null;
  emotion: Emotion | null;
};

export type ConfirmDialogState = {
  title: string;
  message: string;
  confirmLabel: string;
  itemHint?: string;
  onConfirm: () => void | Promise<void>;
};

// ─── News ───────────────────────────────────────────────────────

export type NewsWarning = {
  title: string;
  country: string;
  impact: string;
  date_utc: string;
  minutes_until: number;
  status: "past" | "imminent" | "upcoming";
};

export type CalendarEvent = {
  title: string;
  country: string;
  impact: string;
  date_utc: string;
  time_madrid: string;
  forecast?: string | null;
  previous?: string | null;
};

// ─── Stats / aggregations ───────────────────────────────────────

export type Agg = {
  n: number;
  wins: number;
  losses: number;
  be: number;
  win_rate: number;
  pnl: number;
};

export type Stats = {
  total_signals: number;
  closed: number;
  open: number;
  overall: Agg;
  overall_taken?: Agg;
  overall_rated?: Agg;
  execution_rate?: number;
  by_decision: Record<string, Agg>;
  by_source: Record<string, Agg>;
  by_quality: Record<string, Agg>;
  by_emotion?: Record<string, Agg>;
  by_respected_plan?: Record<string, Agg>;
};

export const EMPTY_AGG: Agg = { n: 0, wins: 0, losses: 0, be: 0, win_rate: 0, pnl: 0 };

// ─── Scanner ────────────────────────────────────────────────────

export type ScannerFactor = {
  key: string;
  label: string;
  desc: string;
  value: -1 | 0 | 1 | number;
};

export type ScannerPair = {
  pair: string;
  td_symbol?: string;
  yahoo_symbol?: string;
  price: number;
  prev_close: number;
  change_pct: number;
  rsi: number | null;
  atr: number | null;
  range_pos: number;
  bias: number;
  side: "LONG" | "SHORT" | "NEUTRAL";
  confluence: number;
  max: number;
  bloque?: "1" | "2" | "3";
  bloque_reason?: string;
  factors: ScannerFactor[];
  spark: number[];
  // Nuevos campos para scalping M5
  ema9_dist_atr: number | null;
  extended_status: "normal" | "extended" | "skip";
  structure: string;
  struct_bullish: boolean | null;
};

export type DailyBrief = {
  sesgo_dia: string;
  pares_operables: string[];
  pares_excluidos: string[];
  mejor_setup: string;
  correlacion_dominante: string;
};

// ─── Radar ──────────────────────────────────────────────────────

export type RadarSetup = {
  symbol: string;
  price: number;
  bloque: 1 | 2 | 3 | 4;
  side: "LONG" | "SHORT" | "TRAP_LONG" | "TRAP_SHORT";
  strength: "STRONG" | "NORMAL" | "WARN" | null;
  quality: number;
  range_pos: number;
  rsi: number | null;
  atr: number | null;
  key_levels: {
    support: number | null;
    resistance: number | null;
    dist_support: number | null;
    dist_resistance: number | null;
    near_support: boolean;
    near_resistance: boolean;
  };
  rejection: {
    rejection: boolean;
    type: string | null;
    wick_ratio: number;
    direction: string | null;
    candle_age: number | null;
    candle_ts: string | null;
    expired: boolean;
  };
  divergence: {
    divergence: boolean;
    type: string | null;
    direction: string | null;
  };
  sl: {
    price: number;
    distance_pips: number;
    cap_pips: number;
    too_wide: boolean;
    tp_price: number | null;
    reward_pips: number | null;
    rrr: number | null;
    rrr_below_min: boolean;
    rrr_min: number;
  } | null;
  alignment: {
    status: "aligned" | "conflict" | "neutral" | "unknown";
    scanner_bias: string | null;
    scanner_confluence: number | null;
    scanner_bias_value?: number | null;
    mtf_lock_passed: boolean | null;
    mtf_lock_failed: boolean;
    reclassified: boolean;
    original_bloque?: number;
  } | null;
  candles?: Array<{
    ts: string;
    open: number;
    high: number;
    low: number;
    close: number;
  }>;
  smc?: SmcAnalysis | null;
  geometria?: GeometryAnalysis | null;
};

export type GeometryAnalysis = {
  canal: {
    detectado: boolean;
    tipo: "ALCISTA" | "BAJISTA" | "LATERAL" | "NINGUNO";
    estado:
      | "DENTRO"
      | "RUPTURA_ALCISTA"
      | "RUPTURA_BAJISTA"
      | "RETESTEO_SUPERIOR"
      | "RETESTEO_INFERIOR"
      | "NINGUNO";
    linea_superior: number | null;
    linea_inferior: number | null;
    confianza: "ALTA" | "MEDIA" | "BAJA";
    r_squared_sup: number;
    r_squared_inf: number;
  };
  triangulo: {
    detectado: boolean;
    tipo: "SIMETRICO" | "ASCENDENTE" | "DESCENDENTE" | "NINGUNO";
    estado: "FORMANDO" | "EN_VERTICE" | "RUPTURA_ALCISTA" | "RUPTURA_BAJISTA" | "NINGUNO";
    vertice_estimado: number | null;
    confianza: "ALTA" | "MEDIA" | "BAJA";
  };
  ruptura: {
    confirmada: boolean;
    direccion: "BULLISH" | "BEARISH" | "NINGUNA";
    figura: "TRIANGULO" | "CANAL" | "NINGUNA";
  };
};

export type SmcAnalysis = {
  sesgo: "LONG_ONLY" | "SHORT_ONLY" | "NO_TRADE";
  estructura: {
    ultimo_movimiento: "HH" | "HL" | "LH" | "LL";
    descripcion: string;
  };
  nivel_activo: {
    precio: number;
    tipo: "SOPORTE" | "RESISTENCIA";
    frescura: "FRESCO" | "TESTEADO" | "AGOTADO";
    fuerza: "FUERTE" | "NORMAL" | "DEBIL";
    proximidad_pips: number;
    operable: boolean;
  };
  alerta: {
    activa: boolean;
    motivo: string;
  };
  resumen: string;
};

export type RadarResponse = {
  timestamp: string;
  active_setups: RadarSetup[];
  expired_setups: RadarSetup[];
  total_setups: number;
  strong_setups: number;
  total_expired: number;
  market_closed?: boolean;
  data_age_minutes?: number | null;
  last_candle_ts?: string | null;
};
