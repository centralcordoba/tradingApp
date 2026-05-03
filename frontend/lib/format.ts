export function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** Formatea un PnL con signo explícito (+/-) y N decimales. */
export function formatPnL(pnl: number, decimals = 2): string {
  const sign = pnl >= 0 ? "+" : "";
  return `${sign}${pnl.toFixed(decimals)}`;
}

/** Formatea un porcentaje con signo explícito. */
export function formatPct(pct: number, decimals = 2): string {
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(decimals)}%`;
}
