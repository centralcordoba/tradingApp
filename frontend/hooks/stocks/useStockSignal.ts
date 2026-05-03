"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { calculateSignal, intervalFor } from "@/lib/stocks/signalEngine";
import {
  clearStocksCache,
  getTimeSeriesWithIndicators,
  StocksApiError,
} from "@/lib/stocks/twelvedata";
import type { InvestorProfile, Signal } from "@/lib/stocks/types";

type UseStockSignalState = {
  signal: Signal | null;
  loading: boolean;
  error: { code: StocksApiError["code"]; message: string } | null;
  /** ISO de la última carga exitosa. */
  lastFetched: string | null;
};

type UseStockSignal = UseStockSignalState & {
  /** Re-fetch ignorando el cache de twelvedata (botón refresh manual). */
  refetch: () => void;
};

/**
 * Calcula la señal para un ticker dado un perfil. Si symbol o profile
 * son null devuelve `{ signal: null, loading: false }` sin disparar
 * fetch.
 *
 * Re-fetch automático cuando:
 *   - cambia el ticker
 *   - cambia el horizonte del perfil (afecta intervalo + pesos)
 */
export function useStockSignal(
  symbol: string | null,
  profile: InvestorProfile | null,
): UseStockSignal {
  const [state, setState] = useState<UseStockSignalState>({
    signal: null,
    loading: false,
    error: null,
    lastFetched: null,
  });

  // Bandera para abortar setState si el componente se desmontó
  // (o el ticker cambió antes de que termine el fetch en curso).
  const reqIdRef = useRef(0);

  const run = useCallback(async (forceRefetch: boolean) => {
    if (!symbol || !profile) {
      setState({ signal: null, loading: false, error: null, lastFetched: null });
      return;
    }

    const myReqId = ++reqIdRef.current;
    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      if (forceRefetch) clearStocksCache(symbol);
      const interval = intervalFor(profile);
      const bundle = await getTimeSeriesWithIndicators(symbol, interval);
      if (myReqId !== reqIdRef.current) return; // request stale
      const signal = calculateSignal(profile, bundle);
      setState({
        signal,
        loading: false,
        error: null,
        lastFetched: new Date().toISOString(),
      });
    } catch (err) {
      if (myReqId !== reqIdRef.current) return;
      const apiErr = err instanceof StocksApiError
        ? { code: err.code, message: err.message }
        : { code: "NETWORK" as const, message: String(err) };
      setState(prev => ({ ...prev, loading: false, error: apiErr }));
    }
  }, [symbol, profile]);

  useEffect(() => {
    run(false);
  }, [run]);

  const refetch = useCallback(() => {
    run(true);
  }, [run]);

  return { ...state, refetch };
}
