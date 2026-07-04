"use client";

import "./KpiHero.css";

type Agg = {
  n: number;
  wins: number;
  losses: number;
  be: number;
  win_rate: number;
  pnl: number;
};

type Props = {
  totalSignals: number;
  closed: number;
  open: number;
  overall: Agg;
  taken: Agg;
  executionRate: number;
};

export function KpiHero({ totalSignals, closed, open, overall, taken, executionRate }: Props) {
  const pnl = overall.pnl;
  const pnlClass =
    pnl > 0 ? "pnl-positive" :
    pnl < 0 ? "pnl-negative" :
    "pnl-zero";
  const pnlText = pnl === 0
    ? "$0.00"
    : (pnl > 0 ? `+$${pnl.toFixed(2)}` : `-$${Math.abs(pnl).toFixed(2)}`);

  const wr = overall.win_rate * 100;
  const er = executionRate * 100;

  return (
    <section className="kpi-row" aria-label="Métricas principales">
      <div className="kpi">
        <div className="kpi-label">Profit &amp; Loss</div>
        <div className={`kpi-value num ${pnlClass}`}>{pnlText}</div>
        <div className="kpi-sub">
          Total · <span className="num">{closed} trades cerrados</span>
        </div>
      </div>

      <div className="kpi">
        <div className="kpi-label">Win Rate</div>
        <div className="kpi-value num kpi-wr">{wr.toFixed(0)}%</div>
        <div className="kpi-bar" aria-hidden="true">
          <div
            className={`kpi-bar-fill ${wr >= 50 ? "kpi-bar-good" : "kpi-bar-bad"}`}
            style={{ width: `${Math.max(0, Math.min(100, wr))}%` }}
          />
        </div>
        <div className="kpi-sub">
          <span className="num">{overall.wins} / {overall.losses} / {overall.be}</span> W/L/BE
        </div>
      </div>

      <div className="kpi">
        <div className="kpi-label">Execution Rate</div>
        <div className="kpi-value num kpi-er">{er.toFixed(0)}%</div>
        <div className="kpi-bar" aria-hidden="true">
          <div
            className="kpi-bar-fill kpi-bar-info"
            style={{ width: `${Math.max(0, Math.min(100, er))}%` }}
          />
        </div>
        <div className="kpi-sub">
          <span className="num">{taken.n} / {closed}</span> ejecutadas / evaluadas
        </div>
      </div>

      <div className="kpi">
        <div className="kpi-label">Open Positions</div>
        <div className="kpi-value num kpi-open">{open}</div>
        <div className="kpi-sub">
          Total: <span className="num">{totalSignals}</span> · Cerradas:{" "}
          <span className="num">{closed}</span>
        </div>
      </div>
    </section>
  );
}
