"use client";

// Alertas de audio + Notification compartidas (Zonas S/R + señales del Pine).
// El AudioContext DEBE crearse/resumirse desde un gesto de usuario — los
// navegadores bloquean audio sin interacción previa.

export type ChimeNote = { freq: number; start: number; dur: number };

// Duración objetivo de la alerta sonora (segundos).
export const CHIME_TARGET_SEC = 5;

const NOTE_GAP = 0.26;
const MOTIF_GAP = 1.0;
export const CHIME_REPEATS = 5;

// Partitura del chime: motif de 3 notas (ascendente=compra / descendente=venta)
// repetido `repeats` veces (default ~CHIME_TARGET_SEC; con 1 es un tono corto
// de ~1s para avisos no urgentes como WAIT). Pura para testearse sin AudioContext.
export function chimeSchedule(side: "LONG" | "SHORT", repeats: number = CHIME_REPEATS): ChimeNote[] {
  const motif = side === "LONG"
    ? [523.25, 783.99, 1046.5]   // C5 → G5 → C6
    : [1046.5, 783.99, 523.25];  // C6 → G5 → C5
  const notes: ChimeNote[] = [];
  for (let r = 0; r < repeats; r++) {
    const base = r * MOTIF_GAP;
    motif.forEach((freq, i) => {
      const isLast = r === repeats - 1 && i === motif.length - 1;
      notes.push({ freq, start: base + i * NOTE_GAP, dur: isLast ? 0.55 : 0.24 });
    });
  }
  return notes;
}

export function playChime(ctx: AudioContext, side: "LONG" | "SHORT", repeats?: number) {
  try {
    const t = ctx.currentTime;
    for (const { freq, start, dur } of chimeSchedule(side, repeats)) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0, t + start);
      gain.gain.linearRampToValueAtTime(0.28, t + start + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.001, t + start + dur);
      osc.start(t + start);
      osc.stop(t + start + dur + 0.05);
    }
  } catch {
    // AudioContext suspendido o no disponible
  }
}

export function sendNotification(title: string, body: string, tag: string) {
  if (typeof window === "undefined" || !("Notification" in window)) return;
  if (Notification.permission !== "granted") return;
  try {
    new Notification(title, { body, tag, requireInteraction: true });
  } catch {
    // Silencioso si el navegador no soporta algún campo
  }
}

export function createAudioContext(): AudioContext | null {
  try {
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    return AC ? new AC() : null;
  } catch {
    return null;
  }
}
