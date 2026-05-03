/* ──────────────────────────────────────────────────────────────────
   Stocks signal engine — funciones puras de scoring por indicador.
   Sin side-effects, sin fetch, totalmente testeable.
   ────────────────────────────────────────────────────────────────── */

import type {
  Decision,
  Horizon,
  IndicatorBundle,
  IndicatorKey,
  IndicatorVote,
  Interval,
  InvestorProfile,
  Signal,
  Vote,
} from "./types";

// ─── Pesos por horizonte (suman 1.0) ───────────────────────────

export const WEIGHTS: Record<Horizon, Record<IndicatorKey, number>> = {
  day_trader: { ma_short: 0.10, ma_long: 0.05, rsi: 0.30, macd: 0.30, bbands: 0.15, adx: 0.10 },
  swing:      { ma_short: 0.20, ma_long: 0.15, rsi: 0.20, macd: 0.20, bbands: 0.15, adx: 0.10 },
  long_term:  { ma_short: 0.05, ma_long: 0.35, rsi: 0.10, macd: 0.15, bbands: 0.10, adx: 0.25 },
};

export const INTERVAL_BY_HORIZON: Record<Horizon, Interval> = {
  day_trader: "15min",
  swing: "4h",
  long_term: "1day",
};

/** Threshold para mover de HOLD a BUY/SELL. */
export const DECISION_THRESHOLD = 0.4;

// ─── Funciones de voto (puras, todas devuelven Vote) ───────────

/**
 * MA corta (típicamente SMA20). +1 si precio > MA con margen,
 * -1 si precio < MA con margen, 0 dentro del margen (ruido).
 */
export function voteMaShort(price: number, ma20: number | null): Vote {
  if (ma20 == null || ma20 === 0) return 0;
  const diff = (price - ma20) / ma20;
  if (diff > 0.005) return 1;
  if (diff < -0.005) return -1;
  return 0;
}

/** MA larga (típicamente SMA200). Margen mayor (1%) por menor frecuencia. */
export function voteMaLong(price: number, ma200: number | null): Vote {
  if (ma200 == null || ma200 === 0) return 0;
  const diff = (price - ma200) / ma200;
  if (diff > 0.01) return 1;
  if (diff < -0.01) return -1;
  return 0;
}

/** RSI(14). <30 → +1 sobreventa (oportunidad de compra). >70 → -1 sobrecompra. */
export function voteRsi(rsi14: number | null): Vote {
  if (rsi14 == null) return 0;
  if (rsi14 < 30) return 1;
  if (rsi14 > 70) return -1;
  return 0;
}

/**
 * MACD histograma. Mira el último valor + cruce reciente:
 *  - último > 0 y previo ≤ 0 → cruce alcista → +1
 *  - último < 0 y previo ≥ 0 → cruce bajista → -1
 *  - sin cruce: tendencia consolidada → +1 si último > 0 con magnitud > 0.1, -1 si < -0.1, else 0.
 */
export function voteMacd(macdHist: number[]): Vote {
  if (!macdHist || macdHist.length < 2) return 0;
  const last = macdHist[macdHist.length - 1];
  const prev = macdHist[macdHist.length - 2];
  if (last > 0 && prev <= 0) return 1;
  if (last < 0 && prev >= 0) return -1;
  if (last > 0.1) return 1;
  if (last < -0.1) return -1;
  return 0;
}

/**
 * Bollinger Bands. Precio cerca/debajo banda inferior → +1 (sobreventa).
 * Cerca/encima banda superior → -1 (sobrecompra). Ruido en zona media.
 */
export function voteBbands(price: number, upper: number | null, lower: number | null): Vote {
  if (upper == null || lower == null) return 0;
  const range = upper - lower;
  if (range <= 0) return 0;
  // Touch = dentro del 5% inferior/superior del rango.
  const lowerThreshold = lower + range * 0.05;
  const upperThreshold = upper - range * 0.05;
  if (price <= lowerThreshold) return 1;
  if (price >= upperThreshold) return -1;
  return 0;
}

/**
 * ADX + DI. Tendencia válida solo con ADX ≥ 25; el signo lo da el
 * dominante entre +DI y -DI.
 */
export function voteAdx(
  adx: number | null,
  plusDI: number | null,
  minusDI: number | null,
): Vote {
  if (adx == null || plusDI == null || minusDI == null) return 0;
  if (adx < 25) return 0;
  if (plusDI > minusDI + 2) return 1;
  if (minusDI > plusDI + 2) return -1;
  return 0;
}

// ─── Razones humanas por voto ──────────────────────────────────

function maShortReason(price: number, ma20: number | null, vote: Vote): string {
  if (ma20 == null) return "MA20 sin datos";
  if (vote === 1) return `Precio (${price.toFixed(2)}) sobre SMA20 (${ma20.toFixed(2)}) → momentum corto alcista`;
  if (vote === -1) return `Precio (${price.toFixed(2)}) bajo SMA20 (${ma20.toFixed(2)}) → momentum corto bajista`;
  return `Precio cerca de SMA20 (${ma20.toFixed(2)}) — sin sesgo claro`;
}

function maLongReason(price: number, ma200: number | null, vote: Vote): string {
  if (ma200 == null) return "MA200 sin datos (poca historia)";
  if (vote === 1) return `Precio sobre SMA200 (${ma200.toFixed(2)}) → tendencia primaria alcista`;
  if (vote === -1) return `Precio bajo SMA200 (${ma200.toFixed(2)}) → tendencia primaria bajista`;
  return `Precio cerca de SMA200 — tendencia indecisa`;
}

function rsiReason(rsi14: number | null, vote: Vote): string {
  if (rsi14 == null) return "RSI sin datos";
  if (vote === 1) return `RSI(14) = ${rsi14.toFixed(1)} → sobreventa`;
  if (vote === -1) return `RSI(14) = ${rsi14.toFixed(1)} → sobrecompra`;
  return `RSI(14) = ${rsi14.toFixed(1)} → zona neutral`;
}

function macdReason(macdHist: number[], vote: Vote): string {
  if (!macdHist.length) return "MACD sin datos";
  const last = macdHist[macdHist.length - 1];
  if (vote === 1 && macdHist.length >= 2 && macdHist[macdHist.length - 2] <= 0)
    return `MACD: cruce alcista del histograma (${last.toFixed(3)})`;
  if (vote === -1 && macdHist.length >= 2 && macdHist[macdHist.length - 2] >= 0)
    return `MACD: cruce bajista del histograma (${last.toFixed(3)})`;
  if (vote === 1) return `MACD histograma positivo (${last.toFixed(3)})`;
  if (vote === -1) return `MACD histograma negativo (${last.toFixed(3)})`;
  return `MACD plano (${last.toFixed(3)})`;
}

function bbandsReason(price: number, upper: number | null, lower: number | null, vote: Vote): string {
  if (upper == null || lower == null) return "Bollinger sin datos";
  if (vote === 1) return `Precio en banda inferior (${lower.toFixed(2)}) → posible rebote`;
  if (vote === -1) return `Precio en banda superior (${upper.toFixed(2)}) → posible reversión`;
  return `Precio dentro de Bollinger (${lower.toFixed(2)}–${upper.toFixed(2)})`;
}

function adxReason(
  adx: number | null,
  plusDI: number | null,
  minusDI: number | null,
  vote: Vote,
): string {
  if (adx == null) return "ADX sin datos";
  if (adx < 25) return `ADX = ${adx.toFixed(1)} → mercado lateral, sin tendencia`;
  if (vote === 1) return `ADX = ${adx.toFixed(1)} con +DI > -DI → tendencia alcista fuerte`;
  if (vote === -1) return `ADX = ${adx.toFixed(1)} con -DI > +DI → tendencia bajista fuerte`;
  return `ADX = ${adx.toFixed(1)} sin dirección dominante`;
}

// ─── Construcción de IndicatorVote[] ───────────────────────────

function buildVotes(b: IndicatorBundle): IndicatorVote[] {
  const vMaShort  = voteMaShort(b.price, b.ma20);
  const vMaLong   = voteMaLong(b.price, b.ma200);
  const vRsi      = voteRsi(b.rsi14);
  const vMacd     = voteMacd(b.macdHist);
  const vBbands   = voteBbands(b.price, b.bbandsUpper, b.bbandsLower);
  const vAdx      = voteAdx(b.adx, b.plusDI, b.minusDI);

  return [
    { indicator: "ma_short", value: b.ma20  ?? 0, vote: vMaShort, reason: maShortReason(b.price, b.ma20,  vMaShort) },
    { indicator: "ma_long",  value: b.ma200 ?? 0, vote: vMaLong,  reason: maLongReason (b.price, b.ma200, vMaLong) },
    { indicator: "rsi",      value: b.rsi14 ?? 0, vote: vRsi,     reason: rsiReason    (b.rsi14, vRsi) },
    { indicator: "macd",     value: b.macdHist[b.macdHist.length - 1] ?? 0, vote: vMacd, reason: macdReason(b.macdHist, vMacd) },
    { indicator: "bbands",   value: b.bbandsLower ?? 0, vote: vBbands, reason: bbandsReason(b.price, b.bbandsUpper, b.bbandsLower, vBbands) },
    { indicator: "adx",      value: b.adx ?? 0,    vote: vAdx,    reason: adxReason   (b.adx, b.plusDI, b.minusDI, vAdx) },
  ];
}

// ─── Top reasons ───────────────────────────────────────────────

const PESO_LABEL = (w: number) => `${Math.round(w * 100)}%`;

function pickTopReasons(votes: IndicatorVote[], weights: Record<IndicatorKey, number>): string[] {
  const ranked = [...votes]
    .filter(v => v.vote !== 0)
    .map(v => ({ v, impact: Math.abs(v.vote * weights[v.indicator]) }))
    .sort((a, b) => b.impact - a.impact)
    .slice(0, 3);
  return ranked.map(({ v }) => {
    const w = weights[v.indicator];
    return `${v.reason} — peso ${PESO_LABEL(w)}`;
  });
}

// ─── Decisión final + confianza ────────────────────────────────

function clamp(x: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, x));
}

function decideFromScore(score: number): { decision: Decision; confidence: number } {
  if (score > DECISION_THRESHOLD) {
    return { decision: "BUY", confidence: clamp(score, 0, 1) };
  }
  if (score < -DECISION_THRESHOLD) {
    return { decision: "SELL", confidence: clamp(-score, 0, 1) };
  }
  // En HOLD, mayor confianza cuanto más cerca de 0 esté el score
  // (1 cuando score=0, 0.6 cuando score=±threshold).
  return { decision: "HOLD", confidence: clamp(1 - Math.abs(score), 0, 1) };
}

// ─── API pública ───────────────────────────────────────────────

/**
 * Calcula la señal final dada una bundle de indicadores y un perfil.
 *
 * Función pura: misma entrada → misma salida, sin fetch ni Date.now.
 */
export function calculateSignal(
  profile: InvestorProfile,
  bundle: IndicatorBundle,
): Signal {
  const weights = WEIGHTS[profile.horizon];
  const votes = buildVotes(bundle);

  const score = votes.reduce(
    (acc, v) => acc + v.vote * weights[v.indicator],
    0,
  );

  const { decision, confidence } = decideFromScore(score);
  const topReasons = pickTopReasons(votes, weights);

  return {
    symbol: bundle.symbol,
    decision,
    confidence,
    score,
    votes,
    topReasons,
    generatedAt: bundle.generatedAt,
    interval: bundle.interval,
    marketStatus: bundle.marketStatus,
  };
}

/** Helper para el wizard / hooks: traduce horizonte → intervalo recomendado. */
export function intervalFor(profile: InvestorProfile): Interval {
  return INTERVAL_BY_HORIZON[profile.horizon];
}
