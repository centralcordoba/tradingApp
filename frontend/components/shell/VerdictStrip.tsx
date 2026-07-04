"use client";

import { useEffect, useRef, useState } from "react";
import { API } from "@/lib/api";
import type { ZonesResponse } from "@/lib/types";
import { getActiveKillZone } from "@/lib/killZones";
import { useTick } from "@/hooks/useTick";
import { POLL_MARKET_MS } from "@/lib/config";
import "./VerdictStrip.css";

const DECISION_ICO: Record<string, string> = {
  OPERAR: "●",
  ESPERAR: "◐",
  NO_OPERAR: "○",
};

/**
 * Strip global "qué hago ahora": una línea por par operado con el veredicto
 * del marco (OPERAR/ESPERAR/NO OPERAR + side), el cross M30+M5 y la kill zone
 * actual — visible desde cualquier vista sin cruzar 3 pantallas mentalmente.
 *
 * Consume /api/zones con los pares default: misma cache backend que la vista
 * Zonas S/R → cero créditos TD extra.
 */
export function VerdictStrip() {
  const [data, setData] = useState<ZonesResponse | null>(null);
  const marketClosedRef = useRef(false);
  const now = useTick(60_000);

  useEffect(() => {
    let cancelled = false;
    const fetchZones = async () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      try {
        const r = await fetch(`${API}/api/zones`, { cache: "no-store" });
        if (!r.ok) return;
        const j: ZonesResponse = await r.json();
        if (cancelled) return;
        setData(j);
        marketClosedRef.current = !!j.market_closed;
      } catch {
        // silencioso — el strip es informativo, no crítico
      }
    };
    fetchZones();
    const id = setInterval(() => {
      if (marketClosedRef.current) return;
      fetchZones();
    }, POLL_MARKET_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  if (!data?.items?.length) return null;
  const kz = now ? getActiveKillZone(now) : null;

  return (
    <div className="verdict-strip" role="status" aria-label="Veredicto por par">
      {kz && (
        <span className={`vs-kz vs-kz-${kz.status}`} title={kz.note}>
          {kz.icon} {kz.label}
        </span>
      )}
      {data.market_closed && <span className="vs-closed">🌙 Mercado cerrado</span>}
      {data.items.map(it => {
        const m = it.marco;
        const decision = m?.decision ?? "NO_OPERAR";
        const side = m?.side ?? null;
        const toneCls =
          decision === "OPERAR" && side
            ? (side === "LONG" ? "vs-long" : "vs-short")
            : decision === "ESPERAR" ? "vs-wait" : "vs-no";
        return (
          <span key={it.pair} className={`vs-pair ${toneCls}`} title={m?.reason || it.cross?.summary || ""}>
            <b className="num">{it.pair}</b>
            {" "}{DECISION_ICO[decision] || "○"} {decision.replace("_", " ")}
            {decision === "OPERAR" && side ? ` ${side}` : ""}
            {it.cross?.state === "A" && <span className="vs-cross"> · A FAVOR M30</span>}
            {it.cross?.state === "B" && <span className="vs-cross"> · FADE EN RANGO</span>}
            {it.cross?.state === "C" && <span className="vs-cross vs-cross-conflict"> · ⚠ CONFLICTO</span>}
          </span>
        );
      })}
    </div>
  );
}
