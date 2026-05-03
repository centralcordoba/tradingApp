"use client";

import type { IndicatorVote, Vote } from "@/lib/stocks/types";
import { WEIGHTS } from "@/lib/stocks/signalEngine";
import "./IndicatorBreakdown.css";

type Props = {
  votes: IndicatorVote[];
  horizon: keyof typeof WEIGHTS;
};

const INDICATOR_LABEL: Record<string, string> = {
  ma_short: "SMA 20",
  ma_long:  "SMA 200",
  rsi:      "RSI 14",
  macd:     "MACD 12/26/9",
  bbands:   "Bollinger 20/2",
  adx:      "ADX 14 + DI",
};

function votePill(vote: Vote): { label: string; cls: string } {
  if (vote === 1) return { label: "+1", cls: "vote-buy" };
  if (vote === -1) return { label: "-1", cls: "vote-sell" };
  return { label: " 0", cls: "vote-neutral" };
}

function formatValue(indicator: string, value: number): string {
  if (value === 0 || isNaN(value)) return "—";
  if (indicator === "rsi" || indicator === "adx") return value.toFixed(1);
  if (indicator === "macd") return value.toFixed(3);
  return value.toFixed(2);
}

export function IndicatorBreakdown({ votes, horizon }: Props) {
  const weights = WEIGHTS[horizon];
  // Ordenamos por peso descendente para destacar los más influyentes.
  const ordered = [...votes].sort((a, b) =>
    (weights[b.indicator] ?? 0) - (weights[a.indicator] ?? 0)
  );

  return (
    <div className="ind-breakdown">
      <table className="ind-table">
        <thead>
          <tr>
            <th>Indicador</th>
            <th className="right">Valor</th>
            <th className="center">Voto</th>
            <th className="right">Peso</th>
            <th>Razón</th>
          </tr>
        </thead>
        <tbody>
          {ordered.map((v) => {
            const pill = votePill(v.vote);
            const weight = weights[v.indicator] ?? 0;
            return (
              <tr key={v.indicator}>
                <td className="ind-name">{INDICATOR_LABEL[v.indicator] ?? v.indicator}</td>
                <td className="right num">{formatValue(v.indicator, v.value)}</td>
                <td className="center">
                  <span className={`vote-pill ${pill.cls}`}>{pill.label}</span>
                </td>
                <td className="right num">{Math.round(weight * 100)}%</td>
                <td className="ind-reason">{v.reason}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
