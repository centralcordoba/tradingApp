"use client";

import type { CapitalRange } from "@/lib/stocks/types";

type Props = {
  value: CapitalRange | null;
  onChange: (c: CapitalRange) => void;
};

const OPTIONS: Array<{ id: CapitalRange; label: string; detail: string }> = [
  { id: "<1k",      label: "Menos de $1.000",     detail: "Concentrá en pocos tickers líquidos. Cuidá comisiones relativas." },
  { id: "1k-10k",   label: "$1.000 – $10.000",    detail: "Diversificás 4-8 tickers. Riesgo por trade ~1-2% del capital." },
  { id: "10k-50k",  label: "$10.000 – $50.000",   detail: "Cartera estructurada. Posición sizing más fino, mejores entradas." },
  { id: "50k+",     label: "Más de $50.000",      detail: "Diversificación completa. Considerá liquidez y tax-loss harvesting." },
];

export function CapitalStep({ value, onChange }: Props) {
  return (
    <div className="step-options" role="radiogroup" aria-label="Rango de capital">
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
            <div className="step-option-title num">{opt.label}</div>
            <div className="step-option-detail">{opt.detail}</div>
          </button>
        );
      })}
    </div>
  );
}
