/* ──────────────────────────────────────────────────────────────────
   NYSE / NASDAQ market hours — DST-safe vía Intl.

   Horario regular en hora de Nueva York (America/New_York):
     - Pre-market : 04:00–09:30
     - Regular    : 09:30–16:00
     - Post-market: 16:00–20:00
     - Cerrado    : 20:00–04:00 + sábado y domingo

   Holidays oficiales: NO se modelan en el MVP. Si TD devuelve
   `marketStatus="closed"` en un día laborable, el SignalCard lo
   muestra correctamente — esta capa es solo para el reloj/countdown.
   ────────────────────────────────────────────────────────────────── */

export type NyseStatus = "regular" | "pre" | "post" | "closed";

export type NyseSnapshot = {
  status: NyseStatus;
  /** Hora ET formateada `HH:MM:SS` (24h). */
  et: string;
  /** Día de la semana en ET: 0 = domingo, 6 = sábado. */
  weekday: number;
  /** Minutos restantes hasta el próximo evento (cierre o apertura). */
  minutesUntilNext: number;
  /** Etiqueta humana del próximo evento. */
  nextEventLabel: string;
};

/** Devuelve hora/minuto/segundo + weekday (0-6) en America/New_York. */
function getEtParts(now: Date): { h: number; m: number; s: number; weekday: number } {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    weekday: "short",
  }).formatToParts(now);

  const h = parseInt(fmt.find(p => p.type === "hour")!.value, 10);
  const m = parseInt(fmt.find(p => p.type === "minute")!.value, 10);
  const s = parseInt(fmt.find(p => p.type === "second")!.value, 10);
  const wd = fmt.find(p => p.type === "weekday")!.value;

  // 'en-US' weekday short: Sun, Mon, Tue, Wed, Thu, Fri, Sat
  const map: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  return { h, m, s, weekday: map[wd] ?? 0 };
}

const PRE_OPEN_MIN = 4 * 60;       // 04:00
const REG_OPEN_MIN = 9 * 60 + 30;  // 09:30
const REG_CLOSE_MIN = 16 * 60;     // 16:00
const POST_CLOSE_MIN = 20 * 60;    // 20:00

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/**
 * Snapshot del estado actual del mercado US. `now` es opcional para tests.
 */
export function getNyseSnapshot(now: Date = new Date()): NyseSnapshot {
  const { h, m, s, weekday } = getEtParts(now);
  const totalMin = h * 60 + m + s / 60;
  const isWeekend = weekday === 0 || weekday === 6;
  const isFridayLate = weekday === 5 && totalMin >= POST_CLOSE_MIN;
  const isSundayEarly = weekday === 0 && totalMin < PRE_OPEN_MIN; // siempre true para domingo
  const _ = isFridayLate || isSundayEarly; // referencias para futuro uso (calc minutos a Mon)

  let status: NyseStatus;
  if (isWeekend) {
    status = "closed";
  } else if (totalMin < PRE_OPEN_MIN) {
    status = "closed";
  } else if (totalMin < REG_OPEN_MIN) {
    status = "pre";
  } else if (totalMin < REG_CLOSE_MIN) {
    status = "regular";
  } else if (totalMin < POST_CLOSE_MIN) {
    status = "post";
  } else {
    status = "closed";
  }

  // Minutos al próximo evento ─────────────────────────────────
  let minutesUntilNext: number;
  let nextEventLabel: string;

  if (status === "regular") {
    minutesUntilNext = REG_CLOSE_MIN - totalMin;
    nextEventLabel = "Cierra";
  } else if (status === "pre") {
    minutesUntilNext = REG_OPEN_MIN - totalMin;
    nextEventLabel = "Abre regular";
  } else if (status === "post") {
    minutesUntilNext = POST_CLOSE_MIN - totalMin;
    nextEventLabel = "Cierra post";
  } else {
    // Cerrado: calcular minutos hasta el próximo PRE_OPEN en día hábil.
    minutesUntilNext = minutesUntilNextOpen(weekday, totalMin);
    nextEventLabel = "Abre pre-market";
  }

  return {
    status,
    et: `${pad(h)}:${pad(m)}:${pad(s)}`,
    weekday,
    minutesUntilNext: Math.max(0, Math.round(minutesUntilNext)),
    nextEventLabel,
  };
}

function minutesUntilNextOpen(weekday: number, totalMin: number): number {
  // Ordena días para encontrar el próximo lunes-viernes con PRE_OPEN futuro.
  for (let offset = 0; offset < 8; offset++) {
    const day = (weekday + offset) % 7;
    if (day === 0 || day === 6) continue; // sábado/domingo
    const dayMinutes = offset * 24 * 60;
    // Si es hoy y aún no llegó pre-open, contamos hasta hoy.
    if (offset === 0 && totalMin < PRE_OPEN_MIN) {
      return PRE_OPEN_MIN - totalMin;
    }
    // Si es hoy y ya pasó post-close, ese día no abre más → siguiente.
    if (offset === 0) continue;
    return dayMinutes + PRE_OPEN_MIN - totalMin;
  }
  return 0;
}

/** Formato `Xh YYm` o `MMm` para countdowns. */
export function formatMinutes(min: number): string {
  const total = Math.max(0, Math.floor(min));
  const hh = Math.floor(total / 60);
  const mm = total % 60;
  if (hh >= 24) {
    const days = Math.floor(hh / 24);
    const remH = hh % 24;
    return `${days}d ${remH}h ${pad(mm)}m`;
  }
  if (hh > 0) return `${hh}h ${pad(mm)}m`;
  return `${mm}m`;
}
