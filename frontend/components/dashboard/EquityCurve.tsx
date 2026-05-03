"use client";

import { useEffect, useMemo, useState } from "react";
import { API } from "@/lib/api";
import "./EquityCurve.css";

type Range = "1D" | "7D" | "30D" | "ALL";

type ClosedSignal = {
  id: number;
  received_at: string;
  closed_at?: string | null;
  pnl: number | null;
  result: "WIN" | "LOSS" | "BE" | null;
};

type Point = { t: number; cum: number; pnl: number };

const RANGE_DAYS: Record<Range, number | null> = {
  "1D": 1,
  "7D": 7,
  "30D": 30,
  "ALL": null,
};

function buildSeries(rows: ClosedSignal[]): Point[] {
  const closed = rows
    .filter(r => r.pnl != null && r.result != null)
    .map(r => ({
      t: new Date(r.closed_at || r.received_at).getTime(),
      pnl: r.pnl as number,
    }))
    .filter(p => !isNaN(p.t))
    .sort((a, b) => a.t - b.t);
  let cum = 0;
  return closed.map(p => {
    cum += p.pnl;
    return { t: p.t, cum, pnl: p.pnl };
  });
}

function filterRange(series: Point[], range: Range): Point[] {
  const days = RANGE_DAYS[range];
  if (days == null) return series;
  const cutoff = Date.now() - days * 24 * 3600 * 1000;
  return series.filter(p => p.t >= cutoff);
}

function buildPath(points: Point[], width: number, height: number): { line: string; area: string } {
  if (points.length === 0) return { line: "", area: "" };
  const ts = points.map(p => p.t);
  const minT = ts[0];
  const maxT = ts[ts.length - 1];
  const spanT = Math.max(1, maxT - minT);

  const cums = points.map(p => p.cum);
  const minC = Math.min(0, ...cums);
  const maxC = Math.max(0, ...cums);
  const spanC = Math.max(1, maxC - minC);

  const x = (t: number) => points.length === 1 ? width / 2 : ((t - minT) / spanT) * width;
  const y = (c: number) => height - ((c - minC) / spanC) * height;

  const segs = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t).toFixed(1)},${y(p.cum).toFixed(1)}`);
  const line = segs.join(" ");

  const first = points[0];
  const last = points[points.length - 1];
  const area = `${line} L${x(last.t).toFixed(1)},${height} L${x(first.t).toFixed(1)},${height} Z`;
  return { line, area };
}

export function EquityCurve() {
  const [range, setRange] = useState<Range>("7D");
  const [rows, setRows] = useState<ClosedSignal[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const fetchRows = async () => {
      try {
        const r = await fetch(`${API}/signals?limit=500`, { cache: "no-store" });
        const j = await r.json();
        if (alive) setRows(j.items || []);
      } catch {
        if (alive) setRows([]);
      } finally {
        if (alive) setLoading(false);
      }
    };
    fetchRows();
    const id = setInterval(fetchRows, 30_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const allSeries = useMemo(() => buildSeries(rows), [rows]);
  const series = useMemo(() => filterRange(allSeries, range), [allSeries, range]);

  const { line, area } = useMemo(
    () => buildPath(series, 800, 140),
    [series],
  );

  const lastCum = series.length > 0 ? series[series.length - 1].cum : 0;
  const positive = lastCum >= 0;

  return (
    <section className="chart-card" aria-label="Curva de equidad">
      <div className="chart-header">
        <div className="chart-title-block">
          <div className="chart-title">Equity Curve</div>
          <div className="chart-subtitle">
            <span className={`chart-cum num ${positive ? "pl-up" : "pl-down"}`}>
              {positive ? "+" : ""}{lastCum.toFixed(2)}
            </span>
            <span className="chart-trades">· <span className="num">{series.length}</span> trades</span>
          </div>
        </div>
        <div className="chart-toggle" role="tablist">
          {(["1D", "7D", "30D", "ALL"] as Range[]).map(r => (
            <button
              key={r}
              role="tab"
              aria-selected={range === r}
              className={range === r ? "active" : ""}
              onClick={() => setRange(r)}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="chart-empty"><span>Cargando…</span></div>
      ) : series.length === 0 ? (
        <div className="chart-empty"><span>Sin trades cerrados en este rango</span></div>
      ) : (
        <svg className="chart-svg" viewBox="0 0 800 140" preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <linearGradient id="equityGradient" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%"   stopColor={positive ? "#22C55E" : "#EF4444"} stopOpacity="0.25"/>
              <stop offset="100%" stopColor={positive ? "#22C55E" : "#EF4444"} stopOpacity="0"/>
            </linearGradient>
          </defs>
          <line x1="0" y1="35"  x2="800" y2="35"  stroke="var(--border-subtle)" strokeDasharray="2,4"/>
          <line x1="0" y1="70"  x2="800" y2="70"  stroke="var(--border-subtle)" strokeDasharray="2,4"/>
          <line x1="0" y1="105" x2="800" y2="105" stroke="var(--border-subtle)" strokeDasharray="2,4"/>
          <path d={area} fill="url(#equityGradient)"/>
          <path d={line} fill="none" stroke={positive ? "#22C55E" : "#EF4444"} strokeWidth="1.5" strokeLinejoin="round"/>
        </svg>
      )}
    </section>
  );
}
