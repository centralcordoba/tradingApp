/* ──────────────────────────────────────────────────────────────────
   Twelve Data — frontend client.
   Las llamadas no van directo a api.twelvedata.com (la API key vive
   en el backend FastAPI para no exponerla). Este cliente proxy-ea
   contra los endpoints `/stocks/*` que monta el backend en Fase 3.
   ────────────────────────────────────────────────────────────────── */

import { API } from "@/lib/api";
import type {
  IndicatorBundle,
  Interval,
  Quote,
  SymbolMatch,
} from "./types";

// ─── Errores ───────────────────────────────────────────────────

export class StocksApiError extends Error {
  constructor(
    public status: number,
    public code: "NOT_FOUND" | "RATE_LIMIT" | "NETWORK" | "INVALID" | "UPSTREAM",
    message: string,
  ) {
    super(message);
    this.name = "StocksApiError";
  }
}

// ─── Cache en memoria ──────────────────────────────────────────

type CacheEntry<T> = { value: T; expiresAt: number };
const cache = new Map<string, CacheEntry<unknown>>();

const TTL_QUOTE_MS = 5 * 60_000;        // 5 min
const TTL_INTRADAY_MS = 5 * 60_000;     // 5 min
const TTL_DAILY_MS = 60 * 60_000;       // 1 h

function cacheGet<T>(key: string): T | null {
  const entry = cache.get(key);
  if (!entry) return null;
  if (Date.now() >= entry.expiresAt) {
    cache.delete(key);
    return null;
  }
  return entry.value as T;
}

function cacheSet<T>(key: string, value: T, ttlMs: number): void {
  cache.set(key, { value, expiresAt: Date.now() + ttlMs });
}

/** Limpia el cache. Útil para "refrescar manual" desde la UI. */
export function clearStocksCache(symbol?: string): void {
  if (!symbol) {
    cache.clear();
    return;
  }
  for (const key of cache.keys()) {
    if (key.includes(`:${symbol.toUpperCase()}:`)) cache.delete(key);
  }
}

// ─── Retry con backoff diferenciado ───────────────────────────
//
// Twelve Data free tier limita a 8 req/min (rolling window). Cuando
// ese tope se cruza, esperar 1-4s no alcanza — el window es de 60s.
// Por eso separamos:
//   - 429 (rate limit) → 3s, 8s, 20s = 31s total. Da chance a que el
//     window se vacíe sin bloquear al usuario indefinidamente.
//   - Network errors → 1s, 2s, 4s = 7s total. Son transitorios cortos.

const RATE_LIMIT_RETRY_MS = [3000, 8000, 20000];
const NETWORK_RETRY_MS = [1000, 2000, 4000];

async function fetchWithRetry(url: string, init?: RequestInit): Promise<Response> {
  let lastErr: unknown = null;
  let rlAttempt = 0;
  let netAttempt = 0;

  while (true) {
    try {
      const r = await fetch(url, { cache: "no-store", ...init });
      if (r.status === 429 && rlAttempt < RATE_LIMIT_RETRY_MS.length) {
        await sleep(RATE_LIMIT_RETRY_MS[rlAttempt++]);
        continue;
      }
      return r;
    } catch (err) {
      lastErr = err;
      if (netAttempt < NETWORK_RETRY_MS.length) {
        await sleep(NETWORK_RETRY_MS[netAttempt++]);
        continue;
      }
      throw new StocksApiError(0, "NETWORK", `Fallo de red: ${String(lastErr)}`);
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(res => setTimeout(res, ms));
}

// ─── Helpers ───────────────────────────────────────────────────

async function parseOrThrow<T>(r: Response, ctx: string): Promise<T> {
  if (r.ok) {
    return (await r.json()) as T;
  }
  if (r.status === 404) {
    throw new StocksApiError(404, "NOT_FOUND", `${ctx}: símbolo no encontrado`);
  }
  if (r.status === 429) {
    throw new StocksApiError(429, "RATE_LIMIT", `${ctx}: rate limit superado`);
  }
  if (r.status >= 500) {
    throw new StocksApiError(r.status, "UPSTREAM", `${ctx}: error del proveedor (${r.status})`);
  }
  throw new StocksApiError(r.status, "INVALID", `${ctx}: respuesta inválida (${r.status})`);
}

/**
 * Si la última vela es >24h vieja → mercado cerrado.
 * Útil para sobreescribir el `marketStatus` que devuelva el backend.
 */
export function isStaleData(timestampISO: string, thresholdHours = 24): boolean {
  const t = new Date(timestampISO).getTime();
  if (isNaN(t)) return true;
  const ageMs = Date.now() - t;
  return ageMs > thresholdHours * 3600 * 1000;
}

// ─── API pública ───────────────────────────────────────────────

/**
 * Búsqueda de símbolos por texto. No cachea (poco volumen, queries únicas).
 * Twelve Data symbol_search es free y no cuenta créditos.
 */
export async function searchSymbols(query: string): Promise<SymbolMatch[]> {
  const q = query.trim();
  if (q.length < 1) return [];
  const url = `${API}/stocks/search?q=${encodeURIComponent(q)}`;
  const r = await fetchWithRetry(url);
  const data = await parseOrThrow<{ matches: SymbolMatch[] }>(r, "searchSymbols");
  return data.matches ?? [];
}

/** Quote en tiempo real (precio + cambio). Cacheado 5 min. */
export async function getQuote(symbol: string): Promise<Quote> {
  const sym = symbol.toUpperCase();
  const key = `quote:${sym}:1`;
  const cached = cacheGet<Quote>(key);
  if (cached) return cached;

  const url = `${API}/stocks/quote?symbol=${encodeURIComponent(sym)}`;
  const r = await fetchWithRetry(url);
  const data = await parseOrThrow<Quote>(r, `getQuote(${sym})`);
  cacheSet(key, data, TTL_QUOTE_MS);
  return data;
}

/**
 * Bundle de indicadores listo para signalEngine. El backend agrupa
 * SMA20/50/200, EMA20/50, RSI14, MACD(12,26,9), BBANDS(20,2),
 * ADX(14)+DI en una sola respuesta para minimizar créditos TD.
 *
 * TTL depende del intervalo:
 *  - 15min/1h/4h → 5 min
 *  - 1day → 1 h
 */
export async function getTimeSeriesWithIndicators(
  symbol: string,
  interval: Interval,
): Promise<IndicatorBundle> {
  const sym = symbol.toUpperCase();
  const key = `indicators:${sym}:${interval}`;
  const cached = cacheGet<IndicatorBundle>(key);
  if (cached) return cached;

  const url = `${API}/stocks/indicators?symbol=${encodeURIComponent(sym)}&interval=${interval}`;
  const r = await fetchWithRetry(url);
  const data = await parseOrThrow<IndicatorBundle>(r, `getIndicators(${sym}, ${interval})`);

  // Si la última vela es stale → forzamos marketStatus="closed"
  // (overrride del valor devuelto por el backend, que puede venir desfasado).
  const corrected: IndicatorBundle = {
    ...data,
    marketStatus: isStaleData(data.generatedAt) ? "closed" : data.marketStatus,
  };

  const ttl = interval === "1day" ? TTL_DAILY_MS : TTL_INTRADAY_MS;
  cacheSet(key, corrected, ttl);
  return corrected;
}
