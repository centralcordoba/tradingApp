"use client";

// Alertas de audio + Notification compartidas (Zonas S/R + señales del Pine).
// El AudioContext DEBE crearse/resumirse desde un gesto de usuario — los
// navegadores bloquean audio sin interacción previa.

export function playChime(ctx: AudioContext, side: "LONG" | "SHORT") {
  try {
    const note = (freq: number, start: number, dur = 0.24) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0, start);
      gain.gain.linearRampToValueAtTime(0.28, start + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.001, start + dur);
      osc.start(start);
      osc.stop(start + dur + 0.05);
    };
    const t = ctx.currentTime;
    // Motif de 3 notas (ascendente=compra / descendente=venta) repetido para que
    // la alerta dure ~3 segundos.
    const motif = side === "LONG"
      ? [523.25, 783.99, 1046.5]   // C5 → G5 → C6
      : [1046.5, 783.99, 523.25];  // C6 → G5 → C5
    const REPEATS = 3;
    const NOTE_GAP = 0.26;
    const MOTIF_GAP = 1.0;
    for (let r = 0; r < REPEATS; r++) {
      const base = t + r * MOTIF_GAP;
      motif.forEach((freq, i) => {
        const isLast = r === REPEATS - 1 && i === motif.length - 1;
        note(freq, base + i * NOTE_GAP, isLast ? 0.55 : 0.24);
      });
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
