"use client";

import { useEffect } from "react";
import type { InvestorProfile } from "@/lib/stocks/types";
import { useStockSignal } from "@/hooks/stocks/useStockSignal";
import { useStocksWatchlist } from "@/hooks/stocks/useStocksWatchlist";
import { TickerSearch } from "./TickerSearch";
import { SignalCard } from "./SignalCard";
import { ProfileBadge } from "../ProfileBadge";
import "./StocksDashboard.css";

type Props = {
  profile: InvestorProfile;
  onEditProfile: () => void;
  /** Controlado por el padre (Home) — compartido con la sidebar. */
  activeSymbol: string | null;
  onSymbolChange: (symbol: string | null) => void;
};

export function StocksDashboard({
  profile,
  onEditProfile,
  activeSymbol,
  onSymbolChange,
}: Props) {
  const { items: watchlist, addSymbol, hasSymbol, updateItem } = useStocksWatchlist();

  const {
    signal,
    loading,
    error,
    lastFetched,
    refetch,
  } = useStockSignal(activeSymbol, profile);

  // Cuando llega una signal nueva, cacheamos (decision, conf) en watchlist
  // si el símbolo está agregado.
  useEffect(() => {
    if (!signal || !activeSymbol) return;
    if (hasSymbol(activeSymbol)) {
      updateItem(activeSymbol, {
        lastDecision: signal.decision,
        lastConfidence: signal.confidence,
      });
    }
  }, [signal, activeSymbol, hasSymbol, updateItem]);

  const handleSelect = (symbol: string) => {
    onSymbolChange(symbol);
  };

  const handleAddToWatchlist = () => {
    if (!activeSymbol) return;
    addSymbol(activeSymbol);
  };

  const inWatchlist = activeSymbol ? hasSymbol(activeSymbol) : false;

  return (
    <div className="stocks-dashboard">
      <ProfileBadge profile={profile} onEdit={onEditProfile} />

      {/* Search */}
      <div className="stocks-search-row">
        <TickerSearch onSelect={handleSelect} />
        {activeSymbol && (
          <button
            type="button"
            className={`stocks-watchlist-toggle ${inWatchlist ? "is-added" : ""}`}
            onClick={handleAddToWatchlist}
            disabled={inWatchlist}
            title={inWatchlist ? "Ya está en tu watchlist" : "Añadir al watchlist"}
          >
            {inWatchlist ? "★ En watchlist" : "☆ Añadir al watchlist"}
          </button>
        )}
      </div>

      {/* Signal area */}
      {!activeSymbol ? (
        <EmptyState
          watchlistCount={watchlist.length}
          onPickFromWatchlist={watchlist.length > 0 ? () => onSymbolChange(watchlist[0].symbol) : undefined}
        />
      ) : (
        <SignalCard
          symbol={activeSymbol}
          signal={signal}
          loading={loading}
          error={error}
          lastFetched={lastFetched}
          profile={profile}
          onRefresh={refetch}
        />
      )}
    </div>
  );
}

function EmptyState({
  watchlistCount,
  onPickFromWatchlist,
}: {
  watchlistCount: number;
  onPickFromWatchlist?: () => void;
}) {
  return (
    <div className="stocks-empty">
      <div className="stocks-empty-icon" aria-hidden="true">🔎</div>
      <h2 className="stocks-empty-title">Buscá un ticker para empezar</h2>
      <p className="stocks-empty-text">
        Escribí el símbolo (MSFT, AAPL, TSLA…) o el nombre de la compañía
        en el buscador. La señal y el desglose aparecen acá.
      </p>
      {watchlistCount > 0 && onPickFromWatchlist && (
        <button
          type="button"
          className="stocks-empty-cta"
          onClick={onPickFromWatchlist}
        >
          O usá el primero de tu watchlist →
        </button>
      )}
    </div>
  );
}
