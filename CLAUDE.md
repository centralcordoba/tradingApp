# CLAUDE.md

Contexto operativo del proyecto para futuras sesiones de Claude Code.

## Qué es esto

**AI Trading Assistant**: motor de decisión contextual sobre señales de TradingView para scalp intradía (0–15 min) en XAUUSD y EURUSD.

**No genera señales** — recibe las que dispara un Pine script propio del usuario y decide **ENTER / WAIT / AVOID** según calidad, contexto y timing. Cuando una señal está fuerte pero el precio está extendido, **degrada a WAIT y emite un plan operativo concreto** (zona de espera, precio trigger, invalidación, instrucciones) para evitar entradas tardías — ese fue el dolor original del usuario: entraba en la vela explosiva y perdía.

**Dos capas de análisis independientes que complementan al Pine**:
- **Scanner en vivo** (pestaña "Análisis de zonas"): sesgo macro y tendencia por confluencia técnica multi-factor (EMA9/21/50/200, RSI, rango, impulso) sobre ~11 pares. Clasifica en 3 bloques (trend / sin edge / reversión).
- **Radar de setups** (pestaña "Radar"): segunda capa que busca puntos concretos de entrada en zonas clave (pin bar / envolvente sobre soporte/resistencia + divergencia RSI). Clasifica en 4 bloques (B1 compra válida, B2 trampa long, B3 venta válida, B4 trampa short). Cross-check con el sesgo del scanner — si hay conflicto el setup se marca con **NO CUMPLE MTF LOCK** (no se reclasifica a trampa, se preserva el bloque original pero con badge explícito y card dimeada). Encima de la grilla hay un **semáforo consolidado** (OPERAR / ESPERAR / EVITAR) que evalúa 5 filtros A+ por setup: kill zone, MTF LOCK, fuerza STRONG, RRR≥2:1, SL dentro del cap.

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
                                                      ├─→ ai_client (OpenRouter, opcional)
                                                      │
                                                      ├─→ scanner ──┐
                                                      │             ├─→ Twelve Data (OHLC 15m)
                                                      └─→ radar  ───┘   via _ohlc_cache compartido

Frontend Next.js (local) ←─polling── Render
        ├── dashboard: polling 5s (/signals, /stats, /news/warnings)
        ├── scanner:  polling 5min (/scanner/pairs) — pausa si market_closed
        └── radar:    polling 5min (/api/radar)     — pausa si market_closed
```

**Cache de OHLC crudo compartido**: scanner y radar llaman a `scanner._fetch_chart()` — misma entrada en `_ohlc_cache` (key `f"{pair}:15min:200"`). TTL 15 min. Evita pagar 2 veces por los mismos datos.

## Estructura

```
tradingApp/
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI: rutas (forex + stocks) + CORS abierto
│   │   ├── schemas.py          # TVSignal, AnalyzeResponse, EntryPlan (Pydantic)
│   │   ├── decision_engine.py  # Vetos duros + scoring → decisión
│   │   ├── entry_planner.py    # Genera plan operativo (PULLBACK/RETEST/MOMENTUM/SWEEP)
│   │   ├── tv_parser.py        # Acepta JSON o texto legacy multilínea
│   │   ├── ai_client.py        # OpenRouter via urllib (sin deps extra)
│   │   ├── news_client.py      # ForexFactory fetch + cache + warnings por ventana
│   │   ├── scanner.py          # Scanner en vivo (Twelve Data OHLC 15m, 3 bloques) + cache OHLC
│   │   ├── radar.py            # Radar de setups (pin bar/envolv + divergencia + SL cap) + cross-check con scanner
│   │   ├── stocks_client.py    # Twelve Data stocks (search/quote/time_series) + indicadores Python (SMA/EMA/RSI/MACD/BBANDS/ADX)
│   │   └── storage.py          # Dual-mode PG/SQLite. Tablas: signals + investor_profile + stocks_watchlist
│   ├── tests/
│   │   └── test_radar.py       # 49 tests unitarios del radar (pivots, rechazo, SL, RRR, alignment/MTF LOCK, market_closed)
│   ├── requirements.txt
│   ├── render.yaml             # Config deploy Render
│   ├── supabase_init.sql       # SQL inicial para tabla signals en Supabase
│   ├── .env.example
│   └── signals.db              # solo en dev local
├── frontend/
│   ├── app/
│   │   ├── page.tsx            # Home: shell (AppShell) + view router + load() unificado
│   │   ├── radarChart.ts       # drawRadarChart(canvas, setup) — minigráfico Canvas 2D (7 capas)
│   │   ├── layout.tsx          # next/font: Space Grotesk + Space Mono → CSS vars
│   │   └── globals.css         # Tokens (colores, type scale +30%), legacy CSS, dashboard table
│   ├── components/
│   │   ├── shell/              # AppShell, Topbar, Sidebar (forex|stocks), RightBar (forex|stocks)
│   │   ├── dashboard/          # SessionsTimeline, KillZonesTrack, KpiHero, EquityCurve
│   │   ├── icons/              # SVG inline (refresh, settings, sun, moon)
│   │   └── stocks/
│   │       ├── StocksView.tsx              # Container: wizard | dashboard según perfil
│   │       ├── StocksSidebarSection.tsx    # Search + watchlist en sidebar
│   │       ├── StocksActiveSignalsPanel.tsx # Top 5 BUY/SELL en rightbar
│   │       ├── MarketHoursCard.tsx         # NYSE pre/regular/post + countdown ET
│   │       ├── ProfileBadge.tsx            # Pill clickeable con resumen del perfil
│   │       ├── onboarding/
│   │       │   ├── ProfileWizard.tsx       # 5 steps + progress bar + disclaimer
│   │       │   └── steps/                  # Horizon, Risk, Capital, Experience, Sectors
│   │       └── dashboard/
│   │           ├── StocksDashboard.tsx     # Orquesta search + signal + breakdown
│   │           ├── TickerSearch.tsx        # Debounce 300ms + autocomplete + keyboard nav
│   │           ├── SignalCard.tsx          # Decisión 57px + barra confianza + reasons
│   │           └── IndicatorBreakdown.tsx  # Tabla votos/pesos por indicador
│   ├── hooks/
│   │   ├── useTick.ts                      # Re-render por intervalo (timeline, MarketHours)
│   │   ├── useFavoritePairs.ts             # Favoritos forex (sidebar)
│   │   └── stocks/
│   │       ├── useInvestorProfile.ts       # Hidrata cache → backend; saveProfile/clearProfile
│   │       ├── useStockSignal.ts           # Race-safe fetch + refetch ignorando cache
│   │       └── useStocksWatchlist.ts       # Items + add/remove/update + sync entre instancias
│   ├── lib/
│   │   ├── api.ts              # API base URL
│   │   ├── types.ts            # Signal, Stats, RadarSetup, View ('dashboard'|'zones'|'radar'|'stocks')
│   │   ├── sessions.ts         # SESSIONS UTC + Madrid offset DST-safe + overlap window
│   │   ├── killZones.ts        # KILL_ZONES Madrid + getKillZonesMadrid passthrough
│   │   ├── format.ts, dates.ts, zones.ts, symbols.ts, blockLegend.ts, config.ts
│   │   ├── radar/              # labels, blocks, aplus
│   │   └── stocks/
│   │       ├── types.ts                    # InvestorProfile, Vote, Signal, IndicatorBundle, etc.
│   │       ├── signalEngine.ts             # Funciones puras de voto + WEIGHTS por horizonte + calculateSignal
│   │       ├── signalEngine.test.ts        # 5 tests runnable (BUY/SELL/HOLD/missing/voteFns)
│   │       ├── twelvedata.ts               # Frontend client → /stocks/* (cache 5min/1h, retry 1/2/4s)
│   │       ├── profileStorage.ts           # Backend Supabase + cache localStorage + custom event
│   │       ├── watchlistStorage.ts         # idem
│   │       └── marketHours.ts              # NYSE DST-safe (pre/regular/post/closed)
│   ├── .env.local              # NEXT_PUBLIC_API_URL → Render
│   └── .env.local.example
├── scriptsTradingView/
│   ├── SMS_XAUUSD_v8_9_1.pine
│   └── SMS_EURUSD_v8_10_1.pine
├── dashboard_mockup.html       # Mockup HTML del rediseño AppShell (referencia visual)
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
| GET | `/scanner/pairs?pairs=XAUUSD,EURUSD` | Scanner en vivo (consume Twelve Data). Devuelve `market_closed` para pausar polling |
| GET | `/scanner/debug` | Diagnóstico de API key + `last_error` del scanner |
| GET | `/api/radar?pairs=XAUUSD,EURUSD` | Radar de setups con active/expired separados, candles, alignment, market_closed |
| GET | `/stocks/search?q=` | TD symbol_search (gratis). Devuelve `{matches: [...]}`. Cache 24h |
| GET | `/stocks/quote?symbol=MSFT` | Quote en tiempo real (1 crédito TD). Cache 5min |
| GET | `/stocks/indicators?symbol=&interval=` | IndicatorBundle listo para signalEngine (2 créditos TD). Intervalos: 15min/1h/4h/1day |
| GET / POST / DELETE | `/stocks/profile` | Singleton id=1. POST validado contra whitelists |
| GET | `/stocks/watchlist` | `{items: [...]}` ordenado por addedAt |
| POST | `/stocks/watchlist` | Body `{symbol}`. Idempotente |
| DELETE | `/stocks/watchlist/{symbol}` | |
| PATCH | `/stocks/watchlist/{symbol}` | Body `{lastDecision?, lastConfidence?}` para cachear última eval |

`?ai=1` activa el refinamiento OpenRouter (si está configurado). El motor heurístico siempre corre primero; si la IA falla, cae a heurística.

**Endpoints que consumen créditos Twelve Data**: `/scanner/pairs`, `/api/radar`, `/stocks/quote`, `/stocks/indicators`. El resto son gratis (incluyendo `/stocks/search`, que TD ofrece sin contar contra cuota).

## Tablas DB (idénticas en SQLite y PostgreSQL)

### Tabla `signals`

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

### Tablas del módulo Stocks

```
investor_profile (
    id INTEGER PRIMARY KEY,           -- siempre 1 (singleton single-user)
    horizon TEXT NOT NULL,            -- day_trader|swing|long_term
    risk_tolerance INTEGER NOT NULL,  -- 1-5
    capital_range TEXT NOT NULL,      -- <1k|1k-10k|10k-50k|50k+
    experience TEXT NOT NULL,         -- novice|intermediate|advanced
    sectors_json TEXT NOT NULL,       -- JSON array de sectores GICS
    updated_at TEXT NOT NULL
)

stocks_watchlist (
    symbol TEXT PRIMARY KEY,          -- UPPERCASE
    last_decision TEXT,               -- BUY|SELL|HOLD|NULL
    last_confidence REAL/DOUBLE,      -- 0-1
    added_at TEXT NOT NULL
)
```

Auto-creadas vía `CREATE TABLE IF NOT EXISTS` en `init_db()`. Para añadir columnas, agregar a ambos branches (PG y SQLite) igual que con `signals`.

Funciones CRUD en `storage.py`: `get_investor_profile`, `save_investor_profile` (upsert con `ON CONFLICT DO UPDATE` / `INSERT OR REPLACE`), `clear_investor_profile`, `get_stocks_watchlist`, `add_to_stocks_watchlist` (idempotente), `remove_from_stocks_watchlist`, `update_stocks_watchlist_item`.

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

# Scanner en vivo (solapa "Análisis de zonas") — Twelve Data free tier
TWELVEDATA_API_KEY=
```

## Scanner en vivo (solapa "Análisis de zonas")

Análisis **independiente** (no depende de las señales del Pine). Hace su propia lectura técnica multi-factor sobre OHLC 15m y devuelve los pares rankeados por confluencia.

- **Fuente**: Twelve Data (`api.twelvedata.com/time_series`, free tier 800 créditos/día, 8 req/min). **Yahoo Finance no funciona desde Render** — bloquea IPs datacenter, por eso migramos a Twelve Data que requiere API key pero es estable desde cloud.
- **Símbolos**: conversión automática `XAUUSD → XAU/USD`, `EURUSD → EUR/USD`, etc. `_parse_ohlc` extrae `open`/`high`/`low`/`close`/`ts` (el `open` lo usa el radar para pin bars).
- **Cache**: 15 min (`CACHE_TTL_SECONDS = 900` en `scanner.py`). Dos caches internos — `_cache` guarda las cards scored, `_ohlc_cache` el OHLC crudo **compartido con el radar**. Frontend puede poleear a 5 min sin gastar créditos (cache hit).
- **Indicadores**: EMA9/21/50/200, RSI14, ATR14, posición en rango 50v, impulso 5v.
- **Scoring**: 7 factores direccionales cada uno vale +1/-1/0. `bias = Σfactores`, `side = LONG` si `bias≥3`, `SHORT` si `bias≤-3`, `NEUTRAL` en medio. `confluence = |bias|` (0-7).
- **Endpoint**: `GET /scanner/pairs?pairs=XAUUSD,EURUSD,...` (pairs opcional, default 11 pares). Devuelve `{items, count, brief, last_error, market_closed, data_age_minutes}`. `market_closed=true` si la vela más reciente en cache tiene >30 min desde cierre (fin de semana, feed caído) → frontend pausa polling.
- **Diagnóstico**: cuando el scanner devuelve 0 items, el frontend muestra el `last_error` en rojo. `GET /scanner/debug` confirma que la API key llega al servidor.

## Radar de setups (solapa "Radar")

Segunda capa de análisis que convive con el scanner. Busca **puntos concretos de entrada en zonas clave (M15)** usando price action puro: pin bar / envolvente sobre soporte o resistencia + divergencia RSI opcional.

### Pipeline por par (`radar._analyze_symbol`)

1. `scanner._fetch_chart` → reutiliza `_ohlc_cache` (compartido).
2. `_find_key_levels` → pivots fractales (2 velas a cada lado) + clustering 0.2% → soporte/resistencia más cercanos.
3. **Filtro de rango comprimido**: si `(R - S) / price < MIN_RANGE_PCT` (0.15% XAU / 0.10% EUR / 0.12% default) → `return None`. El par está en consolidación, no operable. Log DEBUG `COMPRESSED_RANGE`.
4. `_detect_recent_rejection` → escanea las últimas 3 velas buscando pin bar / envolvente. Devuelve `candle_age` (1/2/3) y `candle_ts`. Si `age=3` → `expired=True`.
5. `_detect_rsi_divergence` → divergencia alcista (precio nuevo mínimo + RSI sube + RSI<50) o bajista (simétrico).
6. `_classify_reversal_setup` → 5 bloques (ver tabla abajo).
7. `_estimate_sl` → SL = soporte/resistencia ± 0.5·ATR. Distancia en pips con cap por instrumento. **También calcula RRR** contra el nivel opuesto como TP natural: LONG → `tp=resistance`, SHORT → `tp=support`. Devuelve `rrr`, `rrr_below_min` (true si `rrr < MIN_RRR=2.0`), `reward_pips`, `tp_price`, `rrr_min`.
8. **Stale data check**: si la última vela se cerró hace >30 min, fuerza `rejection.expired=True` (evita mostrar setups "frescos" con datos del viernes el lunes por la mañana).
9. Adjunta `candles` = últimas 20 OHLC en formato ISO 8601 (para el minigráfico del frontend).

### Bloques del radar

| Bloque | Condición | Side | Strength |
|---|---|---|---|
| **B1 STRONG** | soporte + rechazo LONG + range_pos<0.35 + divergencia alcista | LONG | STRONG |
| **B1 NORMAL** | soporte + rechazo LONG + range_pos<0.35 | LONG | NORMAL |
| **B3 STRONG** | resistencia + rechazo SHORT + range_pos>0.65 + divergencia bajista | SHORT | STRONG |
| **B3 NORMAL** | resistencia + rechazo SHORT + range_pos>0.65 | SHORT | NORMAL |
| **B2 TRAP** | soporte + rechazo SHORT (soporte va a ceder) | TRAP_LONG | WARN |
| **B4 TRAP** | resistencia + rechazo LONG (resistencia va a ceder) | TRAP_SHORT | WARN |
| B0 | nada cumple | — | — (no se devuelve) |

`quality` = cuenta de señales positivas (near_level + rejection + divergence) — máx 3.

### Cross-check con scanner (MTF LOCK explícito — sin reclasificar)

En `get_radar_response`, tras armar los setups, se llama `scanner.scan_pairs()` (cache compartido → sin fetch extra) y se cruza el bias macro. **Importante**: desde la revisión de mejoras UX, el cross-check **NO reclasifica** bloques a trampa — preserva `bloque`, `side`, `strength` y `sl` originales, y solo expone flags explícitos en `alignment`:

- `mtf_lock_passed: boolean | null` — true si alineado con sesgo macro, false si conflicto, null si neutral/unknown.
- `mtf_lock_failed: boolean` — true solo cuando hay conflicto claro (escáner con bias LONG/SHORT opuesto al setup).
- `reclassified: false` siempre — se mantiene el campo por compat, pero ya no se reclasifica.

Casos:
- Radar B1 LONG + scanner bias LONG → `status="aligned"`, `mtf_lock_passed=true`.
- **Radar B1 LONG + scanner bias SHORT → `status="conflict"`, `mtf_lock_failed=true`** — el frontend muestra badge rojo "⛔ NO CUMPLE MTF LOCK" y dimea la card, pero el SL y los valores siguen visibles para referencia.
- Scanner NEUTRAL → `status="neutral"`, `mtf_lock_passed=null` (no bloquea, no respalda).
- Sin data del scanner → `status="unknown"`, `mtf_lock_passed=null`.

**Por qué este cambio**: reclasificar ocultaba información operativa. Con el semáforo consolidado + badge explícito, el usuario ve la señal completa y el sistema le dice claramente cuándo no operarla.

### SL caps (pips absolutos por instrumento)

```python
SL_MAX_PIPS = {
    "XAUUSD": 40,   # 40 pips × $0.25 (0.25 lotes) = $10
    "EURUSD": 25,   # 25 pips × $1.00 (1 lote)    = $25
    "default": 20,
}
```

Si `distance_pips > cap` → `too_wide=true`, la card se pinta dimmed con badge "SL EXCEDE" y NO cuenta en `total_setups`.

### RRR y `rrr_below_min` (filtro visual de calidad)

`_estimate_sl` calcula RRR contra el nivel opuesto (reverse-to-level target):

- **LONG**: `risk = price - sl_price`, `reward = resistance - price`, `rrr = reward / risk`.
- **SHORT**: `risk = sl_price - price`, `reward = price - support`, `rrr = reward / risk`.
- `MIN_RRR = 2.0` (constante en `radar.py`). Debajo de ese umbral, `rrr_below_min=true`.
- Si no hay nivel opuesto calculable (`resistance=None` en LONG, etc), `rrr=None` y `rrr_below_min=false` (no castigamos lo indeterminable).

**Frontend**: cards con `rrr_below_min=true` se dimean (opacity 0.55), los valores de precio/SL se tachan, badge naranja `RRR < 2`. Fila TP/RRR se muestra bajo el SL con el valor numérico del ratio.

### Semáforo consolidado (OPERAR / ESPERAR / EVITAR)

Componente `RadarSemaforo` al tope de la vista radar. Evalúa cada setup contra **5 filtros A+** y decide globalmente:

| Filtro | Cumple si... |
|---|---|
| Kill zone activa | sesión actual (hora Madrid) es `fire` u `ok` |
| MTF LOCK | `alignment.mtf_lock_passed === true` |
| Fuerza STRONG | `strength === "STRONG"` (setup con divergencia) |
| RRR ≥ 2:1 | `sl.rrr >= sl.rrr_min` |
| SL dentro del cap | `sl.too_wide === false` |

Decisión global (por el **mejor** setup del batch):
- **5/5 → OPERAR** (verde, pulsing)
- **3-4/5 → ESPERAR** (amarillo)
- **<3/5 → EVITAR** (rojo)
- **market_closed → EVITAR** (override, sin evaluar)

Los 5 chips ✓/· se pintan bajo la decisión para que el usuario vea exactamente qué filtro falló. La idea: **el sistema decide, el usuario ejecuta** — no más "evaluar mentalmente" si entrar.

### Detección de mercado cerrado

`_minutes_since_candle_close(ts)` calcula el gap entre la última vela cacheada y ahora. Si > 30 min → `market_closed=true`. Se expone a nivel de respuesta junto con `data_age_minutes` y `last_candle_ts`. Frontend:
- Banner superior 🌙 "Mercado cerrado · última vela hace Xd Yh".
- Empty state específico distingue "mercado cerrado" de "sin setups".
- **Pausa `setInterval` de polling** — cero tráfico a Twelve Data en fin de semana. Se reactiva al refrescar manualmente cuando el mercado reabre.

### Payload del endpoint `/api/radar`

```json
{
  "timestamp": "...",
  "active_setups": [ ... age ≤ 2, con campo `candles` ... ],
  "expired_setups": [ ... age = 3 ó stale, sin `candles` ... ],
  "total_setups": N,         // solo activos y sin too_wide
  "strong_setups": N,        // solo activos STRONG
  "total_expired": N,
  "market_closed": bool,
  "data_age_minutes": N,
  "last_candle_ts": "ISO"
}
```

Dentro de cada setup, los campos clave añadidos por las mejoras UX:

```json
{
  "sl": {
    "price": 1.0985,
    "distance_pips": 14.5,
    "cap_pips": 25,
    "too_wide": false,
    "tp_price": 1.1030,         // nivel opuesto (= resistance para LONG, support para SHORT)
    "reward_pips": 30.0,
    "rrr": 2.07,                // reward / risk
    "rrr_below_min": false,
    "rrr_min": 2.0
  },
  "alignment": {
    "status": "aligned|conflict|neutral|unknown",
    "scanner_bias": "LONG|SHORT|NEUTRAL|null",
    "scanner_confluence": 5,
    "mtf_lock_passed": true,    // true=aligned, false=conflict, null=neutral/unknown
    "mtf_lock_failed": false,   // explícito para el badge del frontend
    "reclassified": false       // siempre false (compat; ya no se reclasifica)
  }
}
```

### Minigráfico frontend (`radarChart.ts`)

Canvas 2D puro, **sin librerías**. Función pura `drawRadarChart(canvas, setup)`. 7 capas en orden: fondo, soporte (verde), resistencia (roja), SL (naranja punteado), 20 velas japonesas, triángulo marcador en la vela de rechazo, zona TP sombreada (solo B1/B3). Responsive vía `ResizeObserver` sobre el parent. Labels mínimos (10px mono): precio S/R solo si `near_*`, texto "SL" solo si no too_wide.

### Watchlist operativa

`WATCHLIST = ["XAUUSD", "EURUSD"]` en frontend. **No hay filtro** — el toggle "Solo mis pares" se eliminó por completo. La constante solo pinta el badge `● Operativo` en las cards de tus pares para identificarlas visualmente. El radar por backend escanea los 11 pares por defecto para tener contexto de MTF LOCK aunque no operes esos pares.

## Frontend rediseñado — AppShell de 3 columnas

El `page.tsx` legacy (un solo componente con todo inline) se descompuso en un shell + componentes. El layout se inspira en un mockup en `dashboard_mockup.html` (terminal-style 3-col).

### Shell (`components/shell/`)

```
┌─────────────────────────────────────────────────────────────┐
│ Topbar  AI Trading Assistant  [Dashboard|Zonas|Radar|Stocks] [Refresh|Theme|Settings]
├──────────┬─────────────────────────────────────┬────────────┤
│ Sidebar  │ Main                                │ RightBar   │
│ 232px    │ flexible                            │ 320px      │
└──────────┴─────────────────────────────────────┴────────────┘
```

- **`AppShell`**: grid CSS `grid-template-areas`. Activa `body[data-shell="active"]` con `overflow:hidden; height:100vh` para que cada columna haga scroll independiente. Responsive: <1024 oculta rightbar, <768 oculta sidebar.
- **`Topbar`**: brand + tabs + spacer + session pill + iconos (refresh, theme, settings). Shortcuts D/Z/R/S para cambiar tab (ignora si foco en input). Session pill muestra sesión activa (LDN/NYC/ASIA) o próxima con countdown — usa `useTick(60_000)`.
- **`Sidebar` (context-aware)**: prop `context: 'forex' | 'stocks'`.
  - **forex**: search de pares + lista (con favoritos persistidos en localStorage vía `useFavoritePairs`) + calendario económico mini-list.
  - **stocks**: `StocksSidebarSection` (search ticker → fetch backend + watchlist con pills BUY/SELL/HOLD).
- **`RightBar` (context-aware)**: prop `context: 'forex' | 'stocks'`.
  - **forex**: Next A+ Setup (countdown a overlap LDN-NY) + Active Signals (open positions filtradas) + Próxima ventana (overlap info en hora Madrid) + disclaimer.
  - **stocks**: `MarketHoursCard` (NYSE pre/regular/post/closed + countdown ET) + `StocksActiveSignalsPanel` (top 5 BUY/SELL de la watchlist con conf ≥ 40%) + disclaimer.

### Dashboard view (`components/dashboard/`)

- **`SessionsTimeline`**: timeline 24h en hora Madrid. Convierte SESSIONS UTC → Madrid via `madridOffsetHours()` + `utcToMadrid()` (DST-safe vía `Intl.DateTimeFormat`). Renderiza bandas de sesión + overlap A+ + now-marker + axis. Helper `projectToMadrid(openUTC, closeUTC, offset)` para sesiones que cruzan medianoche en Madrid (por si pasa con DST extremo).
- **`KillZonesTrack`**: barra fina 14px alineada con el timeline. Consume `getKillZonesMadrid()` (passthrough de KILL_ZONES, ya están en hora Madrid).
- **`KpiHero`**: 4 cards KPI con valores grandes en mono (PnL, Win Rate con barra, Execution Rate con barra info, Open Positions). Reemplazó el `.stats` legacy.
- **`EquityCurve`**: SVG puro (sin librerías). Construye serie desde `/signals?limit=500` filtrando `result+pnl`, suma cumulativo, dibuja path + área con gradient. Toggle 1D/7D/30D/ALL. Empty state con línea punteada horizontal y texto centrado (no caja gigante vacía).

### Bugs/limpieza aplicados (no repetir)

- **Madrid timezone consistency**: SessionsTimeline antes mostraba "Hora UTC", RightBar decía "12:00–16:00 UTC", calendario decía Madrid. Unificado todo a hora Madrid (las helpers `madridHourOf`/`madridOffsetHours`/`utcToMadrid` viven en `lib/sessions.ts`).
- **Topbar pill "abre en"**: bug numérico — `next.minutesUntil` venía como float (e.g. `48.95`). Fix: `Math.floor(next.minutesUntil)` antes de calcular hh/mm.
- **openSignals dedicado**: el RightBar de forex antes filtraba `items.filter(result==null)` que estaba paginado a 10 → contador inconsistente con `stats.open`. Fix: `Home.load()` hace fetch separado a `/signals?limit=50` y guarda en `openSignals` state. RightBar recibe `openCount={stats?.open}` (verdad) + lista `openSignals` (UI).
- **EmptyState webhook URL exposed**: la tabla legacy decía "Configura el webhook a https://tradingapp-2glz.onrender.com/webhook/tradingview" → expuesta. Mensaje neutro: "Sin operaciones todavía. Las señales aparecerán acá cuando se ejecuten".
- **Stats-split y Calendario duplicados removidos** del main: el calendario vive en sidebar, las split-cards "Ejecutadas/Calificadas" se duplicaban con KpiHero.
- **`activeStockSymbol` lifted a `Home`**: la sidebar (stocks context) y el StocksDashboard comparten state con persistencia en localStorage (`tradingapp:stocks_last_ticker`).

## Identidad visual — Bloomberg Terminal moderno

Decisión deliberada de no usar el preset "AI-built dashboard" (Inter + slate + indigo). Direcciónal "Bloomberg moderno":

### Tipografía (`next/font/google` en `layout.tsx`)

- **Sans UI**: `Space Grotesk` (weights 400/500/600/700) → CSS var `--font-sans` → consumido por `--font-ui`.
- **Mono / números**: `Space Mono` (weights 400/700) → CSS var `--font-mono-prim` → consumido por `--font-mono`. Tabular-nums en `.num` y `.mono`.

### Type scale (+30% sobre la primera iteración del rediseño)

Body 18px (era 13 originalmente), labels 16, KPIs 42, hero 57. Tokens en `globals.css`:

```css
--fs-label: 16px;   --fs-body: 18px;   --fs-sub: 21px;
--fs-section: 26px; --fs-kpi: 42px;    --fs-hero: 57px;
```

Componentes con hero numbers hardcoded también bumpeados (decisión SignalCard 57.2px, KPI value 39px, symbol 33.8px, decimales por el `*1.3` directo — los browsers renderizan sub-pixel sin problema).

### Paleta (acento ámbar = terminal financiero clásico)

Cambios sobre el indigo default:

| Token | Antes | Ahora |
|---|---|---|
| `--accent` | `#6366F1` indigo | **`#F59E0B` ámbar** |
| `--warn`   | `#F59E0B` ámbar  | `#FB923C` naranja (movido para no chocar con accent) |
| `--info`   | `#3B82F6` azul   | `#38BDF8` cyan |
| `--bg`     | `#0A0E14` slate frío | `#0B0D12` slate ligeramente cálido |

Light theme: ámbar oscuro `#B45309` (amber-700) para contraste sobre fondo claro.

Brand mark gradient: `var(--accent) → #EF4444` (ámbar → rojo, "sunset trader") en lugar del clásico indigo→violet.

### Por qué importa

El stack visual previo (Inter + JetBrains Mono + slate + indigo) es indistinguible de Linear, Cursor, Vercel y cualquier dashboard SaaS post-2018. Space Grotesk + Space Mono + acento ámbar da una identidad reconocible y, además, el ámbar evoca el terminal Bloomberg que es referencia cultural en trading.

## Módulo Stocks (pestaña "Stocks")

Cuarta pestaña independiente para análisis de **acciones US (NYSE/NASDAQ)** con perfil de inversor personalizado. Single-user MVP, persistencia en Supabase + cache localStorage.

### Flujo del usuario

```
Click tab Stocks
       ↓
¿Tiene perfil? ── NO ──→ ProfileWizard (5 steps) ─→ guarda perfil ─→ Dashboard
       │
       SÍ
       ↓
StocksDashboard
   ├── ProfileBadge (clickeable → reabre wizard precargado)
   ├── TickerSearch (debounce 300ms → /stocks/search)
   ├── SignalCard (decisión BUY/SELL/HOLD + confianza + 3 razones)
   └── IndicatorBreakdown (expandible: tabla votos/pesos)
```

### Backend (`stocks_client.py` + endpoints en `main.py`)

Cliente Twelve Data que **comparte API key con el scanner forex** (mismo `TWELVEDATA_API_KEY`, mismo presupuesto free tier 800 créditos/día).

**Indicadores en Python puro** (no en endpoints individuales de TD): `_sma`, `_ema_series`, `_rsi_last`, `_macd_hist`, `_bbands`, `_adx`. Calcular acá ahorra créditos: 1 fetch a `/time_series` (1 crédito) + 1 a `/quote` (1 crédito) = 2 créditos por bundle, vs ~7 si pidiéramos cada indicador a TD.

Cache propio (separado del de scanner): `_cache: dict[str, tuple[float, dict]]` con TTL por intervalo (5min intraday / 1h diario) + 24h para `symbol_search`. `clear_cache(prefix)` para invalidar.

`StocksUpstreamError` tipada (status 404/429/400/500-599) → `_raise_upstream()` la mapea a `HTTPException` adecuada en los endpoints.

Endpoints expuestos:

| Método | Ruta | Créditos TD | Notas |
|---|---|---|---|
| `GET`    | `/stocks/search?q=` | 0 | TD `symbol_search` es gratis. Cache 24h. |
| `GET`    | `/stocks/quote?symbol=` | 1 | Cache 5min. |
| `GET`    | `/stocks/indicators?symbol=&interval=` | 2 | Devuelve `IndicatorBundle` listo para signalEngine. Intervalos: 15min/1h/4h/1day. |
| `GET`    | `/stocks/profile` | 0 | Singleton (id=1). `null` si no existe. |
| `POST`   | `/stocks/profile` | 0 | Body validado (whitelists + 1≤risk≤5). |
| `DELETE` | `/stocks/profile` | 0 | |
| `GET`    | `/stocks/watchlist` | 0 | `{items: [...]}` ordenado por addedAt. |
| `POST`   | `/stocks/watchlist` | 0 | Body `{symbol}`. Idempotente (ON CONFLICT DO NOTHING). |
| `DELETE` | `/stocks/watchlist/{symbol}` | 0 | |
| `PATCH`  | `/stocks/watchlist/{symbol}` | 0 | Body `{lastDecision?, lastConfidence?}` para cachear última eval. |

### Frontend signal engine (`lib/stocks/signalEngine.ts`)

Funciones puras testeables. 6 votos por bundle:

```
voteMaShort(price, ma20)    -1/0/+1   margen 0.5%
voteMaLong(price, ma200)    -1/0/+1   margen 1%
voteRsi(rsi14)              -1/0/+1   <30 +1, >70 -1
voteMacd(hist[])            -1/0/+1   cruce o magnitud >0.1
voteBbands(price, up, lo)   -1/0/+1   touch 5% del rango
voteAdx(adx, +DI, -DI)      -1/0/+1   ADX≥25 + diff DI≥2
```

Pesos por horizonte (suman 1.0):

```python
day_trader: { ma_short: .10, ma_long: .05, rsi: .30, macd: .30, bbands: .15, adx: .10 }
swing:      { ma_short: .20, ma_long: .15, rsi: .20, macd: .20, bbands: .15, adx: .10 }
long_term:  { ma_short: .05, ma_long: .35, rsi: .10, macd: .15, bbands: .10, adx: .25 }
```

`score = Σ(vote × weight)`. `score > 0.4 → BUY`, `< -0.4 → SELL`, else `HOLD`. Confianza = `min(|score|, 1)` para BUY/SELL, `1 - |score|` para HOLD. `topReasons` = top 3 votos por `|vote × weight|` con string humano + peso.

Intervalo recomendado por horizonte: day=15min, swing=4h, long_term=1day.

### Storage hooks (Fase 9: backend Supabase + cache localStorage)

`profileStorage.ts` y `watchlistStorage.ts` son las dos únicas superficies que hablan con `${API}/stocks/profile` y `${API}/stocks/watchlist`. Patrón:

- **Cache-first**: `getCachedX()` lee localStorage instantáneamente (primer paint).
- **Background fetch**: `fetchXFromBackend()` async, sincroniza cache si responde, **fallback a cache si backend falla** (offline-tolerant).
- **Mutaciones optimistas**: `saveX()/addX()/removeX()` escriben cache primero (UI snappy) + async backend; el response autoritativo del server reemplaza la optimistic. Si backend falla, log a console y mantenemos optimistic.

Sync entre instancias del hook (sidebar y dashboard usan dos instancias separadas):
- Cross-tab: `StorageEvent` estándar.
- **Same-tab**: `window.dispatchEvent(new Event(PROFILE_CHANGE_EVENT))` y `WATCHLIST_CHANGE_EVENT`. `StorageEvent` solo dispara en otros tabs — sin custom event, agregar un ticker desde sidebar no se reflejaba en el dashboard.

`activeStockSymbol` (qué ticker está viendo el usuario) NO va al backend — vive en `Home` con persistencia en localStorage (`tradingapp:stocks_last_ticker`). Es UI state, no datos del usuario.

### Tablas DB añadidas (auto-migran en `init_db()`)

```sql
investor_profile (
    id INTEGER PRIMARY KEY,           -- siempre 1 (singleton single-user)
    horizon TEXT NOT NULL,            -- day_trader|swing|long_term
    risk_tolerance INTEGER NOT NULL,  -- 1-5
    capital_range TEXT NOT NULL,      -- <1k|1k-10k|10k-50k|50k+
    experience TEXT NOT NULL,         -- novice|intermediate|advanced
    sectors_json TEXT NOT NULL,       -- JSON array de GICS sectors
    updated_at TEXT NOT NULL
)

stocks_watchlist (
    symbol TEXT PRIMARY KEY,          -- UPPERCASE
    last_decision TEXT,               -- BUY|SELL|HOLD|NULL (cache de última eval)
    last_confidence DOUBLE PRECISION, -- 0-1
    added_at TEXT NOT NULL
)
```

Upsert de profile via `INSERT ... ON CONFLICT (id) DO UPDATE` (PG) / `INSERT OR REPLACE` (SQLite). Add a watchlist idempotente via `ON CONFLICT (symbol) DO NOTHING` / `INSERT OR IGNORE`.

### Detalles operativos del módulo Stocks

- **Cuota TD compartida**: con TTL 5min/1h y `symbol_search` siendo gratis, una sesión típica de ~10 tickers consultados consume ~70 créditos/día. Margen sobrado dentro del cap 800.
- **`marketStatus` con override stale**: si la última vela del bundle tiene >24h, frontend fuerza `marketStatus="closed"` (función `isStaleData()` en `twelvedata.ts`). Mismo patrón que el `market_closed` del radar.
- **NYSE holidays NO modelados** en `marketHours.ts`. Si TD devuelve `marketStatus="closed"` en un holiday, el SignalCard lo refleja correctamente, pero el reloj/countdown de la `MarketHoursCard` no detecta holidays — tratará Christmas como día hábil. Acceptable para MVP.
- **`MarketPulse` (DXY/VIX/SPX/US10Y) NO se construyó** — el rightbar de stocks tiene MarketHours + ActiveSignalsPanel + disclaimer. Si querés agregarlo, son ~3 endpoints TD compartidos.
- **Errores tipados**: `StocksApiError.code` es `NOT_FOUND | RATE_LIMIT | NETWORK | INVALID | UPSTREAM`. SignalCard traduce a mensajes humanos contextuales. Retry con backoff exponencial (1s/2s/4s) en 429 (rate limit).
- **Race condition en mutaciones rápidas**: si user agrega 2-3 tickers seguidos antes de que respondan los backends, puede haber un parpadeo (~50-100ms) — el backend response del primero "sobrescribe" momentáneamente, se autocorrige cuando llega el siguiente. Tolerable para MVP.
- **`clearWatchlist()` solo limpia cache local** — backend no tiene endpoint clear-all. Para purgar hay que borrar uno por uno desde la UI.

## Polling y consumo de créditos Twelve Data

- **Frontend**: scanner y radar poleen cada 5 min. TTL backend 15 min → 2 de cada 3 polls son cache hit (0 créditos).
- **`market_closed` pausa el `setInterval`** en ambas vistas. Fin de semana = 0 tráfico upstream (ahorro ~900 créditos/semana).
- **Webhook TradingView, `/health`, `/signals`, `/stats`, `/news/*` NO tocan Twelve Data**. Solo los endpoints de datos de mercado consumen: `/scanner/pairs` y `/api/radar`.
- **El backend NO tiene cron/scheduler propio** — es 100% reactivo. Si ves créditos subir sin nadie usando la app, sospechas:
  1. Pinger mal configurado (UptimeRobot apuntando a `/scanner/pairs` en vez de `/health`).
  2. Otra sesión del frontend abierta.
  3. Bot/crawler en la URL pública.

Verificar en Render Dashboard → Logs qué IPs pegan a `/scanner/pairs` y `/api/radar`.

## Convenciones del usuario

- **Idioma**: español. Toda salida visible (instrucciones del planner, razones, UI) en español.
- **Estilo de código**: directo, sin comentarios obvios, sin abstracciones especulativas. Ya hay una decisión validada de evitar over-engineering.
- **Stack del usuario**: Windows 11, PowerShell. **Cuidado con `curl`** en PowerShell — es alias de `Invoke-WebRequest`. Usar `curl.exe` o `Invoke-RestMethod` con `@{}` y `ConvertTo-Json`.
- **`localhost` vs `127.0.0.1`**: en su Windows, `localhost` resolvía a IPv6 y uvicorn solo escucha IPv4 por defecto → usar `127.0.0.1` o arrancar uvicorn con `--host 0.0.0.0`.
- **Horario del usuario**: opera en hora Madrid. Todas las horas visibles en UI (calendario económico, sesiones, kill zones, NYSE en stocks) se muestran en `Europe/Madrid` o ET según el contexto del mercado.
- **Dirección visual**: NO usar el preset "AI-built dashboard" (Inter + slate + indigo). Identidad propia: Space Grotesk + Space Mono + accent ámbar `#F59E0B` (terminal financiero clásico). Body 18px, hero numbers 40-57px. Cualquier nuevo componente debe respetar este lenguaje.
- **Single-user**: cero auth. `investor_profile` es singleton id=1. Si en el futuro se agrega multi-usuario, hay que migrar a `user_id` y filtrar en endpoints.

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
- **Scanner + Radar comparten cache de OHLC**: `scanner._ohlc_cache` (TTL 15 min) usado por ambos — una fetch por par por 15 min, independiente de cuántas vistas lo consulten.
- **Radar de setups (pestaña "Radar")**: ✓ detecta pin bars / envolventes en soporte/resistencia, filtra rango comprimido (MIN_RANGE_PCT), SL estimado con cap por instrumento en pips absolutos (XAU=40, EUR=25), separación active/expired en el payload, minigráfico Canvas 2D por card.
- **RRR calculado en backend**: ✓ `_estimate_sl` devuelve `tp_price`, `reward_pips`, `rrr`, `rrr_below_min`, `rrr_min=2.0`. TP natural = nivel opuesto. Frontend dimea + tacha cards con `rrr < 2`.
- **MTF LOCK explícito (sin reclasificación)**: ✓ `_cross_check_alignment` ya no muta `bloque/side/strength/sl` en conflicto. Solo marca `alignment.mtf_lock_passed/mtf_lock_failed`. Frontend muestra badge rojo "⛔ NO CUMPLE MTF LOCK" sobre la card. Decisión: mejor mostrar la señal completa + razón de rechazo que ocultarla reclasificándola a trampa.
- **Semáforo consolidado OPERAR/ESPERAR/EVITAR**: ✓ componente `RadarSemaforo` al tope del radar. Evalúa cada setup contra 5 filtros A+ (kill zone, MTF LOCK, STRONG, RRR≥2, SL cap) y pinta la decisión global del mejor setup. Chips ✓/· visibles para entender qué falla.
- **Filtro "Solo mis pares" eliminado**: ✓ toggle removido por completo (estado, helper, UI, texto del empty state). La constante `WATCHLIST` sobrevive solo para el badge `● Operativo` sutil en las cards.
- **Market closed pause**: ✓ backend detecta vela cacheada >30min (fin de semana o feed caído), frontend pausa `setInterval` → cero tráfico upstream en finde. Banner distintivo 🌙 en radar, indicador sutil en scanner.
- **49 tests unitarios del radar**: ✓ `backend/tests/test_radar.py` cubre pivots, rejection en 3 velas, divergencia, SL cap, RRR, alignment/MTF LOCK, compression, stale data, normalización ISO. Ejecutable con `.venv/Scripts/python tests/test_radar.py`.
- **Decisión operativa confirmada**: watchlist del radar = XAUUSD + EURUSD. Los demás pares se escanean por contexto para el cross-check de sesgo (MTF LOCK), no para operar.
- **Rediseño AppShell de 3 columnas**: ✓ migración completa de `page.tsx` legacy a `AppShell` + `Topbar` + `Sidebar` (forex|stocks) + `RightBar` (forex|stocks). Mockup HTML en `dashboard_mockup.html` como referencia. Componentes en `components/{shell,dashboard,stocks,icons}/`.
- **Sidebar y RightBar context-aware**: ✓ prop `context: 'forex' | 'stocks'` desde `Home` según `view`. Cada uno tiene rama interna distinta. La sidebar sustituye Pares por Tickers; el rightbar sustituye Next A+ Setup por MarketHoursCard NYSE.
- **`activeStockSymbol` lifted a Home**: ✓ persistencia en localStorage (`tradingapp:stocks_last_ticker`). Sidebar y Dashboard son consumidores controlados — única fuente de verdad.
- **KpiHero + EquityCurve**: ✓ reemplazaron las stats legacy. KpiHero con valores en mono grandes (PnL/WR/ExecRate/Open Positions). EquityCurve construye serie cumulativa desde `/signals?limit=500`, SVG puro con range toggle.
- **SessionsTimeline en hora Madrid**: ✓ helpers `madridOffsetHours/utcToMadrid` proyectan SESSIONS UTC + OVERLAPS + KILL_ZONES a coordenadas Madrid. DST-safe vía `Intl.DateTimeFormat`. Topbar pill, RightBar Próxima ventana y MarketHoursCard también muestran tiempos consistentes (Madrid o ET según contexto).
- **Identidad visual diferenciada (Bloomberg moderno)**: ✓ Space Grotesk + Space Mono via `next/font/google` reemplazan Inter + JetBrains Mono. Accent ámbar `#F59E0B` reemplaza indigo. Brand mark gradient ámbar→rojo. Type scale +30% global (body 18px, KPIs 42px, decisión SignalCard 57px). 260 declaraciones `font-size:` bumpeadas + tokens `--fs-*` actualizados. Justificación: el preset Inter + slate + indigo es indistinguible de cualquier dashboard SaaS post-2018.
- **Módulo Stocks completo (Fases 1-9)**: ✓ Cuarta pestaña con perfil de inversor (5-step wizard: horizonte/riesgo/capital/experiencia/sectores), TickerSearch contra TD `symbol_search`, SignalCard con decisión BUY/SELL/HOLD + confianza + 3 razones + breakdown expandible, watchlist en sidebar con pills BUY/SELL/HOLD cacheadas, NYSE MarketHoursCard en rightbar (DST-safe), `/stocks/*` endpoints en FastAPI con persistencia Supabase + cache localStorage, optimistic mutations + offline-tolerant fallback. Engine puro testeable (`signalEngine.test.ts` con 5 tests).
- **Stocks: backend + frontend integrados (Fase 9)**: ✓ `profileStorage.ts` y `watchlistStorage.ts` hablan con `${API}/stocks/*` con cache localStorage. Custom events (`PROFILE_CHANGE_EVENT`, `WATCHLIST_CHANGE_EVENT`) para sync entre instancias del mismo tab (sidebar y dashboard usan instancias separadas del hook). Cross-tab sync via `StorageEvent` estándar. Optimistic UX: cache primero, backend después; si backend falla mantenemos optimistic + log a console.

## Próximos pasos posibles (mencionados, no hechos)

### Forex
- Notificaciones a Telegram cuando llega ENTER.
- Calculadora de tamaño de posición integrada (capital + % riesgo → lotes).
- R:R floor como veto duro en el motor del Pine (rechazar si `(tp-entry)/(entry-sl) < 1.5`). Nota: el radar ya filtra visualmente con `rrr_below_min`; lo pendiente es integrarlo como veto en `decision_engine.py` para las señales del Pine.
- Kill zone como veto duro en el backend (fuera de London/NY → WAIT automático). Nota: el panel visual ya existe, falta integrar como veto en `decision_engine.py`.
- Daily loss limit + cooldown post-trade (circuit breaker anti-revenge-trading).
- Heatmap hora-del-día vs PnL en frontend (la equity curve ya existe).
- Backtest del motor sobre el historial acumulado en Supabase.
- Stats/breakdowns basados en journal (ver qué emociones pierden, si respetar el plan correlaciona con WR).

### Stocks
- **MarketPulse** en rightbar (DXY/VIX/SPX/US10Y) — ~3 endpoints TD compartidos con TTL 5min.
- **NYSE holidays** en `marketHours.ts` — lista hardcoded (Christmas, Thanksgiving, etc.) para que el reloj/countdown no diga "abierto" en holiday laborable.
- **`DELETE /stocks/watchlist`** clear-all en backend (hoy hay que borrar uno por uno).
- **Loading/error states UI** para mutaciones que fallen en backend (toast o banner).
- **Stocks signals tracking** análogo a forex: registrar evaluaciones BUY/SELL ejecutadas + journal post-mortem específico de stocks (entry+exit price, holding period, reason).

### Operativo
- Migrar frontend a Vercel para que todo sea público (hoy sigue siendo local).
- Auth multi-user → migrar `investor_profile` de singleton a `user_id` por usuario.

## Gotchas conocidos

- **PowerShell + curl**: ver convenciones arriba.
- **`localhost` vs `127.0.0.1`**: ver convenciones arriba.
- **Render free spin-down**: tras 15min de inactividad el servicio se apaga, cold start ~30-50s. Mitigación: UptimeRobot/cron-job.org pinging `/health` cada 5min. **CRÍTICO**: el pinger debe apuntar a `/health` (gratis) — NUNCA a `/scanner/pairs` o `/api/radar` (queman ~11 créditos por ping × 288 pings/día = ~3168 créditos/día, muy por encima del cap 800).
- **Consumo de créditos Twelve Data**: el backend es 100% reactivo — no tiene cron propio. Solo consume al llamar `/scanner/pairs` o `/api/radar`. TTL 15 min + market_closed pause hace el resto. Si ves créditos subir con frontend cerrado, revisa (1) pinger, (2) otra sesión abierta, (3) logs de Render.
- **Cold start borra cache**: tras spin-down Render arranca con cache vacío. Primera llamada a endpoint de datos tras el wake refetchea todos los pares. Pinger `/health` evita este escenario.
- **Supabase password con caracteres especiales**: `@`, `#`, `:`, etc. rompen el parsing del `DATABASE_URL`. Resetear con solo letras y números.
- **Supabase Direct Connection no funciona en Render** (IPv4 only). Usar **Transaction pooler** (port 6543, user `postgres.PROJECT_REF`).
- **`zoneinfo` en Windows**: requiere paquete `tzdata` (está en `requirements.txt`). Linux/Render trae la base IANA del sistema.
- **`/webhook/tradingview` no aparece en `/docs`** con schema de body: usa `Request` crudo (para aceptar también texto legacy). Para probar desde `/docs`, usar `/analyze`.
- **`.env.local` del frontend apunta a Render**: si el backend local tiene código nuevo, el frontend no lo verá hasta hacer push a Render o cambiar temporalmente `NEXT_PUBLIC_API_URL` a `http://127.0.0.1:8000`.
- **Stocks endpoints en backend dev local sin TWELVEDATA_API_KEY**: si arrancás uvicorn local sin la key configurada, `/stocks/quote` y `/stocks/indicators` devuelven 502 con mensaje claro. La key está en Render. Para validar TD localmente, copiá la key de Render Dashboard → backend/.env como `TWELVEDATA_API_KEY=...`.
- **Stocks profile y watchlist en cache local cuando backend está caído**: `profileStorage.ts` y `watchlistStorage.ts` hacen fallback a localStorage si el fetch falla. La app sigue funcionando en "modo local" hasta que el backend vuelve. Watch en `console.warn` para ver caídas.
- **Race condition en mutaciones rápidas de stocks**: agregar 2-3 tickers seguidos antes de que respondan los backends puede causar parpadeo (~50-100ms). Es self-correcting. Si pega molesto, sumar sequence numbers o queue de operaciones.
- **NYSE holidays en `marketHours.ts`**: NO modelados. Christmas en día hábil aparece como "abierto" en la card. TD igual devuelve `closed` en el bundle real. Si querés precisión total, agregar lista hardcoded de holidays del año.
- **Custom events para sync entre instancias del mismo tab**: `StorageEvent` solo dispara en otros tabs. Si un hook se consume en sidebar y dashboard simultáneamente (mismo tab), agregar al patrón de `useStocksWatchlist`/`useInvestorProfile`: dispatchear custom event tras cada mutación + listener en cada hook.
