"use client";

import { useEffect, useMemo, useState } from "react";
import { useFavoritePairs } from "@/hooks/useFavoritePairs";
import { API } from "@/lib/api";
import { todayMadrid } from "@/lib/dates";
import { StocksSidebarSection } from "@/components/stocks/StocksSidebarSection";
import "./Sidebar.css";

type Props = {
  context: "forex" | "stocks";
  symbols: string[];
  filter: string;
  onFilterChange: (s: string) => void;
  /** Solo aplica si context==="stocks". */
  stocksActiveSymbol?: string | null;
  onStocksSelect?: (symbol: string) => void;
};

type CalendarEvent = {
  title: string;
  country: string;
  impact: string;
  date_utc: string;
  time_madrid: string;
};

const COUNTRY_FLAG: Record<string, string> = {
  USD: "🇺🇸", EUR: "🇪🇺", GBP: "🇬🇧", JPY: "🇯🇵",
  CHF: "🇨🇭", AUD: "🇦🇺", NZD: "🇳🇿", CAD: "🇨🇦",
  CNY: "🇨🇳", XAU: "🥇",
};

export function Sidebar({
  context,
  symbols,
  filter,
  onFilterChange,
  stocksActiveSymbol,
  onStocksSelect,
}: Props) {
  const [favorites, toggleFavorite] = useFavoritePairs();
  const [query, setQuery] = useState("");
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const fetchEvents = async () => {
      try {
        const today = todayMadrid();
        const r = await fetch(`${API}/news/calendar?date=${today}&impact=high`, { cache: "no-store" });
        const j = await r.json();
        if (alive) setEvents((j.events || []).slice(0, 6));
      } catch {
        if (alive) setEvents([]);
      } finally {
        if (alive) setLoading(false);
      }
    };
    fetchEvents();
    const id = setInterval(fetchEvents, 5 * 60_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const filteredPairs = useMemo(() => {
    const q = query.trim().toUpperCase();
    const list = q ? symbols.filter(s => s.toUpperCase().includes(q)) : symbols;
    return [...list].sort((a, b) => {
      const fa = favorites.has(a) ? 0 : 1;
      const fb = favorites.has(b) ? 0 : 1;
      if (fa !== fb) return fa - fb;
      return a.localeCompare(b);
    });
  }, [symbols, query, favorites]);

  return (
    <div className="sidebar-root">
      {context === "stocks" ? (
        <StocksSidebarSection
          activeSymbol={stocksActiveSymbol ?? null}
          onSelectSymbol={(s) => onStocksSelect?.(s)}
        />
      ) : (
        <div className="sb-section">
          <div className="sb-label">Pares</div>
          <input
            className="sb-search"
            placeholder="Buscar par…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Buscar par"
          />
          <button
            className={`pair-row pair-all ${filter === "ALL" ? "active" : ""}`}
            onClick={() => onFilterChange("ALL")}
          >
            <div className="pair-row-main">
              <div className="pair-name">Todos</div>
              <div className="pair-sub">{symbols.length} símbolos</div>
            </div>
          </button>
          {filteredPairs.map((pair) => {
            const isFav = favorites.has(pair);
            const isActive = filter === pair;
            return (
              <div key={pair} className={`pair-row ${isActive ? "active" : ""}`}>
                <button
                  className="pair-row-main"
                  onClick={() => onFilterChange(pair)}
                  aria-pressed={isActive}
                >
                  <div className="pair-name num">{pair}</div>
                </button>
                <button
                  className={`star ${isFav ? "filled" : ""}`}
                  onClick={(e) => { e.stopPropagation(); toggleFavorite(pair); }}
                  aria-label={isFav ? "Quitar de favoritos" : "Añadir a favoritos"}
                  title={isFav ? "Favorito" : "Marcar como favorito"}
                >
                  {isFav ? "★" : "☆"}
                </button>
              </div>
            );
          })}
          {filteredPairs.length === 0 && (
            <div className="pair-empty">Sin resultados</div>
          )}
        </div>
      )}

      <div className="sb-section sb-divider">
        <div className="sb-label">Calendario económico</div>
      </div>
      <div className="sb-events">
        {loading && <div className="sb-events-empty">Cargando…</div>}
        {!loading && events.length === 0 && (
          <div className="sb-events-empty">Sin eventos high-impact hoy</div>
        )}
        {!loading && events.map((e, i) => {
          const flag = COUNTRY_FLAG[e.country] || "🏳";
          const impactClass = e.impact === "high" ? "impact-high"
            : e.impact === "medium" ? "impact-med"
            : "impact-low";
          return (
            <div key={`${e.date_utc}-${i}`} className="event-item" title={e.title}>
              <span className="event-time num">{e.time_madrid}</span>
              <span className="event-name">
                <span className="event-flag" aria-hidden="true">{flag}</span>{" "}
                {e.title}
              </span>
              <span className={`impact-dot ${impactClass}`} aria-label={`Impacto ${e.impact}`} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
