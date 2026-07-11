"""
Motor de decisión contextual para señales de TradingView.

NO genera señales — solo decide ENTER / WAIT / AVOID sobre una señal recibida,
usando el contexto que ya entrega el Pine script (Conf, Quality, MTF, Zona,
Overhead, Patron, RSI, Vol) más contexto propio (R:R, kill zone, staleness).

Reglas duras (vetos):
  - LONG en VENDE YA o con MTF BEAR  -> AVOID  (compra en resistencia / contra-tendencia)
  - SHORT en COMPRA YA o con MTF BULL -> AVOID  (venta en soporte / contra-tendencia)
  - Overhead/congestion en dirección de la señal -> AVOID
  - RSI extendido (>78 LONG, <22 SHORT) -> AVOID (entrada tardía)
  - Conf < 5 -> AVOID (setup débil)
  - SL en pips > cap del instrumento -> AVOID (SL de OB lejano)
  - R:R (tp vs sl) < 1.5 -> AVOID (geometría insuficiente)
  - Señal con edad > 10 min -> AVOID (stale para scalp M5)

Scoring (después de pasar los vetos):
  - Quality: PREMIUM +4, STRONG +3, NORMAL +1, LOW 0
    (quality ES el tier de conf del Pine — NO se re-puntúa conf aparte;
    hacerlo contaba la misma variable dos veces)
  - MTF alineado +2
  - Zona favorable (descuento para LONG, premium para SHORT) +2
  - Patron direccional presente +1 (NR7/Inside Bar no puntúan: son neutros)
  - Volumen alto +1
  - FVG presente +1
  - IFVG (retest de FVG invertido) +1
  - Kill zone Madrid: FIRE +1, WARN -1, AVOID -2

Mapeo final (provisional hasta calibrar con la tabla signals):
  - score >= 7  -> ENTER (degrada a WAIT si el plan exige esperar,
                   si la señal tiene edad > 3 min, o si la kill zone es AVOID)
  - score >= 4  -> WAIT
  - score <  4  -> AVOID
"""
from datetime import datetime, timezone

from .constants import PIP_SIZES, SL_MAX_PIPS
from .schemas import TVSignal, AnalyzeResponse
from .entry_planner import plan_entry, _round

try:
    from zoneinfo import ZoneInfo
    _MADRID_TZ = ZoneInfo("Europe/Madrid")
except Exception:  # tzdata ausente
    _MADRID_TZ = None


LONG_ALIASES = {"LONG", "BUY"}
SHORT_ALIASES = {"SHORT", "SELL"}

DECISION_MIN_RR = 1.5
STALE_WAIT_MIN = 3.0    # edad > 3 min → nunca ENTER (scalp M5)
STALE_AVOID_MIN = 10.0  # edad > 10 min → AVOID

# Patrones sin dirección (el Pine los cuenta para ambos lados) — no puntúan.
_NEUTRAL_PATTERNS = ("NR7", "INSIDE")

# Kill zones en hora Madrid — mismas ventanas que lib/killZones.ts del frontend.
_KZ_FIRE = ((9.0, 10.5), (14.0, 17.0))   # London Open · Overlap LDN-NY
_KZ_OK = ((10.5, 12.0),)                 # London continuación
_KZ_WARN = ((12.0, 14.0), (17.0, 19.0))  # Pre-NY · NY mid


def _kill_zone_status(now: datetime | None = None) -> str:
    """'fire' | 'ok' | 'warn' | 'avoid' según la hora Madrid actual."""
    ref = now or datetime.now(timezone.utc)
    if _MADRID_TZ is not None:
        ref = ref.astimezone(_MADRID_TZ)
    h = ref.hour + ref.minute / 60.0
    for lo, hi in _KZ_FIRE:
        if lo <= h < hi:
            return "fire"
    for lo, hi in _KZ_OK:
        if lo <= h < hi:
            return "ok"
    for lo, hi in _KZ_WARN:
        if lo <= h < hi:
            return "warn"
    return "avoid"


def _signal_age_minutes(raw_time: str | None, now: datetime | None = None) -> float | None:
    """Edad de la señal en minutos. Acepta epoch ms/s (str.tostring(time) del
    Pine) o ISO 8601. None si no parseable o ausente."""
    if not raw_time:
        return None
    ref = now or datetime.now(timezone.utc)
    s = str(raw_time).strip()
    try:
        if s.replace(".", "", 1).isdigit():
            val = float(s)
            if val > 1e12:      # epoch en milisegundos
                val /= 1000.0
            dt = datetime.fromtimestamp(val, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return (ref - dt).total_seconds() / 60.0
    except (ValueError, OSError, OverflowError):
        return None


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

    # Zona de entrada: ±0.25×ATR alrededor del precio de señal (fallback ±0.05%
    # si el Pine no envió ATR), con la precisión decimal del símbolo.
    half = sig.atr * 0.25 if (sig.atr and sig.atr > 0) else sig.price * 0.0005
    entry_zone = [_round(sig.symbol, sig.price - half), _round(sig.symbol, sig.price + half)]
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

    # ── VETOS DE GEOMETRÍA (R:R + SL cap) ───────────────────────────────
    pip = PIP_SIZES.get(sig.symbol.upper(), PIP_SIZES["default"])
    sl_cap = SL_MAX_PIPS.get(sig.symbol.upper(), SL_MAX_PIPS["default"])
    risk = (sig.price - sig.sl) if is_long else (sig.sl - sig.price)
    reward = (sig.tp - sig.price) if is_long else (sig.price - sig.tp)

    if risk <= 0:
        return avoid("SL del lado equivocado de la entrada. Señal malformada.")
    risk_pips = risk / pip
    if risk_pips > sl_cap:
        return avoid(
            f"SL a {risk_pips:.0f} pips excede el cap de {sl_cap} pips del instrumento. "
            f"Riesgo desproporcionado para scalp (probable OB lejano)."
        )
    rr = reward / risk
    if rr < DECISION_MIN_RR:
        return avoid(
            f"R:R {rr:.2f} < {DECISION_MIN_RR}. El TP no compensa el riesgo del SL."
        )

    # ── VETO DE STALENESS (requiere que el Pine envíe `time`) ───────────
    age_min = _signal_age_minutes(sig.time)
    if age_min is not None and age_min > STALE_AVOID_MIN:
        return avoid(
            f"Señal con {age_min:.0f} min de antigüedad. Stale para scalp M5 "
            f"(cold start / reintento tardío del webhook)."
        )

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
        p_upper = sig.pattern.upper()
        if not any(n in p_upper for n in _NEUTRAL_PATTERNS):
            score += 1
            reasons.append(f"patrón {sig.pattern}")

    if sig.vol_high:
        score += 1
        reasons.append(f"vol {sig.vol_ratio:.1f}x")

    if sig.fvg:
        score += 1
        reasons.append("FVG activo")

    if sig.ifvg:
        score += 1
        reasons.append("IFVG: retest de FVG invertido")

    # NOTA: conf NO se puntúa aparte — quality ya es el tier de conf del Pine.

    kz = _kill_zone_status()
    if kz == "fire":
        score += 1
        reasons.append("kill zone FIRE")
    elif kz == "warn":
        score -= 1
    elif kz == "avoid":
        score -= 2

    # ── PLAN DE ENTRADA (cuando hay datos del Pine) ────────────────────
    plan = plan_entry(sig)

    # ── DECISIÓN ────────────────────────────────────────────────────────
    if score >= 7:
        # Degradaciones ENTER → WAIT: plan que exige esperar, señal con edad
        # >3 min (scalp M5), o fuera de ventana operativa (kill zone AVOID).
        if plan and plan.trigger_type in ("PULLBACK_EMA9", "EXTENDED_SKIP", "SWEEP_REVERSAL", "RETEST"):
            return AnalyzeResponse(
                decision="WAIT",
                confidence=0.78,
                entry_zone=entry_zone, stop_loss=sl, take_profit=tp, score=score,
                reason=f"Setup fuerte ({sig.conf}/19) pero requiere confirmación. Sigue el plan de entrada.",
                plan=plan,
            )
        if age_min is not None and age_min > STALE_WAIT_MIN:
            return AnalyzeResponse(
                decision="WAIT",
                confidence=0.7,
                entry_zone=entry_zone, stop_loss=sl, take_profit=tp, score=score,
                reason=(
                    f"Setup fuerte pero la señal tiene {age_min:.0f} min. No persigas el precio: "
                    f"opera solo si sigue en la zona de entrada."
                ),
                plan=plan,
            )
        if kz == "avoid":
            return AnalyzeResponse(
                decision="WAIT",
                confidence=0.7,
                entry_zone=entry_zone, stop_loss=sl, take_profit=tp, score=score,
                reason=(
                    f"Setup fuerte ({sig.conf}/19) pero fuera de ventana operativa "
                    f"(kill zone AVOID en Madrid). El playbook no opera esta franja."
                ),
                plan=plan,
            )
        return AnalyzeResponse(
            decision="ENTER",
            confidence=min(0.95, 0.6 + score * 0.04),
            entry_zone=entry_zone, stop_loss=sl, take_profit=tp, score=score,
            reason=f"Setup alineado ({sig.conf}/19, " + ", ".join(reasons) + f"). R:R {rr:.1f}.",
            plan=plan,
        )

    if score >= 4:
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
