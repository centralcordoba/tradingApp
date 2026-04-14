"use client";
import { useEffect, useState, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Signal = {
  id: number;
  received_at: string;
  signal: {
    signal: string;
    symbol: string;
    price: number;
    conf: number;
    quality: string;
    mtf: string;
    zona: string;
    pattern: string;
    rsi: number;
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

export default function Home() {
  const [items, setItems] = useState<Signal[]>([]);
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

  const load = useCallback(async () => {
    try {
      const url = filter === "ALL" ? `${API}/signals?limit=100` : `${API}/signals?limit=100&symbol=${filter}`;
      const [sR, stR, syR, nR] = await Promise.all([
        fetch(url, { cache: "no-store" }),
        fetch(`${API}/stats`, { cache: "no-store" }),
        fetch(`${API}/symbols`, { cache: "no-store" }),
        fetch(`${API}/news/warnings`, { cache: "no-store" }),
      ]);
      setItems(await sR.json());
      setStats(await stR.json());
      setSymbols(await syR.json());
      const nj = await nR.json();
      setNewsWarnings(nj.warnings || []);
    } catch {
      setItems([]);
      setStats(null);
      setNewsWarnings([]);
    } finally {
      setLoading(false);
    }
  }, [filter]);

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

      <SessionsPanel />
      <KillZonesPanel />

      {newsWarnings.length > 0 && (
        <div className="news-banner">
          {newsWarnings.map((w, i) => (
            <NewsBannerItem key={`${w.date_utc}-${i}`} warning={w} />
          ))}
        </div>
      )}

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
        <button className={filter === "ALL" ? "tab active" : "tab"} onClick={() => setFilter("ALL")}>TODOS</button>
        {symbols.map((s) => (
          <button key={s} className={filter === s ? "tab active" : "tab"} onClick={() => setFilter(s)}>{s}</button>
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
