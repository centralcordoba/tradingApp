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
};

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

  const load = useCallback(async () => {
    try {
      const url = filter === "ALL" ? `${API}/signals?limit=100` : `${API}/signals?limit=100&symbol=${filter}`;
      const [sR, stR, syR] = await Promise.all([
        fetch(url, { cache: "no-store" }),
        fetch(`${API}/stats`, { cache: "no-store" }),
        fetch(`${API}/symbols`, { cache: "no-store" }),
      ]);
      setItems(await sR.json());
      setStats(await stR.json());
      setSymbols(await syR.json());
    } catch {
      setItems([]);
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  const mark = async (id: number, result: "WIN" | "LOSS" | "BE") => {
    await fetch(`${API}/signals/${id}/result`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ result }),
    });
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
                      <button className="btn-win"  onClick={() => mark(it.id, "WIN")}>W</button>
                      <button className="btn-loss" onClick={() => mark(it.id, "LOSS")}>L</button>
                      <button className="btn-be"   onClick={() => mark(it.id, "BE")}>BE</button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
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
