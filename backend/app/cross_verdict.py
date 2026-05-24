"""Veredicto cruzado M30 + M5 — reconcilia bias direccional con señal de entrada.

Cuarta capa de síntesis: cruza el BIAS M30 (de zones.py, EMA50 vs EMA100 sobre
velas M30) con el VEREDICTO M5 del scanner (LONG/SHORT/NEUTRAL por confluencia).
El M30 manda, el M5 ejecuta dentro de lo que el M30 permite.

Una sola fuente de verdad: la función pura `reconcile()` (las reglas) + las
cachés OHLC/scored ya compartidas (los inputs). Ambos endpoints (/scanner/pairs
y /api/zones) llaman a `build_cross_map()`, así que el veredicto sale idéntico
en las dos pantallas sin duplicar el cálculo.

Estados:
- A  "A FAVOR"          BULL+LONG | BEAR+SHORT          tendencia alineada (verde)
- B  "FADE EN RANGO"    RANGO + (LONG|SHORT)            mean-reversion (ámbar)
- C  "CONFLICTO M30/M5" BULL+SHORT | BEAR+LONG          contra-tendencia (rojo)
- D  "SIN SETUP"        scanner NEUTRAL (cualquier bias)                  (gris)
- NA "no reconciliable" bias M30 no disponible                           (gris)
- OUT "fuera de alcance" par sin bias M30 calculado                      (gris)

Lenguaje neutro: describe estado y riesgo; no da órdenes de compra/venta.
"""
from __future__ import annotations

import logging
from typing import Optional

from . import scanner, zones
from .constants import ZONES_DEFAULT_PAIRS

logger = logging.getLogger(__name__)

# Solo estos pares reciben veredicto cruzado (los que el usuario opera y que
# Zonas S/R calcula). El resto del scanner cae en estado OUT sin fetch extra.
CROSS_PAIRS = {p.upper() for p in ZONES_DEFAULT_PAIRS}


def _verdict(state: str, tone: str, label: str, summary: str,
             target_side: Optional[str] = None,
             target_price: Optional[float] = None) -> dict:
    return {
        "state": state,
        "tone": tone,
        "label": label,
        "summary": summary,
        "target_side": target_side,
        "target_price": target_price,
    }


def reconcile(
    scanner_side: str,
    bias_label: Optional[str],
    bias_available: bool,
    opposite_price: Optional[float] = None,
) -> dict:
    """Cruza side M5 con label M30 → estado A/B/C/D/NA. Función pura, sin I/O.

    Precedencia: D (sin señal M5) → NA (sin bias M30) → A/B/C.
    `opposite_price` es el nivel S/R activo opuesto para el objetivo del FADE.
    """
    # D — el scanner no da dirección: no hay nada que reconciliar.
    if scanner_side == "NEUTRAL":
        return _verdict(
            "D", "gray", "Sin señal M5",
            "El scanner no da dirección en M5 (NEUTRAL). Nada que reconciliar con el M30.",
        )

    # NA — sin bias M30: no se asume dirección.
    if not bias_available or bias_label not in ("BULL", "BEAR", "RANGO"):
        return _verdict(
            "NA", "gray", "Bias M30 no disponible",
            "No se puede reconciliar: el bias M30 no está disponible (datos insuficientes "
            "o no calculable). No se asume dirección.",
        )

    # A — tendencia alineada.
    if (bias_label == "BULL" and scanner_side == "LONG") or (bias_label == "BEAR" and scanner_side == "SHORT"):
        return _verdict(
            "A", "green", f"A FAVOR M30 · {scanner_side} de tendencia",
            "El M5 va en la misma dirección que el bias director M30. Setup de tendencia "
            "alineado — la confluencia del scanner cuenta completa.",
        )

    # C — contra-tendencia. Aviso fuerte, sin bloquear.
    if (bias_label == "BULL" and scanner_side == "SHORT") or (bias_label == "BEAR" and scanner_side == "LONG"):
        return _verdict(
            "C", "red", "⚠ CONFLICTO M30/M5 · el M5 va contra tu bias director",
            "El M5 va EN CONTRA del bias director M30. Operar esto es ir contra tu tendencia M30. "
            "Tu regla histórica: respeta la tendencia. Si entras, es bajo tu criterio.",
        )

    # B — FADE EN RANGO (bias RANGO + side direccional). Objetivo: extremo opuesto.
    # SHORT en rango → objetivo soporte; LONG en rango → objetivo resistencia.
    target_side = "support" if scanner_side == "SHORT" else "resistance"
    tipo = "soporte" if target_side == "support" else "resistencia"
    if opposite_price is not None:
        objetivo = f"hacia el {tipo} activo más cercano ({opposite_price})"
    else:
        objetivo = f"hacia el extremo opuesto del rango ({tipo}, sin nivel S/R activo localizado)"
    return _verdict(
        "B", "amber", "FADE EN RANGO · objetivo extremo opuesto",
        f"Sin tendencia M30: el movimiento M5 ocurre dentro de un rango. No es trade de "
        f"tendencia sino fade (mean-reversion) {objetivo}. Caducidad: salir en ese extremo, "
        f"no dejar correr esperando tendencia.",
        target_side=target_side,
        target_price=opposite_price,
    )


def _nearest_opposite_level(zone_item: dict, scanner_side: str) -> Optional[float]:
    """Nivel S/R activo opuesto más cercano para el objetivo del FADE.

    SHORT → soporte (debajo); LONG → resistencia (encima). Prefiere niveles
    activos, luego dentro de rango; el más cercano por distancia. None si no hay.
    """
    target_type = "support" if scanner_side == "SHORT" else "resistance"
    levels = [lv for lv in zone_item.get("levels", []) if lv.get("type") == target_type]
    if not levels:
        return None
    active = [lv for lv in levels if lv.get("active")]
    within = [lv for lv in levels if lv.get("within_range")]
    pool = active or within or levels
    best = min(pool, key=lambda lv: lv.get("distance_pips", float("inf")))
    return best.get("price")


def build_cross_map(pairs: list[str], zones_params: Optional[dict] = None) -> dict[str, dict]:
    """Veredicto cruzado por par. Pares fuera de CROSS_PAIRS → OUT (sin fetch).

    Reutiliza las cachés del scanner (M5) y de zones (M15→M30). `zones_params`
    propaga los overrides de la vista Zonas S/R (p.ej. rango_atr_mult) para que
    el cruce use el MISMO bias que el chip M30 que ve el usuario en esa pantalla.
    """
    out: dict[str, dict] = {}
    target = [p for p in pairs if p.upper() in CROSS_PAIRS]
    for p in pairs:
        if p.upper() not in CROSS_PAIRS:
            out[p] = _verdict(
                "OUT", "gray", "M30 fuera de alcance",
                "El bias M30 solo se calcula para los pares operados "
                f"({', '.join(sorted(CROSS_PAIRS))}).",
            )

    if not target:
        return out

    try:
        scan = {x["pair"]: x for x in scanner.scan_pairs(target)}
    except Exception as e:
        logger.exception("cross_verdict: scanner.scan_pairs falló: %s", e)
        scan = {}
    try:
        zres = zones.get_zones_response(target, zones_params or {})
        zmap = {it["pair"]: it for it in zres.get("items", [])}
    except Exception as e:
        logger.exception("cross_verdict: zones.get_zones_response falló: %s", e)
        zmap = {}

    for p in target:
        s = scan.get(p)
        z = zmap.get(p)
        side = s["side"] if s else "NEUTRAL"
        bias = z.get("bias_m30") if z else None
        bias_label = bias.get("label") if bias else None
        bias_avail = bool(bias.get("available")) if bias else False
        opp = (
            _nearest_opposite_level(z, side)
            if (z and bias_avail and bias_label == "RANGO" and side in ("LONG", "SHORT"))
            else None
        )
        out[p] = reconcile(side, bias_label, bias_avail, opp)

    return out
