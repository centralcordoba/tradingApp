"use client";

import "./PlaybookView.css";

export function PlaybookView() {
  return (
    <div className="playbook">
      <div className="pb-actions pb-no-print">
        <button className="pb-btn" onClick={() => window.print()}>
          Imprimir / PDF
        </button>
      </div>

      <header className="pb-header">
        <div className="pb-meta">Reglas operativas · v1.0</div>
        <h1>Horarios y reglas por franja</h1>
        <p className="pb-subtitle">
          Qué par operar en cada hora, qué evitar, y por qué.
        </p>
      </header>

      {/* QUICK CARDS */}
      <div className="pb-quick-cards">
        <div className="pb-qc pb-qc-aud">
          <div className="pb-qc-label">Mañana</div>
          <div className="pb-qc-pair">AUDUSD</div>
          <div className="pb-qc-hours">
            <strong>09:00 – 14:00</strong> Madrid
          </div>
          <div className="pb-qc-hours">03:00 – 08:00 NY</div>
          <div className="pb-qc-stat">9/9 wins históricos · +$615 · 100% WR</div>
        </div>
        <div className="pb-qc pb-qc-cad">
          <div className="pb-qc-label">Tarde</div>
          <div className="pb-qc-pair">USDCAD</div>
          <div className="pb-qc-hours">
            <strong>14:00 – 21:00</strong> Madrid
          </div>
          <div className="pb-qc-hours">08:00 – 15:00 NY</div>
          <div className="pb-qc-stat">8/8 wins históricos · +$679 · 100% WR</div>
        </div>
      </div>

      {/* TIMELINE */}
      <section className="pb-section">
        <h2>Mapa horario visual</h2>
        <p className="pb-section-sub">
          Hora Madrid arriba, hora NY abajo · Cada celda indica el par habilitado
        </p>

        <div className="pb-timeline">
          <div className="pb-tl-cell pb-tl-aud">09<div className="pb-tl-cell-tag">AUD</div></div>
          <div className="pb-tl-cell pb-tl-aud">10<div className="pb-tl-cell-tag">AUD</div></div>
          <div className="pb-tl-cell pb-tl-aud">11<div className="pb-tl-cell-tag">AUD</div></div>
          <div className="pb-tl-cell pb-tl-aud">12<div className="pb-tl-cell-tag">AUD</div></div>
          <div className="pb-tl-cell pb-tl-aud">13<div className="pb-tl-cell-tag">AUD</div></div>
          <div className="pb-tl-cell pb-tl-both">14<div className="pb-tl-cell-tag">cruce</div></div>
          <div className="pb-tl-cell pb-tl-cad">15<div className="pb-tl-cell-tag">CAD</div></div>
          <div className="pb-tl-cell pb-tl-cad">16<div className="pb-tl-cell-tag">CAD</div></div>
          <div className="pb-tl-cell pb-tl-cad">17<div className="pb-tl-cell-tag">CAD</div></div>
          <div className="pb-tl-cell pb-tl-none">18<div className="pb-tl-cell-tag">opc</div></div>
          <div className="pb-tl-cell pb-tl-cad">19<div className="pb-tl-cell-tag">CAD</div></div>
          <div className="pb-tl-cell pb-tl-cad">20<div className="pb-tl-cell-tag">CAD</div></div>
          <div className="pb-tl-cell pb-tl-cad">21<div className="pb-tl-cell-tag">CAD</div></div>
        </div>
        <div className="pb-timeline-ny">
          {["03","04","05","06","07","08","09","10","11","12","13","14","15"].map(h => (
            <div key={h} className="pb-tl-ny-cell">{h}</div>
          ))}
        </div>

        <div className="pb-legend">
          <div className="pb-legend-item">
            <span className="pb-legend-dot" style={{ background: "var(--pb-aud-bg)", border: "1px solid var(--pb-aud)" }} />
            Solo AUDUSD
          </div>
          <div className="pb-legend-item">
            <span className="pb-legend-dot" style={{ background: "var(--pb-cad-bg)", border: "1px solid var(--pb-cad)" }} />
            Solo USDCAD
          </div>
          <div className="pb-legend-item">
            <span className="pb-legend-dot" style={{ background: "var(--pb-aud-bg-strong)" }} />
            Hora de cruce
          </div>
          <div className="pb-legend-item">
            <span className="pb-legend-dot" style={{ background: "var(--bg-hover)", border: "1px solid var(--border-subtle)" }} />
            Sin operaciones
          </div>
        </div>
      </section>

      {/* HOUR BLOCKS */}
      <section className="pb-section">
        <h2>Detalle franja por franja</h2>
        <p className="pb-section-sub">
          Para cada hora, qué hacer con AUDUSD y qué hacer con USDCAD
        </p>

        <div className="pb-hour-block aud">
          <div className="pb-hb-head">
            <div className="pb-hb-time">
              09:00 – 13:59 Madrid <span className="pb-ny">03:00 – 07:59 NY</span>
            </div>
            <div className="pb-hb-badge aud">Mañana AUDUSD</div>
          </div>
          <div className="pb-hb-rules">
            <div className="pb-hb-rule pb-hb-rule-yes">
              <div className="pb-hb-rule-label">Sí operar</div>
              <div className="pb-hb-rule-pair">AUDUSD</div>
              <div className="pb-hb-rule-action">
                Ventana óptima. Buscar setup SMC completo (BOS + OB + FVG).
              </div>
            </div>
            <div className="pb-hb-rule pb-hb-rule-no">
              <div className="pb-hb-rule-label">No operar</div>
              <div className="pb-hb-rule-pair">USDCAD</div>
              <div className="pb-hb-rule-action">
                Pre-apertura NY. Ahí cayeron las 2 pérdidas: −$292 y −$134.
              </div>
            </div>
          </div>
          <div className="pb-hb-context">
            Sesión Asia tardía + Londres activa. AUDUSD tiene flujo institucional propio.
            USDCAD aún no tiene liquidez NY, movimiento errático.
          </div>
        </div>

        <div className="pb-hour-block cross">
          <div className="pb-hb-head">
            <div className="pb-hb-time">
              14:00 – 14:59 Madrid <span className="pb-ny">08:00 – 08:59 NY</span>
            </div>
            <div className="pb-hb-badge cross">Hora de cruce</div>
          </div>
          <div className="pb-hb-rules">
            <div className="pb-hb-rule pb-hb-rule-warn">
              <div className="pb-hb-rule-label">Cerrar</div>
              <div className="pb-hb-rule-pair">AUDUSD</div>
              <div className="pb-hb-rule-action">
                A las 14:00 cierre manual de cualquier posición abierta, sin importar resultado.
              </div>
            </div>
            <div className="pb-hb-rule pb-hb-rule-yes cad">
              <div className="pb-hb-rule-label">Abrir</div>
              <div className="pb-hb-rule-pair">USDCAD</div>
              <div className="pb-hb-rule-action">
                Comienza ventana CAD. Apertura institucional NY. La mejor hora del día históricamente.
              </div>
            </div>
          </div>
          <div className="pb-hb-context">
            Apertura de Wall Street. Rotación de flujo: AUD pierde apoyo, CAD lo gana.
            Única hora donde ambos pares fueron rentables en tu historial.
          </div>
        </div>

        <div className="pb-hour-block cad">
          <div className="pb-hb-head">
            <div className="pb-hb-time">
              15:00 – 17:59 Madrid <span className="pb-ny">09:00 – 11:59 NY</span>
            </div>
            <div className="pb-hb-badge cad">Tarde USDCAD</div>
          </div>
          <div className="pb-hb-rules">
            <div className="pb-hb-rule pb-hb-rule-yes cad">
              <div className="pb-hb-rule-label">Sí operar</div>
              <div className="pb-hb-rule-pair">USDCAD</div>
              <div className="pb-hb-rule-action">
                Sesión NY plena. Liquidez peak, dirección establecida. Ventana óptima de CAD.
              </div>
            </div>
            <div className="pb-hb-rule pb-hb-rule-no">
              <div className="pb-hb-rule-label">PROHIBIDO</div>
              <div className="pb-hb-rule-pair">AUDUSD</div>
              <div className="pb-hb-rule-action">
                Las 2 peores pérdidas del historial: −$552 y −$420. Cero excepciones.
              </div>
            </div>
          </div>
          <div className="pb-hb-context">
            AUD pierde liquidez asiática y se mueve por arrastre del USD.
            CAD recibe flujo NY directo + reacción a datos US/CA + petróleo. Cada par en su mundo.
          </div>
        </div>

        <div className="pb-hour-block dead">
          <div className="pb-hb-head">
            <div className="pb-hb-time">
              18:00 – 18:59 Madrid <span className="pb-ny">12:00 – 12:59 NY</span>
            </div>
            <div className="pb-hb-badge dead">NY lunch</div>
          </div>
          <div className="pb-hb-rules">
            <div className="pb-hb-rule pb-hb-rule-warn">
              <div className="pb-hb-rule-label">Opcional</div>
              <div className="pb-hb-rule-pair">USDCAD</div>
              <div className="pb-hb-rule-action">
                Solo si hay setup muy claro. Por defecto, esperar a 19:00. Fakeouts comunes.
              </div>
            </div>
            <div className="pb-hb-rule pb-hb-rule-no">
              <div className="pb-hb-rule-label">No operar</div>
              <div className="pb-hb-rule-pair">AUDUSD</div>
              <div className="pb-hb-rule-action">Fuera de su sesión completamente.</div>
            </div>
          </div>
          <div className="pb-hb-context">
            Lunch hour de NY. Volumen baja, traders institucionales descansan.
            Tu historial no tiene data acá. Si dudás, pasá.
          </div>
        </div>

        <div className="pb-hour-block cad">
          <div className="pb-hb-head">
            <div className="pb-hb-time">
              19:00 – 21:00 Madrid <span className="pb-ny">13:00 – 15:00 NY</span>
            </div>
            <div className="pb-hb-badge cad">USDCAD tarde-NY</div>
          </div>
          <div className="pb-hb-rules">
            <div className="pb-hb-rule pb-hb-rule-yes cad">
              <div className="pb-hb-rule-label">Sí operar</div>
              <div className="pb-hb-rule-pair">USDCAD</div>
              <div className="pb-hb-rule-action">
                Segunda mitad de NY. Dirección confirmada del día. Setups limpios típicamente.
              </div>
            </div>
            <div className="pb-hb-rule pb-hb-rule-no">
              <div className="pb-hb-rule-label">No operar</div>
              <div className="pb-hb-rule-pair">AUDUSD</div>
              <div className="pb-hb-rule-action">Asia aún no abre. AUD muerto operativamente.</div>
            </div>
          </div>
          <div className="pb-hb-context">
            3 trades históricos USDCAD acá: 3 wins, +$198. Buena ventana secundaria si la primaria no dio setup.
          </div>
        </div>

        <div className="pb-hour-block dead">
          <div className="pb-hb-head">
            <div className="pb-hb-time">
              Resto del día <span className="pb-ny">21:01 – 08:59 Madrid</span>
            </div>
            <div className="pb-hb-badge dead">FUERA</div>
          </div>
          <div className="pb-hb-rules">
            <div className="pb-hb-rule pb-hb-rule-no">
              <div className="pb-hb-rule-label">No operar</div>
              <div className="pb-hb-rule-pair">AUDUSD</div>
              <div className="pb-hb-rule-action">Fuera de la ventana de mañana definida.</div>
            </div>
            <div className="pb-hb-rule pb-hb-rule-no">
              <div className="pb-hb-rule-label">No operar</div>
              <div className="pb-hb-rule-pair">USDCAD</div>
              <div className="pb-hb-rule-action">Fuera de la ventana de tarde definida.</div>
            </div>
          </div>
          <div className="pb-hb-context">
            Plataforma cerrada. Sin gráficos. Sin "una mirada rápida".
            Operar fuera de horario es la causa principal de pérdidas catastróficas.
          </div>
        </div>
      </section>

      {/* RESUMEN POR PAR */}
      <section className="pb-section">
        <h2>Resumen por par</h2>
        <p className="pb-section-sub">
          Lo que sí y lo que no, para cada par, de un vistazo
        </p>

        <h3 className="pb-section-h3 aud">AUDUSD</h3>
        <div className="pb-sum-card">
          <div className="pb-sum-row pb-sum-row-yes">
            <div className="pb-sum-row-label">SÍ operar</div>
            <div>Entre las <strong>09:00 y 14:00 Madrid</strong>, con setup SMC completo.</div>
          </div>
          <div className="pb-sum-row pb-sum-row-no">
            <div className="pb-sum-row-label">NO operar</div>
            <div>Después de las <strong>14:00 Madrid</strong>. Ahí están las 2 pérdidas más grandes del historial.</div>
          </div>
          <div className="pb-sum-row pb-sum-row-no">
            <div className="pb-sum-row-label">NUNCA</div>
            <div>Pasar de las 14:00 con posición abierta. Cierre manual obligatorio.</div>
          </div>
          <div className="pb-sum-row pb-sum-row-no">
            <div className="pb-sum-row-label">NUNCA</div>
            <div>Operar AUDUSD en sesión NY plena (15:00–17:00 Madrid).</div>
          </div>
        </div>

        <h3 className="pb-section-h3 cad">USDCAD</h3>
        <div className="pb-sum-card">
          <div className="pb-sum-row pb-sum-row-yes cad-mode">
            <div className="pb-sum-row-label">SÍ operar</div>
            <div>Entre las <strong>14:00 y 21:00 Madrid</strong>, con setup SMC completo.</div>
          </div>
          <div className="pb-sum-row pb-sum-row-no">
            <div className="pb-sum-row-label">NO operar</div>
            <div>Antes de las <strong>14:00 Madrid</strong>. Pre-apertura NY = pérdidas históricas.</div>
          </div>
          <div className="pb-sum-row pb-sum-row-no">
            <div className="pb-sum-row-label">NUNCA</div>
            <div>Operar USDCAD por la mañana, ni siquiera con setup "muy bueno".</div>
          </div>
          <div className="pb-sum-row pb-sum-row-no">
            <div className="pb-sum-row-label">NUNCA</div>
            <div>Solapar posición de USDCAD con una de AUDUSD abierta.</div>
          </div>
        </div>
      </section>

      {/* REGLAS GLOBALES */}
      <section className="pb-section">
        <h2>Reglas globales que aplican siempre</h2>
        <p className="pb-section-sub">No dependen de la hora ni del par</p>

        <div className="pb-sum-card">
          <div className="pb-sum-row pb-sum-row-no">
            <div className="pb-sum-row-label">NUNCA</div>
            <div>Mover el SL después de abrir el trade. Es la causa #1 de las pérdidas catastróficas.</div>
          </div>
          <div className="pb-sum-row pb-sum-row-no">
            <div className="pb-sum-row-label">NUNCA</div>
            <div>Abrir un tercer trade en el día. Máximo 2 trades diarios, en total.</div>
          </div>
          <div className="pb-sum-row pb-sum-row-no">
            <div className="pb-sum-row-label">NUNCA</div>
            <div>Operar después de una pérdida en el mismo día. Cierre obligatorio.</div>
          </div>
          <div className="pb-sum-row pb-sum-row-no">
            <div className="pb-sum-row-label">NUNCA</div>
            <div>Operar XAU/USD ni USDCHF. Pares excluidos del plan.</div>
          </div>
          <div className="pb-sum-row pb-sum-row-no">
            <div className="pb-sum-row-label">NUNCA</div>
            <div>Operar fines de semana, con noticias high-impact a menos de 30 min, o con menos de 6h de sueño.</div>
          </div>
        </div>
      </section>

      <footer className="pb-footer">
        <div>Horarios y reglas · v1.0 · mayo 2026</div>
        <div style={{ marginTop: 4 }}>
          Horarios calculados con broker GMT+3 · Madrid CEST · NY EDT
        </div>
      </footer>
    </div>
  );
}
