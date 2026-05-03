/* ──────────────────────────────────────────────────────────────────
   Investor profile — backend Supabase (vía FastAPI) + localStorage como cache.

   Patrón:
     - getCachedProfile() : lectura síncrona desde localStorage para el primer
       paint instantáneo.
     - fetchProfileFromBackend() : trae el server state, sincroniza cache.
     - saveProfile() / clearProfile() : optimistic write a cache + async al
       backend. Si el backend falla, mantenemos cache local (modo offline-tolerant).

   Sync entre instancias del mismo tab: custom event PROFILE_CHANGE_EVENT.
   Sync entre tabs: StorageEvent estándar (mismo CACHE_KEY).
   ────────────────────────────────────────────────────────────────── */

import { API } from "@/lib/api";
import type { InvestorProfile } from "./types";

const CACHE_KEY = "tradingapp:investor_profile:v1";
export const PROFILE_CACHE_KEY = CACHE_KEY;
export const PROFILE_CHANGE_EVENT = "tradingapp:profile:changed";

// ─── Validación defensiva ──────────────────────────────────────

const HORIZONS = new Set(["day_trader", "swing", "long_term"]);
const CAPITAL_RANGES = new Set(["<1k", "1k-10k", "10k-50k", "50k+"]);
const EXPERIENCES = new Set(["novice", "intermediate", "advanced"]);

function parseProfile(raw: unknown): InvestorProfile | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;

  if (typeof r.horizon !== "string" || !HORIZONS.has(r.horizon)) return null;
  if (typeof r.riskTolerance !== "number" || r.riskTolerance < 1 || r.riskTolerance > 5) return null;
  if (typeof r.capitalRange !== "string" || !CAPITAL_RANGES.has(r.capitalRange)) return null;
  if (typeof r.experience !== "string" || !EXPERIENCES.has(r.experience)) return null;
  if (!Array.isArray(r.sectors) || !r.sectors.every(s => typeof s === "string")) return null;

  return {
    horizon: r.horizon as InvestorProfile["horizon"],
    riskTolerance: Math.round(r.riskTolerance) as InvestorProfile["riskTolerance"],
    capitalRange: r.capitalRange as InvestorProfile["capitalRange"],
    experience: r.experience as InvestorProfile["experience"],
    sectors: r.sectors as string[],
  };
}

// ─── Cache helpers (sync, localStorage) ────────────────────────

function readCache(): InvestorProfile | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    return parseProfile(JSON.parse(raw));
  } catch {
    return null;
  }
}

function writeCache(profile: InvestorProfile | null): void {
  if (typeof window === "undefined") return;
  try {
    if (profile === null) localStorage.removeItem(CACHE_KEY);
    else localStorage.setItem(CACHE_KEY, JSON.stringify(profile));
    window.dispatchEvent(new Event(PROFILE_CHANGE_EVENT));
  } catch { /* ignore */ }
}

// ─── API pública ───────────────────────────────────────────────

/** Lectura síncrona desde cache. Útil para el primer paint. */
export function getCachedProfile(): InvestorProfile | null {
  return readCache();
}

/**
 * Trae el perfil desde backend. Sincroniza cache si responde.
 * En error de red o servidor, devuelve cache (puede ser null).
 */
export async function fetchProfileFromBackend(): Promise<InvestorProfile | null> {
  try {
    const r = await fetch(`${API}/stocks/profile`, { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    if (data === null || data === undefined) {
      writeCache(null);
      return null;
    }
    const parsed = parseProfile(data);
    if (parsed) writeCache(parsed);
    return parsed;
  } catch (err) {
    console.warn("fetchProfileFromBackend: usando cache local", err);
    return readCache();
  }
}

/**
 * Guarda el perfil. Optimistic write a cache (UI instantánea), luego
 * sincroniza con backend. Si backend falla, mantenemos optimistic.
 */
export async function saveProfile(profile: InvestorProfile): Promise<InvestorProfile> {
  writeCache(profile); // optimistic
  try {
    const r = await fetch(`${API}/stocks/profile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
      cache: "no-store",
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const parsed = parseProfile(data);
    if (parsed) {
      writeCache(parsed);
      return parsed;
    }
    return profile;
  } catch (err) {
    console.warn("saveProfile: backend falló, cache local conservado", err);
    return profile;
  }
}

export async function clearProfile(): Promise<void> {
  writeCache(null);
  try {
    await fetch(`${API}/stocks/profile`, { method: "DELETE", cache: "no-store" });
  } catch (err) {
    console.warn("clearProfile: backend falló, cache local borrado", err);
  }
}
