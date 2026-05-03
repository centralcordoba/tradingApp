"use client";

import type { RiskTolerance } from "@/lib/stocks/types";

type Props = {
  value: RiskTolerance | null;
  onChange: (r: RiskTolerance) => void;
};

const LEVELS: Array<{ v: RiskTolerance; label: string; detail: string }> = [
  { v: 1, label: "Muy conservador", detail: "Priorizás preservar capital. Aceptás señales solo con alta confluencia." },
  { v: 2, label: "Conservador",     detail: "Aceptás drawdowns mínimos. Preferís tendencias confirmadas." },
  { v: 3, label: "Moderado",        detail: "Balance entre crecimiento y protección. Operás señales medias y altas." },
  { v: 4, label: "Agresivo",        detail: "Buscás retornos altos. Aceptás más volatilidad por más oportunidades." },
  { v: 5, label: "Muy agresivo",    detail: "Priorizás retorno máximo. Operás incluso señales de menor confluencia." },
];

export function RiskStep({ value, onChange }: Props) {
  const current = value ?? 3;
  const active = LEVELS.find(l => l.v === current) ?? LEVELS[2];

  return (
    <div className="risk-step">
      <div className="risk-display">
        <div className="risk-value num">{current}<span className="risk-of">/5</span></div>
        <div className="risk-label">{active.label}</div>
        <div className="risk-detail">{active.detail}</div>
      </div>

      <div className="risk-slider-wrap">
        <input
          type="range"
          min={1}
          max={5}
          step={1}
          value={current}
          onChange={(e) => onChange(parseInt(e.target.value, 10) as RiskTolerance)}
          className="risk-slider"
          aria-label="Nivel de riesgo"
        />
        <div className="risk-ticks" aria-hidden="true">
          {LEVELS.map(l => (
            <button
              key={l.v}
              type="button"
              className={`risk-tick ${current === l.v ? "is-active" : ""}`}
              onClick={() => onChange(l.v)}
            >
              <span className="risk-tick-num num">{l.v}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
