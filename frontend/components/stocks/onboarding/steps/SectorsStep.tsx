"use client";

type Props = {
  value: string[];
  onChange: (sectors: string[]) => void;
};

/** Sectores GICS — los 11 estándar + "Cripto" (más adelante si extendés). */
const SECTORS = [
  "Technology",
  "Healthcare",
  "Financials",
  "Consumer Discretionary",
  "Consumer Staples",
  "Energy",
  "Industrials",
  "Materials",
  "Real Estate",
  "Utilities",
  "Communication Services",
];

export function SectorsStep({ value, onChange }: Props) {
  const toggle = (sector: string) => {
    if (value.includes(sector)) {
      onChange(value.filter(s => s !== sector));
    } else {
      onChange([...value, sector]);
    }
  };

  return (
    <div className="sectors-step">
      <div className="sectors-grid">
        {SECTORS.map(s => {
          const selected = value.includes(s);
          return (
            <button
              key={s}
              type="button"
              className={`sector-chip ${selected ? "is-selected" : ""}`}
              onClick={() => toggle(s)}
              aria-pressed={selected}
            >
              {selected && <span className="sector-check" aria-hidden="true">✓</span>}
              {s}
            </button>
          );
        })}
      </div>
      <div className="sectors-hint">
        Opcional · {value.length === 0
          ? "elegí los que más operás"
          : `${value.length} ${value.length === 1 ? "sector" : "sectores"}`}
      </div>
    </div>
  );
}
