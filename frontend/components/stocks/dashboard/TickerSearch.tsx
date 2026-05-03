"use client";

import { useEffect, useRef, useState } from "react";
import { searchSymbols, StocksApiError } from "@/lib/stocks/twelvedata";
import type { SymbolMatch } from "@/lib/stocks/types";

type Props = {
  onSelect: (symbol: string) => void;
  /** Texto del placeholder. */
  placeholder?: string;
  /** Auto-focus al montar (útil cuando se abre modal o vista vacía). */
  autoFocus?: boolean;
};

const DEBOUNCE_MS = 300;
const MIN_QUERY_LEN = 1;

const COUNTRY_FLAG: Record<string, string> = {
  "United States": "🇺🇸",
  "Canada": "🇨🇦",
  "United Kingdom": "🇬🇧",
  "Germany": "🇩🇪",
  "France": "🇫🇷",
  "Spain": "🇪🇸",
  "Italy": "🇮🇹",
  "Netherlands": "🇳🇱",
  "Switzerland": "🇨🇭",
  "Japan": "🇯🇵",
  "China": "🇨🇳",
  "Hong Kong": "🇭🇰",
  "Australia": "🇦🇺",
  "Brazil": "🇧🇷",
  "Mexico": "🇲🇽",
  "India": "🇮🇳",
};

function flagFor(country: string): string {
  return COUNTRY_FLAG[country] || "🏳️";
}

export function TickerSearch({ onSelect, placeholder, autoFocus }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);

  const containerRef = useRef<HTMLDivElement>(null);
  const reqIdRef = useRef(0);

  // Debounced fetch
  useEffect(() => {
    const q = query.trim();
    if (q.length < MIN_QUERY_LEN) {
      setResults([]);
      setLoading(false);
      setError(null);
      return;
    }

    const myReq = ++reqIdRef.current;
    setLoading(true);
    setError(null);

    const handle = setTimeout(async () => {
      try {
        const matches = await searchSymbols(q);
        if (myReq !== reqIdRef.current) return;
        setResults(matches.slice(0, 10));
        setActiveIdx(-1);
      } catch (err) {
        if (myReq !== reqIdRef.current) return;
        const msg = err instanceof StocksApiError
          ? err.message
          : "Error al buscar tickers";
        setError(msg);
        setResults([]);
      } finally {
        if (myReq === reqIdRef.current) setLoading(false);
      }
    }, DEBOUNCE_MS);

    return () => clearTimeout(handle);
  }, [query]);

  // Click-outside cierra el dropdown
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, []);

  const handleSelect = (sym: string) => {
    onSelect(sym.toUpperCase());
    setQuery("");
    setResults([]);
    setOpen(false);
  };

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx(i => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx(i => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const idx = activeIdx >= 0 ? activeIdx : 0;
      const m = results[idx];
      if (m) handleSelect(m.symbol);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const showDropdown = Boolean(
    open && (loading || results.length > 0 || error || query.trim().length >= MIN_QUERY_LEN),
  );

  return (
    <div className="ticker-search" ref={containerRef}>
      <input
        type="text"
        className="ticker-search-input"
        placeholder={placeholder ?? "Buscar ticker (MSFT, AAPL, TSLA)…"}
        value={query}
        autoFocus={autoFocus}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKey}
        aria-autocomplete="list"
        aria-expanded={showDropdown}
      />
      {loading && <span className="ticker-search-spinner" aria-hidden="true" />}

      {showDropdown && (
        <div className="ticker-search-dropdown" role="listbox">
          {loading && (
            <div className="ticker-search-state">Buscando…</div>
          )}
          {!loading && error && (
            <div className="ticker-search-state ticker-search-error">{error}</div>
          )}
          {!loading && !error && results.length === 0 && query.trim().length >= MIN_QUERY_LEN && (
            <div className="ticker-search-state">Sin resultados para “{query}”</div>
          )}
          {!loading && results.map((m, i) => (
            <button
              key={`${m.symbol}-${m.exchange}-${i}`}
              type="button"
              role="option"
              aria-selected={i === activeIdx}
              className={`ticker-search-item ${i === activeIdx ? "is-active" : ""}`}
              onMouseEnter={() => setActiveIdx(i)}
              onClick={() => handleSelect(m.symbol)}
            >
              <span className="ticker-search-flag" aria-hidden="true">{flagFor(m.country)}</span>
              <span className="ticker-search-symbol num">{m.symbol}</span>
              <span className="ticker-search-name">{m.instrument_name}</span>
              <span className="ticker-search-exchange">{m.exchange}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
