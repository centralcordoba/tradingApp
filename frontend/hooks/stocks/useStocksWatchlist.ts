"use client";

import { useCallback, useEffect, useState } from "react";
import {
  addToWatchlist as storageAdd,
  fetchWatchlistFromBackend,
  getCachedWatchlist,
  removeFromWatchlist as storageRemove,
  updateWatchlistItem as storageUpdate,
  WATCHLIST_CACHE_KEY,
  WATCHLIST_CHANGE_EVENT,
} from "@/lib/stocks/watchlistStorage";
import type { Decision, WatchlistItem } from "@/lib/stocks/types";

type UseStocksWatchlist = {
  items: WatchlistItem[];
  isLoaded: boolean;
  addSymbol: (symbol: string) => void;
  removeSymbol: (symbol: string) => void;
  updateItem: (
    symbol: string,
    patch: { lastDecision?: Decision | null; lastConfidence?: number | null },
  ) => void;
  hasSymbol: (symbol: string) => boolean;
};

/**
 * Watchlist con backend Supabase + cache localStorage.
 *
 * Mount: cache → setItems → setIsLoaded → background fetch → resync.
 * Mutaciones: optimistic update local + async backend; el response del
 * backend (autoritativo) reemplaza el optimistic state al volver.
 *
 * Sync entre instancias del mismo tab vía WATCHLIST_CHANGE_EVENT.
 */
export function useStocksWatchlist(): UseStocksWatchlist {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    setItems(getCachedWatchlist());
    setIsLoaded(true);

    let alive = true;
    fetchWatchlistFromBackend().then(serverItems => {
      if (alive) setItems(serverItems);
    });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const reload = () => setItems(getCachedWatchlist());
    const onStorage = (e: StorageEvent) => {
      if (e.key === WATCHLIST_CACHE_KEY) reload();
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(WATCHLIST_CHANGE_EVENT, reload);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(WATCHLIST_CHANGE_EVENT, reload);
    };
  }, []);

  const addSymbol = useCallback((symbol: string) => {
    void storageAdd(symbol).then(setItems);
  }, []);

  const removeSymbol = useCallback((symbol: string) => {
    void storageRemove(symbol).then(setItems);
  }, []);

  const updateItem = useCallback((
    symbol: string,
    patch: { lastDecision?: Decision | null; lastConfidence?: number | null },
  ) => {
    void storageUpdate(symbol, patch).then(setItems);
  }, []);

  const hasSymbol = useCallback(
    (symbol: string) => {
      const sym = symbol.toUpperCase();
      return items.some(i => i.symbol === sym);
    },
    [items],
  );

  return { items, isLoaded, addSymbol, removeSymbol, updateItem, hasSymbol };
}
