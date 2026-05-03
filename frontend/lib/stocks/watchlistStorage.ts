/* ──────────────────────────────────────────────────────────────────
   Watchlist de stocks — backend Supabase + cache localStorage.

   Mismo patrón que profileStorage: optimistic writes + async sync.
   Cross-tab via StorageEvent, same-tab via WATCHLIST_CHANGE_EVENT.
   ────────────────────────────────────────────────────────────────── */

import { API } from "@/lib/api";
import type { Decision, WatchlistItem } from "./types";

const CACHE_KEY = "tradingapp:stocks_watchlist:v1";
export const WATCHLIST_CACHE_KEY = CACHE_KEY;
export const WATCHLIST_CHANGE_EVENT = "tradingapp:watchlist:changed";

const DECISIONS = new Set<Decision>(["BUY", "SELL", "HOLD"]);

// ─── Parse / validación ────────────────────────────────────────

function parseItem(raw: unknown): WatchlistItem | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.symbol !== "string" || !r.symbol) return null;
  // El backend devuelve `addedAt`, el cache podría tener legacy `addedAt` también.
  const addedAt = typeof r.addedAt === "string"
    ? r.addedAt
    : typeof r.added_at === "string"
    ? r.added_at
    : "";
  if (!addedAt) return null;

  const lastDecision =
    typeof r.lastDecision === "string" && DECISIONS.has(r.lastDecision as Decision)
      ? (r.lastDecision as Decision)
      : null;
  const lastConfidence =
    typeof r.lastConfidence === "number" && !isNaN(r.lastConfidence)
      ? r.lastConfidence
      : null;

  return {
    symbol: r.symbol.toUpperCase(),
    lastDecision,
    lastConfidence,
    addedAt,
  };
}

function parseList(raw: unknown): WatchlistItem[] {
  if (!Array.isArray(raw)) return [];
  return raw.map(parseItem).filter((x): x is WatchlistItem => x !== null);
}

// ─── Cache (localStorage) ──────────────────────────────────────

function readCache(): WatchlistItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return [];
    return parseList(JSON.parse(raw));
  } catch {
    return [];
  }
}

function writeCache(items: WatchlistItem[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(items));
    window.dispatchEvent(new Event(WATCHLIST_CHANGE_EVENT));
  } catch { /* ignore */ }
}

// ─── API pública ───────────────────────────────────────────────

export function getCachedWatchlist(): WatchlistItem[] {
  return readCache();
}

/**
 * Trae la watchlist del backend. En error usa cache.
 */
export async function fetchWatchlistFromBackend(): Promise<WatchlistItem[]> {
  try {
    const r = await fetch(`${API}/stocks/watchlist`, { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const items = parseList(data.items);
    writeCache(items);
    return items;
  } catch (err) {
    console.warn("fetchWatchlistFromBackend: usando cache local", err);
    return readCache();
  }
}

export async function addToWatchlist(symbol: string): Promise<WatchlistItem[]> {
  const sym = (symbol || "").toUpperCase().trim();
  if (!sym) return readCache();

  // Optimistic
  const cached = readCache();
  if (cached.some(i => i.symbol === sym)) return cached;
  const optimistic: WatchlistItem[] = [
    ...cached,
    {
      symbol: sym,
      lastDecision: null,
      lastConfidence: null,
      addedAt: new Date().toISOString(),
    },
  ];
  writeCache(optimistic);

  try {
    const r = await fetch(`${API}/stocks/watchlist`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: sym }),
      cache: "no-store",
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const items = parseList(data.items);
    writeCache(items);
    return items;
  } catch (err) {
    console.warn("addToWatchlist: backend falló, cache local conservado", err);
    return optimistic;
  }
}

export async function removeFromWatchlist(symbol: string): Promise<WatchlistItem[]> {
  const sym = (symbol || "").toUpperCase().trim();
  if (!sym) return readCache();

  // Optimistic
  const optimistic = readCache().filter(i => i.symbol !== sym);
  writeCache(optimistic);

  try {
    const r = await fetch(`${API}/stocks/watchlist/${encodeURIComponent(sym)}`, {
      method: "DELETE",
      cache: "no-store",
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const items = parseList(data.items);
    writeCache(items);
    return items;
  } catch (err) {
    console.warn("removeFromWatchlist: backend falló", err);
    return optimistic;
  }
}

export async function updateWatchlistItem(
  symbol: string,
  patch: Partial<Pick<WatchlistItem, "lastDecision" | "lastConfidence">>,
): Promise<WatchlistItem[]> {
  const sym = (symbol || "").toUpperCase().trim();
  if (!sym) return readCache();

  // Optimistic
  const optimistic = readCache().map(i =>
    i.symbol === sym ? { ...i, ...patch } : i,
  );
  writeCache(optimistic);

  try {
    const r = await fetch(`${API}/stocks/watchlist/${encodeURIComponent(sym)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
      cache: "no-store",
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const items = parseList(data.items);
    writeCache(items);
    return items;
  } catch (err) {
    console.warn("updateWatchlistItem: backend falló", err);
    return optimistic;
  }
}

export async function clearWatchlist(): Promise<void> {
  writeCache([]);
  // Backend no tiene endpoint "clear all" — borramos uno por uno.
  // Como es una operación rara, no la disparamos por defecto. Solo
  // limpiamos la cache local. Si querés purgar el backend también,
  // andá borrando uno por uno desde la UI.
}
