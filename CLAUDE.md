# CLAUDE.md

Contexto operativo del proyecto para futuras sesiones de Claude Code.

## Qué es esto

**AI Trading Assistant**: motor de decisión contextual sobre señales de TradingView para scalp intradía (0–15 min) en XAUUSD y EURUSD.

**No genera señales** — recibe las que dispara un Pine script propio del usuario y decide **ENTER / WAIT / AVOID** según calidad, contexto y timing. Cuando una señal está fuerte pero el precio está extendido, **degrada a WAIT y emite un plan operativo concreto** (zona de espera, precio trigger, invalidación, instrucciones) para evitar entradas tardías — ese fue el dolor original del usuario: entraba en la vela explosiva y perdía.

## Stack

- **Backend**: FastAPI (`backend/`). Python 3.11+. Desplegado en **Render free tier** (URL: `https://tradingapp-2glz.onrender.com`).
- **DB**: Dual-mode — **Supabase PostgreSQL** en producción (via `DATABASE_URL` + transaction pooler), **SQLite** en dev local si no hay `DATABASE_URL`. `storage.py` detecta y ramifica.
- **Frontend**: Next.js 14 App Router + TypeScript (`frontend/`). Corre local pero apunta a Render via `NEXT_PUBLIC_API_URL` en `.env.local`.
- **Pine scripts**: `scriptsTradingView/SMS_XAUUSD_v8_9_1.pine` y `SMS_EURUSD_v8_10_1.pine` (modificados para emitir JSON al webhook).
- **IA opcional**: OpenRouter (Claude/cualquier modelo) refina la decisión heurística si `USE_AI=1` y `OPENROUTER_API_KEY` están en env. Sin API key, motor heurístico puro.
- **News feed**: ForexFactory (JSON público gratis, sin key). `news_client.py` cachea 1h en memoria.

## Arquitectura del flujo

```
TradingView (Pine) ─alert()→ Render (URL fija) ─POST→ FastAPI ─→ Supabase PostgreSQL
                                                      │
                                                      ├─→ decision_engine (vetos + score)
                                                      ├─→ entry_planner (plan operativo)
                                                      ├─→ news_client (warnings, NO bloquea)
                                                      └─→ ai_client (OpenRouter, opcional)

Frontend Next.js (local) ←─polling 5s── Render
                         ├── /signals, /stats, /symbols
                         ├── /news/warnings (banner avisos activos)
                         ├── /news/calendar (sección colapsable, hora Madrid)
                         └── POST W/L/BE ─→ /signals/{id}/result (con journal opcional)
```

## Estructura

```
tradingApp/
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI: rutas + CORS abierto
│   │   ├── schemas.py          # TVSignal, AnalyzeResponse, EntryPlan (Pydantic)
│   │   ├── decision_engine.py  # Vetos duros + scoring → decisión
│   │   ├── entry_planner.py    # Genera plan operativo (PULLBACK/RETEST/MOMENTUM/SWEEP)
│   │   ├── tv_parser.py        # Acepta JSON o texto legacy multilínea
│   │   ├── ai_client.py        # OpenRouter via urllib (sin deps extra)
│   │   ├── news_client.py      # ForexFactory fetch + cache + warnings por ventana
│   │   └── storage.py          # Dual-mode: PostgreSQL (Supabase) / SQLite
│   ├── requirements.txt
│   ├── render.yaml             # Config deploy Render
│   ├── supabase_init.sql       # SQL inicial para tabla signals en Supabase
│   ├── .env.example
│   └── signals.db              # solo en dev local
├── frontend/
│   ├── app/
│   │   ├── page.tsx            # Dashboard + sesiones + kill zones + banner news + modal journal + calendario
│   │   ├── layout.tsx
│   │   └── globals.css
│   ├── .env.local              # NEXT_PUBLIC_API_URL → Render
│   └── .env.local.example
├── scriptsTradingView/
│   ├── SMS_XAUUSD_v8_9_1.pine
│   └── SMS_EURUSD_v8_10_1.pine
├── README.md
└── CLAUDE.md
```

## Lógica del motor de decisión

### Vetos duros (→ AVOID inmediato)

- LONG en zona `VENDE YA`, MTF30 BEAR, RSI ≥ 78, overhead/resistencia inmediata.
- SHORT en zona `COMPRA YA`, MTF30 BULL, RSI ≤ 22, soporte inmediato.
- `conf < 5`, `congestion = true`.

**Nota**: el filtro de noticias **NO es un veto**. Las señales que caen en ventana de noticia high-impact se evalúan normalmente; el frontend muestra un banner de aviso pero no bloquea. Decisión explícita del usuario.

### Score (después de pasar vetos)

| Factor | Pts |
|---|---|
| Quality PREMIUM / STRONG / NORMAL | +4 / +3 / +1 |
| MTF30 alineado | +2 |
| Zona favorable (`COMPRA*` LONG, `VENDE*` SHORT) | +2 |
| Patrón presente alineado | +1 |
| `vol_high` | +1 |
| FVG presente alineado | +1 |
| `conf >= 14` / `>= 10` | +2 / +1 |

### Mapeo

- score ≥ 8 → **ENTER** (pero degrada a WAIT si el plan dice PULLBACK/EXTENDED/SWEEP).
- score ≥ 5 → **WAIT** (con plan operativo si hay datos).
- score < 5 → **AVOID**.

## Entry planner — tipos de plan

Calcula `wait_zone`, `trigger_price`, `invalidation` e `instructions` operativas en español. Requiere que el Pine envíe `ema9`, `ema21`, `atr`, `swing_high`, `swing_low`, `high`, `low`.

| Tipo | Cuándo se elige |
|---|---|
| `SWEEP_REVERSAL` | Zona extrema (`VENDE YA` / `COMPRA YA`) → barrida + vuelta dentro |
| `PULLBACK_EMA9` | Precio a >1× ATR del EMA9 → esperar retroceso a EMA9/EMA21 |
| `EXTENDED_SKIP` | Precio a >2.5× ATR del EMA9 → mejor saltar |
| `RETEST` | Viene de romper swing reciente → esperar retest del nivel |
| `MOMENTUM_CONFIRM` | Cerca del EMA pero sin cierre fuerte → esperar cierre próxima vela con cuerpo >50% |

**Filosofía pro scalper aplicada**: nunca entrar en la vela de señal si está extendida; los pros esperan pullback al EMA9, retest del nivel roto, o sweep + reversión.

## News warnings (ForexFactory)

**Comportamiento**: aviso visual, no veto. Banner en el dashboard cuando hay high-impact news en ventana.

- **Fuente**: `https://nfs.faireconomy.media/ff_calendar_thisweek.json` (free, sin auth)
- **Cache**: 1h en memoria (`news_client._cache`). Si falla fetch, mantiene cache viejo o devuelve `[]`.
- **Ventana default**: 30 min antes, 5 min después del evento (`NEWS_WINDOW_BEFORE_MIN`, `NEWS_WINDOW_AFTER_MIN`).
- **Mapeo símbolo → monedas**: `XAUUSD/XAGUSD → USD`, `EURUSD → EUR+USD`, genérico parte el string en 2 códigos de 3 letras.
- **Estados del banner**: `upcoming` (amarillo), `imminent` (rojo pulsante, ≤5min), `past` (gris tenue, ya pasó pero en ventana).
- **Desactivar**: `NEWS_FILTER_ENABLED=0`.

**Calendario económico en frontend**: sección colapsable con date picker + hora Madrid (vía `zoneinfo` + `tzdata`). Carga perezosa al abrir la sección. Requiere `tzdata` en `requirements.txt` porque Windows Python no trae la base IANA.

## Market Sessions + Kill Zones (frontend)

### Panel de sesiones de mercado

4 cards en grid con reloj en tiempo real (tick 1s):
- **Asia · Tokyo**, **Londres**, **New York** — cada una muestra hora local, estado ABIERTO/CERRADO, barra de progreso, countdown al cierre/apertura.
- **Madrid · Local** — hora del usuario + detección de overlap (LDN+NYC, ASIA+LDN).

Las horas de apertura/cierre están en UTC en `SESSIONS[]`. `isSessionOpen()`, `sessionProgress()`, `sessionCountdown()` calculan estado en tiempo real.

### Panel Kill Zones (hora Madrid)

Sección colapsable (`KillZonesPanel`) con timeline vertical que muestra las ventanas operativas del scalper en hora Madrid. Definidas en `KILL_ZONES[]`:

| Hora Madrid | Sesión | Status | Acción |
|---|---|---|---|
| 02:00–05:00 | Asia | avoid | No operar (solo análisis de rango) |
| 05:00–09:00 | Pre-London | avoid | No operar (identificar liquidez) |
| 09:00–10:30 | London Open | fire | Setup principal (breakout / liquidity sweep) |
| 10:30–12:00 | London Continuation | ok | Solo continuación (no forzar trades) |
| 12:00–14:00 | Pre-NY | warn | Pullbacks / manipulación (avanzado) |
| 14:00–17:00 | Overlap LDN-NY | fire | MEJOR VENTANA (A+ setups) |
| 17:00–19:00 | NY Mid | warn | Selectivo (reversals / rangos) |
| 19:00–22:00 | NY Close | avoid | Evitar |

- **Detección automática**: `getMadridHourMin()` usa `Intl.DateTimeFormat` con `Europe/Madrid` para obtener la hora local. `isInKillZone()` determina la sesión activa.
- **UX**: la sesión activa se resalta con dot animado, tag "AHORA", barra de progreso y opacidad completa. Las inactivas se atenúan (opacity 0.55).
- **Header inteligente**: el botón toggle muestra un badge con la kill zone activa sin necesidad de abrir el panel.
- **Colores por tipo**: `fire` (naranja), `ok` (verde), `warn` (amarillo), `avoid` (gris).
- **Leyenda**: footer con los 4 niveles + nota "Hora Madrid".

### Zona chips con color coding (tabla de señales)

La columna "Zona" de la tabla de señales usa chips coloreados en vez de texto plano:

| Zona | Clase CSS | Color | Significado |
|---|---|---|---|
| `COMPRA YA` | `zona-deep-discount` | Verde intenso + glow | Descuento extremo — ideal para LONG |
| `COMPRA` | `zona-discount` | Verde suave | Zona de descuento |
| `VENDE` | `zona-premium` | Naranja | Zona premium |
| `VENDE YA` | `zona-deep-premium` | Rojo + glow | Premium extremo — ideal para SHORT |

**Tooltips contextuales**: `zonaTooltip(zona, side)` genera texto que depende de la zona **y** del lado de la señal. Ejemplo: `VENDE YA` + LONG → "Premium extremo — NO comprar aquí (resistencia fuerte)".

**Decisión de diseño**: se evaluó agregar un panel independiente de zonas de compra/venta pero se descartó por redundancia (el motor ya usa `zona` en vetos, score y entry planner) y principio pro-scalper de minimizar indicadores visuales. El color coding da feedback instantáneo sin ruido adicional.

## Taken vs Rated + Journal post-mortem

Concepto clave: separar **calidad del sistema** (rated) de **calidad de ejecución** (taken).

Al marcar W/L/BE se abre un **modal obligatorio** (sin botón Saltar). Primera pregunta: **¿Operaste esta señal?**

- **No, solo calificar** → se guarda `taken='no'`. Solo se pide el resultado (WIN/LOSS/BE). No se pide journal. Mide el **edge del sistema** sin ruido de ejecución. Muchas señales entran aquí.
- **Sí, la operé** → se guarda `taken='yes'` y obliga a contestar:
  1. ¿Respetaste el plan? (Sí/No)
  2. ¿Cerraste antes del TP/SL? (Sí/No)
  3. Emoción dominante (Confianza / Miedo / FOMO / Venganza)

El botón **Guardar** queda deshabilitado hasta que todos los campos requeridos estén completos.

**Stats divididas** (en `/stats`):
- `overall` — todas las cerradas (legacy, incluye null)
- `overall_taken` — solo `taken='yes'` (PnL real de ejecuciones)
- `overall_rated` — solo `taken='no'` (PnL hipotético, edge del sistema)
- `execution_rate` — `len(taken) / len(closed)` (cuántas ejecutas de las que evalúas)
- `by_emotion`, `by_respected_plan` — breakdowns solo sobre taken (calificadas no tienen journal)

**Lectura como trader pro**:
- Si `overall_rated.WR > overall_taken.WR` → el sistema tiene edge, tu ejecución lo destruye (entries tardías, cierres tempranos, emoción)
- Si ambas son similares y bajas → el sistema es débil
- Si `execution_rate` es muy bajo → demasiado selectivo o indeciso

**Tabla de señales**: badge `EJEC` (verde) o `CAL` (azul) junto al resultado para distinguir visualmente.

## Esquema TVSignal (lo que envía el Pine)

Campos obligatorios: `signal`, `symbol`, `price`, `sl`, `be`, `tp`, `conf`, `quality`.
Contextuales: `pattern`, `fvg`, `vol_high`, `vol_ratio`, `rsi`, `kz`, `mtf`, `zona`, `overhead`, `congestion`.
Para el planner (opcionales pero recomendados): `ema9`, `ema21`, `atr`, `swing_high`, `swing_low`, `high`, `low`.

Valores categóricos esperados:
- `signal`: `LONG | SHORT | BUY | SELL`
- `quality`: `PREMIUM | STRONG | NORMAL | LOW`
- `mtf`: `BULL | BEAR | MIX`
- `zona`: `COMPRA YA | COMPRA | VENDE | VENDE YA`

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | `{ok: true}` |
| POST | `/analyze?ai=0\|1` | Evalúa una señal estructurada Pydantic |
| POST | `/webhook/tradingview?ai=0\|1` | Recibe del Pine, parsea JSON o texto legacy |
| GET | `/signals?limit=100&symbol=XAUUSD` | Lista paginada filtrable por símbolo |
| GET | `/symbols` | Símbolos únicos vistos (para tabs del frontend) |
| POST | `/signals/{id}/result` | Body `{result, exit_price?, journal_*?}` — marca WIN/LOSS/BE + journal |
| DELETE | `/signals/{id}` | Borra una señal (para limpiar data sucia) |
| GET | `/stats` | Agregados: overall + by_symbol/decision/source/quality/side/zona/mtf/pattern |
| GET | `/news?symbol=X&hours=24` | Próximas high-impact news relevantes al símbolo |
| GET | `/news/warnings?currencies=USD,EUR&now=ISO` | Warnings activos (frontend polea cada 5s). `now` para simular |
| GET | `/news/calendar?date=YYYY-MM-DD&impact=high` | Eventos de un día en hora Madrid |

`?ai=1` activa el refinamiento OpenRouter (si está configurado). El motor heurístico siempre corre primero; si la IA falla, cae a heurística.

## Tabla `signals` (idéntica en SQLite y PostgreSQL)

```
id                        SERIAL/INTEGER PK
received_at               TEXT            -- ISO UTC
signal_json               TEXT            -- JSON completo de TVSignal
response_json             TEXT            -- JSON completo de AnalyzeResponse (incluye plan)
decision                  TEXT            -- ENTER | WAIT | AVOID
symbol                    TEXT
side                      TEXT            -- LONG | SHORT
result                    TEXT            -- WIN | LOSS | BE | NULL
exit_price                REAL/DOUBLE
pnl                       REAL/DOUBLE
closed_at                 TEXT
source                    TEXT            -- heuristic | ai
taken                     TEXT            -- yes (ejecutada) | no (solo calificada) | NULL
journal_respected_plan    TEXT            -- yes | no | NULL (solo si taken=yes)
journal_closed_early      TEXT            -- yes | no | NULL (solo si taken=yes)
journal_emotion           TEXT            -- confianza | miedo | fomo | venganza | NULL (solo si taken=yes)
```

**Migración automática** en `init_db()`:
- PostgreSQL usa `ALTER TABLE ADD COLUMN IF NOT EXISTS` idempotente
- SQLite hace `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` condicional

Al añadir columnas nuevas en el futuro, agregarlas a la lista en ambos branches de `init_db()`.

## Variables de entorno

```bash
# DB (vacío = SQLite local)
DATABASE_URL=postgresql://postgres.XXX:PASS@aws-1-us-east-2.pooler.supabase.com:6543/postgres

# OpenRouter (opcional)
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=anthropic/claude-sonnet-4
OPENROUTER_REFERER=http://localhost
USE_AI=0

# News warnings
NEWS_FILTER_ENABLED=1
NEWS_WINDOW_BEFORE_MIN=30
NEWS_WINDOW_AFTER_MIN=5
```

## Convenciones del usuario

- **Idioma**: español. Toda salida visible (instrucciones del planner, razones, UI) en español.
- **Estilo de código**: directo, sin comentarios obvios, sin abstracciones especulativas. Ya hay una decisión validada de evitar over-engineering.
- **Stack del usuario**: Windows 11, PowerShell. **Cuidado con `curl`** en PowerShell — es alias de `Invoke-WebRequest`. Usar `curl.exe` o `Invoke-RestMethod` con `@{}` y `ConvertTo-Json`.
- **`localhost` vs `127.0.0.1`**: en su Windows, `localhost` resolvía a IPv6 y uvicorn solo escucha IPv4 por defecto → usar `127.0.0.1` o arrancar uvicorn con `--host 0.0.0.0`.
- **Horario del usuario**: opera en hora Madrid. Todas las horas visibles en UI (calendario económico) se muestran en `Europe/Madrid`.

## Cómo se levanta

### Producción (actual)
- **Backend**: Render auto-despliega en cada push a `main`
- **Frontend**: local (`npm run dev`) apuntando a Render via `.env.local`
- **DB**: Supabase (persistente, se mantiene entre redeploys)
- **TradingView webhook**: `https://tradingapp-2glz.onrender.com/webhook/tradingview`

### Dev local (opcional)
```bash
# 1) Backend local (usa SQLite si no hay DATABASE_URL)
cd backend && .venv\Scripts\activate && uvicorn app.main:app --reload

# 2) Frontend (apuntar a localhost temporalmente: editar .env.local)
cd frontend && npm run dev

# 3) ngrok si quieres recibir webhooks de TradingView en local
ngrok.exe http 8000
```

Frontend: http://localhost:3000 · Docs API: http://127.0.0.1:8000/docs

## Estado actual / decisiones tomadas

- **Deploy producción**: ✓ Backend en Render, DB en Supabase, frontend local apuntando a Render.
- **DB**: Dual-mode funcionando. Local usa SQLite, prod usa PostgreSQL con transaction pooler (port 6543).
- **IA OpenRouter**: implementada pero `USE_AI=0` por defecto.
- **Tracking de resultados**: ✓ botones W/L/BE + modal de journal post-mortem.
- **Multi-símbolo**: ✓ tabs en frontend, breakdowns por símbolo en stats.
- **Entry planner**: ✓ funciona si el Pine envía los campos contextuales.
- **News warnings**: ✓ banner visual (no veto), ventana 30min antes / 5min después.
- **Calendario económico**: ✓ sección colapsable con date picker y hora Madrid.
- **Borrado de señales**: ✓ DELETE `/signals/{id}` para limpiar data sucia.
- **Panel sesiones de mercado**: ✓ 4 cards con reloj real-time (Tokyo, Londres, NY, Madrid) + overlap detection.
- **Panel Kill Zones**: ✓ timeline vertical con 8 franjas horarias (hora Madrid), detección de sesión activa, barra de progreso, header con badge de sesión actual.
- **Zona chips coloreados**: ✓ chips con color coding (deep-discount → deep-premium) + tooltips contextuales según zona+lado en la tabla de señales.
- **Decisión de diseño UI**: se descartó un panel independiente de zonas compra/venta por redundancia con el motor y principio pro-scalper de "menos indicadores = mejor ejecución". Se optó por color coding inline.

## Próximos pasos posibles (mencionados, no hechos)

- Notificaciones a Telegram cuando llega ENTER.
- Calculadora de tamaño de posición integrada (capital + % riesgo → lotes).
- R:R floor como veto duro (rechazar si `(tp-entry)/(entry-sl) < 1.5`).
- Kill zone como veto duro en el backend (fuera de London/NY → WAIT automático). Nota: el panel visual ya existe, falta integrar como veto en `decision_engine.py`.
- Daily loss limit + cooldown post-trade (circuit breaker anti-revenge-trading).
- Equity curve y heatmap hora-del-día vs PnL en frontend.
- Backtest del motor sobre el historial acumulado en Supabase.
- Stats/breakdowns basados en journal (ver qué emociones pierden, si respetar el plan correlaciona con WR).
- Migrar frontend a Vercel para que todo sea público (hoy sigue siendo local).

## Gotchas conocidos

- **PowerShell + curl**: ver convenciones arriba.
- **`localhost` vs `127.0.0.1`**: ver convenciones arriba.
- **Render free spin-down**: tras 15min de inactividad el servicio se apaga, cold start ~30-50s. Mitigación: UptimeRobot/cron-job.org pinging `/health` cada 5min.
- **Supabase password con caracteres especiales**: `@`, `#`, `:`, etc. rompen el parsing del `DATABASE_URL`. Resetear con solo letras y números.
- **Supabase Direct Connection no funciona en Render** (IPv4 only). Usar **Transaction pooler** (port 6543, user `postgres.PROJECT_REF`).
- **`zoneinfo` en Windows**: requiere paquete `tzdata` (está en `requirements.txt`). Linux/Render trae la base IANA del sistema.
- **`/webhook/tradingview` no aparece en `/docs`** con schema de body: usa `Request` crudo (para aceptar también texto legacy). Para probar desde `/docs`, usar `/analyze`.
- **`.env.local` del frontend apunta a Render**: si el backend local tiene código nuevo, el frontend no lo verá hasta hacer push a Render o cambiar temporalmente `NEXT_PUBLIC_API_URL` a `http://127.0.0.1:8000`.
