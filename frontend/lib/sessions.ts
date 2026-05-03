/* ──────────────────────────────────────────────────────────────────
   Forex sessions — definiciones en UTC.
   getCurrentSession / getNextSession / getOverlapWindow son nuevos
   helpers de alto nivel; los demás (isOpen, progress, countdown)
   son extracciones literales del page.tsx legacy.
   ────────────────────────────────────────────────────────────────── */

export type SessionInfo = {
  id: "asia" | "ldn" | "ny";
  name: string;
  timezone: string;
  abbr: string;
  /** Apertura en UTC (hora decimal, ej. 7.5 = 07:30) */
  openHourUTC: number;
  closeHourUTC: number;
};

export const SESSIONS: SessionInfo[] = [
  { id: "asia", name: "Asia · Tokyo", timezone: "Asia/Tokyo", abbr: "ASIA", openHourUTC: 0, closeHourUTC: 9 },
  { id: "ldn",  name: "Londres",       timezone: "Europe/London", abbr: "LDN",  openHourUTC: 7, closeHourUTC: 16 },
  { id: "ny",   name: "New York",      timezone: "America/New_York", abbr: "NYC", openHourUTC: 12, closeHourUTC: 21 },
];

export type OverlapWindow = {
  id: "asia-ldn" | "ldn-ny";
  label: string;
  fromUTC: number;
  toUTC: number;
  /** A+ window — la mejor ventana de scalp del día */
  aplus: boolean;
};

export const OVERLAPS: OverlapWindow[] = [
  { id: "asia-ldn", label: "ASIA + LDN", fromUTC: 7,  toUTC: 9,  aplus: false },
  { id: "ldn-ny",   label: "LDN + NYC",  fromUTC: 12, toUTC: 16, aplus: true  },
];

// ─── Time helpers ───────────────────────────────────────────────

export function utcHourOf(now: Date): number {
  return now.getUTCHours() + now.getUTCMinutes() / 60 + now.getUTCSeconds() / 3600;
}

/** Hora actual en Europe/Madrid como decimal 0-24 (DST-safe via Intl). */
export function madridHourOf(now: Date): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Madrid",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const h = parseInt(parts.find(p => p.type === "hour")!.value, 10);
  const m = parseInt(parts.find(p => p.type === "minute")!.value, 10);
  const s = parseInt(parts.find(p => p.type === "second")!.value, 10);
  return h + m / 60 + s / 3600;
}

/** Offset Madrid - UTC en horas (entero, +1 invierno / +2 verano). */
export function madridOffsetHours(now: Date): number {
  const diff = madridHourOf(now) - utcHourOf(now);
  if (diff < -12) return Math.round(diff + 24);
  if (diff > 12)  return Math.round(diff - 24);
  return Math.round(diff);
}

/** Convierte una hora UTC (0-24) a hora Madrid (0-24, con wrap). */
export function utcToMadrid(hourUTC: number, offset: number): number {
  return ((hourUTC + offset) % 24 + 24) % 24;
}

export function formatTime(date: Date, tz: string): string {
  return date.toLocaleTimeString("es-ES", {
    timeZone: tz,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

// ─── Per-session helpers ────────────────────────────────────────

export function isSessionOpen(now: Date, session: SessionInfo): boolean {
  const h = utcHourOf(now);
  return h >= session.openHourUTC && h < session.closeHourUTC;
}

export function sessionProgress(now: Date, session: SessionInfo): number {
  const h = utcHourOf(now);
  if (h < session.openHourUTC || h >= session.closeHourUTC) return 0;
  const duration = session.closeHourUTC - session.openHourUTC;
  return ((h - session.openHourUTC) / duration) * 100;
}

export function sessionCountdown(now: Date, session: SessionInfo): { label: string; minutes: number } {
  const h = now.getUTCHours();
  const m = now.getUTCMinutes();
  const s = now.getUTCSeconds();
  const currentMin = h * 60 + m + s / 60;
  const openMin = session.openHourUTC * 60;
  const closeMin = session.closeHourUTC * 60;
  const open = currentMin >= openMin && currentMin < closeMin;

  let diffMin: number;
  if (open) {
    diffMin = closeMin - currentMin;
  } else {
    diffMin = currentMin < openMin ? openMin - currentMin : (24 * 60 - currentMin) + openMin;
  }

  const totalSec = Math.max(0, Math.floor(diffMin * 60));
  const hh = Math.floor(totalSec / 3600);
  const mm = Math.floor((totalSec % 3600) / 60);
  const ss = totalSec % 60;

  const prefix = open ? "Cierra en" : "Abre en";
  const time = hh > 0
    ? `${hh}h ${String(mm).padStart(2, "0")}m`
    : `${mm}m ${String(ss).padStart(2, "0")}s`;

  return { label: `${prefix} ${time}`, minutes: diffMin };
}

// ─── Aggregate helpers (alto nivel) ─────────────────────────────

export function getCurrentSession(now: Date): SessionInfo | null {
  return SESSIONS.find(s => isSessionOpen(now, s)) ?? null;
}

export function getNextSession(now: Date): { session: SessionInfo; minutesUntil: number } {
  const sorted = [...SESSIONS].map(s => ({ s, cd: sessionCountdown(now, s) }));
  // El "next" de una sesión cerrada da su próximo open. Buscamos la sesión
  // cerrada con menor diffMin → es la próxima en abrir.
  const closed = sorted.filter(({ s }) => !isSessionOpen(now, s));
  closed.sort((a, b) => a.cd.minutes - b.cd.minutes);
  const winner = closed[0] ?? sorted[0];
  return { session: winner.s, minutesUntil: winner.cd.minutes };
}

export function getOverlapLabel(now: Date): string | null {
  const ldn = isSessionOpen(now, SESSIONS[1]);
  const nyc = isSessionOpen(now, SESSIONS[2]);
  const asia = isSessionOpen(now, SESSIONS[0]);
  if (ldn && nyc) return "LDN + NYC";
  if (asia && ldn) return "ASIA + LDN";
  return null;
}

export function activeOverlap(now: Date): OverlapWindow | null {
  const h = utcHourOf(now);
  return OVERLAPS.find(o => h >= o.fromUTC && h < o.toUTC) ?? null;
}

/**
 * Estado del A+ window LDN-NY: si está activo, devuelve minutesLeft.
 * Si no, devuelve minutesUntil para el próximo (siempre el LDN-NY del día,
 * o del día siguiente si ya pasó).
 */
export function getOverlapWindow(now: Date): {
  active: boolean;
  minutesUntil: number;
  minutesLeft: number;
} {
  const aplusOverlap = OVERLAPS.find(o => o.aplus)!;
  const h = utcHourOf(now);
  const active = h >= aplusOverlap.fromUTC && h < aplusOverlap.toUTC;
  if (active) {
    return {
      active: true,
      minutesUntil: 0,
      minutesLeft: Math.round((aplusOverlap.toUTC - h) * 60),
    };
  }
  const target = h < aplusOverlap.fromUTC
    ? aplusOverlap.fromUTC
    : aplusOverlap.fromUTC + 24;
  return {
    active: false,
    minutesUntil: Math.round((target - h) * 60),
    minutesLeft: 0,
  };
}
