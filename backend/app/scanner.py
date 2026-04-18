"""Scanner independiente: analiza pares en vivo desde Twelve Data.

No depende de las señales del Pine — hace su propia lectura técnica multi-factor
y devuelve los pares rankeados por confluencia.

Fuente: api.twelvedata.com (free tier 800 créditos/día, 8 req/min).
Requiere env var TWELVEDATA_API_KEY.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_PAIRS = [
    "XAUUSD",  # plata (XAGUSD) requiere plan Grow en Twelve Data, no incluida
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
    "AUDUSD", "NZDUSD", "USDCAD",
    "EURJPY", "GBPJPY", "EURGBP",
]

TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
TWELVEDATA_BASE = "https://api.twelvedata.com/time_series"

# Twelve Data usa slash: "EUR/USD", "XAU/USD"
def _td_symbol(pair: str) -> str:
    p = pair.upper().replace("/", "").replace("-", "")
    if p.startswith("XAU"):
        return "XAU/USD"
    if p.startswith("XAG"):
        return "XAG/USD"
    if len(p) == 6:
        return f"{p[:3]}/{p[3:]}"
    return p

# TTL alto para proteger el presupuesto del plan free (800 créditos/día)
CACHE_TTL_SECONDS = 300  # 5 min
_cache: dict[str, tuple[float, dict]] = {}
_last_error: str = ""


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_chart(pair: str, interval: str = "15min", outputsize: int = 200) -> Optional[dict]:
    """Descarga OHLC de Twelve Data. None si falla."""
    global _last_error
    if not TWELVEDATA_API_KEY:
        _last_error = "TWELVEDATA_API_KEY no configurada"
        return None

    params = {
        "symbol": _td_symbol(pair),
        "interval": interval,
        "outputsize": str(outputsize),
        "order": "ASC",  # oldest first, los indicadores calculan sobre series cronológicas
        "apikey": TWELVEDATA_API_KEY,
    }
    url = f"{TWELVEDATA_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (AI Trading Assistant Scanner)",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:250]
        except Exception:
            pass
        _last_error = f"{pair}: HTTP {e.code} — {body or e.reason}"
        return None
    except Exception as e:
        _last_error = f"{pair}: {type(e).__name__}: {e}"
        return None

    if isinstance(data, dict) and data.get("status") == "error":
        _last_error = f"{pair}: {data.get('message', 'error')}"
        return None
    return data


def _parse_ohlc(raw: dict) -> Optional[dict]:
    """Extrae listas opens/closes/highs/lows/timestamps del formato Twelve Data."""
    values = raw.get("values") if isinstance(raw, dict) else None
    if not values:
        return None

    out_ts, out_o, out_c, out_h, out_l = [], [], [], [], []
    for v in values:
        try:
            c = float(v["close"])
        except (TypeError, ValueError, KeyError):
            continue
        try:
            o = float(v.get("open", c))
        except (TypeError, ValueError):
            o = c
        try:
            h = float(v.get("high", c))
        except (TypeError, ValueError):
            h = c
        try:
            l = float(v.get("low", c))
        except (TypeError, ValueError):
            l = c
        out_ts.append(v.get("datetime"))
        out_o.append(o)
        out_c.append(c)
        out_h.append(h)
        out_l.append(l)

    if len(out_c) < 60:
        return None

    return {"ts": out_ts, "open": out_o, "close": out_c, "high": out_h, "low": out_l}


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------

def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    # Prepend None-placeholder para alinear índices: longitud = len(values) - period + 1
    return out


def _rsi(values: list[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(values)):
        diff = values[i] - values[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_pair(pair: str, ohlc: dict) -> dict:
    """Evalúa 7 factores direccionales + salud. Devuelve card completa."""
    closes = ohlc["close"]
    highs = ohlc["high"]
    lows = ohlc["low"]

    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200) if len(closes) >= 200 else []

    last_close = closes[-1]
    prev_close = closes[-2] if len(closes) > 1 else last_close
    day_open = closes[-96] if len(closes) >= 96 else closes[0]
    change_pct = ((last_close - day_open) / day_open) * 100 if day_open else 0.0

    rsi = _rsi(closes, 14)
    atr = _atr(highs, lows, closes, 14)

    # Posición en rango últimas 50 velas
    lookback = closes[-50:]
    rng_hi = max(lookback)
    rng_lo = min(lookback)
    range_pos = (last_close - rng_lo) / (rng_hi - rng_lo) if rng_hi > rng_lo else 0.5

    # Impulso 5 velas
    mom_ret = (last_close - closes[-6]) / closes[-6] if len(closes) >= 6 and closes[-6] else 0.0

    factors = []

    # 1. EMA9 vs EMA21 (trend corto)
    if ema9 and ema21:
        val = 1 if ema9[-1] > ema21[-1] else -1
        factors.append({
            "key": "ema_short",
            "label": "EMA9 vs EMA21",
            "desc": "Tendencia corta alcista" if val > 0 else "Tendencia corta bajista",
            "value": val,
        })

    # 2. EMA21 vs EMA50 (trend medio)
    if ema21 and ema50:
        val = 1 if ema21[-1] > ema50[-1] else -1
        factors.append({
            "key": "ema_medium",
            "label": "EMA21 vs EMA50",
            "desc": "Tendencia media alcista" if val > 0 else "Tendencia media bajista",
            "value": val,
        })

    # 3. Precio vs EMA50 (sesgo estructural)
    if ema50:
        val = 1 if last_close > ema50[-1] else -1
        factors.append({
            "key": "price_ema50",
            "label": "Precio vs EMA50",
            "desc": "Precio sobre EMA50" if val > 0 else "Precio bajo EMA50",
            "value": val,
        })

    # 4. Precio vs EMA200 (macro)
    if ema200:
        val = 1 if last_close > ema200[-1] else -1
        factors.append({
            "key": "macro",
            "label": "Macro (EMA200)",
            "desc": "Sesgo macro alcista" if val > 0 else "Sesgo macro bajista",
            "value": val,
        })

    # 5. RSI momentum
    if rsi is not None:
        if 50 <= rsi < 70:
            val = 1
            desc = f"RSI {rsi:.0f} — momentum alcista sano"
        elif 30 < rsi < 50:
            val = -1
            desc = f"RSI {rsi:.0f} — momentum bajista sano"
        elif rsi >= 70:
            val = 0
            desc = f"RSI {rsi:.0f} — sobrecompra (agotamiento)"
        else:
            val = 0
            desc = f"RSI {rsi:.0f} — sobreventa (agotamiento)"
        factors.append({"key": "rsi", "label": "RSI 14", "desc": desc, "value": val})

    # 6. Posición en rango (50 velas)
    if range_pos < 0.3:
        val = 1
        desc = "Zona de descuento (parte baja del rango)"
    elif range_pos > 0.7:
        val = -1
        desc = "Zona premium (parte alta del rango)"
    else:
        val = 0
        desc = "Precio en mitad del rango"
    factors.append({"key": "range_pos", "label": "Posición en rango", "desc": desc, "value": val})

    # 7. Impulso 5 velas
    if mom_ret > 0.001:
        val = 1
        desc = f"Impulso reciente +{mom_ret*100:.2f}%"
    elif mom_ret < -0.001:
        val = -1
        desc = f"Impulso reciente {mom_ret*100:.2f}%"
    else:
        val = 0
        desc = "Sin impulso claro"
    factors.append({"key": "momentum", "label": "Impulso 5v", "desc": desc, "value": val})

    bias = sum(f["value"] for f in factors)
    total_weight = sum(abs(f["value"]) or 1 for f in factors) or len(factors)
    confluence = abs(bias)
    # max confluencia posible: cada factor puede aportar 1 en valor absoluto
    max_confluence = len(factors)

    if bias >= 3:
        side = "LONG"
    elif bias <= -3:
        side = "SHORT"
    else:
        side = "NEUTRAL"

    # Sparkline: últimos 60 closes normalizados
    spark = closes[-60:]

    ema_aligned = (
        bool(ema9 and ema21 and ema50) and
        (
            (ema9[-1] > ema21[-1] > ema50[-1]) or
            (ema9[-1] < ema21[-1] < ema50[-1])
        )
    )
    bloque, bloque_reason = _classify_bloque(
        bias=bias,
        confluence=confluence,
        range_pos=range_pos,
        rsi=rsi,
        ema_aligned=ema_aligned,
    )

    return {
        "pair": pair,
        "td_symbol": _td_symbol(pair),
        "price": round(last_close, 5),
        "prev_close": round(prev_close, 5),
        "change_pct": round(change_pct, 2),
        "rsi": round(rsi, 1) if rsi is not None else None,
        "atr": round(atr, 5) if atr is not None else None,
        "range_pos": round(range_pos, 2),
        "bias": bias,
        "side": side,
        "confluence": confluence,
        "max": max_confluence,
        "bloque": bloque,              # "1" | "2" | "3"
        "bloque_reason": bloque_reason,
        "factors": factors,
        "spark": [round(c, 5) for c in spark],
    }


def _classify_bloque(
    bias: int,
    confluence: int,
    range_pos: float,
    rsi: Optional[float],
    ema_aligned: bool,
) -> tuple[str, str]:
    """Clasifica un par en uno de tres bloques operativos.

    Bloque 1 — Trend-follow: |bias|≥4, EMAs alineadas monotónicamente, RSI no agotado.
    Bloque 3 — Reversión en extremo: rango extremo (<15% o >85%) + RSI en zona de exhaustion (<32 o >68).
    Bloque 2 — Sin edge: resto (lateral, EMAs mixtas, bias bajo).
    """
    at_extreme = range_pos <= 0.15 or range_pos >= 0.85
    rsi_exhausted = rsi is not None and (rsi <= 32 or rsi >= 68)

    # Bloque 3 — reversión: precio en extremo + RSI agotado (señal de reversión)
    # El sentido de la reversión viene dado por qué extremo: low+oversold = LONG, high+overbought = SHORT
    if at_extreme and rsi_exhausted:
        if range_pos <= 0.15 and rsi is not None and rsi <= 32:
            return "3", "Reversión potencial LONG — rango bajo + RSI sobrevendido"
        if range_pos >= 0.85 and rsi is not None and rsi >= 68:
            return "3", "Reversión potencial SHORT — rango alto + RSI sobrecomprado"

    # Bloque 1 — tendencia limpia: bias alto, EMAs alineadas, RSI sano
    if confluence >= 4 and ema_aligned:
        # excluir si precio está pegado al extremo contrario al bias (riesgo de agotamiento)
        exhausted_against = (
            (bias > 0 and range_pos >= 0.9 and rsi is not None and rsi >= 72) or
            (bias < 0 and range_pos <= 0.1 and rsi is not None and rsi <= 28)
        )
        if not exhausted_against:
            direction = "alcista" if bias > 0 else "bajista"
            return "1", f"Tendencia {direction} limpia — EMAs alineadas, confluencia {confluence}/7"

    # Bloque 2 — excluido: razón más específica posible
    if confluence < 3:
        return "2", "Sin dirección clara — bias bajo"
    if not ema_aligned:
        return "2", "EMAs mixtas — estructura no definida"
    if at_extreme and not rsi_exhausted:
        return "2", "Precio en extremo sin confirmación de agotamiento"
    return "2", "Sin edge — contexto ambiguo"


def _analyze_pair(pair: str) -> Optional[dict]:
    """Descarga + scoring para un par. None si falla."""
    raw = _fetch_chart(pair)
    if raw is None:
        return None
    ohlc = _parse_ohlc(raw)
    if ohlc is None:
        return None
    try:
        return _score_pair(pair, ohlc)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Daily brief — síntesis estilo analista
# ---------------------------------------------------------------------------

def _macro_theme(by_pair: dict[str, dict]) -> str:
    """Heurística simple: correlación dominante del día."""
    # USD strength score: + significa USD fuerte
    usd_score = 0
    for p, d in by_pair.items():
        b = d.get("bias", 0)
        if p in ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"):
            usd_score -= b          # SHORT de XXXUSD = USD fuerte
        elif p in ("USDCAD", "USDCHF", "USDJPY"):
            usd_score += b          # LONG de USDXXX = USD fuerte
        elif p == "XAUUSD":
            usd_score -= b          # oro SHORT = USD fuerte

    gold = by_pair.get("XAUUSD", {}).get("bias", 0)
    usdjpy = by_pair.get("USDJPY", {}).get("bias", 0)
    aud = by_pair.get("AUDUSD", {}).get("bias", 0)
    nzd = by_pair.get("NZDUSD", {}).get("bias", 0)

    # Safe-haven: oro arriba + yen fuerte (USDJPY bajista)
    if gold >= 3 and usdjpy <= -3:
        return "Risk-off / refugio — oro y yen bid, evita riesgo cíclico"
    # Risk-on: AUD/NZD fuertes + oro débil
    if (aud + nzd) >= 4 and gold <= -2:
        return "Risk-on — divisas cíclicas al alza, debilidad de refugios"
    if usd_score >= 10:
        return "Dólar fuerte transversalmente — vendedor de todo lo demás"
    if usd_score <= -10:
        return "Dólar débil transversalmente — comprador de todo lo demás"
    if usd_score >= 5:
        return "Sesgo favorable al dólar, no extremo"
    if usd_score <= -5:
        return "Sesgo contrario al dólar, no extremo"
    return "Sin tema macro dominante — mercado mixto / lateral"


def _sesgo_dia(items: list[dict]) -> str:
    """Resumen one-liner del sesgo general."""
    longs = sum(1 for x in items if x["side"] == "LONG")
    shorts = sum(1 for x in items if x["side"] == "SHORT")
    neutrals = sum(1 for x in items if x["side"] == "NEUTRAL")
    total = len(items) or 1

    high_conf = [x for x in items if x["confluence"] >= 5]
    n_hc = len(high_conf)

    if longs > shorts and longs >= total * 0.5:
        tone = "sesgo alcista general"
    elif shorts > longs and shorts >= total * 0.5:
        tone = "sesgo bajista general"
    elif neutrals >= total * 0.6:
        tone = "mercado lateral — mayoría sin dirección"
    else:
        tone = "mercado mixto sin sesgo único"

    hc_note = f", {n_hc} par{'es' if n_hc != 1 else ''} con confluencia ≥5/7" if n_hc else ""
    return f"{tone} ({longs} LONG · {shorts} SHORT · {neutrals} neutral){hc_note}"


def _mejor_setup(operables: list[dict]) -> str:
    """Top pick entre Bloque 1 y Bloque 3, máx 15 palabras."""
    if not operables:
        return "Sin setup operable hoy — todo en Bloque 2"
    top = max(operables, key=lambda x: (x["confluence"], abs(x.get("change_pct", 0))))
    pair = top["pair"]
    side = top["side"] if top["side"] != "NEUTRAL" else ("LONG" if top["bias"] > 0 else "SHORT")
    bloq = top["bloque"]
    razon = top["bloque_reason"]
    # Compact: "XAUUSD SHORT [B1] bias -6, macro bajista, conf 6/7"
    return f"{pair} {side} [B{bloq}] — {razon.split(' — ')[-1] if ' — ' in razon else razon}"[:140]


def _xauusd_resumen(by_pair: dict[str, dict]) -> str:
    """Línea dedicada al oro."""
    g = by_pair.get("XAUUSD")
    if not g:
        return "XAUUSD no disponible"
    return (
        f"Bloque {g['bloque']} · {g['side']} · confluencia {g['confluence']}/{g['max']} · "
        f"RSI {g['rsi']:.0f} · rango {int(g['range_pos']*100)}% · {g['bloque_reason']}"
    )


def build_daily_brief(items: list[dict]) -> dict:
    """Aggrega los resultados en formato brief estilo analista."""
    by_pair = {x["pair"]: x for x in items}
    operables = [x for x in items if x["bloque"] in ("1", "3")]
    excluidos = [x for x in items if x["bloque"] == "2"]

    # Orden: operables por confluencia desc, excluidos por bias absoluto desc
    operables.sort(key=lambda x: -x["confluence"])
    excluidos.sort(key=lambda x: -abs(x["bias"]))

    return {
        "sesgo_dia": _sesgo_dia(items),
        "pares_operables": [
            f"{x['pair']} {x['side']} [B{x['bloque']}] conf {x['confluence']}/{x['max']}"
            for x in operables
        ],
        "pares_excluidos": [
            f"{x['pair']} — {x['bloque_reason']}"
            for x in excluidos
        ],
        "mejor_setup": _mejor_setup(operables),
        "correlacion_dominante": _macro_theme(by_pair),
        "xauusd_resumen": _xauusd_resumen(by_pair),
    }


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def scan_pairs(pairs: Optional[list[str]] = None) -> list[dict]:
    """Escanea pares en paralelo. Devuelve lista rankeada por confluencia desc.

    Cachea cada par individualmente con TTL, para que recargas rápidas no
    machaquen Yahoo.
    """
    pairs = pairs or DEFAULT_PAIRS
    now = time.time()
    results: list[dict] = []
    to_fetch: list[str] = []

    for p in pairs:
        entry = _cache.get(p)
        if entry and (now - entry[0]) < CACHE_TTL_SECONDS:
            results.append(entry[1])
        else:
            to_fetch.append(p)

    if to_fetch:
        # Free tier: 8 req/min. Concurrencia 4 para dejar holgura.
        with ThreadPoolExecutor(max_workers=4) as ex:
            future_map = {ex.submit(_analyze_pair, p): p for p in to_fetch}
            for fut in as_completed(future_map):
                p = future_map[fut]
                data = fut.result()
                if data is not None:
                    _cache[p] = (now, data)
                    results.append(data)

    results.sort(key=lambda r: (-r["confluence"], -abs(r.get("change_pct", 0))))
    return results


def last_error() -> str:
    """Último mensaje de error para diagnóstico (vacío si todo OK)."""
    return _last_error
