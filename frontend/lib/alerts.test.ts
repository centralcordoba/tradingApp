/* ──────────────────────────────────────────────────────────────────
   alerts — tests del chime de alerta (Zonas S/R + señales del Pine).

   No hay runner instalado en el repo. Este archivo está pensado para:
     1. Tipo-chequearse junto con el resto vía `tsc --noEmit`.
     2. Ejecutarse manualmente con `npx tsx lib/alerts.test.ts`.
   ────────────────────────────────────────────────────────────────── */

import { chimeSchedule, playChime, CHIME_TARGET_SEC, CHIME_REPEATS, type ChimeNote } from "./alerts";

function assert(cond: boolean, msg: string): void {
  if (!cond) throw new Error(`ASSERTION FAILED: ${msg}`);
}

function totalDuration(notes: ChimeNote[]): number {
  return Math.max(...notes.map(n => n.start + n.dur));
}

// ─── Duración ~5s en ambas direcciones ─────────────────────────

for (const side of ["LONG", "SHORT"] as const) {
  const notes = chimeSchedule(side);
  const dur = totalDuration(notes);
  assert(
    Math.abs(dur - CHIME_TARGET_SEC) <= 0.5,
    `${side}: duración ${dur.toFixed(2)}s fuera de ${CHIME_TARGET_SEC}±0.5s`,
  );
  assert(notes.length > 0, `${side}: partitura vacía`);
  // Los starts deben ser monotónicos no-decrecientes (partitura ordenada).
  for (let i = 1; i < notes.length; i++) {
    assert(notes[i].start >= notes[i - 1].start, `${side}: starts desordenados en nota ${i}`);
  }
  assert(notes[0].start === 0, `${side}: la primera nota debe sonar inmediatamente`);
}

// ─── Dirección del motif ────────────────────────────────────────

const long3 = chimeSchedule("LONG").slice(0, 3).map(n => n.freq);
const short3 = chimeSchedule("SHORT").slice(0, 3).map(n => n.freq);
assert(long3[0] < long3[1] && long3[1] < long3[2], "LONG: motif debe ser ascendente");
assert(short3[0] > short3[1] && short3[1] > short3[2], "SHORT: motif debe ser descendente");
assert(
  JSON.stringify(long3) === JSON.stringify([...short3].reverse()),
  "LONG y SHORT deben ser motifs espejo",
);

// ─── playChime programa osciladores según la partitura ──────────
// Mock mínimo de AudioContext: registra cada osc.start/stop programado.

type Scheduled = { freq: number; start: number; stop: number };

function mockAudioContext(now: number) {
  const scheduled: Scheduled[] = [];
  const gainNode = () => ({
    connect: () => {},
    gain: {
      setValueAtTime: () => {},
      linearRampToValueAtTime: () => {},
      exponentialRampToValueAtTime: () => {},
    },
  });
  const ctx = {
    currentTime: now,
    destination: {},
    createGain: gainNode,
    createOscillator: () => {
      const osc: Scheduled = { freq: 0, start: -1, stop: -1 };
      scheduled.push(osc);
      return {
        type: "sine",
        connect: () => {},
        frequency: { set value(v: number) { osc.freq = v; } },
        start: (t: number) => { osc.start = t; },
        stop: (t: number) => { osc.stop = t; },
      };
    },
  };
  return { ctx: ctx as unknown as AudioContext, scheduled };
}

for (const side of ["LONG", "SHORT"] as const) {
  const NOW = 42.5; // currentTime arbitrario: los offsets deben sumarse a él
  const { ctx, scheduled } = mockAudioContext(NOW);
  playChime(ctx, side);
  const expected = chimeSchedule(side);
  assert(
    scheduled.length === expected.length,
    `${side}: playChime creó ${scheduled.length} osciladores, esperaba ${expected.length}`,
  );
  const audioEnd = Math.max(...scheduled.map(s => s.stop)) - NOW;
  assert(
    Math.abs(audioEnd - CHIME_TARGET_SEC) <= 0.5,
    `${side}: el audio real termina en ${audioEnd.toFixed(2)}s, esperaba ~${CHIME_TARGET_SEC}s`,
  );
  scheduled.forEach((s, i) => {
    assert(s.freq === expected[i].freq, `${side}: nota ${i} freq ${s.freq} != ${expected[i].freq}`);
    assert(
      Math.abs(s.start - (NOW + expected[i].start)) < 1e-9,
      `${side}: nota ${i} no está anclada a currentTime`,
    );
    assert(s.stop > s.start, `${side}: nota ${i} stop <= start`);
  });
}

// ─── Tono corto (repeats=1) para avisos no urgentes (WAIT) ──────

for (const side of ["LONG", "SHORT"] as const) {
  const short = chimeSchedule(side, 1);
  assert(short.length === 3, `${side}: repeats=1 debe dar un solo motif de 3 notas`);
  assert(totalDuration(short) < 1.5, `${side}: el tono corto debe durar ~1s, dura ${totalDuration(short).toFixed(2)}s`);
}
assert(
  JSON.stringify(chimeSchedule("LONG", CHIME_REPEATS)) === JSON.stringify(chimeSchedule("LONG")),
  "sin repeats debe equivaler a CHIME_REPEATS",
);

{
  const { ctx, scheduled } = mockAudioContext(0);
  playChime(ctx, "SHORT", 1);
  assert(scheduled.length === 3, `playChime con repeats=1 creó ${scheduled.length} osciladores, esperaba 3`);
}

// ─── playChime no lanza con un contexto roto ────────────────────

const broken = { get currentTime(): number { throw new Error("suspendido"); } };
playChime(broken as unknown as AudioContext, "LONG"); // no debe lanzar

console.log("alerts.test.ts: OK — todos los asserts pasaron");
