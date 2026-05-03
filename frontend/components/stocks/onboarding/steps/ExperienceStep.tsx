"use client";

import type { Experience } from "@/lib/stocks/types";

type Props = {
  value: Experience | null;
  onChange: (e: Experience) => void;
};

const OPTIONS: Array<{ id: Experience; title: string; detail: string }> = [
  {
    id: "novice",
    title: "Novato",
    detail: "Pocas operaciones cerradas. Las explicaciones de la app vienen en lenguaje claro y con contexto.",
  },
  {
    id: "intermediate",
    title: "Intermedio",
    detail: "Conocés indicadores básicos (RSI, MACD, MA). Lectura técnica + razones del motor.",
  },
  {
    id: "advanced",
    title: "Avanzado",
    detail: "Dominás multi-timeframe y price action. Mostramos números crudos + breakdown completo.",
  },
];

export function ExperienceStep({ value, onChange }: Props) {
  return (
    <div className="step-options" role="radiogroup" aria-label="Experiencia">
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
            <div className="step-option-detail">{opt.detail}</div>
          </button>
        );
      })}
    </div>
  );
}
