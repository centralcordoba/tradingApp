"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { drawRadarChart } from "./radarChart";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Signal = {
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

type Emotion = "confianza" | "miedo" | "fomo" | "venganza";
type JournalDraft = {
  signalId: number;
  result: "WIN" | "LOSS" | "BE";
  taken: "yes" | "no" | null;
  respected_plan: "yes" | "no" | null;
  closed_early: "yes" | "no" | null;
  emotion: Emotion | null;
};

type NewsWarning = {
  title: string;
  country: string;
  impact: string;
  date_utc: string;
  minutes_until: number;
  status: "past" | "imminent" | "upcoming";
};

type CalendarEvent = {
  title: string;
  country: string;
  impact: string;
  date_utc: string;
  time_madrid: string;
  forecast?: string | null;
  previous?: string | null;
};

function todayMadrid(): string {
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Madrid",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return fmt.format(new Date()); // YYYY-MM-DD
}

type Agg = { n: number; wins: number; losses: number; be: number; win_rate: number; pnl: number };
type Stats = {
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

const EMPTY_AGG: Agg = { n: 0, wins: 0, losses: 0, be: 0, win_rate: 0, pnl: 0 };

/* ── Market Sessions Panel ── */
type SessionInfo = {
  name: string;
  timezone: string;
  openHourUTC: number;
  closeHourUTC: number;
  abbr: string;
};

const SESSIONS: SessionInfo[] = [
  { name: "Asia · Tokyo", timezone: "Asia/Tokyo", openHourUTC: 0, closeHourUTC: 9, abbr: "TYO" },
  { name: "Londres", timezone: "Europe/London", openHourUTC: 7, closeHourUTC: 16, abbr: "LDN" },
  { name: "New York", timezone: "America/New_York", openHourUTC: 12, closeHourUTC: 21, abbr: "NYC" },
];

function useClockTick(intervalMs = 1000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

function formatTime(date: Date, tz: string): string {
  return date.toLocaleTimeString("es-ES", {
    timeZone: tz,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function isSessionOpen(now: Date, session: SessionInfo): boolean {
  const h = now.getUTCHours();
  const m = now.getUTCMinutes();
  const current = h + m / 60;
  return current >= session.openHourUTC && current < session.closeHourUTC;
}

function sessionProgress(now: Date, session: SessionInfo): number {
  const h = now.getUTCHours();
  const m = now.getUTCMinutes();
  const current = h + m / 60;
  if (current < session.openHourUTC || current >= session.closeHourUTC) return 0;
  const duration = session.closeHourUTC - session.openHourUTC;
  return ((current - session.openHourUTC) / duration) * 100;
}

function sessionCountdown(now: Date, session: SessionInfo): { label: string; minutes: number } {
  const h = now.getUTCHours();
  const m = now.getUTCMinutes();
  const s = now.getUTCSeconds();
  const currentMin = h * 60 + m + s / 60;
  const openMin = session.openHourUTC * 60;
  const closeMin = session.closeHourUTC * 60;
  const open = currentMin >= openMin && currentMin < closeMin;

  let diffMin: number;
  if (open) {
    diffMin = closeMin - currentMin;
  } else {
    diffMin = currentMin < openMin ? openMin - currentMin : (24 * 60 - currentMin) + openMin;
  }

  const totalSec = Math.max(0, Math.floor(diffMin * 60));
  const hh = Math.floor(totalSec / 3600);
  const mm = Math.floor((totalSec % 3600) / 60);
  const ss = totalSec % 60;

  const prefix = open ? "Cierra en" : "Abre en";
  const time = hh > 0
    ? `${hh}h ${String(mm).padStart(2, "0")}m`
    : `${mm}m ${String(ss).padStart(2, "0")}s`;

  return { label: `${prefix} ${time}`, minutes: diffMin };
}

function getOverlapLabel(now: Date): string | null {
  const ldn = isSessionOpen(now, SESSIONS[1]);
  const nyc = isSessionOpen(now, SESSIONS[2]);
  const asia = isSessionOpen(now, SESSIONS[0]);
  if (ldn && nyc) return "LDN + NYC";
  if (asia && ldn) return "ASIA + LDN";
  return null;
}

/* ── Kill Zones Panel ── */
type KillZone = {
  label: string;
  startH: number; startM: number;
  endH: number;   endM: number;
  icon: string;
  status: "fire" | "ok" | "warn" | "avoid";
  note: string;
};

const KILL_ZONES: KillZone[] = [
  { label: "Asia",               startH: 2,  startM: 0,  endH: 5,  endM: 0,  icon: "🔴", status: "avoid", note: "No operar (solo análisis de rango)" },
  { label: "Pre-London",         startH: 5,  startM: 0,  endH: 9,  endM: 0,  icon: "🔴", status: "avoid", note: "No operar (identificar liquidez)" },
  { label: "London Open",        startH: 9,  startM: 0,  endH: 10, endM: 30, icon: "🔥", status: "fire",  note: "Setup principal (breakout / liquidity sweep)" },
  { label: "London Continuation",startH: 10, startM: 30, endH: 12, endM: 0,  icon: "✅", status: "ok",    note: "Solo continuación (no forzar trades)" },
  { label: "Pre-NY",             startH: 12, startM: 0,  endH: 14, endM: 0,  icon: "⚠️", status: "warn",  note: "Pullbacks / manipulación (avanzado)" },
  { label: "Overlap LDN-NY",     startH: 14, startM: 0,  endH: 17, endM: 0,  icon: "🏆", status: "fire",  note: "MEJOR VENTANA (A+ setups)" },
  { label: "NY Mid",             startH: 17, startM: 0,  endH: 19, endM: 0,  icon: "⚠️", status: "warn",  note: "Selectivo (reversals / rangos)" },
  { label: "NY Close",           startH: 19, startM: 0,  endH: 22, endM: 0,  icon: "🔴", status: "avoid", note: "Evitar" },
];

function getMadridHourMin(now: Date): { h: number; m: number } {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Madrid",
    hour: "2-digit", minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const h = parseInt(parts.find(p => p.type === "hour")!.value, 10);
  const m = parseInt(parts.find(p => p.type === "minute")!.value, 10);
  return { h, m };
}

function isInKillZone(now: Date, kz: KillZone): boolean {
  const { h, m } = getMadridHourMin(now);
  const cur = h * 60 + m;
  const start = kz.startH * 60 + kz.startM;
  const end = kz.endH * 60 + kz.endM;
  return cur >= start && cur < end;
}

function kzProgress(now: Date, kz: KillZone): number {
  const { h, m } = getMadridHourMin(now);
  const cur = h * 60 + m;
  const start = kz.startH * 60 + kz.startM;
  const end = kz.endH * 60 + kz.endM;
  if (cur < start || cur >= end) return 0;
  return ((cur - start) / (end - start)) * 100;
}

function pad2(n: number) { return String(n).padStart(2, "0"); }

function KillZonesPanel() {
  const now = useClockTick(1000);
  const [open, setOpen] = useState(true);
  const activeIdx = KILL_ZONES.findIndex(kz => isInKillZone(now, kz));

  return (
    <div className="kz-section">
      <button className="kz-toggle" onClick={() => setOpen(!open)}>
        <span className="kz-toggle-left">
          <span className="kz-toggle-icon">🎯</span>
          <span>Kill Zones</span>
          {activeIdx >= 0 && (
            <span className={`kz-active-badge kz-st-${KILL_ZONES[activeIdx].status}`}>
              {KILL_ZONES[activeIdx].icon} {KILL_ZONES[activeIdx].label}
            </span>
          )}
          {activeIdx < 0 && (
            <span className="kz-active-badge kz-st-avoid">Fuera de horario</span>
          )}
        </span>
        <span className="kz-chevron">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="kz-body">
          <div className="kz-timeline">
            {KILL_ZONES.map((kz, i) => {
              const active = i === activeIdx;
              const progress = kzProgress(now, kz);
              return (
                <div key={i} className={`kz-row ${active ? "kz-active" : ""} kz-st-${kz.status}`}>
                  <div className="kz-time-col">
                    <span className="kz-time">{pad2(kz.startH)}:{pad2(kz.startM)}</span>
                    <span className="kz-time-sep">–</span>
                    <span className="kz-time">{pad2(kz.endH)}:{pad2(kz.endM)}</span>
                  </div>
                  <div className="kz-indicator">
                    <div className={`kz-dot ${active ? "kz-dot-active" : ""}`} />
                    {i < KILL_ZONES.length - 1 && <div className="kz-line" />}
                  </div>
                  <div className="kz-content">
                    <div className="kz-header-row">
                      <span className="kz-icon">{kz.icon}</span>
                      <span className="kz-label">{kz.label}</span>
                      {active && <span className="kz-now-tag">AHORA</span>}
                    </div>
                    <div className="kz-note">{kz.note}</div>
                    {active && (
                      <div className="kz-progress-track">
                        <div className="kz-progress-fill" style={{ width: `${progress}%` }} />
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="kz-footer">
            <span className="kz-legend"><span className="kz-leg-dot kz-leg-fire" /> A+ Setup</span>
            <span className="kz-legend"><span className="kz-leg-dot kz-leg-ok" /> Operar con cautela</span>
            <span className="kz-legend"><span className="kz-leg-dot kz-leg-warn" /> Avanzado / selectivo</span>
            <span className="kz-legend"><span className="kz-leg-dot kz-leg-avoid" /> No operar</span>
            <span className="kz-tz-note">Hora Madrid</span>
          </div>
        </div>
      )}
    </div>
  );
}

function SessionsPanel() {
  const now = useClockTick(1000);
  const madridTime = formatTime(now, "Europe/Madrid");
  const overlap = getOverlapLabel(now);

  return (
    <div className="sessions-panel">
      <div className="sessions-grid">
        {SESSIONS.map((s) => {
          const open = isSessionOpen(now, s);
          const progress = sessionProgress(now, s);
          const time = formatTime(now, s.timezone);
          const countdown = sessionCountdown(now, s);
          return (
            <div key={s.abbr} className={`session-card ${open ? "session-open" : "session-closed"}`}>
              <div className="session-header">
                <span className={`session-dot ${open ? "dot-open" : "dot-closed"}`} />
                <span className="session-name">{s.name}</span>
                <span className={`session-status ${open ? "status-open" : "status-closed"}`}>
                  {open ? "ABIERTO" : "CERRADO"}
                </span>
              </div>
              <div className="session-time">{time}</div>
              <div className={`session-countdown ${open ? "countdown-close" : "countdown-open"}`}>
                {countdown.label}
              </div>
              <div className="session-bar-track">
                <div
                  className="session-bar-fill"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          );
        })}
        <div className="session-card session-madrid">
          <div className="session-header">
            <span className="session-dot dot-madrid" />
            <span className="session-name">Madrid · Local</span>
          </div>
          <div className="session-time">{madridTime}</div>
          {overlap && (
            <div className="session-overlap">
              <span className="overlap-icon">⚡</span> Overlap {overlap}
            </div>
          )}
          {!overlap && (
            <div className="session-hours" style={{ opacity: 0.5 }}>Sin overlap activo</div>
          )}
          <div className="session-bar-track">
            <div className="session-bar-fill" style={{ width: "0%" }} />
          </div>
        </div>
      </div>
    </div>
  );
}

function zonaClass(zona: string): string {
  switch (zona) {
    case "COMPRA YA": return "deep-discount";
    case "COMPRA":    return "discount";
    case "VENDE":     return "premium";
    case "VENDE YA":  return "deep-premium";
    default:          return "neutral";
  }
}

function zonaTooltip(zona: string, side: string): string {
  const isLong = side === "LONG" || side === "BUY";
  switch (zona) {
    case "COMPRA YA":
      return isLong
        ? "Descuento extremo — zona ideal para LONG"
        : "Descuento extremo — peligroso para SHORT (soporte fuerte)";
    case "COMPRA":
      return isLong
        ? "Zona de descuento — favorable para LONG"
        : "Zona de descuento — SHORT contra el valor";
    case "VENDE":
      return isLong
        ? "Zona premium — LONG caro, riesgo de rechazo"
        : "Zona premium — favorable para SHORT";
    case "VENDE YA":
      return isLong
        ? "Premium extremo — NO comprar aquí (resistencia fuerte)"
        : "Premium extremo — zona ideal para SHORT";
    default:
      return "Zona no definida";
  }
}

type View = "dashboard" | "zones" | "radar";

// Pares operativos del usuario — usados por el radar para filtrar ruido.
const WATCHLIST = ["XAUUSD", "EURUSD"];

type RadarSetup = {
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
  } | null;
  alignment: {
    status: "aligned" | "conflict" | "neutral" | "unknown";
    scanner_bias: string | null;
    scanner_confluence: number | null;
    scanner_bias_value?: number | null;
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
};

type RadarResponse = {
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

const PRESET_SYMBOLS = [
  "XAUUSD",
  "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
  "AUDUSD", "NZDUSD", "USDCAD",
  "EURJPY", "GBPJPY", "EURGBP",
];

function mergeSymbols(apiSymbols: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const s of [...apiSymbols, ...PRESET_SYMBOLS]) {
    const k = s.toUpperCase();
    if (!seen.has(k)) { seen.add(k); out.push(k); }
  }
  return out;
}

type ScannerFactor = {
  key: string;
  label: string;
  desc: string;
  value: -1 | 0 | 1 | number;
};

type ScannerPair = {
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
};

type DailyBrief = {
  sesgo_dia: string;
  pares_operables: string[];
  pares_excluidos: string[];
  mejor_setup: string;
  correlacion_dominante: string;
  xauusd_resumen: string;
};

function Sparkline({ data, side, width = 120, height = 36 }: {
  data: number[];
  side: "LONG" | "SHORT" | "NEUTRAL";
  width?: number;
  height?: number;
}) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const rng = max - min || 1;
  const stepX = width / (data.length - 1);
  const pts = data.map((v, i) => {
    const x = i * stepX;
    const y = height - ((v - min) / rng) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const color = side === "LONG" ? "#4ade80" : side === "SHORT" ? "#f87171" : "#60a5fa";
  const fillId = `spark-${side}-${Math.random().toString(36).slice(2, 7)}`;
  const lastY = height - ((data[data.length - 1] - min) / rng) * height;
  const firstPt = `0,${height}`;
  const lastPt = `${width},${height}`;
  const areaPts = `${firstPt} ${pts} ${lastPt}`;

  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={areaPts} fill={`url(#${fillId})`} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={width} cy={lastY} r="2.5" fill={color} />
    </svg>
  );
}

const BLOCK_LEGEND: { k: "1" | "2" | "3"; ico: string; name: string; def: string; tip: string }[] = [
  {
    k: "1",
    ico: "🟢",
    name: "Bloque 1 — Tendencia limpia",
    def: "EMAs alineadas (9>21>50 o al revés) + confluencia ≥4. Sin extremos agotados.",
    tip: "Operar a favor de la tendencia. Esperar pullback al EMA9 / EMA21.",
  },
  {
    k: "3",
    ico: "🟡",
    name: "Bloque 3 — Reversión en extremo",
    def: "Precio en extremo del rango (<15% o >85%) + RSI en exhaustion (<32 o >68).",
    tip: "Operar contra-tendencia corta. Esperar sweep + vela de reversión.",
  },
  {
    k: "2",
    ico: "⚪",
    name: "Bloque 2 — Excluido",
    def: "Bias bajo, EMAs mixtas o precio en zona ambigua sin confirmación.",
    tip: "No operar. Observar hasta que se rompa la estructura.",
  },
];

function ZoneAnalysisView() {
  const [pairs, setPairs] = useState<ScannerPair[]>([]);
  const [brief, setBrief] = useState<DailyBrief | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [sideFilter, setSideFilter] = useState<"ALL" | "LONG" | "SHORT" | "B1" | "B3">("ALL");
  const [showAll, setShowAll] = useState(false);
  const [showLegend, setShowLegend] = useState(false);

  const VISIBLE_N = 6;

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API}/scanner/pairs`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      setPairs(j.items || []);
      setBrief(j.brief || null);
      setError(j.last_error && (j.items || []).length === 0 ? j.last_error : null);
      setLastUpdate(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error de red");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 300000);  // 5 min — coincide con el TTL del backend
    return () => clearInterval(id);
  }, [load]);

  const filtered = pairs.filter(p => {
    if (sideFilter === "ALL") return true;
    if (sideFilter === "LONG" || sideFilter === "SHORT") return p.side === sideFilter;
    if (sideFilter === "B1") return p.bloque === "1";
    if (sideFilter === "B3") return p.bloque === "3";
    return true;
  });
  const visible = showAll ? filtered : filtered.slice(0, VISIBLE_N);
  const hiddenCount = filtered.length - visible.length;

  const longsN = pairs.filter(p => p.side === "LONG").length;
  const shortsN = pairs.filter(p => p.side === "SHORT").length;
  const neutralN = pairs.filter(p => p.side === "NEUTRAL").length;

  return (
    <div className="zone-view">
      <div className="zone-intro">
        <div className="zone-intro-head">
          <div>
            <div className="zone-intro-title">🎯 Scanner en vivo · confluencia técnica</div>
            <div className="zone-intro-sub">
              Análisis independiente multi-factor (EMA9/21/50/200, RSI, rango, impulso) sobre datos 15m.
              Prioriza los pares con <b>mayor confluencia</b>.
            </div>
          </div>
          <div className="zone-intro-meta">
            <div className="zone-meta-row">
              <span className="zone-meta-dot zone-dot-long" /> {longsN} LONG
              <span className="zone-meta-dot zone-dot-short" style={{ marginLeft: 10 }} /> {shortsN} SHORT
              <span className="zone-meta-dot zone-dot-neutral" style={{ marginLeft: 10 }} /> {neutralN} neutral
            </div>
            {lastUpdate && (
              <div className="zone-meta-time">
                Actualizado: {lastUpdate.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </div>
            )}
          </div>
        </div>
      </div>

      {brief && <DailyBriefPanel brief={brief} />}

      <div className="zone-controls">
        <div className="zone-tabs">
          <button className={sideFilter === "ALL" ? "tab active" : "tab"} onClick={() => setSideFilter("ALL")}>TODOS</button>
          <button
            className={sideFilter === "B1" ? "tab active" : "tab"}
            onClick={() => setSideFilter("B1")}
            title={`${BLOCK_LEGEND[0].name} — ${BLOCK_LEGEND[0].def}`}
          >🟢 B1</button>
          <button
            className={sideFilter === "B3" ? "tab active" : "tab"}
            onClick={() => setSideFilter("B3")}
            title={`${BLOCK_LEGEND[1].name} — ${BLOCK_LEGEND[1].def}`}
          >🟡 B3</button>
          <button className={sideFilter === "LONG" ? "tab active" : "tab"} onClick={() => setSideFilter("LONG")}>LONG</button>
          <button className={sideFilter === "SHORT" ? "tab active" : "tab"} onClick={() => setSideFilter("SHORT")}>SHORT</button>
          <button
            className={`tab block-info-btn ${showLegend ? "active" : ""}`}
            onClick={() => setShowLegend(s => !s)}
            title="¿Qué significan B1/B2/B3?"
          >ⓘ Bloques</button>
        </div>
        <button className="refresh" onClick={load}>↻ Refrescar ahora</button>
      </div>

      {showLegend && (
        <div className="block-legend">
          {BLOCK_LEGEND.map(b => (
            <div key={b.k} className={`block-legend-row bloque-b${b.k}-border`}>
              <span className={`bloque-badge bloque-b${b.k}`}>B{b.k}</span>
              <div className="block-legend-txt">
                <div className="block-legend-name">{b.ico} {b.name}</div>
                <div className="block-legend-def">{b.def}</div>
                <div className="block-legend-tip">💡 {b.tip}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {loading && pairs.length === 0 ? (
        <div className="zone-empty">Analizando mercados… (primera llamada puede tardar 5-10s)</div>
      ) : error && pairs.length === 0 ? (
        <div className="zone-empty" style={{ color: "#f87171" }}>
          No se pudo cargar el scanner: {error}
        </div>
      ) : filtered.length === 0 ? (
        <div className="zone-empty">Sin pares para este filtro.</div>
      ) : (
        <>
          <div className="scanner-grid">
            {visible.map((p, i) => (
              <ScannerCard key={p.pair} data={p} isTop={i === 0 && pairs.indexOf(p) === 0} />
            ))}
          </div>
          {hiddenCount > 0 && (
            <button className="zone-more" onClick={() => setShowAll(true)}>
              Ver {hiddenCount} más (menor confluencia)
            </button>
          )}
          {showAll && filtered.length > VISIBLE_N && (
            <button className="zone-more" onClick={() => setShowAll(false)}>
              Colapsar
            </button>
          )}
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Radar de setups — reversiones en soporte/resistencia (M15)
// ─────────────────────────────────────────────────────────────────────────

const REJECTION_LABELS: Record<string, string> = {
  pin_bar_bull: "Pin bar alcista",
  pin_bar_bear: "Pin bar bajista",
  engulf_bull: "Envolvente alcista",
  engulf_bear: "Envolvente bajista",
};

function parseCandleDate(iso: string | null): Date | null {
  if (!iso) return null;
  try {
    let s = iso.replace(" ", "T");
    if (!s.endsWith("Z") && !s.includes("+")) s += "Z";
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  } catch { return null; }
}

function formatCandleTime(iso: string | null): string {
  const d = parseCandleDate(iso);
  if (!d) return "";
  const tz = { timeZone: "Europe/Madrid" };
  const todayMadrid = new Date().toLocaleDateString("es-ES", tz);
  const candleDate = d.toLocaleDateString("es-ES", tz);
  const hhmm = d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", ...tz });
  if (todayMadrid === candleDate) return hhmm;
  // Día distinto → prefijar fecha corta (DD/MM)
  const short = d.toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit", ...tz });
  return `${short} ${hhmm}`;
}

function formatDataAge(min: number): string {
  const v = Math.max(0, min);
  if (v < 60) return `${Math.round(v)} min`;
  const h = Math.floor(v / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

function ageText(age: number | null, ts: string | null): string {
  if (age == null) return "";
  const hhmm = formatCandleTime(ts);
  const suffix = hhmm ? ` (${hhmm})` : "";
  if (age === 1) return `vela recién cerrada${suffix}`;
  return `hace ${age} velas${suffix}`;
}

function blockMeta(bloque: number, strength: string | null) {
  switch (bloque) {
    case 1: return {
      label: strength === "STRONG" ? "B1 ★ STRONG" : "B1",
      cls: strength === "STRONG" ? "radar-b1-strong" : "radar-b1",
      tone: "Compra válida",
    };
    case 3: return {
      label: strength === "STRONG" ? "B3 ★ STRONG" : "B3",
      cls: strength === "STRONG" ? "radar-b3-strong" : "radar-b3",
      tone: "Venta válida",
    };
    case 2: return { label: "B2 ⚠ TRAMPA", cls: "radar-trap", tone: "Trampa long" };
    case 4: return { label: "B4 ⚠ TRAMPA", cls: "radar-trap", tone: "Trampa short" };
    default: return { label: "—", cls: "", tone: "" };
  }
}

function trapCopy(bloque: number): { title: string; detail: string } {
  if (bloque === 2) return {
    title: "Trampa long — no comprar aquí",
    detail: "El soporte parece válido pero el rechazo es bajista. Esperar ruptura del soporte confirmada.",
  };
  if (bloque === 4) return {
    title: "Trampa short — no vender aquí",
    detail: "La resistencia parece válida pero el rechazo es alcista. Esperar ruptura confirmada.",
  };
  return { title: "", detail: "" };
}

function RadarChart({ setup }: { setup: RadarSetup }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const parent = canvas.parentElement;
    const draw = () => drawRadarChart(canvas, setup);
    draw();
    if (!parent || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(draw);
    ro.observe(parent);
    return () => ro.disconnect();
  }, [setup]);

  return (
    <div className="radar-chart-wrap">
      <canvas ref={ref} className="radar-chart" />
    </div>
  );
}

function RadarCard({ setup }: { setup: RadarSetup }) {
  const meta = blockMeta(setup.bloque, setup.strength);
  const isTrap = setup.bloque === 2 || setup.bloque === 4;
  const expired = setup.rejection?.expired;
  const tooWide = setup.sl?.too_wide;
  const inWatchlist = WATCHLIST.includes(setup.symbol);
  const trap = isTrap ? trapCopy(setup.bloque) : null;

  const cls = [
    "radar-card",
    meta.cls,
    expired ? "radar-expired" : "",
    tooWide ? "radar-toowide" : "",
  ].filter(Boolean).join(" ");

  return (
    <article className={cls}>
      <header className="radar-head">
        <div>
          <div className="radar-pair">
            {setup.symbol}
            {inWatchlist && <span className="radar-pair-op">● Operativo</span>}
          </div>
          <div className="radar-price">{setup.price}</div>
        </div>
        <div className="radar-badges">
          <span className={`radar-badge ${meta.cls}`}>{meta.label}</span>
          {expired && <span className="radar-badge radar-badge-expired">EXPIRADO</span>}
          {tooWide && <span className="radar-badge radar-badge-toowide">SL EXCEDE</span>}
        </div>
      </header>

      <div className="radar-meta-row">
        <span>{setup.side.replace("_", " ")}</span>
        {setup.rsi != null && <span>· RSI {setup.rsi}</span>}
        <span>· Rango {Math.round(setup.range_pos * 100)}%</span>
      </div>

      <div className="radar-levels">
        {setup.key_levels.support != null && (
          <div className={`radar-level ${setup.key_levels.near_support ? "near" : ""}`}>
            <span className="radar-level-label">Soporte</span>
            <span className="radar-level-value">{setup.key_levels.support}</span>
            <span className="radar-level-dist">
              {setup.key_levels.dist_support?.toFixed(2)}%
              {setup.key_levels.near_support && " ◉ cerca"}
            </span>
          </div>
        )}
        {setup.key_levels.resistance != null && (
          <div className={`radar-level ${setup.key_levels.near_resistance ? "near" : ""}`}>
            <span className="radar-level-label">Resistencia</span>
            <span className="radar-level-value">{setup.key_levels.resistance}</span>
            <span className="radar-level-dist">
              {setup.key_levels.dist_resistance?.toFixed(2)}%
              {setup.key_levels.near_resistance && " ◉ cerca"}
            </span>
          </div>
        )}
      </div>

      {setup.candles && setup.candles.length > 0 && !expired && (
        <RadarChart setup={setup} />
      )}

      {setup.sl && !isTrap && (
        <div className={`radar-sl ${tooWide ? "radar-sl-wide" : ""}`}>
          <span className="radar-sl-label">SL estimado</span>
          <span className="radar-sl-value">{setup.sl.price}</span>
          <span className="radar-sl-pips">
            {setup.sl.distance_pips} pips (cap {setup.sl.cap_pips})
          </span>
        </div>
      )}

      {setup.rejection.rejection && (
        <div className="radar-signal">
          <span className="radar-signal-ico">🕯</span>
          {REJECTION_LABELS[setup.rejection.type || ""] || setup.rejection.type}
          {setup.rejection.wick_ratio ? ` · ratio ${setup.rejection.wick_ratio}` : ""}
          <span className="radar-signal-age">· {ageText(setup.rejection.candle_age, setup.rejection.candle_ts)}</span>
        </div>
      )}

      {setup.divergence.divergence && (
        <div className="radar-signal">
          <span className="radar-signal-ico">📈</span>
          Divergencia {setup.divergence.type === "bullish" ? "alcista" : "bajista"} activa
        </div>
      )}

      {trap && (
        <div className="radar-trap-copy">
          <div className="radar-trap-title">⚠ {trap.title}</div>
          <div className="radar-trap-detail">{trap.detail}</div>
        </div>
      )}

      {setup.alignment && <RadarAlignment a={setup.alignment} />}
    </article>
  );
}

function RadarAlignment({ a }: { a: NonNullable<RadarSetup["alignment"]> }) {
  const conf = a.scanner_confluence;
  const bias = a.scanner_bias;
  if (a.status === "aligned") {
    return (
      <div className="radar-align radar-align-ok">
        ✓ Alineado con sesgo {bias} del escáner{conf != null ? ` (${conf}/7)` : ""}
      </div>
    );
  }
  if (a.status === "conflict" && a.reclassified) {
    return (
      <div className="radar-align radar-align-warn">
        ⚠ Reclasificado: escáner dice {bias}{conf != null ? ` (${conf}/7)` : ""} → tratado como trampa
      </div>
    );
  }
  if (a.status === "conflict") {
    return (
      <div className="radar-align radar-align-warn">
        ⚠ Conflicto con sesgo {bias} del escáner{conf != null ? ` (${conf}/7)` : ""}
      </div>
    );
  }
  if (a.status === "neutral") {
    return (
      <div className="radar-align radar-align-neutral">
        · Escáner sin sesgo claro en este par
      </div>
    );
  }
  return null;
}

function RadarView() {
  const [data, setData] = useState<RadarResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [onlyWatchlist, setOnlyWatchlist] = useState(false);
  const [showLegend, setShowLegend] = useState(false);
  const [showExpired, setShowExpired] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/radar`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j: RadarResponse = await r.json();
      setData(j);
      setError(null);
      setLastUpdate(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error de red");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 300000);
    return () => clearInterval(id);
  }, [load]);

  const applyWatchlist = (arr: RadarSetup[]) =>
    onlyWatchlist ? arr.filter(s => WATCHLIST.includes(s.symbol)) : arr;

  const active = applyWatchlist(data?.active_setups || []);
  const expired = applyWatchlist(data?.expired_setups || []);

  const strongN = active.filter(s => s.strength === "STRONG" && !s.sl?.too_wide).length;
  const trapN = active.filter(s => s.bloque === 2 || s.bloque === 4).length;
  const totalValid = active.filter(s => !s.sl?.too_wide).length;

  const emptyActiveWithExpired = active.length === 0 && expired.length > 0;
  const marketClosed = data?.market_closed === true;

  return (
    <div className="radar-view">
      <div className="radar-intro">
        <div>
          <div className="radar-intro-title">📡 Radar de setups · reversiones en S/R</div>
          <div className="radar-intro-sub">
            Pin bar / envolventes sobre soporte o resistencia, cruzado con el sesgo macro del escáner.
            Un conflicto reclasifica el setup como trampa.
          </div>
        </div>
        <div className="radar-intro-meta">
          <div className="radar-meta-kpis">
            <span className="radar-kpi">{totalValid} activos</span>
            <span className="radar-kpi radar-kpi-strong">{strongN} STRONG</span>
            <span className="radar-kpi radar-kpi-trap">{trapN} trampas</span>
          </div>
          {lastUpdate && (
            <div className="radar-meta-time">
              Actualizado: {lastUpdate.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}
            </div>
          )}
        </div>
      </div>

      {marketClosed && (
        <div className="radar-market-closed">
          <span className="radar-market-closed-ico">🌙</span>
          <div>
            <div className="radar-market-closed-title">Mercado cerrado</div>
            <div className="radar-market-closed-sub">
              {data?.last_candle_ts ? (
                <>Última vela M15: <b>{formatCandleTime(data.last_candle_ts)}</b></>
              ) : null}
              {data?.data_age_minutes != null && (
                <> · hace {formatDataAge(data.data_age_minutes)}</>
              )}
              {" · los setups detectados no son accionables hasta que reabra el feed."}
            </div>
          </div>
        </div>
      )}

      <div className="radar-controls">
        <label className="radar-toggle">
          <input
            type="checkbox"
            checked={onlyWatchlist}
            onChange={e => setOnlyWatchlist(e.target.checked)}
          />
          Solo mis pares ({WATCHLIST.join(" · ")})
        </label>
        <button
          className={`tab block-info-btn ${showLegend ? "active" : ""}`}
          onClick={() => setShowLegend(s => !s)}
          title="¿Qué son los bloques?"
        >ⓘ Bloques</button>
        <button className="refresh" onClick={load}>↻ Refrescar ahora</button>
      </div>

      {showLegend && (
        <div className="radar-legend">
          <div className="radar-legend-row"><span className="radar-legend-badge radar-b1">B1</span> Compra válida — precio en soporte + rechazo alcista</div>
          <div className="radar-legend-row"><span className="radar-legend-badge radar-b1-strong">B1 ★</span> Compra STRONG — B1 + divergencia alcista</div>
          <div className="radar-legend-row"><span className="radar-legend-badge radar-b3">B3</span> Venta válida — precio en resistencia + rechazo bajista</div>
          <div className="radar-legend-row"><span className="radar-legend-badge radar-b3-strong">B3 ★</span> Venta STRONG — B3 + divergencia bajista</div>
          <div className="radar-legend-row"><span className="radar-legend-badge radar-trap">B2/B4</span> Trampas — no operar, esperar ruptura confirmada</div>
        </div>
      )}

      {loading && !data ? (
        <div className="zone-empty">Analizando mercados… (primera llamada puede tardar 5-10s)</div>
      ) : error ? (
        <div className="zone-empty" style={{ color: "#f87171" }}>
          No se pudo cargar el radar: {error}
        </div>
      ) : marketClosed && active.length === 0 ? (
        <div className="zone-empty">
          🌙 Sin setups accionables — mercado cerrado.
          {expired.length > 0 && (
            <>
              {" "}Hay {expired.length} setup{expired.length === 1 ? "" : "s"} del último feed activo abajo.
              <button
                className="radar-inline-link"
                onClick={() => setShowExpired(true)}
              >Ver últimos ↓</button>
            </>
          )}
        </div>
      ) : emptyActiveWithExpired ? (
        <div className="zone-empty">
          No hay setups activos · {expired.length} setup{expired.length === 1 ? "" : "s"} expirado{expired.length === 1 ? "" : "s"} reciente{expired.length === 1 ? "" : "s"}.
          <button
            className="radar-inline-link"
            onClick={() => setShowExpired(true)}
          >Ver expirados ↓</button>
        </div>
      ) : active.length === 0 ? (
        <div className="zone-empty">
          No hay setups activos {onlyWatchlist ? "en tu watchlist" : ""}.
          {" "}El radar busca pin bars / envolventes en soporte o resistencia.
        </div>
      ) : (
        <div className="radar-grid">
          {active.map(s => <RadarCard key={s.symbol} setup={s} />)}
        </div>
      )}

      {expired.length > 0 && (
        <section className="radar-expired-section">
          <button
            className="radar-expired-toggle"
            onClick={() => setShowExpired(v => !v)}
            aria-expanded={showExpired}
          >
            <span>{showExpired ? "▾" : "▸"}</span>
            Setups expirados ({expired.length})
            <span className="radar-expired-hint">· velas ya antiguas, no accionables</span>
          </button>
          {showExpired && (
            <div className="radar-grid">
              {expired.map(s => <RadarCard key={`exp-${s.symbol}`} setup={s} />)}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function DailyBriefPanel({ brief }: { brief: DailyBrief }) {
  return (
    <section className="brief-panel">
      <div className="brief-head">
        <span className="brief-head-ico">📊</span>
        <span className="brief-head-title">Brief del día</span>
        <span className="brief-head-sesgo">{brief.sesgo_dia}</span>
      </div>

      <div className="brief-grid">
        <div className="brief-card brief-correlation">
          <div className="brief-card-label"><span>🌐</span> Correlación dominante</div>
          <div className="brief-card-value">{brief.correlacion_dominante}</div>
        </div>

        <div className="brief-card brief-best">
          <div className="brief-card-label"><span>🏆</span> Mejor setup</div>
          <div className="brief-card-value brief-best-value">{brief.mejor_setup}</div>
        </div>

        <div className="brief-card brief-gold">
          <div className="brief-card-label"><span>🥇</span> XAUUSD</div>
          <div className="brief-card-value">{brief.xauusd_resumen}</div>
        </div>

        <div className="brief-card brief-operables">
          <div className="brief-card-label">
            <span>✅</span> Pares operables <span className="brief-count">{brief.pares_operables.length}</span>
          </div>
          {brief.pares_operables.length === 0 ? (
            <div className="brief-list-empty">Ningún par en B1 o B3 hoy</div>
          ) : (
            <ul className="brief-list brief-list-ok">
              {brief.pares_operables.map((s, i) => <li key={i}>{s}</li>)}
            </ul>
          )}
        </div>

        <div className="brief-card brief-excluidos">
          <div className="brief-card-label">
            <span>❌</span> Pares excluidos <span className="brief-count">{brief.pares_excluidos.length}</span>
          </div>
          {brief.pares_excluidos.length === 0 ? (
            <div className="brief-list-empty">Sin exclusiones</div>
          ) : (
            <ul className="brief-list brief-list-bad">
              {brief.pares_excluidos.map((s, i) => <li key={i}>{s}</li>)}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}

function ScannerCard({ data, isTop }: { data: ScannerPair; isTop: boolean }) {
  const sideClass = data.side === "LONG" ? "long" : data.side === "SHORT" ? "short" : "neutral";
  const pct = (data.confluence / data.max) * 100;
  const strength = pct >= 70 ? "high" : pct >= 40 ? "mid" : "low";
  const changeUp = data.change_pct >= 0;

  return (
    <article className={`scanner-card scanner-${sideClass} scanner-${strength} ${isTop ? "scanner-top" : ""}`}>
      {isTop && <div className="scanner-top-tag">🏆 MAYOR CONFLUENCIA</div>}

      <div className="scanner-head">
        <div className="scanner-head-left">
          <span className="scanner-pair">{data.pair}</span>
          <span className={`scanner-side scanner-side-${sideClass}`}>{data.side}</span>
          {data.bloque && (
            <span className={`bloque-badge bloque-b${data.bloque}`} title={data.bloque_reason || ""}>
              B{data.bloque}
            </span>
          )}
        </div>
        <Sparkline data={data.spark} side={data.side} />
      </div>

      <div className="scanner-price-row">
        <span className="scanner-price">{data.price}</span>
        <span className={`scanner-change ${changeUp ? "good" : "bad"}`}>
          {changeUp ? "▲" : "▼"} {changeUp ? "+" : ""}{data.change_pct.toFixed(2)}%
        </span>
      </div>

      <div className="scanner-score-row">
        <div className="scanner-score-big">
          <span className="scanner-score-num">{data.confluence}</span>
          <span className="scanner-score-max">/ {data.max}</span>
        </div>
        <div className="scanner-score-track">
          <div className={`scanner-score-fill scanner-fill-${strength}`} style={{ width: `${pct}%` }} />
        </div>
      </div>

      <div className="scanner-micro">
        {data.rsi != null && <span>RSI <b>{data.rsi.toFixed(0)}</b></span>}
        <span>Rango <b>{(data.range_pos * 100).toFixed(0)}%</b></span>
        <span>Bias <b className={data.bias > 0 ? "good" : data.bias < 0 ? "bad" : ""}>{data.bias > 0 ? "+" : ""}{data.bias}</b></span>
      </div>

      <div className="scanner-factors">
        {data.factors.map(f => {
          const cls = f.value > 0 ? "fac-long" : f.value < 0 ? "fac-short" : "fac-neutral";
          const ico = f.value > 0 ? "▲" : f.value < 0 ? "▼" : "·";
          return (
            <span key={f.key} className={`scanner-chip ${cls}`} title={f.desc}>
              <span className="scanner-chip-ico">{ico}</span>
              {f.label}
            </span>
          );
        })}
      </div>
    </article>
  );
}

export default function Home() {
  const PAGE_SIZE = 10;
  const [view, setView] = useState<View>("dashboard");
  const [items, setItems] = useState<Signal[]>([]);
  const [totalSignals, setTotalSignals] = useState(0);
  const [page, setPage] = useState(1);
  const [stats, setStats] = useState<Stats | null>(null);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [filter, setFilter] = useState<string>("ALL");
  const [loading, setLoading] = useState(true);
  const [journal, setJournal] = useState<JournalDraft | null>(null);
  const [newsWarnings, setNewsWarnings] = useState<NewsWarning[]>([]);
  const [calendarDate, setCalendarDate] = useState<string>(todayMadrid);
  const [calendarOpen, setCalendarOpen] = useState<boolean>(false);
  const [calendarEvents, setCalendarEvents] = useState<CalendarEvent[]>([]);
  const [calendarLoading, setCalendarLoading] = useState<boolean>(false);

  const totalPages = Math.max(1, Math.ceil(totalSignals / PAGE_SIZE));

  const load = useCallback(async () => {
    try {
      const offset = (page - 1) * PAGE_SIZE;
      const symParam = filter === "ALL" ? "" : `&symbol=${filter}`;
      const signalsUrl = `${API}/signals?limit=${PAGE_SIZE}&offset=${offset}${symParam}`;
      const [sR, stR, syR, nR] = await Promise.all([
        fetch(signalsUrl, { cache: "no-store" }),
        fetch(`${API}/stats`, { cache: "no-store" }),
        fetch(`${API}/symbols`, { cache: "no-store" }),
        fetch(`${API}/news/warnings`, { cache: "no-store" }),
      ]);
      const signalsData = await sR.json();
      setItems(signalsData.items || []);
      setTotalSignals(signalsData.total || 0);
      setStats(await stR.json());
      setSymbols(mergeSymbols(await syR.json()));
      const nj = await nR.json();
      setNewsWarnings(nj.warnings || []);
    } catch {
      setItems([]);
      setTotalSignals(0);
      setStats(null);
      setNewsWarnings([]);
    } finally {
      setLoading(false);
    }
  }, [filter, page]);

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  const loadCalendar = useCallback(async (date: string) => {
    setCalendarLoading(true);
    try {
      const r = await fetch(`${API}/news/calendar?date=${date}&impact=high`, { cache: "no-store" });
      const j = await r.json();
      setCalendarEvents(j.events || []);
    } catch {
      setCalendarEvents([]);
    } finally {
      setCalendarLoading(false);
    }
  }, []);

  useEffect(() => {
    if (calendarOpen) loadCalendar(calendarDate);
  }, [calendarOpen, calendarDate, loadCalendar]);

  const openJournal = (id: number, result: "WIN" | "LOSS" | "BE") => {
    setJournal({ signalId: id, result, taken: null, respected_plan: null, closed_early: null, emotion: null });
  };

  const submitJournal = async () => {
    if (!journal || !journal.taken) return;
    const body: Record<string, unknown> = { result: journal.result, taken: journal.taken };
    if (journal.taken === "yes") {
      body.journal_respected_plan = journal.respected_plan;
      body.journal_closed_early = journal.closed_early;
      body.journal_emotion = journal.emotion;
    }
    await fetch(`${API}/signals/${journal.signalId}/result`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setJournal(null);
    load();
  };

  return (
    <div className="container">
      <div className="head">
        <div>
          <h1>AI Trading Assistant</h1>
          <div className="sub">Motor de decisión contextual · auto-refresh 5s</div>
        </div>
        <button className="refresh" onClick={load}>Refrescar</button>
      </div>

      <nav className="view-nav">
        <button
          className={`view-nav-btn ${view === "dashboard" ? "active" : ""}`}
          onClick={() => setView("dashboard")}
        >
          <span className="view-nav-ico">📊</span> Dashboard
        </button>
        <button
          className={`view-nav-btn ${view === "zones" ? "active" : ""}`}
          onClick={() => setView("zones")}
        >
          <span className="view-nav-ico">🎯</span> Análisis de zonas
        </button>
        <button
          className={`view-nav-btn ${view === "radar" ? "active" : ""}`}
          onClick={() => setView("radar")}
        >
          <span className="view-nav-ico">📡</span> Radar de setups
        </button>
      </nav>

      <SessionsPanel />
      <KillZonesPanel />

      {newsWarnings.length > 0 && (
        <div className="news-banner">
          {newsWarnings.map((w, i) => (
            <NewsBannerItem key={`${w.date_utc}-${i}`} warning={w} />
          ))}
        </div>
      )}

      {view === "zones" ? (
        <ZoneAnalysisView />
      ) : view === "radar" ? (
        <RadarView />
      ) : (
      <>
      {stats && (
        <>
          <div className="stats">
            <StatCard label="Total" value={stats.total_signals} />
            <StatCard label="Cerradas" value={stats.closed} />
            <StatCard label="Abiertas" value={stats.open} />
            <StatCard label="Win rate" value={`${(stats.overall.win_rate * 100).toFixed(0)}%`} accent />
            <StatCard label={`W/L/BE`} value={`${stats.overall.wins}/${stats.overall.losses}/${stats.overall.be}`} />
            <StatCard label="PnL ($)" value={stats.overall.pnl.toFixed(2)} accent={stats.overall.pnl >= 0 ? "good" : "bad"} />
          </div>
          <div className="stats-split">
            <SplitCard
              title="Ejecutadas"
              subtitle="PnL real de las que operaste"
              agg={stats.overall_taken ?? EMPTY_AGG}
              variant="taken"
            />
            <SplitCard
              title="Calificadas"
              subtitle="Edge del sistema sin ejecución"
              agg={stats.overall_rated ?? EMPTY_AGG}
              variant="rated"
            />
            <div className="split-card exec-rate">
              <div className="card-label">Execution rate</div>
              <div className="card-value">{((stats.execution_rate ?? 0) * 100).toFixed(0)}%</div>
              <div className="split-sub">
                {(stats.overall_taken ?? EMPTY_AGG).n} ejecutadas / {stats.closed} evaluadas
              </div>
            </div>
          </div>
        </>
      )}

      <div className="calendar-section">
        <button className="calendar-toggle" onClick={() => setCalendarOpen(!calendarOpen)}>
          📅 Calendario económico {calendarOpen ? "▲" : "▼"}
        </button>
        {calendarOpen && (
          <div className="calendar-body">
            <div className="calendar-controls">
              <input
                type="date"
                value={calendarDate}
                onChange={(e) => setCalendarDate(e.target.value)}
                className="calendar-date"
              />
              <button className="calendar-today" onClick={() => setCalendarDate(todayMadrid())}>Hoy</button>
              <span className="calendar-tz">hora Madrid</span>
            </div>
            {calendarLoading ? (
              <div className="calendar-empty">Cargando…</div>
            ) : calendarEvents.length === 0 ? (
              <div className="calendar-empty">Sin eventos high-impact este día</div>
            ) : (
              <table className="calendar-table">
                <tbody>
                  {calendarEvents.map((e, i) => (
                    <tr key={`${e.date_utc}-${i}`}>
                      <td className="cal-time">{e.time_madrid}</td>
                      <td><span className="cal-country">{e.country}</span></td>
                      <td className="cal-title">{e.title}</td>
                      <td className="cal-nums">
                        {e.forecast && <span>F: <b>{e.forecast}</b></span>}
                        {e.previous && <span className="cal-prev">P: {e.previous}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      <div className="tabs">
        <button className={filter === "ALL" ? "tab active" : "tab"} onClick={() => { setFilter("ALL"); setPage(1); }}>TODOS</button>
        {symbols.map((s) => (
          <button key={s} className={filter === s ? "tab active" : "tab"} onClick={() => { setFilter(s); setPage(1); }}>{s}</button>
        ))}
      </div>

      {stats && stats.closed > 0 && (
        <div className="breakdowns">
          <Breakdown title="Por símbolo" data={(stats as any).by_symbol || {}} />
          <Breakdown title="Por decisión" data={stats.by_decision} />
          <Breakdown title="Por fuente" data={stats.by_source} />
          <Breakdown title="Por calidad" data={stats.by_quality} />
        </div>
      )}

      {loading && items.length === 0 ? (
        <div className="empty">Cargando…</div>
      ) : items.length === 0 ? (
        <div className="empty">Sin señales todavía. Configura el webhook a <code>{API}/webhook/tradingview</code></div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Hora</th>
              <th>Símbolo</th>
              <th>Lado</th>
              <th>Precio</th>
              <th>Conf</th>
              <th>Calidad</th>
              <th>MTF</th>
              <th>Zona</th>
              <th>Decisión</th>
              <th>Razón</th>
              <th>Resultado</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id}>
                <td>{new Date(it.received_at).toLocaleTimeString()}</td>
                <td>{it.signal.symbol}</td>
                <td className={it.signal.signal}>{it.signal.signal}</td>
                <td>{it.signal.price}</td>
                <td>{it.signal.conf}/19</td>
                <td>{it.signal.quality}</td>
                <td>{it.signal.mtf}</td>
                <td>
                  <span className={`zona-chip zona-${zonaClass(it.signal.zona)}`} title={zonaTooltip(it.signal.zona, it.signal.signal)}>
                    {it.signal.zona}
                  </span>
                </td>
                <td><span className={`badge ${it.response.decision}`}>{it.response.decision}</span></td>
                <td className="reason">
                  {it.response.reason}
                  {it.response.plan && (
                    <div className="plan">
                      <div className="plan-type">📋 {it.response.plan.trigger_type}</div>
                      <div className="plan-zone">
                        Zona espera: <b>{it.response.plan.wait_zone[0]} – {it.response.plan.wait_zone[1]}</b>
                        {" · "}Trigger: <b className="trigger">{it.response.plan.trigger_price}</b>
                        {" · "}Cancel: <b className="invalid">{it.response.plan.invalidation}</b>
                      </div>
                      <div className="plan-text">{it.response.plan.instructions}</div>
                    </div>
                  )}
                </td>
                <td>
                  {it.result ? (
                    <div className="result-cell">
                      <span className={`badge ${it.result}`}>
                        {it.result} {it.pnl != null && `(${it.pnl >= 0 ? "+" : ""}${it.pnl.toFixed(1)})`}
                      </span>
                      {it.taken === "yes" && <span className="taken-badge exec">EJEC</span>}
                      {it.taken === "no" && <span className="taken-badge rated">CAL</span>}
                    </div>
                  ) : (
                    <div className="actions">
                      <button className="btn-win"  onClick={() => openJournal(it.id, "WIN")}>W</button>
                      <button className="btn-loss" onClick={() => openJournal(it.id, "LOSS")}>L</button>
                      <button className="btn-be"   onClick={() => openJournal(it.id, "BE")}>BE</button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {totalSignals > 0 && (
        <div className="pagination">
          <button
            className="page-btn"
            disabled={page <= 1}
            onClick={() => setPage(1)}
            title="Primera"
          >
            &laquo;
          </button>
          <button
            className="page-btn"
            disabled={page <= 1}
            onClick={() => setPage(p => Math.max(1, p - 1))}
          >
            &lsaquo;
          </button>

          <div className="page-numbers">
            {Array.from({ length: totalPages }, (_, i) => i + 1)
              .filter(p => p === 1 || p === totalPages || Math.abs(p - page) <= 2)
              .reduce<(number | string)[]>((acc, p, idx, arr) => {
                if (idx > 0 && p - (arr[idx - 1] as number) > 1) acc.push("...");
                acc.push(p);
                return acc;
              }, [])
              .map((p, i) =>
                typeof p === "string" ? (
                  <span key={`dots-${i}`} className="page-dots">{p}</span>
                ) : (
                  <button
                    key={p}
                    className={`page-num ${p === page ? "active" : ""}`}
                    onClick={() => setPage(p)}
                  >
                    {p}
                  </button>
                )
              )}
          </div>

          <button
            className="page-btn"
            disabled={page >= totalPages}
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
          >
            &rsaquo;
          </button>
          <button
            className="page-btn"
            disabled={page >= totalPages}
            onClick={() => setPage(totalPages)}
            title="Última"
          >
            &raquo;
          </button>

          <span className="page-info">
            {((page - 1) * PAGE_SIZE) + 1}–{Math.min(page * PAGE_SIZE, totalSignals)} de {totalSignals}
          </span>
        </div>
      )}
      </>
      )}

      {journal && (
        <JournalModal
          draft={journal}
          onChange={setJournal}
          onSave={submitJournal}
          onClose={() => setJournal(null)}
        />
      )}
    </div>
  );
}

function NewsBannerItem({ warning }: { warning: NewsWarning }) {
  const { status, minutes_until, title, country } = warning;
  const when = new Date(warning.date_utc);
  const hhmm = when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const timing =
    status === "past"
      ? `hace ${Math.abs(minutes_until)} min`
      : status === "imminent"
      ? `en ${minutes_until} min · INMINENTE`
      : `en ${minutes_until} min`;

  return (
    <div className={`news-item news-${status}`}>
      <span className="news-icon">⚠️</span>
      <span className="news-country">{country}</span>
      <span className="news-title">{title}</span>
      <span className="news-time">{hhmm} · {timing}</span>
    </div>
  );
}

function JournalModal({
  draft, onChange, onSave, onClose,
}: {
  draft: JournalDraft;
  onChange: (d: JournalDraft) => void;
  onSave: () => void;
  onClose: () => void;
}) {
  const emotions: { key: Emotion; label: string; color: string }[] = [
    { key: "confianza", label: "Confianza", color: "#4ade80" },
    { key: "miedo",     label: "Miedo",     color: "#60a5fa" },
    { key: "fomo",      label: "FOMO",      color: "#facc15" },
    { key: "venganza",  label: "Venganza",  color: "#f87171" },
  ];

  const isTaken = draft.taken === "yes";
  const canSave =
    draft.taken === "no" ||
    (isTaken && draft.respected_plan && draft.closed_early && draft.emotion);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <span className={`badge ${draft.result}`}>{draft.result}</span>
            <span className="modal-title">
              {draft.taken === null
                ? "¿Operaste esta señal?"
                : isTaken
                ? "Post-mortem del trade"
                : "Calificando señal (no operada)"}
            </span>
          </div>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          <div className="modal-q">
            <label>¿Operaste esta señal?</label>
            <div className="modal-options">
              <button
                className={`modal-opt ${draft.taken === "yes" ? "selected good" : ""}`}
                onClick={() => onChange({ ...draft, taken: "yes" })}
              >Sí, la operé</button>
              <button
                className={`modal-opt ${draft.taken === "no" ? "selected accent" : ""}`}
                onClick={() => onChange({ ...draft, taken: "no", respected_plan: null, closed_early: null, emotion: null })}
              >No, solo calificar</button>
            </div>
            {draft.taken === "no" && (
              <div className="modal-hint">
                Calificando: resultado hipotético del setup sin entrar. Sirve para medir el edge del sistema.
              </div>
            )}
          </div>

          {isTaken && (
            <>
              <div className="modal-q">
                <label>¿Respetaste el plan de entrada?</label>
                <div className="modal-options">
                  <button
                    className={`modal-opt ${draft.respected_plan === "yes" ? "selected good" : ""}`}
                    onClick={() => onChange({ ...draft, respected_plan: "yes" })}
                  >Sí</button>
                  <button
                    className={`modal-opt ${draft.respected_plan === "no" ? "selected bad" : ""}`}
                    onClick={() => onChange({ ...draft, respected_plan: "no" })}
                  >No</button>
                </div>
              </div>

              <div className="modal-q">
                <label>¿Cerraste antes del TP/SL?</label>
                <div className="modal-options">
                  <button
                    className={`modal-opt ${draft.closed_early === "no" ? "selected good" : ""}`}
                    onClick={() => onChange({ ...draft, closed_early: "no" })}
                  >No, dejé correr</button>
                  <button
                    className={`modal-opt ${draft.closed_early === "yes" ? "selected bad" : ""}`}
                    onClick={() => onChange({ ...draft, closed_early: "yes" })}
                  >Sí, cerré antes</button>
                </div>
              </div>

              <div className="modal-q">
                <label>Emoción dominante</label>
                <div className="modal-options">
                  {emotions.map((e) => (
                    <button
                      key={e.key}
                      className={`modal-opt ${draft.emotion === e.key ? "selected" : ""}`}
                      style={draft.emotion === e.key ? { borderColor: e.color, color: e.color } : undefined}
                      onClick={() => onChange({ ...draft, emotion: e.key })}
                    >{e.label}</button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>

        <div className="modal-foot">
          <button className="modal-save" onClick={onSave} disabled={!canSave}>Guardar</button>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, accent }: { label: string; value: string | number; accent?: boolean | "good" | "bad" }) {
  const cls = accent === "good" ? "good" : accent === "bad" ? "bad" : accent ? "accent" : "";
  return (
    <div className={`card ${cls}`}>
      <div className="card-label">{label}</div>
      <div className="card-value">{value}</div>
    </div>
  );
}

function SplitCard({
  title, subtitle, agg, variant,
}: {
  title: string;
  subtitle: string;
  agg: Agg;
  variant: "taken" | "rated";
}) {
  const pnlCls = agg.pnl >= 0 ? "good" : "bad";
  return (
    <div className={`split-card split-${variant}`}>
      <div className="split-head">
        <div className="split-title">{title}</div>
        <div className="split-n">{agg.n}</div>
      </div>
      <div className="split-sub">{subtitle}</div>
      <div className="split-metrics">
        <div className="split-metric">
          <span className="split-metric-label">WR</span>
          <span className="split-metric-value">{(agg.win_rate * 100).toFixed(0)}%</span>
        </div>
        <div className="split-metric">
          <span className="split-metric-label">W/L/BE</span>
          <span className="split-metric-value">{agg.wins}/{agg.losses}/{agg.be}</span>
        </div>
        <div className="split-metric">
          <span className="split-metric-label">PnL</span>
          <span className={`split-metric-value ${pnlCls}`}>{agg.pnl.toFixed(2)}</span>
        </div>
      </div>
    </div>
  );
}

function Breakdown({ title, data }: { title: string; data: Record<string, Agg> }) {
  const keys = Object.keys(data);
  if (!keys.length) return null;
  const maxN = Math.max(...keys.map((k) => data[k].n), 1);
  const maxPnl = Math.max(...keys.map((k) => Math.abs(data[k].pnl)), 1);

  return (
    <div className="bd-card">
      <div className="bd-header">{title}</div>
      {keys.map((k) => {
        const agg = data[k];
        const wr = agg.win_rate * 100;
        const pnlPositive = agg.pnl >= 0;
        const pnlBarWidth = (Math.abs(agg.pnl) / maxPnl) * 100;
        const volumeWidth = (agg.n / maxN) * 100;
        return (
          <div key={k} className="bd-row">
            <div className="bd-row-top">
              <span className="bd-label">{k}</span>
              <span className="bd-trades">{agg.n} ops</span>
            </div>
            <div className="bd-volume-track">
              <div className="bd-volume-fill" style={{ width: `${volumeWidth}%` }} />
            </div>
            <div className="bd-metrics">
              <div className="bd-metric-wr">
                <div className="bd-wr-bar-track">
                  <div
                    className={`bd-wr-bar-fill ${wr >= 50 ? "bd-wr-good" : "bd-wr-bad"}`}
                    style={{ width: `${wr}%` }}
                  />
                </div>
                <span className={`bd-wr-value ${wr >= 50 ? "good" : "bad"}`}>{wr.toFixed(0)}%</span>
              </div>
              <div className="bd-wlbe">
                <span className="bd-w">{agg.wins}W</span>
                <span className="bd-l">{agg.losses}L</span>
                <span className="bd-b">{agg.be}BE</span>
              </div>
              <div className="bd-pnl-row">
                <div className="bd-pnl-bar-track">
                  <div
                    className={`bd-pnl-bar-fill ${pnlPositive ? "bd-pnl-pos" : "bd-pnl-neg"}`}
                    style={{ width: `${pnlBarWidth}%` }}
                  />
                </div>
                <span className={`bd-pnl-value ${pnlPositive ? "good" : "bad"}`}>
                  {pnlPositive ? "+" : ""}{agg.pnl.toFixed(1)}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
