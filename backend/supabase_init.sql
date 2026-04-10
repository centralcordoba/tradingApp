-- Ejecutar en Supabase SQL Editor (https://supabase.com/dashboard → SQL Editor)
-- Crea la tabla de señales para el AI Trading Assistant

CREATE TABLE IF NOT EXISTS signals (
    id SERIAL PRIMARY KEY,
    received_at TEXT NOT NULL,
    signal_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    decision TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    result TEXT,
    exit_price DOUBLE PRECISION,
    pnl DOUBLE PRECISION,
    closed_at TEXT,
    source TEXT
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals (symbol);
CREATE INDEX IF NOT EXISTS idx_signals_decision ON signals (decision);
