"use client";

import { useEffect, useState } from "react";

/**
 * setInterval seguro con cleanup. Devuelve `null` durante SSR y la
 * primera render del cliente, luego `Date` actualizado en cada tick.
 *
 * Por qué `null`: `new Date()` en useState initializer no es determinista
 * entre server-render y hydration → mismatch garantizado. El consumer
 * renderiza placeholder mientras el valor es `null`.
 */
export function useTick(intervalMs = 1000): Date | null {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
