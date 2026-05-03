"use client";

import { useEffect, useState } from "react";
import { getQuote, StocksApiError } from "@/lib/stocks/twelvedata";
import type {
  Decision,
  InvestorProfile,
  MarketStatus,
  Quote,
  Signal,
} from "@/lib/stocks/types";
import { IndicatorBreakdown } from "./IndicatorBreakdown";
import "./SignalCard.css";

type Props = {
  symbol: string;
  signal: Signal | null;
  loading: boolean;
  error: { code: string; message: string } | null;
  /** ISO de la última carga exitosa. */
  lastFetched: string | null;
  profile: InvestorProfile;
  onRefresh: () => void;
};

const DECISION_LABEL: Record<Decision, string> = {
  BUY: "COMPRAR",
  SELL: "VENDER",
  HOLD: "ESPERAR",
};
const DECISION_CLS: Record<Decision, string> = {
  BUY: "decision-buy",
  SELL: "decision-sell",
  HOLD: "decision-hold",
};

const STATUS_LABEL: Record<MarketStatus, string> = {
  open: "MERCADO ABIERTO",
  closed: "MERCADO CERRADO",
  pre: "PRE-MERCADO",
  post: "POST-MERCADO",
};
const STATUS_CLS: Record<MarketStatus, string> = {
  open: "ms-open",
  closed: "ms-closed",
  pre: "ms-pre",
  post: "ms-post",
};

function relativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "";
  const diff = Math.max(0, Date.now() - t);
  const sec = Math.floor(diff / 1000);
  if (sec < 5) return "ahora";
  if (sec < 60) return `hace ${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `hace ${min}m`;
  const h = Math.floor(min / 60);
  return `hace ${h}h`;
}

function errorMessage(code: string, message: string): string {
  if (code === "NOT_FOUND") return `Ticker no encontrado: ${message}`;
  if (code === "RATE_LIMIT") {
    return "Twelve Data limita 8 consultas por minuto en el plan free. Esperá ~30 segundos y reintentá. Si pasa seguido, puede ser que el cap diario (800 créditos) se haya alcanzado.";
  }
  if (code === "NETWORK") return "Error de red — revisá tu conexión";
  return message;
}

export function SignalCard({
  symbol,
  signal,
  loading,
  error,
  lastFetched,
  profile,
  onRefresh,
}: Props) {
  const [quote, setQuote] = useState<Quote | null>(null);
  const [breakdownOpen, setBreakdownOpen] = useState(false);
  const [, forceTick] = useState(0);

  // Re-render cada 10s para mantener "hace Xs" actualizado.
  useEffect(() => {
    const id = setInterval(() => forceTick(x => x + 1), 10_000);
    return () => clearInterval(id);
  }, []);

  // Quote separado del bundle para mostrar precio + cambio actuales con
  // su propio TTL del cache (5 min).
  useEffect(() => {
    let alive = true;
    setQuote(null);
    if (!symbol) return;
    (async () => {
      try {
        const q = await getQuote(symbol);
        if (alive) setQuote(q);
      } catch (err) {
        if (err instanceof StocksApiError) {
          // No-op: el error mayor se muestra ya por la signal.
        }
      }
    })();
    return () => { alive = false; };
  }, [symbol, lastFetched]);

  if (error) {
    return (
      <div className="signal-card signal-card-error">
        <div className="signal-card-header">
          <div className="signal-card-symbol num">{symbol}</div>
        </div>
        <div className="signal-card-error-body">
          <div className="signal-card-error-icon" aria-hidden="true">⚠</div>
          <div className="signal-card-error-msg">
            {errorMessage(error.code, error.message)}
          </div>
          <button
            type="button"
            className="signal-card-retry"
            onClick={onRefresh}
          >
            Reintentar
          </button>
        </div>
      </div>
    );
  }

  if (loading || !signal) {
    return (
      <div className="signal-card signal-card-loading">
        <div className="signal-card-header">
          <div className="signal-card-symbol num">{symbol}</div>
          <div className="signal-card-status-pill ms-loading">EVALUANDO…</div>
        </div>
        <div className="signal-card-loading-body">
          <div className="signal-card-skeleton" />
          <div className="signal-card-skeleton signal-card-skeleton-bar" />
          <div className="signal-card-skeleton signal-card-skeleton-line" />
        </div>
      </div>
    );
  }

  const decisionCls = DECISION_CLS[signal.decision];
  const decisionLabel = DECISION_LABEL[signal.decision];
  const confPct = Math.round(signal.confidence * 100);

  const price = quote?.price ?? null;
  const change = quote?.change ?? null;
  const changePct = quote?.percent_change ?? null;
  const changePos = (change ?? 0) >= 0;
  const status: MarketStatus = quote?.marketStatus ?? signal.marketStatus;

  return (
    <div className={`signal-card ${decisionCls}`}>
      {/* Header */}
      <div className="signal-card-header">
        <div className="signal-card-id">
          <div className="signal-card-symbol num">{signal.symbol}</div>
          {price !== null && (
            <div className="signal-card-price">
              <span className="signal-card-price-num num">${price.toFixed(2)}</span>
              {change !== null && changePct !== null && (
                <span className={`signal-card-change num ${changePos ? "ch-up" : "ch-down"}`}>
                  {changePos ? "+" : ""}{change.toFixed(2)} ({changePos ? "+" : ""}{changePct.toFixed(2)}%)
                </span>
              )}
            </div>
          )}
        </div>
        <div className={`signal-card-status-pill ${STATUS_CLS[status]}`}>
          {STATUS_LABEL[status]}
        </div>
      </div>

      {/* Decisión grande */}
      <div className="signal-card-decision">
        <div className={`decision-label ${decisionCls}`}>{decisionLabel}</div>
        <div className="decision-meta">
          Intervalo <b className="num">{signal.interval}</b>
        </div>
      </div>

      {/* Confianza */}
      <div className="signal-card-confidence">
        <div className="confidence-label-row">
          <span className="confidence-label">Confianza</span>
          <span className="confidence-value num">{confPct}%</span>
        </div>
        <div className="confidence-bar">
          <div
            className={`confidence-bar-fill ${decisionCls}-bar`}
            style={{ width: `${Math.max(0, Math.min(100, confPct))}%` }}
          />
        </div>
      </div>

      {/* Top reasons */}
      {signal.topReasons.length > 0 && (
        <ul className="signal-card-reasons">
          {signal.topReasons.map((r, i) => (
            <li key={i} className="signal-card-reason">{r}</li>
          ))}
        </ul>
      )}

      {/* Toggle breakdown */}
      <button
        type="button"
        className="signal-card-expand"
        onClick={() => setBreakdownOpen(b => !b)}
        aria-expanded={breakdownOpen}
      >
        {breakdownOpen ? "▲ Ocultar desglose" : "▼ Ver desglose completo"}
      </button>

      {breakdownOpen && (
        <IndicatorBreakdown votes={signal.votes} horizon={profile.horizon} />
      )}

      {/* Footer */}
      <div className="signal-card-footer">
        <div className="signal-card-fresh">
          {lastFetched
            ? <>Última actualización: <span className="num">{relativeTime(lastFetched)}</span></>
            : "—"}
        </div>
        <button
          type="button"
          className="signal-card-refresh"
          onClick={onRefresh}
          aria-label="Refrescar"
          title="Refrescar"
        >
          ↻
        </button>
      </div>

      <p className="signal-card-disclaimer">
        Análisis técnico automatizado con fines educativos. No constituye
        asesoría financiera. Operar en mercados conlleva riesgo de
        pérdida de capital.
      </p>
    </div>
  );
}
