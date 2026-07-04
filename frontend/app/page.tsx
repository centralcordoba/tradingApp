"use client";
import { useEffect, useState, useCallback, useRef, useId } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { Topbar } from "@/components/shell/Topbar";
import { Sidebar } from "@/components/shell/Sidebar";
import { RightBar } from "@/components/shell/RightBar";
import { SessionsTimeline } from "@/components/dashboard/SessionsTimeline";
import { KpiHero } from "@/components/dashboard/KpiHero";
import { EquityCurve } from "@/components/dashboard/EquityCurve";
import { StocksView } from "@/components/stocks/StocksView";
import { CorrelationsView } from "@/components/correlations/CorrelationsView";
import { PlaybookView } from "@/components/playbook/PlaybookView";
import { ZonasSRView } from "@/components/zones/ZonasSRView";
import { CrossBadge } from "@/components/cross/CrossBadge";
import type { CrossVerdict } from "@/lib/types";
import { useTick } from "@/hooks/useTick";
import { playChime, sendNotification, createAudioContext } from "@/lib/alerts";
import {
  SESSIONS,
  type SessionInfo,
  formatTime,
  isSessionOpen,
  sessionProgress,
  sessionCountdown,
  getOverlapLabel,
} from "@/lib/sessions";
import { KILL_ZONES, type KillZone, isInKillZone, kzProgress } from "@/lib/killZones";
import { WATCHLIST } from "@/lib/config";
import { VerdictStrip } from "@/components/shell/VerdictStrip";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const SIGNAL_ALERTS_KEY = "tradingapp:signal_alerts_on";

const NEWS_ALERT_THRESHOLD_MIN = 20;
const NEWS_ALERT_LINGER_MIN = 5;
const NEWS_ALERTED_KEY = "tradingapp:news_alerted";
const newsKey = (w: NewsWarning) => `${w.date_utc}|${w.title}|${w.country}`;

const NY_PREOPEN_ALERT_MIN = 15;
const NY_PREOPEN_MODAL_KEY = "tradingapp:ny_preopen_modal_shown";

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
    zona: string | null;
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
      expires_after?: number | null;
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

type ConfirmDialogState = {
  title: string;
  message: string;
  confirmLabel: string;
  itemHint?: string;
  onConfirm: () => void | Promise<void>;
};

type NewsWarning = {
  title: string;
  country: string;
  impact: string;
  date_utc: string;
  minutes_until: number;
  status: "past" | "imminent" | "upcoming";
};

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
// Sessions + kill zones: importados de lib/sessions y lib/killZones — antes
// estaban duplicados línea por línea aquí (dos fuentes de verdad con drift).
const useClockTick = useTick;

function pad2(n: number) { return String(n).padStart(2, "0"); }

function KillZonesPanel() {
  const now = useClockTick(1000);
  const [open, setOpen] = useState(true);
  if (!now) return <div className="kz-section kz-placeholder" aria-hidden />;
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
  if (!now) return <div className="sessions-panel sessions-panel-placeholder" aria-hidden />;
  const madridTime = formatTime(now, "Europe/Madrid");
  const overlap = getOverlapLabel(now);

  return (
    <div className="sessions-panel">
      <div className="sessions-grid">
        {SESSIONS.map((s) => {
          const open = isSessionOpen(now, s);
          const progress = sessionProgress(now, s);
          const time = formatTime(now, s.timezone);
          const madridEquivalent = formatTime(now, "Europe/Madrid");
          const countdown = sessionCountdown(now, s);
          const isNY = s.abbr === "NYC";
          const preopenMin = !open && countdown.minutes <= NY_PREOPEN_ALERT_MIN ? Math.max(0, Math.ceil(countdown.minutes)) : null;
          const nyWarn = isNY && preopenMin !== null && preopenMin > 0;
          return (
            <div
              key={s.abbr}
              className={`session-card ${open ? "session-open" : "session-closed"} ${nyWarn ? "session-warn" : ""}`}
            >
              <div className="session-header">
                <span className={`session-dot ${open ? "dot-open" : nyWarn ? "dot-warn" : "dot-closed"}`} />
                <span className="session-name">{s.name}</span>
                <span className={`session-status ${open ? "status-open" : nyWarn ? "status-warn" : "status-closed"}`}>
                  {open ? "ABIERTO" : nyWarn ? `EN ${preopenMin}m` : "CERRADO"}
                </span>
              </div>
              <div className="session-time">{time}</div>
              <div className="session-madrid-row" title="Hora equivalente en Madrid">
                <span className="session-madrid-tag">MAD</span>
                <span className="session-madrid-time num">{madridEquivalent}</span>
              </div>
              <div className={`session-countdown ${open ? "countdown-close" : nyWarn ? "countdown-warn" : "countdown-open"}`}>
                {nyWarn ? `Empieza en ${preopenMin}m` : countdown.label}
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

type View = "dashboard" | "zones" | "radar" | "stocks" | "correlations" | "playbook" | "sr";


const PRESET_SYMBOLS = [
  "EURUSD", "GBPUSD", "USDCAD", "USDCHF", "AUDUSD", "USDJPY",
];

const ALLOWED_SYMBOLS = new Set(PRESET_SYMBOLS);

function mergeSymbols(apiSymbols: string[]): string[] {
  // Solo dejamos los 6 majors operables. Señales históricas en pares fuera de
  // la lista (XAUUSD, EURJPY, etc.) siguen existiendo en la DB y se ven con
  // filtro "Todos", pero no aparecen como tab/sidebar.
  const seen = new Set<string>();
  const out: string[] = [];
  for (const s of [...apiSymbols, ...PRESET_SYMBOLS]) {
    const k = s.toUpperCase();
    if (ALLOWED_SYMBOLS.has(k) && !seen.has(k)) { seen.add(k); out.push(k); }
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
  // Nuevos campos para scalping M5
  ema9_dist_atr: number | null;
  extended_status: "normal" | "extended" | "skip";
  structure: string;
  struct_bullish: boolean | null;
  cross?: CrossVerdict | null;
};

type DailyBrief = {
  sesgo_dia: string;
  pares_operables: string[];
  pares_excluidos: string[];
  mejor_setup: string;
  correlacion_dominante: string;
};

function Sparkline({ data, side, width = 120, height = 36 }: {
  data: number[];
  side: "LONG" | "SHORT" | "NEUTRAL";
  width?: number;
  height?: number;
}) {
  const uid = useId().replace(/:/g, "");
  if (!data || data.length < 2) {
    return (
      <svg className="spark" width={width} height={height}>
        <rect width={width} height={height} fill="none" />
      </svg>
    );
  }
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
  const fillId = `spark-${side}-${uid}`;
  const lastY = height - ((data[data.length - 1] - min) / rng) * height;
  const firstPt = `0,${height}`;
  const lastPt = `${width},${height}`;
  const areaPts = `${firstPt} ${pts} ${lastPt}`;

  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
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
  const [marketClosed, setMarketClosed] = useState(false);
  const [dataAgeMin, setDataAgeMin] = useState<number | null>(null);

  const VISIBLE_N = 6;

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API}/scanner/pairs`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      setPairs(j.items || []);
      setBrief(j.brief || null);
      setError(j.last_error && (j.items || []).length === 0 ? j.last_error : null);
      setMarketClosed(j.market_closed === true);
      setDataAgeMin(typeof j.data_age_minutes === "number" ? j.data_age_minutes : null);
      setLastUpdate(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error de red");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Pausa el polling cuando el mercado está cerrado para no quemar créditos
  // de Twelve Data. Al refrescar manualmente se reactiva si vuelve a open.
  useEffect(() => {
    if (marketClosed) return;
    const id = setInterval(load, 300000);
    return () => clearInterval(id);
  }, [load, marketClosed]);

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
              Análisis independiente multi-factor (EMA9/21/50, RSI, rango, impulso, estructura) sobre datos M5.
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

      {marketClosed && (
        <div className="zone-polling-paused">
          🌙 Mercado cerrado · polling pausado
          {dataAgeMin != null && <> · última vela hace {formatDataAge(dataAgeMin)}</>}
          <span className="zone-polling-hint">· usa "Refrescar ahora" para forzar actualización</span>
        </div>
      )}

      {brief && <DailyBriefPanel brief={brief} />}

      <div className="zone-controls">
        <div className="zone-tabs">
          <button className={sideFilter === "ALL" ? "tab active" : "tab"} onClick={() => setSideFilter("ALL")}>TODOS</button>
          <button
            className={sideFilter === "B1" ? "tab active" : "tab"}
            onClick={() => setSideFilter("B1")}
            title={`${BLOCK_LEGEND.find(b => b.k === "1")!.name} — ${BLOCK_LEGEND.find(b => b.k === "1")!.def}`}
          >🟢 B1</button>
          <button
            className={sideFilter === "B3" ? "tab active" : "tab"}
            onClick={() => setSideFilter("B3")}
            title={`${BLOCK_LEGEND.find(b => b.k === "3")!.name} — ${BLOCK_LEGEND.find(b => b.k === "3")!.def}`}
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

function formatDataAge(min: number): string {
  const v = Math.max(0, min);
  if (v < 60) return `${Math.round(v)} min`;
  const h = Math.floor(v / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
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

  const extendedLabel =
    data.extended_status === "skip" ? "⚠ SKIP" :
    data.extended_status === "extended" ? "⚠ EXTENDED" : null;

  const structLabel = data.structure !== "RANGE" ? data.structure : null;

  return (
    <article className={`scanner-card scanner-${sideClass} scanner-${strength} ${isTop ? "scanner-top" : ""} ${data.extended_status === "skip" ? "scanner-skip" : data.extended_status === "extended" ? "scanner-extended" : ""}`}>
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
          {structLabel && (
            <span className={`struct-badge struct-${data.struct_bullish === true ? "bull" : data.struct_bullish === false ? "bear" : "neutral"}`}>
              {structLabel}
            </span>
          )}
        </div>
        <Sparkline data={data.spark} side={data.side} />
      </div>

      {data.cross && (
        <div className="scanner-cross-row">
          <CrossBadge cross={data.cross} />
        </div>
      )}

      <div className="scanner-price-row">
        <span className="scanner-price">{data.price}</span>
        <span className={`scanner-change ${changeUp ? "good" : "bad"}`}>
          {changeUp ? "▲" : "▼"} {changeUp ? "+" : ""}{data.change_pct.toFixed(2)}%
        </span>
      </div>

      {extendedLabel && (
        <div className={`scanner-extended-badge ext-${data.extended_status}`}>
          {extendedLabel} {data.ema9_dist_atr != null ? `(${data.ema9_dist_atr.toFixed(1)}× ATR)` : ""}
        </div>
      )}

      <div className="scanner-metas">
        {data.atr != null && (
          <span className="scanner-meta">ATR <b className="num">{data.atr.toFixed(4)}</b></span>
        )}
        {data.ema9_dist_atr != null && (
          <span className="scanner-meta" title="Distancia al EMA9 en multiplos de ATR">EMA9 <b className={`num ${data.extended_status !== "normal" ? "warn" : ""}`}>{data.ema9_dist_atr.toFixed(1)}×</b></span>
        )}
        {data.rsi != null && (
          <span className="scanner-meta">RSI <b className="num">{data.rsi.toFixed(0)}</b></span>
        )}
        <span className="scanner-meta">Rango <b className="num">{(data.range_pos * 100).toFixed(0)}%</b></span>
        <span className="scanner-meta">Bias <b className={data.bias > 0 ? "good" : data.bias < 0 ? "bad" : ""}>{data.bias > 0 ? "+" : ""}{data.bias}</b></span>
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
  const [view, setView] = useState<View>("sr");
  const [items, setItems] = useState<Signal[]>([]);
  const [totalSignals, setTotalSignals] = useState(0);
  const [page, setPage] = useState(1);
  const [stats, setStats] = useState<Stats | null>(null);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [filter, setFilter] = useState<string>("ALL");
  const [loading, setLoading] = useState(true);
  const [newsWarnings, setNewsWarnings] = useState<NewsWarning[]>([]);
  const [openSignals, setOpenSignals] = useState<Signal[]>([]);
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [statusFilter, setStatusFilter] = useState<"all" | "open" | "closed">("all");
  const [activeStockSymbol, setActiveStockSymbol] = useState<string | null>(null);
  const [newsAlertEvent, setNewsAlertEvent] = useState<NewsWarning | null>(null);
  const newsAlertedKeysRef = useRef<Set<string>>(new Set());
  const [nyPreopenModalOpen, setNyPreopenModalOpen] = useState(false);
  const nyTick = useClockTick(1000);
  const [backendDown, setBackendDown] = useState(false);
  const loadAbortRef = useRef<AbortController | null>(null);
  // Alertas de señal nueva (ENTER/WAIT): sonido + Notification, como en Zonas S/R.
  const [signalAlertsOn, setSignalAlertsOn] = useState(false);
  const signalAlertsOnRef = useRef(false);
  const signalAudioRef = useRef<AudioContext | null>(null);
  const seenSignalIdsRef = useRef<Set<number> | null>(null);

  useEffect(() => {
    try {
      const on = localStorage.getItem(SIGNAL_ALERTS_KEY) === "1";
      setSignalAlertsOn(on);
      signalAlertsOnRef.current = on;
    } catch { /* ignore */ }
  }, []);

  // Si quedaron activas de otra sesión, el AudioContext necesita un gesto:
  // se desbloquea en el primer clic de la página.
  useEffect(() => {
    if (!signalAlertsOn || signalAudioRef.current) return;
    const unlock = () => {
      if (!signalAudioRef.current) {
        signalAudioRef.current = createAudioContext();
        signalAudioRef.current?.resume().catch(() => {});
      }
    };
    window.addEventListener("pointerdown", unlock, { once: true });
    return () => window.removeEventListener("pointerdown", unlock);
  }, [signalAlertsOn]);

  const toggleSignalAlerts = useCallback(() => {
    setSignalAlertsOn(prev => {
      const next = !prev;
      signalAlertsOnRef.current = next;
      try { localStorage.setItem(SIGNAL_ALERTS_KEY, next ? "1" : "0"); } catch { /* ignore */ }
      if (next) {
        // Activación = gesto de usuario: desbloquea audio y pide permiso de notificación.
        if (!signalAudioRef.current) signalAudioRef.current = createAudioContext();
        signalAudioRef.current?.resume().catch(() => {});
        if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "default") {
          Notification.requestPermission().catch(() => {});
        }
      }
      return next;
    });
  }, []);

  const alertNewSignals = useCallback((all: Signal[]) => {
    const ids = new Set(all.map(s => s.id));
    const prev = seenSignalIdsRef.current;
    seenSignalIdsRef.current = ids;
    if (prev === null) return; // baseline al montar, sin alertar
    if (!signalAlertsOnRef.current) return;
    for (const s of all) {
      if (prev.has(s.id)) continue;
      const d = s.response.decision;
      if (d !== "ENTER" && d !== "WAIT") continue;
      const side: "LONG" | "SHORT" =
        (s.signal.signal === "LONG" || s.signal.signal === "BUY") ? "LONG" : "SHORT";
      const ctx = signalAudioRef.current;
      if (ctx) { ctx.resume().catch(() => {}); playChime(ctx, side); }
      const tp = s.response.take_profit?.length
        ? s.response.take_profit[s.response.take_profit.length - 1]
        : null;
      sendNotification(
        `${d === "ENTER" ? "🚨 ENTER" : "⏳ WAIT"} ${side} · ${s.signal.symbol}`,
        [
          `Precio ${s.signal.price}`,
          s.response.stop_loss != null ? `SL ${s.response.stop_loss}` : null,
          tp != null ? `TP ${tp}` : null,
          s.response.plan ? `Plan ${s.response.plan.trigger_type}` : null,
        ].filter(Boolean).join("  |  "),
        `signal-${s.id}`,
      );
    }
  }, []);

  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(NEWS_ALERTED_KEY) || "[]";
      const arr: string[] = JSON.parse(stored);
      newsAlertedKeysRef.current = new Set(arr);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (!newsWarnings.length || newsAlertEvent) return;
    const candidate = newsWarnings.find(w =>
      w.minutes_until <= NEWS_ALERT_THRESHOLD_MIN &&
      w.minutes_until >= -NEWS_ALERT_LINGER_MIN &&
      !newsAlertedKeysRef.current.has(newsKey(w))
    );
    if (!candidate) return;
    const k = newsKey(candidate);
    newsAlertedKeysRef.current.add(k);
    try {
      sessionStorage.setItem(NEWS_ALERTED_KEY, JSON.stringify([...newsAlertedKeysRef.current]));
    } catch { /* ignore */ }
    setNewsAlertEvent(candidate);
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      try {
        const mins = Math.max(0, candidate.minutes_until);
        new Notification(`Noticia ${candidate.country} en ${mins} min`, {
          body: candidate.title,
          tag: k,
        });
      } catch { /* ignore */ }
    }
  }, [newsWarnings, newsAlertEvent]);

  useEffect(() => {
    if (!nyTick) return;
    const ny = SESSIONS.find(s => s.abbr === "NYC");
    if (!ny) return;
    if (isSessionOpen(nyTick, ny)) return;
    const { minutes } = sessionCountdown(nyTick, ny);
    if (minutes > NY_PREOPEN_ALERT_MIN || minutes <= 0) return;
    const today = nyTick.toISOString().slice(0, 10);
    let shownToday = false;
    try {
      shownToday = localStorage.getItem(NY_PREOPEN_MODAL_KEY) === today;
    } catch { /* ignore */ }
    if (shownToday) return;
    try { localStorage.setItem(NY_PREOPEN_MODAL_KEY, today); } catch { /* ignore */ }
    setNyPreopenModalOpen(true);
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      try {
        new Notification("Sesión NY en 15 min", {
          body: "Prepárate: la sesión de New York abre en menos de 15 minutos.",
          tag: `ny-preopen-${today}`,
        });
      } catch { /* ignore */ }
    }
  }, [nyTick]);

  useEffect(() => {
    const saved = (typeof window !== "undefined" && localStorage.getItem("theme")) as "dark" | "light" | null;
    const initial = saved === "light" || saved === "dark" ? saved : "dark";
    setTheme(initial);
    document.documentElement.setAttribute("data-theme", initial);
  }, []);

  // Persistencia del ticker activo de stocks (compartido entre Sidebar y Dashboard).
  useEffect(() => {
    try {
      const saved = localStorage.getItem("tradingapp:stocks_last_ticker");
      if (saved) setActiveStockSymbol(saved);
    } catch { /* ignore */ }
  }, []);
  useEffect(() => {
    try {
      if (activeStockSymbol) localStorage.setItem("tradingapp:stocks_last_ticker", activeStockSymbol);
    } catch { /* ignore */ }
  }, [activeStockSymbol]);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch {}
  };

  const totalPages = Math.max(1, Math.ceil(totalSignals / PAGE_SIZE));

  const lastSlowFetchRef = useRef(0);

  const load = useCallback(async (force = false) => {
    // Pestaña oculta: no quemar red ni re-renders (se reanuda al volver).
    if (!force && typeof document !== "undefined" && document.visibilityState === "hidden") return;
    // Un solo load en vuelo: con cold start de Render (30-50s) el interval de
    // 5s apilaba requests que podían resolver fuera de orden.
    if (loadAbortRef.current) loadAbortRef.current.abort();
    const ctrl = new AbortController();
    loadAbortRef.current = ctrl;
    const get = async (url: string) => {
      const r = await fetch(url, { cache: "no-store", signal: ctrl.signal });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    };
    try {
      const offset = (page - 1) * PAGE_SIZE;
      const symParam = filter === "ALL" ? "" : `&symbol=${filter}`;
      // /stats y /symbols cambian lento → cada ~60s (o con force), no cada 5s.
      const includeSlow = force || Date.now() - lastSlowFetchRef.current > 55_000;
      const slow = includeSlow
        ? Promise.all([get(`${API}/stats`), get(`${API}/symbols`)])
        : null;
      // Si el Promise.all rápido lanza (p.ej. abort del siguiente load), el
      // `await slow` de abajo nunca se alcanza y su rechazo quedaría unhandled
      // (overlay de error en dev). Este catch lateral lo marca como manejado
      // sin afectar al await del try.
      slow?.catch(() => {});
      const [signalsData, nj, oj] = await Promise.all([
        get(`${API}/signals?limit=${PAGE_SIZE}&offset=${offset}${symParam}`),
        get(`${API}/news/warnings`),
        get(`${API}/signals?limit=50`),
      ]);
      setItems(signalsData.items || []);
      setTotalSignals(signalsData.total || 0);
      setNewsWarnings(nj.warnings || []);
      const allItems: Signal[] = oj.items || [];
      setOpenSignals(allItems.filter(s => s.result == null));
      alertNewSignals(allItems);
      if (slow) {
        const [statsData, symbolsData] = await slow;
        setStats(statsData);
        setSymbols(mergeSymbols(symbolsData));
        lastSlowFetchRef.current = Date.now();
      }
      setBackendDown(false);
    } catch (e) {
      if ((e as { name?: string })?.name === "AbortError") return;
      // Conserva el último estado bueno — un blip de red no debe vaciar el
      // dashboard ni mostrar "Sin operaciones todavía".
      setBackendDown(true);
    } finally {
      setLoading(false);
    }
  }, [filter, page, alertNewSignals]);

  useEffect(() => {
    load(true);
    const id = setInterval(() => load(), 5000);
    const onVis = () => {
      if (document.visibilityState === "visible") load(true);
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [load]);

  // SSE: una señal nueva dispara load inmediato (latencia ~2s en vez de 0-5s).
  // Si la conexión cae (cold start, proxy), EventSource reconecta solo y el
  // polling de 5s sigue siendo la red de seguridad.
  const loadRef = useRef(load);
  useEffect(() => { loadRef.current = load; }, [load]);
  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API}/signals/stream`);
    } catch {
      return;
    }
    const onSignal = () => loadRef.current(true);
    es.addEventListener("signal", onSignal);
    return () => { es?.close(); };
  }, []);

  const deleteSignal = (id: number) => {
    setConfirmDialog({
      title: "Eliminar señal",
      message: "Vas a eliminar esta señal del historial. Esta acción no se puede deshacer.",
      confirmLabel: "Eliminar",
      itemHint: `Señal #${id}`,
      onConfirm: async () => {
        await fetch(`${API}/signals/${id}`, { method: "DELETE" });
        load();
      },
    });
  };

  const deleteAllSignals = () => {
    const scopeLabel = filter === "ALL" ? "todas las señales" : `todas las señales de ${filter}`;
    setConfirmDialog({
      title: filter === "ALL" ? "Eliminar todo el historial" : `Eliminar señales de ${filter}`,
      message: `Vas a eliminar ${scopeLabel} (${totalSignals} ${totalSignals === 1 ? "registro" : "registros"}). Esta acción no se puede deshacer.`,
      confirmLabel: "Eliminar todas",
      itemHint: filter === "ALL" ? `${totalSignals} señales` : `${filter} · ${totalSignals} señales`,
      onConfirm: async () => {
        const qs = filter === "ALL" ? "" : `?symbol=${encodeURIComponent(filter)}`;
        await fetch(`${API}/signals${qs}`, { method: "DELETE" });
        setPage(1);
        load();
      },
    });
  };

  return (
    <AppShell
      topbar={
        <Topbar
          view={view}
          onViewChange={setView}
          onRefresh={() => load(true)}
          theme={theme}
          onThemeToggle={toggleTheme}
          signalAlertsOn={signalAlertsOn}
          onToggleSignalAlerts={toggleSignalAlerts}
        />
      }
      sidebar={
        <Sidebar
          context={view === "stocks" ? "stocks" : "forex"}
          symbols={symbols}
          filter={filter}
          onFilterChange={(s) => { setFilter(s); setPage(1); }}
          stocksActiveSymbol={activeStockSymbol}
          onStocksSelect={(s) => { setActiveStockSymbol(s); setView("stocks"); }}
        />
      }
      rightbar={
        <RightBar
          context={view === "stocks" ? "stocks" : "forex"}
          openSignals={openSignals.map(it => ({
            id: it.id,
            received_at: it.received_at,
            signal: { symbol: it.signal.symbol, signal: it.signal.signal, price: it.signal.price },
            response: { decision: it.response.decision },
            pnl: it.pnl,
          }))}
          openCount={stats?.open ?? openSignals.length}
          totalSignals={stats?.total_signals ?? totalSignals}
          onPairClick={(p) => { setFilter(p); setPage(1); }}
          stocksActiveSymbol={activeStockSymbol}
          onStocksSelect={(s) => { setActiveStockSymbol(s); setView("stocks"); }}
        />
      }
      main={
        <div className="legacy-main-pad">
      {view !== "stocks" && <VerdictStrip />}
      {backendDown && (
        <div
          role="alert"
          style={{
            padding: "8px 14px",
            marginBottom: 10,
            borderRadius: 8,
            border: "1px solid rgba(245, 158, 11, 0.45)",
            background: "rgba(245, 158, 11, 0.10)",
            color: "var(--warn, #fb923c)",
            fontSize: 13,
          }}
        >
          ⚠ El backend no responde — mostrando los últimos datos conocidos (reintentando cada 5s…)
        </div>
      )}
      {view !== "stocks" && view !== "correlations" && view !== "playbook" && view !== "sr" && (
        <NewsAlertBar
          warnings={newsWarnings}
          thresholdMin={NEWS_ALERT_THRESHOLD_MIN}
          lingerMin={NEWS_ALERT_LINGER_MIN}
        />
      )}

      {view !== "stocks" && view !== "correlations" && view !== "playbook" && view !== "sr" && <NYPreOpenBanner />}

      {view !== "stocks" && view !== "correlations" && view !== "playbook" && view !== "sr" && <SessionsPanel />}

      {view !== "stocks" && view !== "correlations" && view !== "playbook" && view !== "sr" && <SessionsTimeline />}

      {view !== "stocks" && view !== "correlations" && view !== "playbook" && view !== "sr" && newsWarnings.length > 0 && (
        <div className="news-banner">
          {newsWarnings.map((w, i) => (
            <NewsBannerItem key={`${w.date_utc}-${i}`} warning={w} />
          ))}
        </div>
      )}

      {view === "sr" ? (
        <ZonasSRView />
      ) : view === "zones" ? (
        <ZoneAnalysisView />
      ) : view === "stocks" ? (
        <StocksView
          activeSymbol={activeStockSymbol}
          onSymbolChange={setActiveStockSymbol}
        />
      ) : view === "correlations" ? (
        <CorrelationsView />
      ) : view === "playbook" ? (
        <PlaybookView />
      ) : (
      <>
      {stats && (
        <>
          <KpiHero
            totalSignals={stats.total_signals}
            closed={stats.closed}
            open={stats.open}
            overall={stats.overall}
            taken={stats.overall_taken ?? EMPTY_AGG}
            executionRate={stats.execution_rate ?? 0}
          />
          <EquityCurve />
        </>
      )}

      {stats && stats.closed > 0 && (
        <div className="breakdowns">
          <Breakdown title="Por símbolo" data={(stats as any).by_symbol || {}} />
          <Breakdown title="Por decisión" data={stats.by_decision} />
          <Breakdown title="Por fuente" data={stats.by_source} />
          <Breakdown title="Por calidad" data={stats.by_quality} />
        </div>
      )}

      <section className="table-card">
        <div className="table-header-row">
          <div className="table-title-block">
            <div className="chart-title">Operaciones</div>
            <div className="table-subtitle">
              {filter === "ALL" ? "Todos los pares" : <span className="num">{filter}</span>}
              {" · "}
              <span className="num">{totalSignals}</span> señales
            </div>
          </div>
          <div className="table-actions">
            <div className="chart-toggle" role="tablist">
              <button
                role="tab"
                aria-selected={statusFilter === "all"}
                className={statusFilter === "all" ? "active" : ""}
                onClick={() => setStatusFilter("all")}
              >Todas</button>
              <button
                role="tab"
                aria-selected={statusFilter === "open"}
                className={statusFilter === "open" ? "active" : ""}
                onClick={() => setStatusFilter("open")}
              >Activas</button>
              <button
                role="tab"
                aria-selected={statusFilter === "closed"}
                className={statusFilter === "closed" ? "active" : ""}
                onClick={() => setStatusFilter("closed")}
              >Cerradas</button>
            </div>
            {totalSignals > 0 && (
              <button
                className="table-delete-btn"
                onClick={deleteAllSignals}
                title={filter === "ALL" ? "Eliminar todas las señales" : `Eliminar todas las señales de ${filter}`}
                aria-label="Eliminar señales"
              >🗑</button>
            )}
          </div>
        </div>

        {loading && items.length === 0 ? (
          <div className="empty">Cargando…</div>
        ) : items.filter(it =>
            statusFilter === "all" ? true :
            statusFilter === "open" ? it.result == null :
            it.result != null
          ).length === 0 ? (
          <div className="empty">
            {items.length === 0
              ? "Sin operaciones todavía. Las señales aparecerán acá cuando se ejecuten."
              : statusFilter === "open" ? "Sin señales activas en esta página"
              : "Sin señales cerradas en esta página"}
          </div>
        ) : (
        <table className="dashboard-table">
          <thead>
            <tr>
              <th>Hora</th>
              <th>Símbolo</th>
              <th>Lado</th>
              <th className="right">Precio</th>
              <th className="right">SL</th>
              <th className="right">TP</th>
              <th className="right">Conf</th>
              <th>Calidad</th>
              <th>MTF</th>
              <th>Zona</th>
              <th>Decisión</th>
              <th>Razón</th>
              <th>Resultado</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.filter(it =>
                statusFilter === "all" ? true :
                statusFilter === "open" ? it.result == null :
                it.result != null
              ).map((it) => {
              const isOpen = it.result == null;
              const sideClassName = (it.signal.signal === "LONG" || it.signal.signal === "BUY")
                ? "side-buy"
                : (it.signal.signal === "SHORT" || it.signal.signal === "SELL")
                ? "side-sell"
                : "side-neutral";
              return (
              <tr key={it.id} className={isOpen ? "row-open" : "row-closed"}>
                <td className="num td-time">{new Date(it.received_at).toLocaleTimeString()}</td>
                <td className="num td-symbol"><strong>{it.signal.symbol}</strong></td>
                <td><span className={`side-pill ${sideClassName}`}>{it.signal.signal}</span></td>
                <td className="right num">{it.signal.price}</td>
                <td className="right num" style={{ color: "var(--sell, #ef4444)" }}>
                  {it.response.stop_loss ?? "—"}
                </td>
                <td className="right num" style={{ color: "var(--buy, #22c55e)" }}>
                  {it.response.take_profit?.length
                    ? Array.from(new Set(it.response.take_profit)).join(" / ")
                    : "—"}
                </td>
                <td className="right num">{it.signal.conf}/19</td>
                <td>{it.signal.quality}</td>
                <td>{it.signal.mtf}</td>
                <td>
                  <span className={`zona-chip zona-${zonaClass(it.signal.zona ?? "")}`} title={zonaTooltip(it.signal.zona ?? "", it.signal.signal)}>
                    {it.signal.zona ?? "—"}
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
                        {it.response.plan.expires_after != null && it.response.plan.expires_after > 0 && (
                          <> · Vigencia: <b>{it.response.plan.expires_after} velas M5</b></>
                        )}
                      </div>
                      <div className="plan-text">{it.response.plan.instructions}</div>
                    </div>
                  )}
                </td>
                <td>
                  {/* El flujo W/L/BE + journal fue retirado de la UI (el usuario
                      ya no marca resultados). Los badges históricos se conservan. */}
                  {it.result ? (
                    <div className="result-cell">
                      <span className={`badge ${it.result}`}>
                        {it.result} {it.pnl != null && `(${it.pnl >= 0 ? "+" : ""}${it.pnl.toFixed(1)})`}
                      </span>
                      {it.taken === "yes" && <span className="taken-badge exec">EJEC</span>}
                      {it.taken === "no" && <span className="taken-badge rated">CAL</span>}
                    </div>
                  ) : (
                    <span className="num" style={{ opacity: 0.4 }}>—</span>
                  )}
                </td>
                <td>
                  <button
                    className="btn-delete-row"
                    onClick={() => deleteSignal(it.id)}
                    title="Eliminar esta señal"
                    aria-label="Eliminar señal"
                  >✕</button>
                </td>
              </tr>
            );})}
          </tbody>
        </table>
        )}
      </section>

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

      {confirmDialog && (
        <ConfirmModal
          state={confirmDialog}
          onClose={() => setConfirmDialog(null)}
        />
      )}

      {newsAlertEvent && (
        <NewsAlertModal
          event={newsAlertEvent}
          onClose={() => setNewsAlertEvent(null)}
        />
      )}

      {nyPreopenModalOpen && (
        <NYPreOpenModal onClose={() => setNyPreopenModalOpen(false)} />
      )}
        </div>
      }
    />
  );
}

function ConfirmModal({
  state, onClose,
}: {
  state: ConfirmDialogState;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  const handleConfirm = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await state.onConfirm();
      onClose();
    } catch (e) {
      setBusy(false);
      console.error(e);
    }
  };

  return (
    <div className="modal-overlay" onClick={busy ? undefined : onClose}>
      <div className="modal modal-confirm" onClick={(e) => e.stopPropagation()}>
        <div className="modal-confirm-icon-wrap">
          <div className="modal-confirm-icon">🗑</div>
        </div>
        <div className="modal-confirm-body">
          <h3 className="modal-confirm-title">{state.title}</h3>
          <p className="modal-confirm-message">{state.message}</p>
          {state.itemHint && (
            <div className="modal-confirm-hint">
              <span className="modal-confirm-hint-dot" />
              {state.itemHint}
            </div>
          )}
        </div>
        <div className="modal-confirm-foot">
          <button
            className="modal-btn modal-btn-cancel"
            onClick={onClose}
            disabled={busy}
          >
            Cancelar
          </button>
          <button
            className="modal-btn modal-btn-danger"
            onClick={handleConfirm}
            disabled={busy}
            autoFocus
          >
            {busy ? "Eliminando…" : state.confirmLabel}
          </button>
        </div>
      </div>
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

function NewsAlertBar({
  warnings, thresholdMin, lingerMin,
}: {
  warnings: NewsWarning[];
  thresholdMin: number;
  lingerMin: number;
}) {
  const tick = useTick(30_000);
  if (!warnings.length) return null;
  const now = (tick ?? new Date()).getTime();

  const live = warnings
    .map(w => ({
      ...w,
      _liveMin: Math.round((new Date(w.date_utc).getTime() - now) / 60_000),
    }))
    .filter(w => w._liveMin <= thresholdMin && w._liveMin >= -lingerMin)
    .sort((a, b) => a._liveMin - b._liveMin);

  if (live.length === 0) return null;
  const closest = live[0];
  const m = closest._liveMin;
  const isLive = m <= 0;
  const isImminent = m > 0 && m <= 5;
  const status = isLive
    ? `EN CURSO · hace ${Math.abs(m)} min`
    : isImminent
    ? `INMINENTE · ${m} min`
    : `EN ${m} MIN`;
  const extra = live.length > 1 ? ` · +${live.length - 1} más` : "";
  const hhmm = new Date(closest.date_utc).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div
      className={`news-alert-bar ${isLive ? "is-live" : isImminent ? "is-imminent" : ""}`}
      role="alert"
      aria-live="assertive"
    >
      <span className="news-alert-pulse" aria-hidden="true" />
      <span className="news-alert-icon" aria-hidden="true">⚠</span>
      <span className="news-alert-tag">ALERTA NOTICIA</span>
      <span className="news-alert-country">{closest.country}</span>
      <span className="news-alert-title">{closest.title}</span>
      <span className="news-alert-time">{hhmm}</span>
      <span className="news-alert-status">{status}{extra}</span>
    </div>
  );
}

function NewsAlertModal({
  event, onClose,
}: {
  event: NewsWarning;
  onClose: () => void;
}) {
  const tick = useTick(1000);
  const now = (tick ?? new Date()).getTime();
  const target = new Date(event.date_utc).getTime();
  const diffSec = Math.round((target - now) / 1000);
  const inProgress = diffSec <= 0;
  const remainingSec = Math.max(0, diffSec);
  const mm = String(Math.floor(remainingSec / 60)).padStart(2, "0");
  const ss = String(remainingSec % 60).padStart(2, "0");
  const passedMin = inProgress ? Math.max(0, Math.round(-diffSec / 60)) : 0;
  const hhmm = new Date(event.date_utc).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal modal-news-alert"
        onClick={(e) => e.stopPropagation()}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="news-alert-title"
      >
        <div className="news-alert-modal-icon" aria-hidden="true">⚠</div>
        <div className="news-alert-modal-tag">ALERTA NOTICIA HIGH-IMPACT</div>
        <h3 id="news-alert-title" className="news-alert-modal-title">{event.title}</h3>
        <div className="news-alert-modal-meta">
          <span className="news-alert-modal-country">{event.country}</span>
          <span className="news-alert-modal-time">{hhmm}</span>
        </div>
        <div className="news-alert-modal-countdown">
          {inProgress ? (
            <>
              <div className="num">EN CURSO</div>
              <div className="news-alert-modal-sub">hace {passedMin} min</div>
            </>
          ) : (
            <>
              <div className="num">{mm}:{ss}</div>
              <div className="news-alert-modal-sub">para el evento</div>
            </>
          )}
        </div>
        <div className="news-alert-modal-foot">
          <button
            className="modal-btn modal-btn-danger"
            onClick={onClose}
            autoFocus
          >
            Entendido
          </button>
        </div>
      </div>
    </div>
  );
}

function NYPreOpenBanner() {
  const now = useClockTick(1000);
  if (!now) return null;
  const ny = SESSIONS.find(s => s.abbr === "NYC");
  if (!ny) return null;
  if (isSessionOpen(now, ny)) return null;
  const { minutes } = sessionCountdown(now, ny);
  if (minutes > NY_PREOPEN_ALERT_MIN || minutes <= 0) return null;

  const totalSec = Math.max(0, Math.floor(minutes * 60));
  const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  const isImminent = minutes <= 5;
  const madridTime = formatTime(now, "Europe/Madrid");

  return (
    <div
      className={`ny-preopen-banner ${isImminent ? "is-imminent" : ""}`}
      role="alert"
      aria-live="polite"
    >
      <span className="ny-preopen-pulse" aria-hidden="true" />
      <span className="ny-preopen-icon" aria-hidden="true">🗽</span>
      <span className="ny-preopen-tag">PRE-OPEN NY</span>
      <span className="ny-preopen-title">
        Sesión de New York abre en menos de {NY_PREOPEN_ALERT_MIN} min
      </span>
      <span className="ny-preopen-madrid">Madrid <span className="num">{madridTime}</span></span>
      <span className="ny-preopen-countdown num">{mm}:{ss}</span>
    </div>
  );
}

function NYPreOpenModal({ onClose }: { onClose: () => void }) {
  const tick = useClockTick(1000);
  const now = tick ?? new Date();
  const ny = SESSIONS.find(s => s.abbr === "NYC")!;
  const { minutes } = sessionCountdown(now, ny);
  const totalSec = Math.max(0, Math.floor(minutes * 60));
  const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  const madridTime = formatTime(now, "Europe/Madrid");
  const nyTime = formatTime(now, "America/New_York");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal modal-ny-preopen"
        onClick={(e) => e.stopPropagation()}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="ny-preopen-title"
      >
        <div className="ny-preopen-modal-icon" aria-hidden="true">🗽</div>
        <div className="ny-preopen-modal-tag">PRE-OPEN NEW YORK</div>
        <h3 id="ny-preopen-title" className="ny-preopen-modal-title">
          Sesión NY abre en menos de {NY_PREOPEN_ALERT_MIN} minutos
        </h3>
        <div className="ny-preopen-modal-meta">
          <span className="ny-preopen-modal-pill">
            <span className="ny-preopen-modal-pill-label">MAD</span>
            <span className="num">{madridTime}</span>
          </span>
          <span className="ny-preopen-modal-pill">
            <span className="ny-preopen-modal-pill-label">NYC</span>
            <span className="num">{nyTime}</span>
          </span>
        </div>
        <div className="ny-preopen-modal-countdown">
          <div className="num">{mm}:{ss}</div>
          <div className="ny-preopen-modal-sub">para la apertura</div>
        </div>
        <div className="ny-preopen-modal-hint">
          Revisá radar y zonas. El overlap LDN+NYC es la mejor ventana del día.
        </div>
        <div className="ny-preopen-modal-foot">
          <button
            className="modal-btn modal-btn-danger"
            onClick={onClose}
            autoFocus
          >
            Entendido
          </button>
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
