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
  journal_respected_plan?: string | null;
  journal_closed_early?: string | null;
  journal_emotion?: string | null;
};

type Emotion = "confianza" | "miedo" | "fomo" | "venganza";
type JournalDraft = {
  signalId: number;
  result: "WIN" | "LOSS" | "BE";
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
  by_decision: Record<string, Agg>;
  by_source: Record<string, Agg>;
  by_quality: Record<string, Agg>;
};

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
    setJournal({ signalId: id, result, respected_plan: null, closed_early: null, emotion: null });
  };

  const submitJournal = async (skip: boolean) => {
    if (!journal) return;
    const body: Record<string, unknown> = { result: journal.result };
    if (!skip) {
      if (journal.respected_plan) body.journal_respected_plan = journal.respected_plan;
      if (journal.closed_early) body.journal_closed_early = journal.closed_early;
      if (journal.emotion) body.journal_emotion = journal.emotion;
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

      {newsWarnings.length > 0 && (
        <div className="news-banner">
          {newsWarnings.map((w, i) => (
            <NewsBannerItem key={`${w.date_utc}-${i}`} warning={w} />
          ))}
        </div>
      )}

      {stats && (
        <div className="stats">
          <StatCard label="Total" value={stats.total_signals} />
          <StatCard label="Cerradas" value={stats.closed} />
          <StatCard label="Abiertas" value={stats.open} />
          <StatCard label="Win rate" value={`${(stats.overall.win_rate * 100).toFixed(0)}%`} accent />
          <StatCard label={`W/L/BE`} value={`${stats.overall.wins}/${stats.overall.losses}/${stats.overall.be}`} />
          <StatCard label="PnL ($)" value={stats.overall.pnl.toFixed(2)} accent={stats.overall.pnl >= 0 ? "good" : "bad"} />
        </div>
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
                <td>{it.signal.zona}</td>
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
                    <span className={`badge ${it.result}`}>
                      {it.result} {it.pnl != null && `(${it.pnl >= 0 ? "+" : ""}${it.pnl.toFixed(1)})`}
                    </span>
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
          onSave={() => submitJournal(false)}
          onSkip={() => submitJournal(true)}
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
  draft, onChange, onSave, onSkip, onClose,
}: {
  draft: JournalDraft;
  onChange: (d: JournalDraft) => void;
  onSave: () => void;
  onSkip: () => void;
  onClose: () => void;
}) {
  const emotions: { key: Emotion; label: string; color: string }[] = [
    { key: "confianza", label: "Confianza", color: "#4ade80" },
    { key: "miedo",     label: "Miedo",     color: "#60a5fa" },
    { key: "fomo",      label: "FOMO",      color: "#facc15" },
    { key: "venganza",  label: "Venganza",  color: "#f87171" },
  ];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <span className={`badge ${draft.result}`}>{draft.result}</span>
            <span className="modal-title">Post-mortem del trade</span>
          </div>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
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
        </div>

        <div className="modal-foot">
          <button className="modal-skip" onClick={onSkip}>Saltar</button>
          <button className="modal-save" onClick={onSave}>Guardar</button>
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

function Breakdown({ title, data }: { title: string; data: Record<string, Agg> }) {
  const keys = Object.keys(data);
  if (!keys.length) return null;
  return (
    <div className="breakdown">
      <h3>{title}</h3>
      <table>
        <thead><tr><th></th><th>N</th><th>WR</th><th>PnL</th></tr></thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k}>
              <td>{k}</td>
              <td>{data[k].n}</td>
              <td>{(data[k].win_rate * 100).toFixed(0)}%</td>
              <td className={data[k].pnl >= 0 ? "good" : "bad"}>{data[k].pnl.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
