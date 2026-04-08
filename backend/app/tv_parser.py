"""
Parser tolerante para alertas de TradingView.

El Pine v8.9.1 puede emitir:
  1. JSON limpio (formato preferido tras la modificación):
     {"signal":"LONG","symbol":"XAUUSD","price":2345.6, ...}
  2. Texto multilínea legacy:
     LONG XAUUSD v8.3
     Entrada: 2345.60
     SL: 2340.00 ($5.6)
     ...
"""
import json
import re
from typing import Any


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _first_num(text: str) -> float | None:
    m = _NUM_RE.search(text)
    return float(m.group()) if m else None


def parse_payload(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    raw = raw.strip()

    # 1) JSON directo
    if raw.startswith("{"):
        return json.loads(raw)

    # 2) Texto legacy multilínea
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        raise ValueError("Payload vacío")

    out: dict[str, Any] = {}
    header = lines[0].upper()
    if "LONG" in header:
        out["signal"] = "LONG"
    elif "SHORT" in header:
        out["signal"] = "SHORT"
    if "XAUUSD" in header:
        out["symbol"] = "XAUUSD"

    field_map = {
        "Entrada": "price",
        "SL": "sl",
        "BE 1:1": "be",
        "TP": "tp",
        "RSI": "rsi",
        "KZ": "kz",
        "MTF30": "mtf",
        "Zona": "zona",
        "Calidad": "quality",
        "Patron": "pattern",
    }

    for line in lines[1:]:
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if key in field_map:
            target = field_map[key]
            if target in ("price", "sl", "be", "tp", "rsi"):
                n = _first_num(val)
                if n is not None:
                    out[target] = n
            else:
                out[target] = val
        elif key == "Confluencias":
            n = _first_num(val)
            if n is not None:
                out["conf"] = int(n)
        elif key == "Vol":
            out["vol_high"] = "HIGH" in val.upper()
            n = _first_num(val)
            if n is not None:
                out["vol_ratio"] = n
        elif key == "FVG":
            out["fvg"] = "SI" in val.upper()

    return out
