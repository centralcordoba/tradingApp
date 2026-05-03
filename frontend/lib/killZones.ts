/* ──────────────────────────────────────────────────────────────────
   Kill zones — definidas en hora Madrid (operativa del usuario).
   getMadridHourMin / isInKillZone / kzProgress son extracciones
   verbatim del legacy.
   getKillZonesUTC convierte los bordes a UTC para alinear con la
   timeline de sesiones (que está en UTC). DST-safe vía Intl.
   ────────────────────────────────────────────────────────────────── */

export type KillZoneStatus = "fire" | "ok" | "warn" | "avoid";
export type KillZoneType = "aplus" | "caution" | "advanced" | "continuation" | "avoid";

export type KillZone = {
  label: string;
  startH: number; startM: number;
  endH: number;   endM: number;
  /** Status del legacy (fire/ok/warn/avoid) — usado por A+ filter */
  status: KillZoneStatus;
  /** Type del mockup (5 categorías visuales) */
  type: KillZoneType;
  note: string;
  /** Icono legacy — solo informativo, no se renderiza en el mockup */
  icon: string;
};

export const KILL_ZONES: KillZone[] = [
  { label: "Asia",                startH: 2,  startM: 0,  endH: 5,  endM: 0,  status: "avoid", type: "avoid",        icon: "🔴", note: "No operar (solo análisis de rango)" },
  { label: "Pre-London",          startH: 5,  startM: 0,  endH: 9,  endM: 0,  status: "avoid", type: "avoid",        icon: "🔴", note: "No operar (identificar liquidez)" },
  { label: "London Open",         startH: 9,  startM: 0,  endH: 10, endM: 30, status: "fire",  type: "aplus",        icon: "🔥", note: "Setup principal (breakout / liquidity sweep)" },
  { label: "London Continuation", startH: 10, startM: 30, endH: 12, endM: 0,  status: "ok",    type: "continuation", icon: "✅", note: "Solo continuación (no forzar trades)" },
  { label: "Pre-NY",              startH: 12, startM: 0,  endH: 14, endM: 0,  status: "warn",  type: "advanced",     icon: "⚠️", note: "Pullbacks / manipulación (avanzado)" },
  { label: "Overlap LDN-NY",      startH: 14, startM: 0,  endH: 17, endM: 0,  status: "fire",  type: "aplus",        icon: "🏆", note: "MEJOR VENTANA (A+ setups)" },
  { label: "NY Mid",              startH: 17, startM: 0,  endH: 19, endM: 0,  status: "warn",  type: "caution",      icon: "⚠️", note: "Selectivo (reversals / rangos)" },
  { label: "NY Close",            startH: 19, startM: 0,  endH: 22, endM: 0,  status: "avoid", type: "avoid",        icon: "🔴", note: "Evitar" },
];

export function getMadridHourMin(now: Date): { h: number; m: number } {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Madrid",
    hour: "2-digit", minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const h = parseInt(parts.find(p => p.type === "hour")!.value, 10);
  const m = parseInt(parts.find(p => p.type === "minute")!.value, 10);
  return { h, m };
}

export function isInKillZone(now: Date, kz: KillZone): boolean {
  const { h, m } = getMadridHourMin(now);
  const cur = h * 60 + m;
  const start = kz.startH * 60 + kz.startM;
  const end = kz.endH * 60 + kz.endM;
  return cur >= start && cur < end;
}

export function kzProgress(now: Date, kz: KillZone): number {
  const { h, m } = getMadridHourMin(now);
  const cur = h * 60 + m;
  const start = kz.startH * 60 + kz.startM;
  const end = kz.endH * 60 + kz.endM;
  if (cur < start || cur >= end) return 0;
  return ((cur - start) / (end - start)) * 100;
}

export function getActiveKillZone(now: Date): KillZone | null {
  return KILL_ZONES.find(kz => isInKillZone(now, kz)) ?? null;
}

// ─── UTC projection (alineación con timeline de sesiones) ──────

/** Devuelve el offset Madrid → UTC en minutos para una fecha dada. */
function madridUTCOffsetMinutes(now: Date): number {
  const { h: madridH, m: madridM } = getMadridHourMin(now);
  const utcMin = now.getUTCHours() * 60 + now.getUTCMinutes();
  let madridMin = madridH * 60 + madridM;
  // Wrap si Madrid está en día siguiente al UTC (raro en este timezone, pero seguro)
  let diff = madridMin - utcMin;
  if (diff > 12 * 60) diff -= 24 * 60;
  if (diff < -12 * 60) diff += 24 * 60;
  return diff;
}

export type KillZoneUTC = {
  zone: KillZone;
  /** Posición 0-24 en escala UTC (puede ser negativa o >24 si cruza medianoche) */
  startUTC: number;
  endUTC: number;
};

/**
 * Variante en escala Madrid (0-24) — pasthrough de KILL_ZONES porque
 * ya están definidas en hora Madrid. La forma {startUTC,endUTC,zone}
 * coincide para ser consumida por KillZonesTrack.
 */
export function getKillZonesMadrid(): KillZoneUTC[] {
  return KILL_ZONES.map(zone => ({
    zone,
    startUTC: zone.startH + zone.startM / 60,
    endUTC:   zone.endH   + zone.endM   / 60,
  }));
}

/**
 * Convierte cada kill zone (definida en Madrid) a coordenadas UTC para
 * alinearla con la timeline de sesiones. DST-aware vía now.
 */
export function getKillZonesUTC(now: Date): KillZoneUTC[] {
  const offsetMin = madridUTCOffsetMinutes(now);
  return KILL_ZONES.map(zone => {
    const startMin = zone.startH * 60 + zone.startM - offsetMin;
    const endMin   = zone.endH   * 60 + zone.endM   - offsetMin;
    return {
      zone,
      startUTC: startMin / 60,
      endUTC:   endMin / 60,
    };
  });
}
