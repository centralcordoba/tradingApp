export const PRESET_SYMBOLS = [
  "USDJPY", "USDCAD", "AUDUSD",
  "EURUSD", "USDCHF", "GBPUSD",
];

/** Une la lista de símbolos del API con el preset, sin duplicados, preservando orden API > preset. */
export function mergeSymbols(apiSymbols: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const s of [...apiSymbols, ...PRESET_SYMBOLS]) {
    const k = s.toUpperCase();
    if (!seen.has(k)) { seen.add(k); out.push(k); }
  }
  return out;
}
