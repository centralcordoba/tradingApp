"""
Capa de refinamiento opcional vía OpenRouter.

Toma la señal cruda + la decisión heurística y le pide al LLM que la valide
o la corrija siguiendo el prompt de scalper profesional. Si OPENROUTER_API_KEY
no está seteada, devuelve None y el endpoint usa solo la decisión heurística.
"""
import os
import json
import urllib.request
import urllib.error
from typing import Optional

from .schemas import TVSignal, AnalyzeResponse

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")

SYSTEM_PROMPT = """Actúa como un trader profesional de scalp intradía de 0 a 15 minutos.
Tu trabajo NO es generar señales nuevas; solo evaluar una señal recibida desde TradingView.

Objetivo:
Decidir entre ENTER, WAIT o AVOID con base en contexto de mercado, timing y calidad de entrada.

Reglas:
- No comprar en resistencia. No vender en soporte.
- Evitar operaciones cuando el precio esté extendido.
- Preferir entradas en pullbacks o retrocesos limpios.
- Confirmar con momentum y estructura.
- Penalizar fake breakouts, velas de rechazo y entradas tardías.
- Si la señal está alineada con tendencia, contexto y timing, favorecer ENTER.
- Si falta confirmación pero el contexto no es malo, devolver WAIT.
- Si el setup es débil, extendido o contraproducente, devolver AVOID.

Salida ESTRICTA en JSON válido (sin markdown, sin texto extra):
{
  "decision": "ENTER" | "WAIT" | "AVOID",
  "confidence": 0.0,
  "entry_zone": [min, max],
  "stop_loss": 0.0,
  "take_profit": [tp1, tp2],
  "reason": "explicación breve, directa y profesional"
}"""


def is_enabled() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY"))


def refine(sig: TVSignal, heuristic: AnalyzeResponse) -> Optional[AnalyzeResponse]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None

    user_payload = {
        "signal": sig.model_dump(),
        "heuristic_decision": heuristic.model_dump(),
    }

    body = {
        "model": DEFAULT_MODEL,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Evalúa esta señal de TradingView y devuelve SOLO el JSON.\n\n"
                    + json.dumps(user_payload, ensure_ascii=False, indent=2)
                ),
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
            "X-Title": "AI Trading Assistant",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"[ai_client] OpenRouter error: {e}")
        return None

    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return AnalyzeResponse(
            decision=parsed["decision"],
            confidence=float(parsed.get("confidence", 0.0)),
            entry_zone=list(parsed.get("entry_zone", heuristic.entry_zone)),
            stop_loss=float(parsed.get("stop_loss", heuristic.stop_loss)),
            take_profit=list(parsed.get("take_profit", heuristic.take_profit)),
            reason=str(parsed.get("reason", "")),
            score=heuristic.score,
        )
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
        print(f"[ai_client] Parse error: {e}")
        return None
