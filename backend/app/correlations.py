"""
Correlation Checker — datos estáticos y consulta vía OpenRouter.

Mapa fijo de correlaciones entre los 6 pares operables del usuario, según los
valores acordados en su spec personal. La matriz no se calcula en runtime —
se mantiene aquí como tabla autoritativa y se sirve tal cual al frontend.

El endpoint de chat usa el system prompt del Correlation Checker contra
OpenRouter para preguntas en lenguaje natural.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from .constants import HTTP_TIMEOUT_AI

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Modelo dedicado para correlaciones: respuestas cortas y deterministas, no
# necesita reasoning de Sonnet. Cae a OPENROUTER_MODEL si no está seteado.
DEFAULT_MODEL = os.getenv(
    "OPENROUTER_MODEL_CORRELATIONS",
    os.getenv("OPENROUTER_MODEL", "anthropic/claude-haiku-4.5"),
)

PAIRS: list[str] = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD"]

# Valores ≈ media histórica en M15-H1 (los del spec del usuario).
_CORRELATIONS: dict[frozenset[str], float] = {
    frozenset({"EURUSD", "GBPUSD"}): +0.85,
    frozenset({"EURUSD", "USDJPY"}): -0.60,
    frozenset({"EURUSD", "AUDUSD"}): +0.65,
    frozenset({"EURUSD", "USDCHF"}): -0.95,
    frozenset({"EURUSD", "USDCAD"}): -0.60,
    frozenset({"GBPUSD", "USDJPY"}): -0.55,
    frozenset({"GBPUSD", "AUDUSD"}): +0.60,
    frozenset({"GBPUSD", "USDCHF"}): -0.75,
    frozenset({"GBPUSD", "USDCAD"}): -0.50,
    frozenset({"USDJPY", "AUDUSD"}): -0.50,
    frozenset({"USDJPY", "USDCHF"}): +0.60,
    frozenset({"USDJPY", "USDCAD"}): +0.50,
    frozenset({"AUDUSD", "USDCHF"}): -0.65,
    frozenset({"AUDUSD", "USDCAD"}): -0.55,
    frozenset({"USDCHF", "USDCAD"}): +0.55,
}

LEGEND = [
    {"emoji": "🔴", "label": "Correlación extrema (≥ |0.85|)", "min_abs": 0.85, "tier": "extreme"},
    {"emoji": "🟠", "label": "Correlación alta (|0.70| a |0.84|)", "min_abs": 0.70, "tier": "high"},
    {"emoji": "🟡", "label": "Correlación moderada (|0.50| a |0.69|)", "min_abs": 0.50, "tier": "moderate"},
    {"emoji": "⚪", "label": "Correlación baja (< |0.50|)", "min_abs": 0.0, "tier": "low"},
]


def get_correlation(a: str, b: str) -> Optional[float]:
    a, b = a.upper(), b.upper()
    if a == b:
        return 1.0
    return _CORRELATIONS.get(frozenset({a, b}))


def tier(value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    v = abs(value)
    if v >= 0.85:
        return "extreme"
    if v >= 0.70:
        return "high"
    if v >= 0.50:
        return "moderate"
    return "low"


def build_matrix() -> dict:
    """Devuelve la matriz completa serializable (filas=cols=PAIRS)."""
    rows = []
    for a in PAIRS:
        cells = []
        for b in PAIRS:
            v = get_correlation(a, b)
            cells.append({"value": v, "tier": tier(v) if v is not None else "low"})
        rows.append(cells)
    return {"pairs": PAIRS, "matrix": rows, "legend": LEGEND}


SYSTEM_PROMPT = """Eres un asistente especializado en correlaciones de pares forex. Tu única función es informar al usuario sobre la correlación entre pares FX y mostrarle un diagrama visual de las correlaciones de sus pares operables.

NO analizas lotaje, ni setups técnicos, ni gestión de riesgo. Solo correlaciones.

PARES OPERABLES: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCHF, USDCAD

MAPA DE CORRELACIONES:
- EURUSD ↔ USDCHF: -0.95 (inversa extrema, espejo perfecto)
- EURUSD ↔ GBPUSD: +0.85 (positiva alta)
- GBPUSD ↔ USDCHF: -0.75 (negativa alta)
- AUDUSD ↔ EURUSD: +0.65 (moderada positiva)
- AUDUSD ↔ GBPUSD: +0.60 (moderada positiva)
- USDCHF ↔ USDJPY: +0.60 (moderada positiva)
- USDCHF ↔ USDCAD: +0.55 (moderada positiva)
- USDJPY ↔ USDCAD: +0.50 (moderada positiva)
- EURUSD ↔ USDJPY: -0.60 (moderada negativa)
- EURUSD ↔ USDCAD: -0.60 (moderada negativa)
- GBPUSD ↔ USDJPY: -0.55 (moderada negativa)
- GBPUSD ↔ USDCAD: -0.50 (moderada negativa)
- AUDUSD ↔ USDJPY: -0.50 (moderada negativa)
- AUDUSD ↔ USDCHF: -0.65 (moderada negativa)
- AUDUSD ↔ USDCAD: -0.55 (moderada negativa)

LEYENDA:
🔴 Extrema (≥ |0.85|) — mismo trade duplicado
🟠 Alta (|0.70| a |0.84|) — riesgo elevado
🟡 Moderada (|0.50| a |0.69|) — vigilar
⚪ Baja (< |0.50|) — independientes

FORMATOS DE RESPUESTA:

Caso 1 — diagrama/matriz/tabla: muestra la matriz completa + leyenda, sin texto adicional.

Caso 2 — correlación entre 2 pares:
═══════════════════════════════
[PAR1] ↔ [PAR2]
═══════════════════════════════
CORRELACIÓN: [valor]
TIPO: [Inversa extrema / Positiva alta / Negativa alta / Moderada positiva / Moderada negativa / Baja]
INTERPRETACIÓN: [una frase explicando si suben juntos, bajan juntos o se mueven opuestos]

Caso 3 — todas las correlaciones de un par: lista del par contra los otros 5, ordenada por |correlación| descendente.

Caso 4 — "¿están correlacionados X e Y?": SI/NO + valor + tipo en una sola frase.

REGLAS:
1. Trabaja en español.
2. Respuestas cortas y directas. Sin sermones, sin advertencias sobre riesgo, sin sugerencias de lotaje, sin opiniones de mercado.
3. Solo informas sobre correlación. El usuario decide qué hacer con esa info.
4. Si te preguntan algo fuera de correlaciones (lotaje, setup, entrada, gestión), responde: "Solo informo sobre correlaciones. Para [tema] consulta otra herramienta."
5. Si el usuario consulta un par fuera de los 6 operables, responde: "Ese par no está en tu lista operable (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCHF, USDCAD)."
"""


class CorrelationsAIDisabled(RuntimeError):
    """OPENROUTER_API_KEY ausente."""


def query(question: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise CorrelationsAIDisabled("OPENROUTER_API_KEY no configurada")

    body = {
        "model": DEFAULT_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question.strip()},
        ],
    }

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "http://localhost"),
            "X-Title": "AI Trading Assistant - Correlations",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_AI) as r:
        data = json.loads(r.read().decode("utf-8"))

    return data["choices"][0]["message"]["content"]
