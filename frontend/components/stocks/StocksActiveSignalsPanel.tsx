"use client";

import { useMemo } from "react";
import { useStocksWatchlist } from "@/hooks/stocks/useStocksWatchlist";
import "./StocksActiveSignalsPanel.css";

type Props = {
  activeSymbol: string | null;
  onSelectSymbol: (symbol: string) => void;
};

const MIN_CONF = 0.4;

export function StocksActiveSignalsPanel({ activeSymbol, onSelectSymbol }: Props) {
  const { items } = useStocksWatchlist();

  const actionable = useMemo(() => {
    return items
      .filter(i =>
        (i.lastDecision === "BUY" || i.lastDecision === "SELL") &&
        (i.lastConfidence ?? 0) >= MIN_CONF
      )
      .sort((a, b) => (b.lastConfidence ?? 0) - (a.lastConfidence ?? 0))
      .slice(0, 5);
  }, [items]);

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Señales activas</span>
        <span className="panel-counter num">
          {actionable.length}/{items.length}
        </span>
      </div>

      {items.length === 0 ? (
        <div className="panel-empty">Tu watchlist está vacía.</div>
      ) : actionable.length === 0 ? (
        <div className="panel-empty">
          Sin señales accionables en tu watchlist (BUY/SELL con conf ≥ {Math.round(MIN_CONF * 100)}%).
        </div>
      ) : (
        actionable.map(item => {
          const isActive = item.symbol === activeSymbol;
          const dec = item.lastDecision!;
          const conf = item.lastConfidence ?? 0;
          const cls = `pill-${dec.toLowerCase()}`;
          return (
            <button
              key={item.symbol}
              type="button"
              className={`stocks-active-row ${isActive ? "is-active" : ""}`}
              onClick={() => onSelectSymbol(item.symbol)}
            >
              <span className="sa-symbol num">{item.symbol}</span>
              <span className={`sa-pill ${cls}`}>{dec}</span>
              <span className="sa-conf num">{Math.round(conf * 100)}%</span>
            </button>
          );
        })
      )}
    </div>
  );
}
