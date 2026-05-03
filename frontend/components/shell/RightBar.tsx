"use client";

import { useTick } from "@/hooks/useTick";
import {
  getOverlapWindow,
  OVERLAPS,
  madridOffsetHours,
  utcToMadrid,
} from "@/lib/sessions";
import { formatCountdown } from "@/lib/dates";
import { MarketHoursCard } from "@/components/stocks/MarketHoursCard";
import { StocksActiveSignalsPanel } from "@/components/stocks/StocksActiveSignalsPanel";
import "./RightBar.css";

type OpenSignal = {
  id: number;
  received_at: string;
  signal: { symbol: string; signal: string; price: number };
  response: { decision: "ENTER" | "WAIT" | "AVOID" };
  pnl: number | null;
};

type Props = {
  context: "forex" | "stocks";
  openSignals: OpenSignal[];
  openCount: number;
  totalSignals: number;
  onPairClick?: (pair: string) => void;
  onRadarOpen?: () => void;
  /** Solo aplica si context==="stocks". */
  stocksActiveSymbol?: string | null;
  onStocksSelect?: (symbol: string) => void;
};

const APLUS_PAIRS = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"];

function relativeTime(iso: string, now: Date): string {
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "";
  const diffMs = now.getTime() - t;
  const min = Math.max(0, Math.floor(diffMs / 60_000));
  if (min < 1) return "ahora";
  if (min < 60) return `hace ${min}m`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h < 24) return `hace ${h}h ${String(m).padStart(2, "0")}m`;
  const d = Math.floor(h / 24);
  return `hace ${d}d`;
}

function decisionLabel(d: string): { label: string; cls: string } {
  if (d === "ENTER") return { label: "ENTER", cls: "side-buy" };
  if (d === "WAIT")  return { label: "WAIT",  cls: "side-wait" };
  return { label: "AVOID", cls: "side-sell" };
}

function sideClass(side: string): string {
  if (side === "LONG" || side === "BUY")  return "side-buy";
  if (side === "SHORT" || side === "SELL") return "side-sell";
  return "side-neutral";
}

export function RightBar({
  context,
  openSignals,
  openCount,
  totalSignals,
  onPairClick,
  onRadarOpen,
  stocksActiveSymbol,
  onStocksSelect,
}: Props) {
  const now = useTick(1000);
  const aplus = now ? getOverlapWindow(now) : { active: false, minutesUntil: 0, minutesLeft: 0 };
  const aplusOverlap = OVERLAPS.find(o => o.aplus)!;
  const offset = now ? madridOffsetHours(now) : 1;
  const aplusMadridFrom = utcToMadrid(aplusOverlap.fromUTC, offset);
  const aplusMadridTo = utcToMadrid(aplusOverlap.toUTC, offset);

  if (context === "stocks") {
    return (
      <div className="rightbar-root">
        <MarketHoursCard />

        <StocksActiveSignalsPanel
          activeSymbol={stocksActiveSymbol ?? null}
          onSelectSymbol={(s) => onStocksSelect?.(s)}
        />

        <div className="rb-disclaimer">
          Análisis técnico automatizado con fines educativos.
          No es asesoría financiera. Operar conlleva riesgo.
        </div>
      </div>
    );
  }

  const countdownText = aplus.active
    ? `Quedan ${aplus.minutesLeft}m`
    : formatCountdown(aplus.minutesUntil);

  const headline = aplus.active
    ? "Overlap LDN-NY · ACTIVO"
    : "Overlap LDN-NY · Mejor ventana del día";

  const limited = openSignals.slice(0, 5);

  return (
    <div className="rightbar-root">
      <div className={`next-setup ${aplus.active ? "is-active" : ""}`}>
        <div className="next-setup-label">
          <span className="star" aria-hidden="true">★</span>
          {aplus.active ? "VENTANA A+ ACTIVA" : "PRÓXIMO A+ SETUP"}
        </div>
        <div className="next-setup-time num">{countdownText}</div>
        <div className="next-setup-name">{headline}</div>
        <div className="next-setup-pairs">
          {APLUS_PAIRS.map((p) => (
            <button
              key={p}
              className="pair-chip"
              onClick={() => onPairClick?.(p)}
              title={`Filtrar por ${p}`}
            >
              {p}
            </button>
          ))}
        </div>
        <button
          className="next-setup-cta"
          onClick={onRadarOpen}
          aria-label="Abrir radar de setups"
        >
          Abrir radar →
        </button>
      </div>

      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">Señales activas</span>
          <span className="panel-counter num">
            {openCount} / {totalSignals}
          </span>
        </div>
        {limited.length === 0 ? (
          <div className="panel-empty">Sin señales abiertas</div>
        ) : limited.map((sig) => {
          const sideKey = sig.signal.signal;
          const dec = decisionLabel(sig.response.decision);
          const sideCls = sideClass(sideKey);
          const pnl = sig.pnl;
          const pnlClass = pnl == null ? "" : pnl >= 0 ? "pl-up" : "pl-down";
          const pnlText = pnl == null ? "—" : (pnl >= 0 ? `+${pnl.toFixed(1)}` : pnl.toFixed(1));
          return (
            <div key={sig.id} className="signal-row">
              <div className="signal-pair-line">
                <span className="num">{sig.signal.symbol}</span>
                <span className={`side-pill ${sideCls}`}>{sideKey}</span>
                <span className={`side-pill side-decision ${dec.cls}`}>{dec.label}</span>
              </div>
              <div className={`signal-pl num ${pnlClass}`}>{pnlText}</div>
              <div className="signal-entry">
                Entry <span className="num">{sig.signal.price}</span>
              </div>
              <div className="signal-meta">
                {now ? relativeTime(sig.received_at, now) : ""}
              </div>
            </div>
          );
        })}
      </div>

      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">Próxima ventana</span>
          <span className="panel-counter">
            {aplus.active ? "ahora" : "pendiente"}
          </span>
        </div>
        <div className="window-info">
          <div className="window-row">
            <span className="window-label">Estado</span>
            <span className={`window-value ${aplus.active ? "is-aplus" : ""}`}>
              {aplus.active ? "🏆 A+ ACTIVO" : "Esperando overlap"}
            </span>
          </div>
          <div className="window-row">
            <span className="window-label">Ventana</span>
            <span className="window-value num">
              {String(Math.floor(aplusMadridFrom)).padStart(2, "0")}:00–
              {String(Math.floor(aplusMadridTo)).padStart(2, "0")}:00 Madrid
            </span>
          </div>
          <div className="window-row">
            <span className="window-label">{aplus.active ? "Tiempo restante" : "Faltan"}</span>
            <span className="window-value num">
              {aplus.active ? `${aplus.minutesLeft}m` : countdownText}
            </span>
          </div>
        </div>
      </div>

      <div className="rb-disclaimer">
        Análisis técnico automatizado con fines educativos.
        No es asesoría financiera. Operar conlleva riesgo.
      </div>
    </div>
  );
}
