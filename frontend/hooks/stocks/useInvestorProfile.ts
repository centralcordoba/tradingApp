"use client";

import { useCallback, useEffect, useState } from "react";
import {
  clearProfile as storageClear,
  fetchProfileFromBackend,
  getCachedProfile,
  PROFILE_CACHE_KEY,
  PROFILE_CHANGE_EVENT,
  saveProfile as storageSave,
} from "@/lib/stocks/profileStorage";
import type { InvestorProfile } from "@/lib/stocks/types";

type UseInvestorProfile = {
  profile: InvestorProfile | null;
  /**
   * `false` mientras la lectura inicial no se hidrató. Sirve para no
   * mostrar el wizard durante un frame antes de saber si hay perfil.
   */
  isLoaded: boolean;
  saveProfile: (p: InvestorProfile) => void;
  clearProfile: () => void;
};

/**
 * Lee/escribe el perfil del inversor — backend Supabase + localStorage cache.
 *
 * Estrategia:
 *   1. Mount → setProfile(cache) inmediato → setIsLoaded(true).
 *   2. Background fetch al backend → setProfile(server) si difiere.
 *   3. Mutaciones: optimistic update + async backend.
 *
 * Sync entre instancias del hook (sidebar y dashboard usan dos instancias
 * separadas del mismo hook): listener al `PROFILE_CHANGE_EVENT` que dispara
 * cualquier mutación + StorageEvent para cross-tab.
 */
export function useInvestorProfile(): UseInvestorProfile {
  const [profile, setProfile] = useState<InvestorProfile | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  // 1 + 2: hidrata desde cache, luego del backend.
  useEffect(() => {
    setProfile(getCachedProfile());
    setIsLoaded(true);

    let alive = true;
    fetchProfileFromBackend().then(p => {
      if (alive) setProfile(p);
    });
    return () => { alive = false; };
  }, []);

  // Sync entre tabs (StorageEvent) + entre instancias del mismo tab (custom event).
  useEffect(() => {
    const reload = () => setProfile(getCachedProfile());
    const onStorage = (e: StorageEvent) => {
      if (e.key === PROFILE_CACHE_KEY) reload();
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(PROFILE_CHANGE_EVENT, reload);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(PROFILE_CHANGE_EVENT, reload);
    };
  }, []);

  const save = useCallback((p: InvestorProfile) => {
    setProfile(p); // optimistic
    void storageSave(p).then(saved => setProfile(saved));
  }, []);

  const clear = useCallback(() => {
    setProfile(null);
    void storageClear();
  }, []);

  return { profile, isLoaded, saveProfile: save, clearProfile: clear };
}
