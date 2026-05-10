"use client";

import { useMemo, useState } from "react";
import { API } from "@/lib/api";
import {
  CORRELATION_PAIRS,
  CorrelationPair,
  CorrelationTier,
  correlationsFor,
  describeCorrelation,
  getCorrelation,
  getTier,
  LEGEND,
  tierEmoji,
} from "@/lib/correlations";
import "./CorrelationsView.css";

type Selection = { a: CorrelationPair; b: CorrelationPair } | null;

const QUICK_PROMPTS = [
  "Muéstrame el diagrama",
  "¿Cuál es la correlación entre EURUSD y GBPUSD?",
  "Dame todas las correlaciones de EURUSD",
  "¿USDJPY y USDCHF están correlacionados?",
];

export function CorrelationsView() {
  const [selection, setSelection] = useState<Selection>(null);
  const [activePair, setActivePair] = useState<CorrelationPair>("EURUSD");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pairList = useMemo(() => correlationsFor(activePair), [activePair]);

  async function ask(q: string) {
    const trimmed = q.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      const r = await fetch(`${API}/correlations/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        throw new Error(j.detail || `HTTP ${r.status}`);
      }
      setAnswer(j.answer || "");
    } catch (e: any) {
      setError(e?.message || "Error desconocido");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="corr-view">
      <header className="corr-header">
        <div>
          <h1 className="corr-title">Correlaciones FX</h1>
          <p className="corr-subtitle">
            Mapa fijo de correlaciones entre los 6 pares operables. Click en una celda para
            ver detalle. Pregunta en lenguaje natural en el panel derecho.
          </p>
        </div>
      </header>

      <div className="corr-grid">
        <section className="corr-card">
          <div className="corr-card-head">
            <h2>Matriz 6 × 6</h2>
            <span className="corr-card-hint">Click en celda</span>
          </div>

          <div className="corr-matrix-wrap">
            <table className="corr-matrix">
              <thead>
                <tr>
                  <th aria-hidden="true" />
                  {CORRELATION_PAIRS.map((p) => (
                    <th key={p} className="num">{p}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {CORRELATION_PAIRS.map((rowPair) => (
                  <tr key={rowPair}>
                    <th
                      scope="row"
                      className={`corr-row-head num ${activePair === rowPair ? "active" : ""}`}
                    >
                      <button onClick={() => setActivePair(rowPair)}>{rowPair}</button>
                    </th>
                    {CORRELATION_PAIRS.map((colPair) => {
                      const v = getCorrelation(rowPair, colPair);
                      const t: CorrelationTier =
                        rowPair === colPair ? "low" : getTier(v);
                      const isDiagonal = rowPair === colPair;
                      const isSelected =
                        selection &&
                        ((selection.a === rowPair && selection.b === colPair) ||
                          (selection.a === colPair && selection.b === rowPair));
                      return (
                        <td
                          key={colPair}
                          className={`corr-cell tier-${t} ${isDiagonal ? "diagonal" : ""} ${
                            isSelected ? "selected" : ""
                          }`}
                          onClick={() =>
                            !isDiagonal &&
                            setSelection({ a: rowPair, b: colPair })
                          }
                          title={
                            isDiagonal
                              ? rowPair
                              : `${rowPair} ↔ ${colPair}: ${v?.toFixed(2)}`
                          }
                        >
                          {isDiagonal ? (
                            <span className="corr-cell-self">·</span>
                          ) : (
                            <span className="num">{v! > 0 ? "+" : ""}{v!.toFixed(2)}</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {selection && (
            <CorrelationDetail a={selection.a} b={selection.b} onClose={() => setSelection(null)} />
          )}

          <div className="corr-list">
            <div className="corr-list-head">
              <span className="corr-list-label">
                <span className="num">{activePair}</span> vs todos
              </span>
              <span className="corr-card-hint">orden: |correlación| desc</span>
            </div>
            <ul className="corr-list-rows">
              {pairList.map((row) => {
                const desc = describeCorrelation(row.value);
                return (
                  <li
                    key={row.pair}
                    className={`corr-list-row tier-${row.tier}`}
                    onClick={() => setSelection({ a: activePair, b: row.pair })}
                  >
                    <span className="corr-list-emoji">{tierEmoji(row.tier)}</span>
                    <span className="corr-list-pair num">{row.pair}</span>
                    <span className="corr-list-val num">
                      {row.value > 0 ? "+" : ""}{row.value.toFixed(2)}
                    </span>
                    <span className="corr-list-tier">{desc.label}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        </section>

        <section className="corr-card corr-chat">
          <div className="corr-card-head">
            <h2>Preguntar al asistente</h2>
            <span className="corr-card-hint">vía OpenRouter</span>
          </div>

          <div className="corr-chat-quick">
            {QUICK_PROMPTS.map((p) => (
              <button
                key={p}
                className="corr-chip"
                onClick={() => { setQuestion(p); ask(p); }}
                disabled={loading}
              >
                {p}
              </button>
            ))}
          </div>

          <div className="corr-chat-input">
            <textarea
              placeholder="Ej: ¿están correlacionados USDJPY y USDCHF?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask(question);
                }
              }}
              rows={3}
              aria-label="Pregunta al asistente de correlaciones"
            />
            <button
              className="corr-send"
              onClick={() => ask(question)}
              disabled={loading || !question.trim()}
            >
              {loading ? "Consultando…" : "Preguntar"}
            </button>
          </div>

          <div className="corr-answer">
            {error && <div className="corr-answer-error">{error}</div>}
            {!error && !answer && !loading && (
              <div className="corr-answer-empty">
                La respuesta aparece aquí. Enter envía, Shift+Enter para nueva línea.
              </div>
            )}
            {answer && <pre className="corr-answer-text">{answer}</pre>}
          </div>
        </section>
      </div>

      <footer className="corr-legend">
        {LEGEND.map((l) => (
          <span key={l.tier} className={`corr-legend-item tier-${l.tier}`}>
            <span aria-hidden="true">{l.emoji}</span> {l.label}
          </span>
        ))}
      </footer>
    </div>
  );
}

function CorrelationDetail({
  a,
  b,
  onClose,
}: {
  a: CorrelationPair;
  b: CorrelationPair;
  onClose: () => void;
}) {
  const v = getCorrelation(a, b)!;
  const t = getTier(v);
  const desc = describeCorrelation(v);
  return (
    <div className={`corr-detail tier-${t}`}>
      <div className="corr-detail-head">
        <span className="num">{a} ↔ {b}</span>
        <button className="corr-detail-close" onClick={onClose} aria-label="Cerrar">×</button>
      </div>
      <div className="corr-detail-body">
        <div className="corr-detail-row">
          <span className="corr-detail-label">Correlación</span>
          <span className="corr-detail-value num">
            {tierEmoji(t)} {v > 0 ? "+" : ""}{v.toFixed(2)}
          </span>
        </div>
        <div className="corr-detail-row">
          <span className="corr-detail-label">Tipo</span>
          <span className="corr-detail-value">{desc.label}</span>
        </div>
        <p className="corr-detail-text">{desc.interpretation}</p>
      </div>
    </div>
  );
}
