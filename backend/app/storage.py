"""Storage dual: PostgreSQL (Supabase) si DATABASE_URL existe, SQLite local si no."""
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Optional

DATABASE_URL = os.getenv("DATABASE_URL")

# ---------------------------------------------------------------------------
# Capa de conexión
# ---------------------------------------------------------------------------

if DATABASE_URL:
    import psycopg2
    import psycopg2.pool
    import psycopg2.extras

    _pool: psycopg2.pool.SimpleConnectionPool | None = None

    def _get_pool() -> psycopg2.pool.SimpleConnectionPool:
        global _pool
        if _pool is None or _pool.closed:
            _pool = psycopg2.pool.SimpleConnectionPool(1, 5, DATABASE_URL)
        return _pool

    class _PgContext:
        """Context manager que saca conexión del pool y hace commit/rollback."""
        def __enter__(self):
            self.conn = _get_pool().getconn()
            self.conn.autocommit = False
            self.cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            return self.cur

        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
            self.cur.close()
            _get_pool().putconn(self.conn)

    def _db():
        return _PgContext()

    _PH = "%s"  # placeholder

else:
    DB_PATH = Path(__file__).resolve().parent.parent / "signals.db"

    class _SqliteContext:
        def __enter__(self):
            self.conn = sqlite3.connect(str(DB_PATH))
            self.conn.row_factory = sqlite3.Row
            self.cur = self.conn.cursor()
            return self.cur

        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
            self.cur.close()
            self.conn.close()

    def _db():
        return _SqliteContext()

    _PH = "?"  # placeholder


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_db() -> None:
    if DATABASE_URL:
        with _db() as cur:
            cur.execute("""
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
                )
            """)
            # Migración idempotente para journal + taken (PostgreSQL)
            for col, ddl in [
                ("journal_respected_plan", "TEXT"),
                ("journal_closed_early", "TEXT"),
                ("journal_emotion", "TEXT"),
                ("taken", "TEXT"),
            ]:
                cur.execute(f"ALTER TABLE signals ADD COLUMN IF NOT EXISTS {col} {ddl}")

            # Stocks: investor profile (singleton) + watchlist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS investor_profile (
                    id INTEGER PRIMARY KEY,
                    horizon TEXT NOT NULL,
                    risk_tolerance INTEGER NOT NULL,
                    capital_range TEXT NOT NULL,
                    experience TEXT NOT NULL,
                    sectors_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS stocks_watchlist (
                    symbol TEXT PRIMARY KEY,
                    last_decision TEXT,
                    last_confidence DOUBLE PRECISION,
                    added_at TEXT NOT NULL
                )
            """)
    else:
        with _db() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    received_at TEXT NOT NULL,
                    signal_json TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL
                )
            """)
            # columnas añadidas progresivamente (SQLite no soporta IF NOT EXISTS en ALTER)
            cur.execute("PRAGMA table_info(signals)")
            cols = {r["name"] for r in cur.fetchall()}
            for col, ddl in [
                ("result", "result TEXT"),
                ("exit_price", "exit_price REAL"),
                ("pnl", "pnl REAL"),
                ("closed_at", "closed_at TEXT"),
                ("source", "source TEXT"),
                ("journal_respected_plan", "journal_respected_plan TEXT"),
                ("journal_closed_early", "journal_closed_early TEXT"),
                ("journal_emotion", "journal_emotion TEXT"),
                ("taken", "taken TEXT"),
            ]:
                if col not in cols:
                    cur.execute(f"ALTER TABLE signals ADD COLUMN {ddl}")

            # Stocks: investor profile (singleton) + watchlist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS investor_profile (
                    id INTEGER PRIMARY KEY,
                    horizon TEXT NOT NULL,
                    risk_tolerance INTEGER NOT NULL,
                    capital_range TEXT NOT NULL,
                    experience TEXT NOT NULL,
                    sectors_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS stocks_watchlist (
                    symbol TEXT PRIMARY KEY,
                    last_decision TEXT,
                    last_confidence REAL,
                    added_at TEXT NOT NULL
                )
            """)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def save_signal(signal_dict: dict, response_dict: dict) -> int:
    ph = _PH
    with _db() as cur:
        sql = (
            f"INSERT INTO signals (received_at, signal_json, response_json, decision, symbol, side, source) "
            f"VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})"
        )
        params = (
            datetime.utcnow().isoformat(),
            json.dumps(signal_dict),
            json.dumps(response_dict),
            response_dict.get("decision", "?"),
            signal_dict.get("symbol", "?"),
            signal_dict.get("signal", "?"),
            response_dict.get("source", "heuristic"),
        )
        if DATABASE_URL:
            cur.execute(sql + " RETURNING id", params)
            return cur.fetchone()["id"]
        else:
            cur.execute(sql, params)
            return cur.lastrowid


def count_signals(symbol: Optional[str] = None) -> int:
    ph = _PH
    with _db() as cur:
        if symbol:
            _exec(cur, f"SELECT COUNT(*) AS cnt FROM signals WHERE symbol = {ph}", (symbol,))
        else:
            _exec(cur, "SELECT COUNT(*) AS cnt FROM signals", ())
        row = _fetchall(cur)
    if not row:
        return 0
    r = row[0]
    return r["cnt"] if isinstance(r, dict) else r[0]


def list_signals(limit: int = 100, offset: int = 0, symbol: Optional[str] = None) -> List[dict]:
    ph = _PH
    with _db() as cur:
        if symbol:
            sql = f"SELECT * FROM signals WHERE symbol = {ph} ORDER BY id DESC LIMIT {ph} OFFSET {ph}"
            _exec(cur, sql, (symbol, limit, offset))
        else:
            sql = f"SELECT * FROM signals ORDER BY id DESC LIMIT {ph} OFFSET {ph}"
            _exec(cur, sql, (limit, offset))
        rows = _fetchall(cur)
    return [_row_to_dict(r) for r in rows]


def set_result(
    signal_id: int,
    result: str,
    exit_price: Optional[float] = None,
    taken: Optional[str] = None,
    journal_respected_plan: Optional[str] = None,
    journal_closed_early: Optional[str] = None,
    journal_emotion: Optional[str] = None,
) -> Optional[dict]:
    if result not in ("WIN", "LOSS", "BE"):
        raise ValueError("result debe ser WIN, LOSS o BE")
    if taken is not None and taken not in ("yes", "no"):
        raise ValueError("taken debe ser 'yes', 'no' o None")

    ph = _PH
    with _db() as cur:
        _exec(cur, f"SELECT * FROM signals WHERE id = {ph}", (signal_id,))
        row = _fetchone(cur)
        if row is None:
            return None

        sig = json.loads(row["signal_json"])
        side = (sig.get("signal") or "").upper()
        entry = float(sig.get("price", 0))
        sl = float(sig.get("sl", 0))
        tp = float(sig.get("tp", 0))

        if exit_price is None:
            if result == "WIN":
                exit_price = tp
            elif result == "LOSS":
                exit_price = sl
            else:
                exit_price = entry

        if side in ("LONG", "BUY"):
            pnl = exit_price - entry
        elif side in ("SHORT", "SELL"):
            pnl = entry - exit_price
        else:
            pnl = 0.0

        _exec(
            cur,
            f"UPDATE signals SET result={ph}, exit_price={ph}, pnl={ph}, closed_at={ph}, "
            f"taken={ph}, journal_respected_plan={ph}, journal_closed_early={ph}, journal_emotion={ph} "
            f"WHERE id={ph}",
            (
                result, exit_price, pnl, datetime.utcnow().isoformat(),
                taken, journal_respected_plan, journal_closed_early, journal_emotion,
                signal_id,
            ),
        )
        _exec(cur, f"SELECT * FROM signals WHERE id = {ph}", (signal_id,))
        row = _fetchone(cur)
        return _row_to_dict(row)


def delete_signal(signal_id: int) -> bool:
    ph = _PH
    with _db() as cur:
        cur.execute(f"DELETE FROM signals WHERE id = {ph}", (signal_id,))
        return cur.rowcount > 0


def delete_all_signals(symbol: Optional[str] = None) -> int:
    ph = _PH
    with _db() as cur:
        if symbol:
            cur.execute(f"DELETE FROM signals WHERE symbol = {ph}", (symbol,))
        else:
            cur.execute("DELETE FROM signals")
        return cur.rowcount or 0


def distinct_symbols() -> List[str]:
    with _db() as cur:
        _exec(cur, "SELECT DISTINCT symbol FROM signals ORDER BY symbol", ())
        rows = _fetchall(cur)
    return [r["symbol"] for r in rows if r["symbol"]]


def stats() -> dict:
    with _db() as cur:
        _exec(cur, "SELECT * FROM signals", ())
        rows = [_row_to_dict(r) for r in _fetchall(cur)]

    closed = [r for r in rows if r["result"] in ("WIN", "LOSS", "BE")]
    taken = [r for r in closed if r.get("taken") == "yes"]
    rated = [r for r in closed if r.get("taken") == "no"]

    def _agg(items: list[dict]) -> dict:
        n = len(items)
        wins = sum(1 for r in items if r["result"] == "WIN")
        losses = sum(1 for r in items if r["result"] == "LOSS")
        be = sum(1 for r in items if r["result"] == "BE")
        pnl = sum((r["pnl"] or 0) for r in items)
        decided = wins + losses
        wr = (wins / decided) if decided else 0.0
        return {
            "n": n, "wins": wins, "losses": losses, "be": be,
            "win_rate": round(wr, 3), "pnl": round(pnl, 2),
        }

    def _bucket(key_fn, items=None) -> dict:
        out: dict[str, list] = {}
        for r in items if items is not None else closed:
            k = key_fn(r) or "unknown"
            out.setdefault(k, []).append(r)
        return {k: _agg(v) for k, v in out.items()}

    execution_rate = round(len(taken) / len(closed), 3) if closed else 0.0

    return {
        "total_signals": len(rows),
        "closed": len(closed),
        "open": len(rows) - len(closed),
        "overall": _agg(closed),
        "overall_taken": _agg(taken),
        "overall_rated": _agg(rated),
        "execution_rate": execution_rate,
        "by_symbol": _bucket(lambda r: r["signal"].get("symbol")),
        "by_decision": _bucket(lambda r: r["response"].get("decision")),
        "by_source": _bucket(lambda r: r["source"]),
        "by_quality": _bucket(lambda r: r["signal"].get("quality")),
        "by_side": _bucket(lambda r: r["signal"].get("signal")),
        "by_zona": _bucket(lambda r: r["signal"].get("zona")),
        "by_mtf": _bucket(lambda r: r["signal"].get("mtf")),
        "by_pattern": _bucket(lambda r: r["signal"].get("pattern")),
        "by_emotion": _bucket(lambda r: r.get("journal_emotion"), items=taken),
        "by_respected_plan": _bucket(lambda r: r.get("journal_respected_plan"), items=taken),
    }


# ---------------------------------------------------------------------------
# Helpers internos para abstraer diferencias sqlite3.Row vs RealDictCursor
# ---------------------------------------------------------------------------

def _exec(cur, sql, params):
    cur.execute(sql, params)


def _fetchall(cur) -> list:
    return cur.fetchall()


def _fetchone(cur):
    return cur.fetchone()


def _row_to_dict(r) -> dict:
    d = dict(r)
    return {
        "id": d["id"],
        "received_at": d["received_at"],
        "signal": json.loads(d["signal_json"]),
        "response": json.loads(d["response_json"]),
        "result": d.get("result"),
        "exit_price": d.get("exit_price"),
        "pnl": d.get("pnl"),
        "closed_at": d.get("closed_at"),
        "source": d.get("source"),
        "taken": d.get("taken"),
        "journal_respected_plan": d.get("journal_respected_plan"),
        "journal_closed_early": d.get("journal_closed_early"),
        "journal_emotion": d.get("journal_emotion"),
    }


# ---------------------------------------------------------------------------
# Stocks: investor profile (singleton) + watchlist
# ---------------------------------------------------------------------------

def _profile_row_to_dict(r) -> dict:
    d = dict(r)
    sectors_raw = d.get("sectors_json") or "[]"
    try:
        sectors = json.loads(sectors_raw)
    except (TypeError, ValueError):
        sectors = []
    return {
        "horizon": d["horizon"],
        "riskTolerance": int(d["risk_tolerance"]),
        "capitalRange": d["capital_range"],
        "experience": d["experience"],
        "sectors": sectors if isinstance(sectors, list) else [],
        "updated_at": d.get("updated_at"),
    }


def get_investor_profile() -> Optional[dict]:
    ph = _PH
    with _db() as cur:
        _exec(cur, f"SELECT * FROM investor_profile WHERE id = {ph}", (1,))
        row = _fetchone(cur)
    return _profile_row_to_dict(row) if row else None


def save_investor_profile(profile: dict) -> dict:
    """Upsert del perfil del inversor (siempre id=1)."""
    payload = (
        profile["horizon"],
        int(profile["riskTolerance"]),
        profile["capitalRange"],
        profile["experience"],
        json.dumps(profile.get("sectors") or []),
        datetime.utcnow().isoformat(),
    )
    ph = _PH
    with _db() as cur:
        if DATABASE_URL:
            cur.execute(
                f"INSERT INTO investor_profile "
                f"(id, horizon, risk_tolerance, capital_range, experience, sectors_json, updated_at) "
                f"VALUES (1, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}) "
                f"ON CONFLICT (id) DO UPDATE SET "
                f"horizon = EXCLUDED.horizon, "
                f"risk_tolerance = EXCLUDED.risk_tolerance, "
                f"capital_range = EXCLUDED.capital_range, "
                f"experience = EXCLUDED.experience, "
                f"sectors_json = EXCLUDED.sectors_json, "
                f"updated_at = EXCLUDED.updated_at",
                payload,
            )
        else:
            cur.execute(
                f"INSERT OR REPLACE INTO investor_profile "
                f"(id, horizon, risk_tolerance, capital_range, experience, sectors_json, updated_at) "
                f"VALUES (1, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})",
                payload,
            )
    return get_investor_profile() or {}


def clear_investor_profile() -> None:
    ph = _PH
    with _db() as cur:
        cur.execute(f"DELETE FROM investor_profile WHERE id = {ph}", (1,))


def _watchlist_row_to_dict(r) -> dict:
    d = dict(r)
    return {
        "symbol": d["symbol"],
        "lastDecision": d.get("last_decision"),
        "lastConfidence": d.get("last_confidence"),
        "addedAt": d["added_at"],
    }


def get_stocks_watchlist() -> List[dict]:
    with _db() as cur:
        _exec(cur, "SELECT * FROM stocks_watchlist ORDER BY added_at ASC", ())
        rows = _fetchall(cur)
    return [_watchlist_row_to_dict(r) for r in rows]


def add_to_stocks_watchlist(symbol: str) -> List[dict]:
    sym = (symbol or "").upper().strip()
    if not sym:
        return get_stocks_watchlist()
    ph = _PH
    now = datetime.utcnow().isoformat()
    with _db() as cur:
        if DATABASE_URL:
            cur.execute(
                f"INSERT INTO stocks_watchlist (symbol, last_decision, last_confidence, added_at) "
                f"VALUES ({ph}, NULL, NULL, {ph}) "
                f"ON CONFLICT (symbol) DO NOTHING",
                (sym, now),
            )
        else:
            cur.execute(
                f"INSERT OR IGNORE INTO stocks_watchlist (symbol, last_decision, last_confidence, added_at) "
                f"VALUES ({ph}, NULL, NULL, {ph})",
                (sym, now),
            )
    return get_stocks_watchlist()


def remove_from_stocks_watchlist(symbol: str) -> List[dict]:
    sym = (symbol or "").upper().strip()
    ph = _PH
    with _db() as cur:
        cur.execute(f"DELETE FROM stocks_watchlist WHERE symbol = {ph}", (sym,))
    return get_stocks_watchlist()


def update_stocks_watchlist_item(
    symbol: str,
    last_decision: Optional[str] = None,
    last_confidence: Optional[float] = None,
) -> List[dict]:
    sym = (symbol or "").upper().strip()
    if not sym:
        return get_stocks_watchlist()
    ph = _PH
    with _db() as cur:
        cur.execute(
            f"UPDATE stocks_watchlist SET last_decision = {ph}, last_confidence = {ph} "
            f"WHERE symbol = {ph}",
            (last_decision, last_confidence, sym),
        )
    return get_stocks_watchlist()
