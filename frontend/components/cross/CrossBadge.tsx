"use client";

import type { CrossVerdict } from "@/lib/types";
import "./CrossBadge.css";

/**
 * Veredicto cruzado M30+M5. Render idéntico en el scanner y en Zonas S/R
 * (misma fuente de verdad en backend → mismo componente en frontend).
 *
 * - A / D / NA / OUT: badge compacto, summary en tooltip.
 * - B (FADE) y C (CONFLICTO): summary visible. C es un aviso fuerte (rojo).
 */
export function CrossBadge({ cross }: { cross?: CrossVerdict | null }) {
  if (!cross) return null;
  const verbose = cross.state === "B" || cross.state === "C";
  return (
    <div
      className={`xv xv-${cross.tone} xv-state-${cross.state}${verbose ? " xv-verbose" : ""}`}
      title={verbose ? undefined : cross.summary}
      role={cross.state === "C" ? "alert" : undefined}
    >
      <span className="xv-label">{cross.label}</span>
      {verbose && <p className="xv-summary">{cross.summary}</p>}
    </div>
  );
}
