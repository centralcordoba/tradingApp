"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API } from "@/lib/api";
import type { ZonesResponse, ZonesPairResponse, ZoneLevel, ZoneMarco, MarcoGate } from "@/lib/types";
import { CrossBadge } from "@/components/cross/CrossBadge";
import "./ZonasSRView.css";

const POLL_INTERVAL_MS = 5 * 60 * 1000; // 5 min
const ALERTS_ON_KEY = "tradingapp:zones_alerts_on";

// ─── Alertas de señal FUERTE (estilo TradingView) ──────────────────────────
// Solo se disparan cuando un par pasa a OPERAR + strength "fuerte". El audio se
// desbloquea en el clic del botón (los navegadores bloquean el AudioContext sin
// un gesto de usuario — ese era el motivo de que la versión anterior no sonara).

function playStrongSound(ctx: AudioContext, side: "LONG" | "SHORT") {
  try {
    const note = (freq: number, start: number, dur = 0.24) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0, start);
      gain.gain.linearRampToValueAtTime(0.28, start + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.001, start + dur);
      osc.start(start);
      osc.stop(start + dur + 0.05);
    };
    const t = ctx.currentTime;
    // Motif de 3 notas (ascendente=compra / descendente=venta) repetido para que
    // la alerta dure ~3 segundos.
    const motif = side === "LONG"
      ? [523.25, 783.99, 1046.5]   // C5 → G5 → C6
      : [1046.5, 783.99, 523.25];  // C6 → G5 → C5
    const REPEATS = 3;
    const NOTE_GAP = 0.26;    // separación entre notas dentro del motif
    const MOTIF_GAP = 1.0;    // separación entre repeticiones
    for (let r = 0; r < REPEATS; r++) {
      const base = t + r * MOTIF_GAP;
      motif.forEach((freq, i) => {
        // La última nota se sostiene para cerrar en ~3s.
        const isLast = r === REPEATS - 1 && i === motif.length - 1;
        note(freq, base + i * NOTE_GAP, isLast ? 0.55 : 0.24);
      });
    }
  } catch {
    // AudioContext suspendido o no disponible
  }
}

function sendStrongNotification(pair: string, marco: ZoneMarco) {
  if (typeof window === "undefined" || !("Notification" in window)) return;
  if (Notification.permission !== "granted") return;
  const isLong = marco.side === "LONG";
  const title = `${isLong ? "📈 FUERTE COMPRA" : "📉 FUERTE VENTA"} · ${pair}`;
  const lines: string[] = [];
  if (marco.entry_price != null) lines.push(`Entrada ${marco.entry_price.toFixed(5)}`);
  if (marco.sl_price != null)    lines.push(`SL ${marco.sl_price.toFixed(5)} (${marco.risk_pips}p)`);
  if (marco.tp_price != null)    lines.push(`TP ${marco.tp_price.toFixed(5)} (${marco.reward_pips}p)`);
  if (marco.rrr != null)         lines.push(`RRR ${marco.rrr.toFixed(2)}:1`);
  try {
    new Notification(title, {
      body: lines.join("  |  "),
      tag: `marco-${pair}`,   // reemplaza notif previa del mismo par
      requireInteraction: true,  // queda en el Centro de actividades de Windows hasta cerrarla
    });
  } catch {
    // Silencioso si el navegador no soporta algún campo
  }
}

// Devuelve el lado si el marco es una señal FUERTE accionable, si no null.
function strongSide(m?: ZoneMarco | null): "LONG" | "SHORT" | null {
  if (!m) return null;
  if (m.decision === "OPERAR" && m.strength === "fuerte" && (m.side === "LONG" || m.side === "SHORT")) {
    return m.side;
  }
  return null;
}

const DEFAULT_PAIRS = [
  "AUDUSD", "USDCAD",
  // "EURUSD", "GBPUSD", "USDCHF", "USDJPY",
];

type Params = {
  window: number;
  merge_distance_pips: number;
  active_range_pips: number;
  min_bars_between: number;
  touch_tolerance_pips: number;
  level_selector: "median" | "mean";
  rango_atr_mult: number;
};

const DEFAULT_PARAMS: Params = {
  window: 3,
  merge_distance_pips: 8,
  active_range_pips: 25,
  min_bars_between: 3,
  touch_tolerance_pips: 3,
  level_selector: "median",
  rango_atr_mult: 0.3,
};

const PARAMS_STORAGE_KEY = "tradingapp:zones_params";

function loadParams(): Params {
  if (typeof window === "undefined") return DEFAULT_PARAMS;
  try {
    const raw = window.localStorage.getItem(PARAMS_STORAGE_KEY);
    if (!raw) return DEFAULT_PARAMS;
    const parsed = JSON.parse(raw);
    return { ...DEFAULT_PARAMS, ...parsed };
  } catch {
    return DEFAULT_PARAMS;
  }
}

function buildQuery(params: Params): string {
  const u = new URLSearchParams({
    pairs: DEFAULT_PAIRS.join(","),
    window: String(params.window),
    merge_distance_pips: String(params.merge_distance_pips),
    active_range_pips: String(params.active_range_pips),
    min_bars_between: String(params.min_bars_between),
    touch_tolerance_pips: String(params.touch_tolerance_pips),
    level_selector: params.level_selector,
    rango_atr_mult: String(params.rango_atr_mult),
  });
  return u.toString();
}

function formatLastUpdate(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "—";
  }
}

function Stars({ score }: { score: number }) {
  const filled = Math.max(0, Math.min(5, score));
  return (
    <span className="zsr-stars" aria-label={`Fuerza ${filled} de 5`}>
      {Array.from({ length: 5 }, (_, i) => (
        <span key={i} className={i < filled ? "zsr-star-on" : "zsr-star-off"}>★</span>
      ))}
    </span>
  );
}

function BiasChip({ bias }: { bias: ZonesPairResponse["bias_m30"] }) {
  if (!bias.available) {
    const detail =
      bias.reason === "insufficient_m30_bars"
        ? `velas M30 insuficientes · ${bias.m30_bars}/${bias.m30_bars_required}`
        : bias.reason === "no_ohlc"
        ? "sin datos OHLC"
        : bias.reason === "ema_failed"
        ? "cálculo EMA falló"
        : bias.reason === "atr_failed"
        ? "cálculo ATR falló"
        : "no disponible";
    const tooltip =
      bias.reason === "insufficient_m30_bars"
        ? `Hacen falta ${bias.m30_bars_required} velas M30, hay ${bias.m30_bars}`
        : detail;
    return (
      <span className="zsr-bias zsr-bias-na" title={tooltip}>
        Bias M30 · {detail}
      </span>
    );
  }
  const cls =
    bias.label === "BULL" ? "zsr-bias-bull" :
    bias.label === "BEAR" ? "zsr-bias-bear" :
    bias.label === "RANGO" ? "zsr-bias-rango" :
    "zsr-bias-neutral";

  // Diagnóstico técnico para el tooltip — ayuda a calibrar el multiplicador.
  const ratio =
    bias.separation != null && bias.atr_m30 != null && bias.atr_m30 > 0
      ? bias.separation / bias.atr_m30
      : null;
  const diag =
    bias.separation_pips != null && bias.atr_pips != null
      ? `separación ${bias.separation_pips}p · ATR ${bias.atr_pips}p` +
        (ratio != null ? ` · ratio ${ratio.toFixed(2)} (umbral ${bias.atr_mult_threshold})` : "")
      : "";
  const txt =
    bias.label === "BULL" ? `EMA50 sobre EMA100 — ${diag}` :
    bias.label === "BEAR" ? `EMA50 bajo EMA100 — ${diag}` :
    bias.label === "RANGO" ? `EMAs pegadas — sin tendencia direccional — ${diag}` :
    `EMA50 ≈ EMA100 — ${diag}`;
  return (
    <span className={`zsr-bias ${cls}`} title={txt}>
      Bias M30 · {bias.label}
    </span>
  );
}

function RangoBanner({ bias }: { bias: ZonesPairResponse["bias_m30"] }) {
  if (!bias.available || bias.label !== "RANGO") return null;
  const ratio =
    bias.separation != null && bias.atr_m30 != null && bias.atr_m30 > 0
      ? (bias.separation / bias.atr_m30).toFixed(2)
      : null;
  return (
    <div className="zsr-rango-banner" role="status">
      <div className="zsr-rango-banner-title">Sin sesgo direccional M30</div>
      <div className="zsr-rango-banner-body">
        EMAs comprimidas — operable a ambos lados con confirmación en M5. Soportes y
        resistencias son válidos para fade desde extremos.
      </div>
      {ratio != null && (
        <div className="zsr-rango-banner-meta num">
          separación {bias.separation_pips}p / ATR {bias.atr_pips}p = {ratio} · umbral {bias.atr_mult_threshold}
        </div>
      )}
    </div>
  );
}

function LevelRow({ level, price }: { level: ZoneLevel; price: number }) {
  const isSupport = level.type === "support";
  const typeLabel = isSupport ? "Soporte" : "Resistencia";
  const arrow = isSupport ? "▼" : "▲";
  const side = isSupport ? "abajo" : "arriba";
  const stateLabel = level.active
    ? "ACTIVO"
    : level.within_range
    ? "EN RANGO"
    : "LEJANO";
  const stateClass = level.active
    ? "zsr-state-active"
    : level.within_range
    ? "zsr-state-range"
    : "zsr-state-far";
  const incoherent = level.within_range && !level.coherent_with_bias;
  const wick = level.last_touch_wick;

  return (
    <article
      className={`zsr-level ${level.active ? "zsr-level-active" : ""}`}
      data-type={level.type}
    >
      <div className="zsr-level-bar" aria-hidden="true" />

      <div className="zsr-level-body">
        <div className="zsr-level-row-top">
          <div className="zsr-level-type">
            <span className="zsr-level-arrow" aria-hidden="true">{arrow}</span>
            <span className="zsr-level-type-label">{typeLabel}</span>
          </div>
          <span className={`zsr-level-state ${stateClass}`}>
            {stateLabel}
          </span>
        </div>

        <div className="zsr-level-price num" title={`Precio del nivel: ${level.price.toFixed(5)}`}>
          {level.price.toFixed(5)}
        </div>

        <div className="zsr-level-meta">
          <span className="zsr-level-meta-item zsr-level-meta-strength">
            <Stars score={level.strength} />
          </span>
          <span className="zsr-level-meta-sep" aria-hidden="true">·</span>
          <span className="zsr-level-meta-item">
            <span className="num">{level.touches}</span>
            <span className="zsr-level-meta-label">{level.touches === 1 ? "toque" : "toques"}</span>
          </span>
          <span className="zsr-level-meta-sep" aria-hidden="true">·</span>
          <span className="zsr-level-meta-item zsr-level-meta-distance">
            <span className="num">{level.distance_pips.toFixed(1)}</span>
            <span className="zsr-level-meta-label">pips {side}</span>
          </span>
          {incoherent && (
            <>
              <span className="zsr-level-meta-sep" aria-hidden="true">·</span>
              <span
                className="zsr-level-flag"
                title="Nivel cercano, pero no coherente con el bias M30"
              >
                ⚠ contra bias
              </span>
            </>
          )}
          {wick && wick.ratio >= 1.5 && (
            <>
              <span className="zsr-level-meta-sep" aria-hidden="true">·</span>
              <span
                className={`zsr-level-wick zsr-wick-${wick.direction}`}
                title={`Wick ${wick.direction === "bull" ? "inferior" : "superior"} ${wick.ratio.toFixed(1)}× body · rechazo detectado`}
              >
                🕯 rechazo {wick.direction === "bull" ? "alcista" : "bajista"} {wick.ratio.toFixed(1)}×
              </span>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

// ─── MarcoCard (marco teórico: gates + confluencia) ─────────────────────────

const DECISION_META: Record<
  ZoneMarco["decision"],
  { label: string; cls: string; ico: string }
> = {
  OPERAR:    { label: "OPERAR",    cls: "marco-go",   ico: "✅" },
  ESPERAR:   { label: "ESPERAR",   cls: "marco-wait", ico: "⏳" },
  NO_OPERAR: { label: "NO OPERAR", cls: "marco-stop", ico: "⛔" },
};

function ScoreBar({ score, max }: { score: number; max: number }) {
  const pct = Math.round((score / max) * 100);
  const cls =
    pct >= 67 ? "zsig-bar-fill-strong"
    : pct >= 42 ? "zsig-bar-fill-normal"
    : "zsig-bar-fill-weak";
  return (
    <div className="zsig-bar-track" title={`Score ${score}/${max}`}>
      <div className={`zsig-bar-fill ${cls}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function MarcoCard({ marco }: { marco: ZoneMarco }) {
  const [showDetail, setShowDetail] = useState(false);
  const meta = DECISION_META[marco.decision] ?? DECISION_META.NO_OPERAR;
  const hasSetup = marco.entry_price != null;
  const hasCriteria = marco.criteria_met.length > 0 || marco.criteria_failed.length > 0;

  // Para una señal accionable (OPERAR con dirección), el color sigue al LADO:
  // LONG = todo verde, SHORT = todo rojo. Evita mezclar verde (decisión) con rojo
  // (lado) en un OPERAR SHORT. Para ESPERAR / NO OPERAR se mantiene el color de la decisión.
  const directional =
    marco.decision === "OPERAR" && (marco.side === "LONG" || marco.side === "SHORT");
  const toneCls = directional
    ? (marco.side === "LONG" ? "marco-long" : "marco-short")
    : meta.cls;

  return (
    <div className={`marco-card ${toneCls}`}>
      {/* Header: decisión */}
      <div className="marco-header">
        <span className={`marco-badge ${toneCls}`}>
          {meta.ico} {meta.label}
          {marco.strength === "fuerte" && (
            <span className={`marco-strong ${toneCls}`}>FUERTE</span>
          )}
        </span>
        {marco.side && (
          <span className={`marco-side marco-side-${marco.side.toLowerCase()}`}>{marco.side}</span>
        )}
      </div>

      <div className="marco-reason">{marco.reason}</div>

      {/* Aviso de noticia (gate blando) */}
      {marco.news_warning && (
        <div className="marco-news" role="status">
          ⚠ Noticia high-impact{marco.news_warning.title ? `: ${marco.news_warning.title}` : ""}
          {typeof marco.news_warning.minutes_until === "number"
            ? ` · ~${marco.news_warning.minutes_until}min`
            : ""} — esperar a que pase
        </div>
      )}

      {/* Confluencia */}
      {marco.decision !== "NO_OPERAR" && (
        <div className="marco-confluence">
          <span className="marco-confluence-label">Confluencia</span>
          <ScoreBar score={marco.confluence.score} max={marco.confluence.max} />
          <span className="marco-confluence-text num">
            {marco.confluence.score}/{marco.confluence.max}
          </span>
        </div>
      )}

      {/* Precios del setup */}
      {hasSetup && (
        <div className="zsig-prices">
          <div className="zsig-price-item">
            <span className="zsig-price-label">Entrada</span>
            <span className="zsig-price-value num">{marco.entry_price!.toFixed(5)}</span>
          </div>
          <div className="zsig-price-item zsig-price-sl">
            <span className="zsig-price-label">Stop Loss</span>
            <span className="zsig-price-value num">{marco.sl_price?.toFixed(5)}</span>
            <span className="zsig-price-sub num">{marco.risk_pips} pips</span>
          </div>
          <div className="zsig-price-item zsig-price-tp">
            <span className="zsig-price-label">Take Profit</span>
            <span className="zsig-price-value num">{marco.tp_price?.toFixed(5)}</span>
            <span className="zsig-price-sub num">{marco.reward_pips} pips</span>
          </div>
          <div className="zsig-price-item">
            <span className="zsig-price-label">RRR</span>
            <span className="zsig-price-value num zsig-rrr">{marco.rrr?.toFixed(2)}:1</span>
          </div>
        </div>
      )}

      {/* Checklist de gates */}
      <div className="marco-gates">
        {marco.gates.map((g: MarcoGate) => (
          <span
            key={g.key}
            className={`marco-gate ${g.passed ? "on" : "off"} ${g.hard ? "" : "soft"}`}
            title={g.detail || g.label}
          >
            {g.passed ? "✓" : "✗"} {g.label}
            {!g.hard && <span className="marco-gate-tag">blando</span>}
          </span>
        ))}
      </div>

      {/* Sesión + nivel usado */}
      <div className="zsig-meta-row">
        {marco.session_status && marco.session_status !== "unknown" && (
          <span className={`zsig-session zsig-session-${marco.session_status}`}>
            {marco.session_status === "fire" ? "🔥 Sesión FIRE"
             : marco.session_status === "ok" ? "✓ Sesión OK"
             : "⚠ Sesión AVOID"}
            {" "}<span className="num">{marco.session_hour_madrid?.toString().padStart(2,"0")}h Madrid</span>
          </span>
        )}
        {marco.level_used && (
          <span className="zsig-level-used-detail num">
            {marco.level_used.type === "support" ? "Soporte" : "Resistencia"}{" "}
            {marco.level_used.price.toFixed(5)} · {marco.level_used.strength}★ · {marco.level_used.touches} toques · {marco.level_used.distance_pips.toFixed(1)} pips
          </span>
        )}
      </div>

      {/* Detalle de confluencia */}
      {hasCriteria && (
        <>
          <button
            type="button"
            className="zsig-detail-toggle"
            onClick={() => setShowDetail(v => !v)}
            aria-expanded={showDetail}
          >
            {showDetail ? "Ocultar" : "Ver"} factores ({marco.criteria_met.length} a favor, {marco.criteria_failed.length} en contra)
          </button>

          {showDetail && (
            <div className="zsig-criteria">
              {marco.criteria_met.length > 0 && (
                <div className="zsig-criteria-group">
                  <div className="zsig-criteria-heading zsig-criteria-met-head">A favor</div>
                  {marco.criteria_met.map((c, i) => (
                    <div key={i} className="zsig-criterion zsig-criterion-met">✓ {c}</div>
                  ))}
                </div>
              )}
              {marco.criteria_failed.length > 0 && (
                <div className="zsig-criteria-group">
                  <div className="zsig-criteria-heading zsig-criteria-fail-head">En contra</div>
                  {marco.criteria_failed.map((c, i) => (
                    <div key={i} className="zsig-criterion zsig-criterion-fail">✗ {c}</div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function PairCard({ data }: { data: ZonesPairResponse }) {
  const activeLevels = useMemo(() => data.levels.filter(l => l.active), [data.levels]);
  const inRange = useMemo(
    () => data.levels.filter(l => l.within_range && !l.active),
    [data.levels]
  );
  const far = useMemo(
    () => data.levels.filter(l => !l.within_range),
    [data.levels]
  );
  const [showFar, setShowFar] = useState(false);

  return (
    <section className="zsr-card">
      <header className="zsr-card-header">
        <div className="zsr-card-title-block">
          <h2 className="zsr-card-pair">{data.pair}</h2>
          <div className="zsr-card-price num">{data.price.toFixed(5)}</div>
        </div>
        <BiasChip bias={data.bias_m30} />
      </header>

      {data.cross && (
        <div className="zsr-cross-row">
          <CrossBadge cross={data.cross} />
        </div>
      )}

      {data.marco && (
        <div className="zsr-signal-section">
          <MarcoCard marco={data.marco} />
        </div>
      )}

      <RangoBanner bias={data.bias_m30} />

      {data.market_closed && (
        <div className="zsr-closed-banner">
          🌙 Mercado cerrado · última vela hace{" "}
          <span className="num">
            {data.data_age_minutes != null ? Math.round(data.data_age_minutes) : "?"}
          </span>{" "}
          min
        </div>
      )}

      <div className="zsr-summary">
        <div className="zsr-summary-item">
          <div className="zsr-summary-label">Activos</div>
          <div className="zsr-summary-value num">{activeLevels.length}</div>
        </div>
        <div className="zsr-summary-item">
          <div className="zsr-summary-label">En rango</div>
          <div className="zsr-summary-value num">{inRange.length}</div>
        </div>
        <div className="zsr-summary-item">
          <div className="zsr-summary-label">Total</div>
          <div className="zsr-summary-value num">{data.levels.length}</div>
        </div>
      </div>

      {activeLevels.length === 0 && inRange.length === 0 ? (
        <div className="zsr-empty">
          Sin niveles dentro del rango activo ({data.params.active_range_pips} pips). Ajusta el
          parámetro o espera a que el precio se acerque a una zona.
        </div>
      ) : (
        <>
          {activeLevels.length > 0 && (
            <div className="zsr-levels-block">
              <div className="zsr-levels-heading">
                <span className="zsr-levels-heading-dot zsr-heading-active" />
                Niveles activos · operables ahora
              </div>
              {activeLevels.map((lv, i) => (
                <LevelRow key={`a-${i}`} level={lv} price={data.price} />
              ))}
            </div>
          )}

          {inRange.length > 0 && (
            <div className="zsr-levels-block">
              <div className="zsr-levels-heading">
                <span className="zsr-levels-heading-dot zsr-heading-range" />
                Cercanos · no coherentes con bias M30
              </div>
              {inRange.map((lv, i) => (
                <LevelRow key={`r-${i}`} level={lv} price={data.price} />
              ))}
            </div>
          )}
        </>
      )}

      {far.length > 0 && (
        <div className="zsr-far-block">
          <button
            type="button"
            className="zsr-far-toggle"
            onClick={() => setShowFar(v => !v)}
            aria-expanded={showFar}
          >
            {showFar ? "Ocultar" : "Ver"} {far.length} nivel{far.length === 1 ? "" : "es"} lejano{far.length === 1 ? "" : "s"}
          </button>
          {showFar && (
            <div className="zsr-levels-block">
              {far.map((lv, i) => (
                <LevelRow key={`f-${i}`} level={lv} price={data.price} />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function ParamsPanel({
  params, onChange, onReset,
}: {
  params: Params;
  onChange: (p: Params) => void;
  onReset: () => void;
}) {
  const [open, setOpen] = useState(false);

  function update<K extends keyof Params>(key: K, value: Params[K]) {
    onChange({ ...params, [key]: value });
  }

  return (
    <div className="zsr-params">
      <button
        type="button"
        className="zsr-params-toggle"
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
      >
        Parámetros del detector {open ? "▴" : "▾"}
      </button>
      {open && (
        <div className="zsr-params-body">
          <label className="zsr-param">
            <span>Ventana pivot</span>
            <input
              type="number" min={1} max={10} step={1}
              value={params.window}
              onChange={e => update("window", Math.max(1, Number(e.target.value) || 1))}
            />
            <em>velas a cada lado</em>
          </label>
          <label className="zsr-param">
            <span>Fundir pivots</span>
            <input
              type="number" min={1} max={50} step={0.5}
              value={params.merge_distance_pips}
              onChange={e => update("merge_distance_pips", Math.max(0.5, Number(e.target.value) || 1))}
            />
            <em>pips</em>
          </label>
          <label className="zsr-param">
            <span>Rango activo</span>
            <input
              type="number" min={5} max={200} step={1}
              value={params.active_range_pips}
              onChange={e => update("active_range_pips", Math.max(5, Number(e.target.value) || 25))}
            />
            <em>pips desde precio</em>
          </label>
          <label className="zsr-param">
            <span>Mín velas entre pivots</span>
            <input
              type="number" min={1} max={20} step={1}
              value={params.min_bars_between}
              onChange={e => update("min_bars_between", Math.max(1, Number(e.target.value) || 1))}
            />
            <em>velas</em>
          </label>
          <label className="zsr-param">
            <span>Tolerancia toque</span>
            <input
              type="number" min={0.5} max={20} step={0.5}
              value={params.touch_tolerance_pips}
              onChange={e => update("touch_tolerance_pips", Math.max(0.5, Number(e.target.value) || 3))}
            />
            <em>pips</em>
          </label>
          <label className="zsr-param">
            <span>Precio del nivel</span>
            <select
              value={params.level_selector}
              onChange={e => update("level_selector", e.target.value as "median" | "mean")}
            >
              <option value="median">Mediana (robusta)</option>
              <option value="mean">Media</option>
            </select>
            <em></em>
          </label>
          <label className="zsr-param zsr-param-wide">
            <span>Umbral RANGO (× ATR M30)</span>
            <div className="zsr-param-slider-row">
              <input
                type="range" min={0.1} max={1.0} step={0.05}
                value={params.rango_atr_mult}
                onChange={e => update("rango_atr_mult", Number(e.target.value))}
              />
              <input
                type="number" min={0.1} max={1.0} step={0.05}
                value={params.rango_atr_mult}
                onChange={e => {
                  const v = Number(e.target.value);
                  if (!Number.isNaN(v)) update("rango_atr_mult", Math.max(0.1, Math.min(1.0, v)));
                }}
                className="zsr-param-slider-num"
              />
            </div>
            <em>separación EMA50/EMA100 menor a este múltiplo del ATR M30 → RANGO. Default 0.3.</em>
          </label>
          <button type="button" className="zsr-params-reset" onClick={onReset}>
            Restaurar valores por defecto
          </button>
        </div>
      )}
    </div>
  );
}

export function ZonasSRView() {
  const [params, setParams] = useState<Params>(DEFAULT_PARAMS);
  const [data, setData] = useState<ZonesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFetchedAt, setLastFetchedAt] = useState<string | null>(null);
  const [alertsOn, setAlertsOn] = useState<boolean>(false);
  const abortRef = useRef<AbortController | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  // Último lado FUERTE por par para detectar transiciones a OPERAR fuerte.
  const prevStrongRef = useRef<Map<string, "LONG" | "SHORT" | null>>(new Map());

  // Cargar parámetros persistidos en el primer render
  useEffect(() => {
    setParams(loadParams());
  }, []);

  // Persistir cambios de parámetros
  useEffect(() => {
    try {
      window.localStorage.setItem(PARAMS_STORAGE_KEY, JSON.stringify(params));
    } catch {
      // ignore
    }
  }, [params]);

  // Activar alertas — DEBE venir de un clic (gesto) para desbloquear audio +
  // permiso de notificación. Llamarlo en useEffect haría que el navegador lo ignore.
  const enableAlerts = useCallback(() => {
    try {
      const AC = window.AudioContext ?? (window as any).webkitAudioContext;
      if (AC) {
        if (!audioCtxRef.current) audioCtxRef.current = new AC();
        audioCtxRef.current.resume().catch(() => {});
      }
    } catch { /* audio no disponible */ }
    if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }
    setAlertsOn(true);
    try { localStorage.setItem(ALERTS_ON_KEY, "1"); } catch {}
  }, []);

  const muteAlerts = useCallback(() => {
    setAlertsOn(false);
    try { localStorage.setItem(ALERTS_ON_KEY, "0"); } catch {}
  }, []);

  // Leer localStorage solo en el cliente para evitar mismatch de hidratación.
  useEffect(() => {
    try { setAlertsOn(localStorage.getItem(ALERTS_ON_KEY) === "1"); } catch { /* ignore */ }
  }, []);

  // Si las alertas quedaron activas de una sesión previa, el AudioContext aún no
  // existe (necesita un gesto). Lo desbloqueamos en el primer clic de la página.
  useEffect(() => {
    if (!alertsOn || audioCtxRef.current) return;
    const unlock = () => {
      try {
        const AC = window.AudioContext ?? (window as any).webkitAudioContext;
        if (AC && !audioCtxRef.current) {
          audioCtxRef.current = new AC();
          audioCtxRef.current.resume().catch(() => {});
        }
      } catch { /* ignore */ }
    };
    window.addEventListener("pointerdown", unlock, { once: true });
    return () => window.removeEventListener("pointerdown", unlock);
  }, [alertsOn]);

  // Detectar transición a señal FUERTE y disparar sonido + notificación.
  useEffect(() => {
    if (!data?.items) return;
    const prev = prevStrongRef.current;
    const isFirst = prev.size === 0;
    for (const item of data.items) {
      const cur = strongSide(item.marco);
      const last = prev.get(item.pair) ?? null;
      prev.set(item.pair, cur);
      if (isFirst) continue;            // baseline al montar, sin alertar
      if (!alertsOn) continue;
      // Nueva señal fuerte (aparece o cambia de dirección)
      if (cur && cur !== last) {
        const ctx = audioCtxRef.current;
        if (ctx) { ctx.resume().catch(() => {}); playStrongSound(ctx, cur); }
        if (item.marco) sendStrongNotification(item.pair, item.marco);
      }
    }
  }, [data, alertsOn]);

  const fetchZones = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/zones?${buildQuery(params)}`, { signal: ctrl.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: ZonesResponse = await res.json();
      setData(json);
      setLastFetchedAt(new Date().toISOString());
    } catch (e: any) {
      if (e?.name === "AbortError") return;
      setError(e?.message || "Error al cargar zonas");
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => {
    fetchZones();
    const interval = setInterval(() => {
      if (data?.market_closed) return; // pausa polling con mercado cerrado
      fetchZones();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchZones]);

  return (
    <div className="zsr-view">
      <header className="zsr-header">
        <div className="zsr-header-left">
          <h1 className="zsr-title">Zonas S/R Activas</h1>
          <p className="zsr-subtitle">
            Niveles relevantes en {DEFAULT_PAIRS.join(" + ")} con bias M30. La app describe el
            terreno; tú decides la entrada en el chart.
          </p>
        </div>
        <div className="zsr-header-right">
          <div className="zsr-meta">
            <span className="zsr-meta-label">Última actualización</span>
            <span className="zsr-meta-value num">{formatLastUpdate(lastFetchedAt)}</span>
          </div>

          {/* Alertas de señal FUERTE (sonido + notificación) */}
          {alertsOn ? (
            <button
              type="button"
              className="zsr-notif-btn zsr-notif-on"
              title="Alertas de señal FUERTE activas — clic para silenciar"
              onClick={muteAlerts}
            >
              🔔 Alertas ON
            </button>
          ) : (
            <button
              type="button"
              className="zsr-notif-btn zsr-notif-pending"
              title="Activar sonido + notificación cuando haya OPERAR fuerte (compra/venta)"
              onClick={enableAlerts}
            >
              🔕 Activar alertas
            </button>
          )}

          <button
            type="button"
            className="zsr-refresh"
            onClick={fetchZones}
            disabled={loading}
            title="Refrescar"
          >
            {loading ? "Cargando…" : "Refrescar"}
          </button>
        </div>
      </header>

      <ParamsPanel
        params={params}
        onChange={setParams}
        onReset={() => setParams(DEFAULT_PARAMS)}
      />

      {error && (
        <div className="zsr-error">
          No se pudo cargar la información: {error}.{" "}
          <button type="button" className="zsr-error-retry" onClick={fetchZones}>
            Reintentar
          </button>
        </div>
      )}

      {data && data.items.length === 0 && !loading && !error && (
        <div className="zsr-empty zsr-empty-global">
          Sin datos disponibles. Verifica que el backend está activo y que tienes créditos en
          Twelve Data.
        </div>
      )}

      <div className="zsr-grid">
        {data?.items.map(item => (
          <PairCard key={item.pair} data={item} />
        ))}
      </div>

      <footer className="zsr-footer">
        <span className="zsr-footer-note">
          Detección: swing pivots ± ventana N + clustering aglomerativo single-linkage por
          distancia en pips. Bias M30 = EMA50 vs EMA100 sobre velas M15 resampleadas. Cache OHLC
          propio (15 min).
        </span>
      </footer>
    </div>
  );
}
