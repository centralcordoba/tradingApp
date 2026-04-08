"""SQLite storage para historial de señales, decisiones y resultados."""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "signals.db"


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(c, table: str, col: str, ddl: str) -> None:
    cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
    if col not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL,
                signal_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                decision TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL
            )
            """
        )
        # columnas añadidas en v0.2 (tracking de resultados)
        _ensure_column(c, "signals", "result", "result TEXT")            # WIN | LOSS | BE | NULL
        _ensure_column(c, "signals", "exit_price", "exit_price REAL")
        _ensure_column(c, "signals", "pnl", "pnl REAL")
        _ensure_column(c, "signals", "closed_at", "closed_at TEXT")
        _ensure_column(c, "signals", "source", "source TEXT")            # ai | heuristic


def save_signal(signal_dict: dict, response_dict: dict) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO signals (received_at, signal_json, response_json, decision, symbol, side, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.utcnow().isoformat(),
                json.dumps(signal_dict),
                json.dumps(response_dict),
                response_dict.get("decision", "?"),
                signal_dict.get("symbol", "?"),
                signal_dict.get("signal", "?"),
                response_dict.get("source", "heuristic"),
            ),
        )
        return cur.lastrowid


def list_signals(limit: int = 100, symbol: Optional[str] = None) -> List[dict]:
    with _conn() as c:
        if symbol:
            rows = c.execute(
                "SELECT * FROM signals WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "received_at": r["received_at"],
        "signal": json.loads(r["signal_json"]),
        "response": json.loads(r["response_json"]),
        "result": r["result"],
        "exit_price": r["exit_price"],
        "pnl": r["pnl"],
        "closed_at": r["closed_at"],
        "source": r["source"],
    }


def set_result(
    signal_id: int,
    result: str,
    exit_price: Optional[float] = None,
) -> Optional[dict]:
    """Marca el resultado de una señal. Calcula PnL automáticamente si no se pasa exit_price."""
    if result not in ("WIN", "LOSS", "BE"):
        raise ValueError("result debe ser WIN, LOSS o BE")

    with _conn() as c:
        row = c.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
        if row is None:
            return None

        sig = json.loads(row["signal_json"])
        side = (sig.get("signal") or "").upper()
        entry = float(sig.get("price", 0))
        sl = float(sig.get("sl", 0))
        tp = float(sig.get("tp", 0))

        # Si no nos dan exit_price, lo inferimos del resultado y la dirección
        if exit_price is None:
            if result == "WIN":
                exit_price = tp
            elif result == "LOSS":
                exit_price = sl
            else:  # BE
                exit_price = entry

        if side in ("LONG", "BUY"):
            pnl = exit_price - entry
        elif side in ("SHORT", "SELL"):
            pnl = entry - exit_price
        else:
            pnl = 0.0

        c.execute(
            "UPDATE signals SET result=?, exit_price=?, pnl=?, closed_at=? WHERE id=?",
            (result, exit_price, pnl, datetime.utcnow().isoformat(), signal_id),
        )
        row = c.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
        return _row_to_dict(row)


def distinct_symbols() -> List[str]:
    with _conn() as c:
        rows = c.execute("SELECT DISTINCT symbol FROM signals ORDER BY symbol").fetchall()
    return [r["symbol"] for r in rows if r["symbol"]]


def stats() -> dict:
    """Métricas agregadas para el dashboard."""
    with _conn() as c:
        rows = [_row_to_dict(r) for r in c.execute("SELECT * FROM signals").fetchall()]

    closed = [r for r in rows if r["result"] in ("WIN", "LOSS", "BE")]

    def _agg(items: list[dict]) -> dict:
        n = len(items)
        wins = sum(1 for r in items if r["result"] == "WIN")
        losses = sum(1 for r in items if r["result"] == "LOSS")
        be = sum(1 for r in items if r["result"] == "BE")
        pnl = sum((r["pnl"] or 0) for r in items)
        # win-rate excluye BE del denominador (más representativo)
        decided = wins + losses
        wr = (wins / decided) if decided else 0.0
        return {
            "n": n, "wins": wins, "losses": losses, "be": be,
            "win_rate": round(wr, 3), "pnl": round(pnl, 2),
        }

    def _bucket(key_fn) -> dict:
        out: dict[str, list] = {}
        for r in closed:
            k = key_fn(r) or "unknown"
            out.setdefault(k, []).append(r)
        return {k: _agg(v) for k, v in out.items()}

    return {
        "total_signals": len(rows),
        "closed": len(closed),
        "open": len(rows) - len(closed),
        "overall": _agg(closed),
        "by_symbol": _bucket(lambda r: r["signal"].get("symbol")),
        "by_decision": _bucket(lambda r: r["response"].get("decision")),
        "by_source": _bucket(lambda r: r["source"]),
        "by_quality": _bucket(lambda r: r["signal"].get("quality")),
        "by_side": _bucket(lambda r: r["signal"].get("signal")),
        "by_zona": _bucket(lambda r: r["signal"].get("zona")),
        "by_mtf": _bucket(lambda r: r["signal"].get("mtf")),
        "by_pattern": _bucket(lambda r: r["signal"].get("pattern")),
    }
