"use client";

import { useCallback, useEffect, useState } from "react";

const KEY = "tradingapp:favorites";

/**
 * Lee/escribe favoritos en localStorage. Tuple de retorno:
 *   [favorites: Set<string>, toggleFavorite: (pair: string) => void]
 *
 * SSR-safe: empieza con set vacío y se hidrata en mount.
 */
export function useFavoritePairs(): [Set<string>, (pair: string) => void] {
  const [favorites, setFavorites] = useState<Set<string>>(new Set());

  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) setFavorites(new Set(parsed));
      }
    } catch {}
  }, []);

  const toggleFavorite = useCallback((pair: string) => {
    setFavorites(prev => {
      const next = new Set(prev);
      if (next.has(pair)) next.delete(pair); else next.add(pair);
      try { localStorage.setItem(KEY, JSON.stringify([...next])); } catch {}
      return next;
    });
  }, []);

  return [favorites, toggleFavorite];
}
