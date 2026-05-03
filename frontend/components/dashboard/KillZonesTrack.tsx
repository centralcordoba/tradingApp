import type { KillZoneUTC } from "@/lib/killZones";

type KillZonesTrackProps = {
  /** Zonas ya proyectadas a UTC (vía getKillZonesUTC). */
  zones: KillZoneUTC[];
};

/**
 * Track de kill zones — escala 0-24h UTC, alineada con la timeline de
 * sesiones que la contiene. Cada kill zone se dibuja como un bloque
 * absolute-positioned coloreado por type.
 */
export function KillZonesTrack({ zones }: KillZonesTrackProps) {
  return (
    <div className="killzones-track" title="Kill zones · proyectadas a UTC">
      {zones.map((z, i) => {
        const start = Math.max(0, z.startUTC);
        const end = Math.min(24, z.endUTC);
        if (end <= start) return null;
        const left = (start / 24) * 100;
        const width = ((end - start) / 24) * 100;
        return (
          <div
            key={`${z.zone.label}-${i}`}
            className={`kz kz-${z.zone.type}`}
            style={{ left: `${left}%`, width: `${width}%` }}
            title={`${z.zone.label} · ${z.zone.note}`}
          />
        );
      })}
    </div>
  );
}
