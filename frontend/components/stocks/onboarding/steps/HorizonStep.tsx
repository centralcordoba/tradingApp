"use client";

import type { Horizon } from "@/lib/stocks/types";

type Props = {
  value: Horizon | null;
  onChange: (h: Horizon) => void;
};

const OPTIONS: Array<{
  id: Horizon;
  title: string;
  subtitle: string;
  detail: string;
}> = [
  {
    id: "day_trader",
    title: "Day trader",
    subtitle: "Operás varias veces al día",
    detail: "Intervalo 15m · prioriza RSI y MACD · entradas y salidas el mismo día",
  },
  {
    id: "swing",
    title: "Swing trader",
    subtitle: "Operaciones de días a pocas semanas",
    detail: "Intervalo 4h · balance entre tendencia y momentum · evitás ruido intradiario",
  },
  {
    id: "long_term",
    title: "Largo plazo",
    subtitle: "Posiciones de meses",
    detail: "Intervalo diario · prioriza SMA200 y ADX · ignorás el ruido de corto",
  },
];

export function HorizonStep({ value, onChange }: Props) {
  return (
    <div className="step-options" role="radiogroup" aria-label="Horizonte de inversión">
      {OPTIONS.map(opt => {
        const selected = value === opt.id;
        return (
          <button
            key={opt.id}
            type="button"
            role="radio"
            aria-checked={selected}
            className={`step-option ${selected ? "is-selected" : ""}`}
            onClick={() => onChange(opt.id)}
          >
            <div className="step-option-title">{opt.title}</div>
            <div className="step-option-sub">{opt.subtitle}</div>
            <div className="step-option-detail">{opt.detail}</div>
          </button>
        );
      })}
    </div>
  );
}
