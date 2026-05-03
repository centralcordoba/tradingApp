"use client";

import { intervalFor } from "@/lib/stocks/signalEngine";
import type { InvestorProfile } from "@/lib/stocks/types";
import "./ProfileBadge.css";

const HORIZON_LABEL: Record<InvestorProfile["horizon"], string> = {
  day_trader: "Day trader",
  swing: "Swing trader",
  long_term: "Largo plazo",
};

type Props = {
  profile: InvestorProfile;
  onEdit: () => void;
};

/**
 * Pill compacto con el resumen del perfil. Toda la fila es clickeable
 * para entrar al wizard en modo edición (más target que solo el botón).
 */
export function ProfileBadge({ profile, onEdit }: Props) {
  return (
    <button
      type="button"
      className="profile-badge"
      onClick={onEdit}
      title="Editar perfil"
      aria-label="Editar perfil del inversor"
    >
      <span className="pb-label">PERFIL</span>
      <span className="pb-sep" aria-hidden="true">·</span>
      <span className="pb-value">{HORIZON_LABEL[profile.horizon]}</span>
      <span className="pb-sep" aria-hidden="true">·</span>
      <span className="pb-meta">
        Riesgo <b className="num">{profile.riskTolerance}/5</b>
      </span>
      <span className="pb-sep" aria-hidden="true">·</span>
      <span className="pb-meta">
        Capital <b className="num">{profile.capitalRange}</b>
      </span>
      <span className="pb-sep" aria-hidden="true">·</span>
      <span className="pb-meta">
        Intervalo <b className="num">{intervalFor(profile)}</b>
      </span>
      <span className="pb-spacer" aria-hidden="true" />
      <span className="pb-edit">✎ Editar</span>
    </button>
  );
}
