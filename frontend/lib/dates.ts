/* ──────────────────────────────────────────────────────────────────
   Helpers de fecha. Extracción literal del page.tsx legacy.
   ────────────────────────────────────────────────────────────────── */

export function todayMadrid(): string {
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Madrid",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return fmt.format(new Date()); // YYYY-MM-DD
}

export function parseCandleDate(iso: string | null): Date | null {
  if (!iso) return null;
  try {
    let s = iso.replace(" ", "T");
    if (!s.endsWith("Z") && !s.includes("+")) s += "Z";
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  } catch { return null; }
}

export function formatCandleTime(iso: string | null): string {
  const d = parseCandleDate(iso);
  if (!d) return "";
  const tz = { timeZone: "Europe/Madrid" };
  const todayLocal = new Date().toLocaleDateString("es-ES", tz);
  const candleDate = d.toLocaleDateString("es-ES", tz);
  const hhmm = d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", ...tz });
  if (todayLocal === candleDate) return hhmm;
  const short = d.toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit", ...tz });
  return `${short} ${hhmm}`;
}

export function formatDataAge(min: number): string {
  const v = Math.max(0, min);
  if (v < 60) return `${Math.round(v)} min`;
  const h = Math.floor(v / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

export function ageText(age: number | null, ts: string | null): string {
  if (age == null) return "";
  const hhmm = formatCandleTime(ts);
  const suffix = hhmm ? ` (${hhmm})` : "";
  if (age === 1) return `vela recién cerrada${suffix}`;
  return `hace ${age} velas${suffix}`;
}

/** Convierte minutos a "HH:MM:SS" o "MM:SS" (countdown-friendly). */
export function formatCountdown(totalMinutes: number): string {
  const totalSec = Math.max(0, Math.round(totalMinutes * 60));
  const hh = Math.floor(totalSec / 3600);
  const mm = Math.floor((totalSec % 3600) / 60);
  const ss = totalSec % 60;
  if (hh > 0) return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
  return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}
