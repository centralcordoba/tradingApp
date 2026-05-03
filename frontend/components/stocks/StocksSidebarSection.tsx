"use client";

import { useStocksWatchlist } from "@/hooks/stocks/useStocksWatchlist";
import { TickerSearch } from "./dashboard/TickerSearch";
import "./StocksSidebarSection.css";

type Props = {
  activeSymbol: string | null;
  onSelectSymbol: (symbol: string) => void;
};

export function StocksSidebarSection({ activeSymbol, onSelectSymbol }: Props) {
  const { items, isLoaded, addSymbol, removeSymbol } = useStocksWatchlist();

  const handlePicked = (symbol: string) => {
    addSymbol(symbol);
    onSelectSymbol(symbol);
  };

  return (
    <div className="stocks-sidebar">
      <div className="sb-section">
        <div className="sb-label">Tickers</div>
        <div className="stocks-sidebar-search">
          <TickerSearch
            placeholder="Buscar ticker…"
            onSelect={handlePicked}
          />
        </div>

        {!isLoaded ? (
          <div className="stocks-sidebar-empty">Cargando…</div>
        ) : items.length === 0 ? (
          <div className="stocks-sidebar-empty">
            Tu watchlist está vacía. Buscá un ticker arriba para empezar.
          </div>
        ) : (
          <div className="stocks-sidebar-list">
            {items.map((item) => {
              const isActive = item.symbol === activeSymbol;
              const decisionCls = item.lastDecision
                ? `pill-${item.lastDecision.toLowerCase()}`
                : "";
              return (
                <div
                  key={item.symbol}
                  className={`stocks-sidebar-item ${isActive ? "is-active" : ""}`}
                >
                  <button
                    type="button"
                    className="stocks-sidebar-item-main"
                    onClick={() => onSelectSymbol(item.symbol)}
                    aria-pressed={isActive}
                  >
                    <span className="stocks-sidebar-symbol num">{item.symbol}</span>
                    {item.lastDecision && (
                      <span className={`stocks-sidebar-pill ${decisionCls}`}>
                        {item.lastDecision}
                      </span>
                    )}
                    {item.lastConfidence != null && (
                      <span className="stocks-sidebar-conf num">
                        {Math.round(item.lastConfidence * 100)}%
                      </span>
                    )}
                  </button>
                  <button
                    type="button"
                    className="stocks-sidebar-remove"
                    onClick={(e) => { e.stopPropagation(); removeSymbol(item.symbol); }}
                    aria-label={`Quitar ${item.symbol}`}
                    title="Quitar del watchlist"
                  >
                    ✕
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
