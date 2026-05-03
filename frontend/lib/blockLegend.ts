export type BlockLegendEntry = {
  k: "1" | "2" | "3";
  ico: string;
  name: string;
  def: string;
  tip: string;
};

export const BLOCK_LEGEND: BlockLegendEntry[] = [
  {
    k: "1",
    ico: "🟢",
    name: "Bloque 1 — Tendencia limpia",
    def: "EMAs alineadas (9>21>50 o al revés) + confluencia ≥4. Sin extremos agotados.",
    tip: "Operar a favor de la tendencia. Esperar pullback al EMA9 / EMA21.",
  },
  {
    k: "3",
    ico: "🟡",
    name: "Bloque 3 — Reversión en extremo",
    def: "Precio en extremo del rango (<15% o >85%) + RSI en exhaustion (<32 o >68).",
    tip: "Operar contra-tendencia corta. Esperar sweep + vela de reversión.",
  },
  {
    k: "2",
    ico: "⚪",
    name: "Bloque 2 — Excluido",
    def: "Bias bajo, EMAs mixtas o precio en zona ambigua sin confirmación.",
    tip: "No operar. Observar hasta que se rompa la estructura.",
  },
];
