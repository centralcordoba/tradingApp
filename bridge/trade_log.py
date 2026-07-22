"""Ledger local en CSV de las órdenes del bridge (real o dry-run).

Complementa el POST a la DB del backend (best-effort, puede fallar si Render está
caído): el CSV es local, siempre disponible y se analiza directo en Excel/pandas.

Una fila por trade: se hace append al abrir y se actualiza in-place (por ticket)
al tomar el parcial 1R y al cerrar. Todas las funciones son best-effort — un fallo
de I/O jamás debe frenar la operativa.
"""
from __future__ import annotations

import csv
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("bridge.tradelog")

_CSV = Path(__file__).parent / "trades.csv"
_lock = threading.Lock()

FIELDS = [
    "ticket", "opened_at", "symbol", "side", "source", "lots",
    "entry_price", "sl_price", "tp_price", "tp1_price", "risk_usd", "rrr",
    "strength", "score", "cross_state", "session", "dry_run",
    "partial_done", "be_moved",
    "result", "exit_price", "pnl_usd", "closed_at",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read() -> list[dict]:
    if not _CSV.exists():
        return []
    with _CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(rows: list[dict]):
    with _CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def log_open(rec: dict):
    """Append de una fila de apertura. `rec` con las claves de FIELDS (opened_at
    lo pone esta función)."""
    try:
        with _lock:
            new = not _CSV.exists()
            row = {k: rec.get(k, "") for k in FIELDS}
            row["opened_at"] = _now()
            row["partial_done"] = row.get("partial_done") or "0"
            row["be_moved"] = row.get("be_moved") or "0"
            with _CSV.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                if new:
                    w.writeheader()
                w.writerow(row)
    except Exception as e:
        log.warning("trade_log open: %s", e)


def log_partial(ticket, be_moved: bool = True):
    """Marca que se tomó el parcial 1R (y si se movió el SL a BE) en la fila abierta."""
    try:
        with _lock:
            rows = _read()
            for r in rows:
                if r.get("ticket") == str(ticket) and not r.get("closed_at"):
                    r["partial_done"] = "1"
                    r["be_moved"] = "1" if be_moved else "0"
            _write(rows)
    except Exception as e:
        log.warning("trade_log partial: %s", e)


def log_close(ticket, result: str, exit_price, pnl_usd):
    """Completa la fila abierta con el resultado del cierre."""
    try:
        with _lock:
            rows = _read()
            for r in rows:
                if r.get("ticket") == str(ticket) and not r.get("closed_at"):
                    r["result"] = result
                    r["exit_price"] = exit_price
                    r["pnl_usd"] = pnl_usd
                    r["closed_at"] = _now()
            _write(rows)
    except Exception as e:
        log.warning("trade_log close: %s", e)
