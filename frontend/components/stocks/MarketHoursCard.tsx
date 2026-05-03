"use client";

import { useTick } from "@/hooks/useTick";
import { formatMinutes, getNyseSnapshot, type NyseStatus } from "@/lib/stocks/marketHours";
import "./MarketHoursCard.css";

const STATUS_LABEL: Record<NyseStatus, string> = {
  regular: "MERCADO ABIERTO",
  pre: "PRE-MERCADO",
  post: "POST-MERCADO",
  closed: "MERCADO CERRADO",
};

const STATUS_COLOR: Record<NyseStatus, string> = {
  regular: "mh-open",
  pre: "mh-pre",
  post: "mh-post",
  closed: "mh-closed",
};

export function MarketHoursCard() {
  const now = useTick(1000);
  const snap = now ? getNyseSnapshot(now) : null;

  if (!snap) {
    return <div className="mh-card mh-loading" aria-hidden />;
  }

  const cls = STATUS_COLOR[snap.status];
  const headline =
    snap.status === "regular"
      ? formatMinutes(snap.minutesUntilNext)
      : formatMinutes(snap.minutesUntilNext);
  const subline = snap.status === "regular"
    ? `Cierra a las 16:00 ET`
    : `${snap.nextEventLabel}`;

  return (
    <div className={`mh-card ${cls}`}>
      <div className="mh-header">
        <span className={`mh-pill ${cls}-pill`}>
          {STATUS_LABEL[snap.status]}
        </span>
        <span className="mh-et num" title="Hora actual de Nueva York">
          {snap.et} ET
        </span>
      </div>

      <div className="mh-time num">{headline}</div>
      <div className="mh-sub">{subline}</div>

      <div className="mh-schedule" aria-label="Horario NYSE/NASDAQ">
        <div className={`mh-slot ${snap.status === "pre" ? "is-active" : ""}`}>
          <span className="mh-slot-label">Pre</span>
          <span className="mh-slot-time num">04:00–09:30</span>
        </div>
        <div className={`mh-slot ${snap.status === "regular" ? "is-active" : ""}`}>
          <span className="mh-slot-label">Regular</span>
          <span className="mh-slot-time num">09:30–16:00</span>
        </div>
        <div className={`mh-slot ${snap.status === "post" ? "is-active" : ""}`}>
          <span className="mh-slot-label">Post</span>
          <span className="mh-slot-time num">16:00–20:00</span>
        </div>
      </div>
    </div>
  );
}
