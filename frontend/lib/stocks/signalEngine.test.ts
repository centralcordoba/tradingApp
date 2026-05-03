/* ──────────────────────────────────────────────────────────────────
   signalEngine — tests unitarios mínimos.

   No hay runner instalado en el repo. Este archivo está pensado para:
     1. Tipo-chequearse junto con el resto vía `tsc --noEmit`.
     2. Ejecutarse manualmente con `npx tsx lib/stocks/signalEngine.test.ts`
        si en el futuro alguien instala tsx (no lo hace este PR).
   Mientras tanto vale como documentación viva de comportamiento esperado.
   ────────────────────────────────────────────────────────────────── */

import {
  calculateSignal,
  voteAdx,
  voteBbands,
  voteMacd,
  voteMaLong,
  voteMaShort,
  voteRsi,
} from "./signalEngine";
import type { IndicatorBundle, InvestorProfile } from "./types";

// ─── Helpers ───────────────────────────────────────────────────

function assert(cond: boolean, msg: string): void {
  if (!cond) throw new Error(`ASSERTION FAILED: ${msg}`);
}

const SWING_PROFILE: InvestorProfile = {
  horizon: "swing",
  riskTolerance: 3,
  capitalRange: "10k-50k",
  experience: "intermediate",
  sectors: ["Technology"],
};

function bundle(overrides: Partial<IndicatorBundle> = {}): IndicatorBundle {
  return {
    symbol: "TEST",
    interval: "4h",
    generatedAt: "2026-05-02T12:00:00Z",
    price: 100,
    ma20: 100,
    ma50: 100,
    ma200: 100,
    ema20: 100,
    ema50: 100,
    rsi14: 50,
    macdHist: [0, 0, 0, 0, 0],
    bbandsUpper: 105,
    bbandsLower: 95,
    adx: 20,
    plusDI: 20,
    minusDI: 20,
    marketStatus: "open",
    ...overrides,
  };
}

// ─── Tests por función de voto (sanidad básica) ────────────────

export function testVoteFunctions(): void {
  // MA short
  assert(voteMaShort(110, 100) === 1, "voteMaShort: precio sobre MA con margen → +1");
  assert(voteMaShort(90, 100) === -1, "voteMaShort: precio bajo MA con margen → -1");
  assert(voteMaShort(100.3, 100) === 0, "voteMaShort: dentro de margen 0.5% → 0");
  assert(voteMaShort(100, null) === 0, "voteMaShort: ma null → 0");

  // MA long
  assert(voteMaLong(120, 100) === 1, "voteMaLong: precio bien sobre MA → +1");
  assert(voteMaLong(80, 100) === -1, "voteMaLong: precio bien bajo MA → -1");

  // RSI
  assert(voteRsi(25) === 1, "voteRsi: 25 → sobreventa → +1");
  assert(voteRsi(75) === -1, "voteRsi: 75 → sobrecompra → -1");
  assert(voteRsi(50) === 0, "voteRsi: 50 → neutral → 0");
  assert(voteRsi(null) === 0, "voteRsi: null → 0");

  // MACD
  assert(voteMacd([-0.5, -0.2, 0.1]) === 1, "voteMacd: cruce alcista del histograma → +1");
  assert(voteMacd([0.5, 0.2, -0.1]) === -1, "voteMacd: cruce bajista del histograma → -1");
  assert(voteMacd([0.05, 0.06, 0.07]) === 0, "voteMacd: positivo pero pequeño + sin cruce → 0");
  assert(voteMacd([0.5]) === 0, "voteMacd: serie corta → 0");

  // BBANDS
  assert(voteBbands(95.1, 105, 95) === 1, "voteBbands: precio en banda inferior → +1");
  assert(voteBbands(104.9, 105, 95) === -1, "voteBbands: precio en banda superior → -1");
  assert(voteBbands(100, 105, 95) === 0, "voteBbands: medio → 0");
  assert(voteBbands(100, null, null) === 0, "voteBbands: null → 0");

  // ADX
  assert(voteAdx(30, 25, 15) === 1, "voteAdx: trend con +DI > -DI → +1");
  assert(voteAdx(30, 15, 25) === -1, "voteAdx: trend con -DI > +DI → -1");
  assert(voteAdx(15, 25, 15) === 0, "voteAdx: ADX < 25 → 0");
  assert(voteAdx(30, 20, 20) === 0, "voteAdx: DI's empatados → 0");

  console.log("✓ testVoteFunctions");
}

// ─── Caso 1: BUY claro ─────────────────────────────────────────

export function testStrongBuy(): void {
  // Setup: tendencia alcista en todos los indicadores.
  //  - Precio sobre SMA20 y SMA200 (+1, +1)
  //  - RSI 28 → sobreventa (+1)
  //  - MACD cruce alcista (+1)
  //  - Precio cerca de banda inferior (+1)
  //  - ADX 32, +DI > -DI (+1)
  // Score swing = 0.20 + 0.15 + 0.20 + 0.20 + 0.15 + 0.10 = 1.0 → BUY conf 1.
  const sig = calculateSignal(SWING_PROFILE, bundle({
    price: 102,
    ma20: 100,
    ma200: 95,
    rsi14: 28,
    macdHist: [-0.3, -0.1, 0.2],
    bbandsUpper: 110,
    bbandsLower: 100,
    adx: 32,
    plusDI: 28,
    minusDI: 14,
  }));

  assert(sig.decision === "BUY", `testStrongBuy: esperado BUY, obtuve ${sig.decision}`);
  assert(sig.score > 0.4, `testStrongBuy: score > 0.4, obtuve ${sig.score}`);
  assert(sig.confidence > 0.4, `testStrongBuy: confianza > 0.4, obtuve ${sig.confidence}`);
  assert(sig.topReasons.length === 3, "testStrongBuy: top 3 reasons");
  assert(
    sig.votes.every(v => v.vote >= 0),
    "testStrongBuy: ningún voto debería ser negativo",
  );
  console.log(`✓ testStrongBuy (score=${sig.score.toFixed(2)}, conf=${sig.confidence.toFixed(2)})`);
}

// ─── Caso 2: SELL claro ────────────────────────────────────────

export function testStrongSell(): void {
  // Mirror del anterior: todo bajista.
  const sig = calculateSignal(SWING_PROFILE, bundle({
    price: 90,
    ma20: 95,
    ma200: 105,
    rsi14: 78,
    macdHist: [0.3, 0.1, -0.2],
    bbandsUpper: 92,   // precio bien arriba para que vote -1
    bbandsLower: 80,
    adx: 32,
    plusDI: 14,
    minusDI: 28,
  }));

  assert(sig.decision === "SELL", `testStrongSell: esperado SELL, obtuve ${sig.decision}`);
  assert(sig.score < -0.4, `testStrongSell: score < -0.4, obtuve ${sig.score}`);
  assert(sig.votes.filter(v => v.vote === -1).length >= 4,
    "testStrongSell: ≥4 votos negativos");
  console.log(`✓ testStrongSell (score=${sig.score.toFixed(2)}, conf=${sig.confidence.toFixed(2)})`);
}

// ─── Caso 3: HOLD (señales mixtas) ─────────────────────────────

export function testHold(): void {
  // Setup conflictivo: algunos +1, otros -1, otros 0 → score cerca de 0.
  const sig = calculateSignal(SWING_PROFILE, bundle({
    price: 100,
    ma20: 100,        // 0
    ma200: 100,       // 0
    rsi14: 50,        // 0
    macdHist: [0, 0.01, 0.02],  // 0 (positivo pero pequeño)
    bbandsUpper: 110, // 0 (medio)
    bbandsLower: 90,
    adx: 20,          // 0 (lateral)
    plusDI: 20,
    minusDI: 20,
  }));

  assert(sig.decision === "HOLD", `testHold: esperado HOLD, obtuve ${sig.decision}`);
  assert(Math.abs(sig.score) <= 0.4,
    `testHold: |score| <= 0.4, obtuve ${sig.score}`);
  console.log(`✓ testHold (score=${sig.score.toFixed(2)}, conf=${sig.confidence.toFixed(2)})`);
}

// ─── Caso 4 bonus: indicadores faltantes no rompen ─────────────

export function testMissingIndicators(): void {
  // Stock recién listado: sin MA200, sin BBANDS.
  const sig = calculateSignal(SWING_PROFILE, bundle({
    ma200: null,
    bbandsUpper: null,
    bbandsLower: null,
    rsi14: 25,
  }));

  assert(sig.decision !== undefined, "testMissingIndicators: devuelve decisión");
  assert(sig.votes.length === 6, "testMissingIndicators: siempre 6 votos");
  console.log(`✓ testMissingIndicators (decision=${sig.decision})`);
}

// ─── Runner ────────────────────────────────────────────────────

export function runAllTests(): void {
  testVoteFunctions();
  testStrongBuy();
  testStrongSell();
  testHold();
  testMissingIndicators();
  console.log("\nAll signalEngine tests passed.");
}

// Permite invocación directa (`node --loader tsx lib/stocks/signalEngine.test.ts`)
// sin afectar el bundle de Next porque este archivo termina en .test.ts y
// no lo importa nadie de runtime.
declare const require: { main?: unknown } | undefined;
declare const module: { exports?: unknown } | undefined;
if (typeof require !== "undefined" && typeof module !== "undefined" && require.main === module) {
  runAllTests();
}
