/* ──────────────────────────────────────────────────────────────────
   Mapa de correlaciones (espejo del backend en correlations.py).
   Local: la matriz se renderiza sin pegarle al server.
   ────────────────────────────────────────────────────────────────── */

export const CORRELATION_PAIRS = [
  "EURUSD",
  "GBPUSD",
  "USDJPY",
  "AUDUSD",
  "USDCHF",
  "USDCAD",
] as const;

export type CorrelationPair = (typeof CORRELATION_PAIRS)[number];

export type CorrelationTier = "extreme" | "high" | "moderate" | "low";

const KEY = (a: string, b: string) => [a, b].sort().join("-");

const RAW: Record<string, number> = {
  [KEY("EURUSD", "GBPUSD")]: +0.85,
  [KEY("EURUSD", "USDJPY")]: -0.6,
  [KEY("EURUSD", "AUDUSD")]: +0.65,
  [KEY("EURUSD", "USDCHF")]: -0.95,
  [KEY("EURUSD", "USDCAD")]: -0.6,
  [KEY("GBPUSD", "USDJPY")]: -0.55,
  [KEY("GBPUSD", "AUDUSD")]: +0.6,
  [KEY("GBPUSD", "USDCHF")]: -0.75,
  [KEY("GBPUSD", "USDCAD")]: -0.5,
  [KEY("USDJPY", "AUDUSD")]: -0.5,
  [KEY("USDJPY", "USDCHF")]: +0.6,
  [KEY("USDJPY", "USDCAD")]: +0.5,
  [KEY("AUDUSD", "USDCHF")]: -0.65,
  [KEY("AUDUSD", "USDCAD")]: -0.55,
  [KEY("USDCHF", "USDCAD")]: +0.55,
};

export function getCorrelation(a: string, b: string): number | null {
  if (a === b) return 1;
  return RAW[KEY(a, b)] ?? null;
}

export function getTier(value: number | null): CorrelationTier {
  if (value === null) return "low";
  const v = Math.abs(value);
  if (v >= 0.85) return "extreme";
  if (v >= 0.7) return "high";
  if (v >= 0.5) return "moderate";
  return "low";
}

export function tierEmoji(tier: CorrelationTier): string {
  switch (tier) {
    case "extreme": return "🔴";
    case "high":    return "🟠";
    case "moderate":return "🟡";
    case "low":     return "⚪";
  }
}

export function describeCorrelation(value: number): {
  label: string;
  interpretation: string;
} {
  const v = Math.abs(value);
  const positive = value > 0;
  if (v >= 0.85) {
    return positive
      ? {
          label: "Positiva extrema",
          interpretation: "Se mueven prácticamente como uno solo: subir uno implica subir el otro casi siempre.",
        }
      : {
          label: "Inversa extrema",
          interpretation: "Espejos casi perfectos: cuando uno sube, el otro baja con la misma fuerza.",
        };
  }
  if (v >= 0.7) {
    return positive
      ? {
          label: "Positiva alta",
          interpretation: "Se mueven juntos casi siempre. Cuando uno sube, el otro tiende a subir; cuando uno baja, el otro tiende a bajar.",
        }
      : {
          label: "Negativa alta",
          interpretation: "Se mueven en direcciones opuestas casi siempre.",
        };
  }
  if (v >= 0.5) {
    return positive
      ? {
          label: "Moderada positiva",
          interpretation: "Tendencia a moverse en la misma dirección, pero con divergencias frecuentes.",
        }
      : {
          label: "Moderada negativa",
          interpretation: "Tendencia a moverse en direcciones opuestas, pero con divergencias frecuentes.",
        };
  }
  return {
    label: "Baja",
    interpretation: "Movimientos en gran medida independientes.",
  };
}

export type CorrelationRow = {
  pair: CorrelationPair;
  value: number;
  tier: CorrelationTier;
};

export function correlationsFor(pair: string): CorrelationRow[] {
  return CORRELATION_PAIRS.filter((p) => p !== pair)
    .map((p) => {
      const v = getCorrelation(pair, p)!;
      return { pair: p, value: v, tier: getTier(v) };
    })
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
}

export const LEGEND: { tier: CorrelationTier; emoji: string; label: string }[] = [
  { tier: "extreme",  emoji: "🔴", label: "Extrema (≥ |0.85|) — mismo trade duplicado" },
  { tier: "high",     emoji: "🟠", label: "Alta (|0.70| a |0.84|) — riesgo elevado" },
  { tier: "moderate", emoji: "🟡", label: "Moderada (|0.50| a |0.69|) — vigilar" },
  { tier: "low",      emoji: "⚪", label: "Baja (< |0.50|) — independientes" },
];
