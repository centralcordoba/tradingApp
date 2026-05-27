"use client";

import { useTick } from "@/hooks/useTick";
import {
  SESSIONS,
  OVERLAPS,
  madridHourOf,
  madridOffsetHours,
  utcToMadrid,
  getCurrentSession,
} from "@/lib/sessions";
import { getKillZonesMadrid } from "@/lib/killZones";
import { KillZonesTrack } from "./KillZonesTrack";
import "./SessionsTimeline.css";

type Props = {
  /** Override de "now" (testing). En prod usa useTick(1000). */
  now?: Date;
};

const HOUR_LABELS = [0, 3, 6, 9, 12, 15, 18, 21];

const SESSION_LABEL: Record<string, string> = {
  asia: "ASIA",
  ldn: "LONDRES",
  ny: "NEW YORK",
};

/**
 * Convierte una ventana UTC [openUTC, closeUTC) a una o dos bandas
 * en coordenadas Madrid (0-24). Si la ventana cruza medianoche en
 * Madrid devuelve dos bandas (0-x y y-24).
 */
function projectToMadrid(openUTC: number, closeUTC: number, offset: number): Array<{ left: number; width: number }> {
  const openM = utcToMadrid(openUTC, offset);
  const closeM = utcToMadrid(closeUTC, offset);
  if (closeM > openM) {
    return [{ left: (openM / 24) * 100, width: ((closeM - openM) / 24) * 100 }];
  }
  return [
    { left: (openM / 24) * 100, width: ((24 - openM) / 24) * 100 },
    { left: 0, width: (closeM / 24) * 100 },
  ];
}

export function SessionsTimeline({ now: nowOverride }: Props) {
  const tick = useTick(1000);
  const now = nowOverride ?? tick;

  if (!now) {
    return <section className="timeline-card timeline-card-loading" aria-hidden />;
  }

  const offset = madridOffsetHours(now);
  const madridH = madridHourOf(now);
  const nowPct = (madridH / 24) * 100;

  const aplusOverlap = OVERLAPS.find(o => o.aplus)!;
  const aplusBands = projectToMadrid(aplusOverlap.fromUTC, aplusOverlap.toUTC, offset);
  const aplusActive = madridH >= utcToMadrid(aplusOverlap.fromUTC, offset)
    && madridH < utcToMadrid(aplusOverlap.toUTC, offset);

  const killZonesMadrid = getKillZonesMadrid();

  const madridTime =
    `${String(Math.floor(madridH)).padStart(2, "0")}:` +
    `${String(Math.floor((madridH % 1) * 60)).padStart(2, "0")}:` +
    `${String(Math.floor(((madridH * 3600) % 60))).padStart(2, "0")}`;

  const sessionOpen = getCurrentSession(now) != null;
  const offsetLabel = `UTC${offset >= 0 ? "+" : ""}${offset}`;

  return (
    <section className="timeline-card" aria-label="Sesiones de mercado · timeline 24h Madrid">
      <div className="timeline-header">
        <span className="timeline-title">Sesiones · 24h · Hora Madrid · {offsetLabel}</span>
        <div className="timeline-now">
          <span className="label">AHORA</span>
          <span className={`value num ${sessionOpen ? "is-open" : ""}`}>{madridTime}</span>
        </div>
      </div>

      <div className="timeline-track">
        {SESSIONS.flatMap(s => {
          const bands = projectToMadrid(s.openHourUTC, s.closeHourUTC, offset);
          return bands.map((b, i) => (
            <div
              key={`${s.id}-${i}`}
              className={`session session-${s.id}`}
              style={{ left: `${b.left}%`, width: `${b.width}%` }}
            >
              {i === 0 ? SESSION_LABEL[s.id] : ""}
            </div>
          ));
        })}

        {aplusBands.map((b, i) => (
          <div
            key={`overlap-${i}`}
            className="timeline-overlap-band"
            style={{ left: `${b.left}%`, width: `${b.width}%` }}
            aria-hidden="true"
          />
        ))}

        {aplusBands.length > 0 && (
          <span
            className={`overlap-badge ${aplusActive ? "is-active" : ""}`}
            style={{ left: `${aplusBands[0].left + aplusBands[0].width / 2}%` }}
            title={aplusOverlap.label}
          >
            ★ A+ OVERLAP
          </span>
        )}

        <div
          className="now-marker"
          style={{ left: `${nowPct}%` }}
          aria-label={`Ahora: ${madridTime} Madrid`}
        />
      </div>

      <KillZonesTrack zones={killZonesMadrid} />

      <div className="timeline-axis" aria-hidden="true">
        {HOUR_LABELS.map(h => (
          <div key={h} className="num">{String(h).padStart(2, "0")}</div>
        ))}
      </div>
    </section>
  );
}
