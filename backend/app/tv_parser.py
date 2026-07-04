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
    _CCY = {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "XAU", "XAG"}
    for m_sym in re.finditer(r"\b([A-Z]{6})\b", header):
        cand = m_sym.group(1)
        if cand[:3] in _CCY and cand[3:] in _CCY:
            out["symbol"] = cand
            break

    # Etiquetas que pueden contener ':' o sufijos ("BE 1:1", "SL[OB]") — se
    # matchean por prefijo, la más larga primero, en vez de partir por ':'.
    field_map = {
        "Entrada": "price",
        "BE 1:1": "be",
        "SL[OB]": "sl",
        "SL": "sl",
        "TP": "tp",
        "RSI": "rsi",
        "KZ": "kz",
        "MTF30": "mtf",
        "Zona": "zona",
        "Calidad": "quality",
        "Patron": "pattern",
    }
    _NUMERIC = {"price", "sl", "be", "tp", "rsi"}
    _CATEGORICAL = {"mtf", "zona", "quality"}
    keys_by_len = sorted(field_map, key=len, reverse=True)

    def _match_field(line: str) -> tuple[str, str] | None:
        for key in keys_by_len:
            if line.upper().startswith(key.upper()):
                rest = line[len(key):].lstrip()
                if rest.startswith(":"):
                    return field_map[key], rest[1:].strip()
        return None

    for line in lines[1:]:
        if ":" not in line:
            continue
        matched = _match_field(line)
        if matched:
            target, val = matched
            if target in _NUMERIC:
                n = _first_num(val)
                if n is not None:
                    out[target] = n
            elif target in _CATEGORICAL:
                # Limpia ✓/emoji/acentos residuales para no romper los Literal.
                clean = re.sub(r"[^A-ZÁÉÍÓÚ ]", "", val.upper()).strip()
                if clean:
                    out[target] = clean
            else:
                out[target] = val
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if key == "Confluencias":
            n = _first_num(val)
            if n is not None:
                out["conf"] = max(0, min(19, int(n)))
        elif key == "Vol":
            out["vol_high"] = "HIGH" in val.upper()
            n = _first_num(val)
            if n is not None:
                out["vol_ratio"] = n
        elif key == "FVG":
            out["fvg"] = "SI" in val.upper()

    return out
