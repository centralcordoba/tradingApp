"""
Capa de enriquecimiento SMC del radar.

Para cada setup activo de los pares operables, llama a OpenRouter con un prompt
de Smart Money Concepts y devuelve un dict con sesgo (LONG_ONLY/SHORT_ONLY/
NO_TRADE), nivel activo (con frescura), alerta y resumen accionable.

Es estrictamente complementario — la heurística del radar sigue siendo la fuente
de verdad para detectar el setup. Si OpenRouter falla, devuelve None y el
frontend muestra solo la heurística.

Cache por (symbol, last_candle_ts): mientras la última vela M30 no cambia,
reutilizamos el resultado. La vela M30 cambia cada 30 min → 1 call por par
cada 30 min en el peor caso.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

from .constants import RADAR_SMC_HTTP_TIMEOUT, AI_TEMPERATURE

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")

SMC_SYSTEM_PROMPT = """Eres un analista de price action especializado en Smart Money Concepts (SMC).
Recibes datos OHLC en M30 de un par forex.
Responde ÚNICAMENTE en JSON válido. Sin texto, sin markdown, sin explicaciones.

ANALIZA y devuelve esto:

{
  "sesgo": "LONG_ONLY" | "SHORT_ONLY" | "NO_TRADE",

  "estructura": {
    "ultimo_movimiento": "HH" | "HL" | "LH" | "LL",
    "descripcion": "una frase corta, ej: HL confirmado en 1.0823, estructura alcista intacta"
  },

  "nivel_activo": {
    "precio": 0.00000,
    "tipo": "SOPORTE" | "RESISTENCIA",
    "frescura": "FRESCO" | "TESTEADO" | "AGOTADO",
    "fuerza": "FUERTE" | "NORMAL" | "DEBIL",
    "proximidad_pips": 0.0,
    "operable": true | false
  },

  "alerta": {
    "activa": true | false,
    "motivo": "precio a X pips de nivel FRESCO" | "CHoCH detectado" | "BOS confirmado" | ""
  },

  "resumen": "una sola frase accionable para ahora mismo"
}

REGLAS DE CLASIFICACIÓN:

sesgo:
- LONG_ONLY si la estructura muestra HH + HL en las últimas 6 velas
- SHORT_ONLY si muestra LH + LL en las últimas 6 velas
- NO_TRADE si la estructura es mixta o no hay patrón claro

nivel_activo:
- Elige UN solo nivel: el más cercano al precio actual que sea operable
- frescura FRESCO = testeado 0-1 veces (nivel válido para operar)
- frescura TESTEADO = 2-3 veces (operable con cautela)
- frescura AGOTADO = 4+ veces (ignorar, no operable)
- operable = true solo si frescura es FRESCO o TESTEADO, Y fuerza no es DEBIL

alerta:
- activa = true si precio está a menos de 15 pips del nivel_activo
- activa = true si hubo CHoCH o BOS en las últimas 4 velas
- si ambas condiciones, prioriza CHoCH/BOS en el motivo

resumen:
- Máximo 12 palabras
- Ejemplos válidos:
  "SHORT_ONLY — resistencia FRESCA en 1.0856, precio a 8 pips"
  "NO_TRADE — estructura mixta, esperar definición"
  "LONG_ONLY — BOS alcista confirmado, buscar pullback a 1.0812\""""

_VALID_SESGO = {"LONG_ONLY", "SHORT_ONLY", "NO_TRADE"}
_VALID_MOVIMIENTO = {"HH", "HL", "LH", "LL"}
_VALID_TIPO = {"SOPORTE", "RESISTENCIA"}
_VALID_FRESCURA = {"FRESCO", "TESTEADO", "AGOTADO"}
_VALID_FUERZA = {"FUERTE", "NORMAL", "DEBIL"}

# Cache por (symbol, last_m30_candle_ts) — mientras la vela no cierre, reusa.
_smc_cache: dict[tuple[str, str], dict] = {}


def is_enabled() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY"))


def _format_candles_for_prompt(candles: list[dict]) -> str:
    """Compacta las velas M30 a una tabla CSV mínima para el prompt.

    Una línea por vela: ts,open,high,low,close. Usa punto decimal y precio sin
    redondear (la IA decide la precisión que mostrar en el output).
    """
    rows = ["ts,open,high,low,close"]
    for c in candles:
        rows.append(
            f"{c.get('ts', '')},{c['open']},{c['high']},{c['low']},{c['close']}"
        )
    return "\n".join(rows)


def _validate_response(parsed: dict) -> Optional[dict]:
    """Valida la forma del JSON. Retorna el dict si pasa, None si no."""
    try:
        sesgo = parsed.get("sesgo")
        if sesgo not in _VALID_SESGO:
            return None

        estructura = parsed.get("estructura") or {}
        if estructura.get("ultimo_movimiento") not in _VALID_MOVIMIENTO:
            return None

        nivel = parsed.get("nivel_activo") or {}
        if nivel.get("tipo") not in _VALID_TIPO:
            return None
        if nivel.get("frescura") not in _VALID_FRESCURA:
            return None
        if nivel.get("fuerza") not in _VALID_FUERZA:
            return None
        # Coerción suave de tipos numéricos
        nivel["precio"] = float(nivel["precio"])
        nivel["proximidad_pips"] = float(nivel.get("proximidad_pips", 0.0))
        nivel["operable"] = bool(nivel.get("operable"))

        alerta = parsed.get("alerta") or {}
        alerta["activa"] = bool(alerta.get("activa"))
        alerta["motivo"] = str(alerta.get("motivo", ""))

        resumen = str(parsed.get("resumen", "")).strip()
        if not resumen:
            return None

        return {
            "sesgo": sesgo,
            "estructura": {
                "ultimo_movimiento": estructura["ultimo_movimiento"],
                "descripcion": str(estructura.get("descripcion", "")),
            },
            "nivel_activo": nivel,
            "alerta": alerta,
            "resumen": resumen,
        }
    except (KeyError, TypeError, ValueError) as e:
        logger.debug("[radar_smc] validación falló: %s", e)
        return None


def analyze_setup_smc(symbol: str, candles_m30: list[dict]) -> Optional[dict]:
    """Llama a OpenRouter con el prompt SMC. Devuelve dict validado o None.

    `candles_m30`: lista de velas M30 ya agregadas (ver radar._aggregate_to_m30).
    Cachea por (symbol, ts_de_la_ultima_vela) — mientras la vela no cambie,
    reusa el resultado.
    """
    if not candles_m30:
        return None

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None

    last_ts = candles_m30[-1].get("ts") or ""
    cache_key = (symbol.upper(), str(last_ts))
    cached = _smc_cache.get(cache_key)
    if cached is not None:
        return cached

    prompt_data = _format_candles_for_prompt(candles_m30)

    body = {
        "model": DEFAULT_MODEL,
        "temperature": AI_TEMPERATURE,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SMC_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Datos OHLC M30 de {symbol}:\n{prompt_data}",
            },
        ],
    }

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "http://localhost"),
            "X-Title": "AI Trading Assistant — Radar SMC",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=RADAR_SMC_HTTP_TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        logger.warning("[radar_smc] %s OpenRouter error: %s", symbol, e)
        return None

    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
        logger.warning("[radar_smc] %s parse error: %s", symbol, e)
        return None

    validated = _validate_response(parsed)
    if validated is None:
        logger.warning("[radar_smc] %s respuesta inválida: %s", symbol, parsed)
        return None

    _smc_cache[cache_key] = validated
    # Limpieza ligera: si el cache crece más de 200 entradas, vacía las viejas.
    # No vale la pena un LRU formal — pares × candles es bajo volumen.
    if len(_smc_cache) > 200:
        # Conservar solo la última entrada de cada par.
        latest_per_symbol: dict[str, tuple[tuple[str, str], dict]] = {}
        for k, v in _smc_cache.items():
            latest_per_symbol[k[0]] = (k, v)
        _smc_cache.clear()
        for k, v in latest_per_symbol.values():
            _smc_cache[k] = v

    return validated
