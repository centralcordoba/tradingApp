"""
Motor de decisión contextual para señales de TradingView.

NO genera señales — solo decide ENTER / WAIT / AVOID sobre una señal recibida,
usando el contexto que ya entrega el Pine script v8.9.1 (Conf, Quality, MTF,
Zona, Overhead, Patron, RSI, Vol).

Reglas duras (vetos):
  - LONG en VENDE YA o con MTF BEAR  -> AVOID  (compra en resistencia / contra-tendencia)
  - SHORT en COMPRA YA o con MTF BULL -> AVOID  (venta en soporte / contra-tendencia)
  - Overhead/congestion en dirección de la señal -> AVOID
  - RSI extendido (>78 LONG, <22 SHORT) -> AVOID (entrada tardía)
  - Conf < 5 -> AVOID (setup débil)

Scoring (después de pasar los vetos):
  - Quality: PREMIUM +4, STRONG +3, NORMAL +1, LOW 0
  - MTF alineado +2
  - Zona favorable (descuento para LONG, premium para SHORT) +2
  - Patron presente alineado +1
  - Volumen alto +1
  - FVG presente +1
  - Conf >= 14 +2 ; >= 10 +1

Mapeo final:
  - score >= 8  -> ENTER
  - score >= 5  -> WAIT
  - score <  5  -> AVOID
"""

from .schemas import TVSignal, AnalyzeResponse
from .entry_planner import plan_entry


LONG_ALIASES = {"LONG", "BUY"}
SHORT_ALIASES = {"SHORT", "SELL"}


def _normalize(side: str) -> str:
    s = side.upper()
    if s in LONG_ALIASES:
        return "LONG"
    if s in SHORT_ALIASES:
        return "SHORT"
    return s


def analyze(sig: TVSignal) -> AnalyzeResponse:
    side = _normalize(sig.signal)
    is_long = side == "LONG"

    entry_zone = [round(sig.price * 0.9995, 2), round(sig.price * 1.0005, 2)]
    sl = sig.sl
    tp = [sig.be, sig.tp] if sig.be and sig.tp else [sig.tp, sig.tp]

    def avoid(reason: str, conf: float = 0.85) -> AnalyzeResponse:
        return AnalyzeResponse(
            decision="AVOID", confidence=conf, entry_zone=entry_zone,
            stop_loss=sl, take_profit=tp, reason=reason, score=0,
        )

    # ── VETOS ───────────────────────────────────────────────────────────
    if sig.conf < 5:
        return avoid(f"Conf {sig.conf}/19 insuficiente. Setup débil sin ventaja clara.")

    if is_long:
        if sig.zona == "VENDE YA":
            return avoid("LONG en zona de premium extremo (VENDE YA). No se compra en resistencia.")
        if sig.mtf == "BEAR":
            return avoid("LONG contra MTF30 BEAR. Sin alineación de tendencia superior.")
        if sig.overhead:
            return avoid("Resistencia inmediata arriba (Bear OB/FVG). Riesgo de rechazo.")
        if sig.rsi >= 78:
            return avoid(f"RSI {sig.rsi:.0f} extendido. Entrada tardía en sobrecompra.")
    else:
        if sig.zona == "COMPRA YA":
            return avoid("SHORT en zona de descuento extremo (COMPRA YA). No se vende en soporte.")
        if sig.mtf == "BULL":
            return avoid("SHORT contra MTF30 BULL. Sin alineación de tendencia superior.")
        if sig.overhead:  # underlying support para shorts
            return avoid("Soporte inmediato debajo (Bull OB). Riesgo de rebote.")
        if sig.rsi <= 22:
            return avoid(f"RSI {sig.rsi:.0f} extendido. Entrada tardía en sobreventa.")

    if sig.congestion:
        return avoid("Zona de congestión / trampa entre OBs. Sin claridad direccional.")

    # ── SCORE ───────────────────────────────────────────────────────────
    score = 0
    reasons: list[str] = []

    quality_pts = {"PREMIUM": 4, "STRONG": 3, "NORMAL": 1, "LOW": 0}.get(sig.quality, 0)
    score += quality_pts
    if quality_pts >= 3:
        reasons.append(f"calidad {sig.quality}")

    if (is_long and sig.mtf == "BULL") or (not is_long and sig.mtf == "BEAR"):
        score += 2
        reasons.append("MTF30 alineado")

    if is_long and sig.zona in ("COMPRA YA", "COMPRA"):
        score += 2
        reasons.append(f"zona {sig.zona}")
    elif (not is_long) and sig.zona in ("VENDE YA", "VENDE"):
        score += 2
        reasons.append(f"zona {sig.zona}")

    if sig.pattern and sig.pattern != "---":
        score += 1
        reasons.append(f"patrón {sig.pattern}")

    if sig.vol_high:
        score += 1
        reasons.append(f"vol {sig.vol_ratio:.1f}x")

    if sig.fvg:
        score += 1
        reasons.append("FVG activo")

    if sig.conf >= 14:
        score += 2
    elif sig.conf >= 10:
        score += 1

    # ── PLAN DE ENTRADA (cuando hay datos del Pine) ────────────────────
    plan = plan_entry(sig)

    # ── DECISIÓN ────────────────────────────────────────────────────────
    if score >= 8:
        # Si está extendido del EMA9, degradamos a WAIT con plan de pullback
        if plan and plan.trigger_type in ("PULLBACK_EMA9", "EXTENDED_SKIP", "SWEEP_REVERSAL"):
            return AnalyzeResponse(
                decision="WAIT",
                confidence=0.78,
                entry_zone=entry_zone, stop_loss=sl, take_profit=tp, score=score,
                reason=f"Setup fuerte ({sig.conf}/19) pero precio extendido. Sigue el plan de entrada.",
                plan=plan,
            )
        return AnalyzeResponse(
            decision="ENTER",
            confidence=min(0.95, 0.6 + score * 0.04),
            entry_zone=entry_zone, stop_loss=sl, take_profit=tp, score=score,
            reason=f"Setup alineado ({sig.conf}/19, " + ", ".join(reasons) + "). R:R favorable.",
            plan=plan,
        )

    if score >= 5:
        return AnalyzeResponse(
            decision="WAIT",
            confidence=0.7,
            entry_zone=entry_zone, stop_loss=sl, take_profit=tp, score=score,
            reason=f"Contexto aceptable ({sig.conf}/19) pero falta confirmación: " + (", ".join(reasons) or "score bajo") + ".",
            plan=plan,
        )

    return AnalyzeResponse(
        decision="AVOID", confidence=0.78,
        entry_zone=entry_zone, stop_loss=sl, take_profit=tp, score=score,
        reason=f"Setup débil ({sig.conf}/19, score {score}). Sin ventaja para scalp.",
    )
