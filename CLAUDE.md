# CLAUDE.md

Contexto operativo del proyecto para futuras sesiones de Claude Code.

## Qué es esto

**AI Trading Assistant**: motor de decisión contextual sobre señales de TradingView para scalp intradía (0–15 min) en XAUUSD y EURUSD.

**No genera señales** — recibe las que dispara un Pine script propio del usuario y decide **ENTER / WAIT / AVOID** según calidad, contexto y timing. Cuando una señal está fuerte pero el precio está extendido, **degrada a WAIT y emite un plan operativo concreto** (zona de espera, precio trigger, invalidación, instrucciones) para evitar entradas tardías — ese fue el dolor original del usuario: entraba en la vela explosiva y perdía.

**Dos capas de análisis independientes que complementan al Pine**:
- **Scanner en vivo** (pestaña "Análisis de zonas"): sesgo macro y tendencia por confluencia técnica multi-factor (EMA9/21/50/200, RSI, rango, impulso) sobre ~11 pares. Clasifica en 3 bloques (trend / sin edge / reversión).
- **Radar de setups** (pestaña "Radar"): segunda capa que busca puntos concretos de entrada en zonas clave (pin bar / envolvente sobre soporte/resistencia + divergencia RSI). Clasifica en 4 bloques (B1 compra válida, B2 trampa long, B3 venta válida, B4 trampa short). Cross-check con el sesgo del scanner — si hay conflicto, reclasifica B1/B3 → B2/B4.

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
│   │   ├── main.py             # FastAPI: rutas + CORS abierto
│   │   ├── schemas.py          # TVSignal, AnalyzeResponse, EntryPlan (Pydantic)
│   │   ├── decision_engine.py  # Vetos duros + scoring → decisión
│   │   ├── entry_planner.py    # Genera plan operativo (PULLBACK/RETEST/MOMENTUM/SWEEP)
│   │   ├── tv_parser.py        # Acepta JSON o texto legacy multilínea
│   │   ├── ai_client.py        # OpenRouter via urllib (sin deps extra)
│   │   ├── news_client.py      # ForexFactory fetch + cache + warnings por ventana
│   │   ├── scanner.py          # Scanner en vivo (Twelve Data OHLC 15m, 3 bloques) + cache OHLC
│   │   ├── radar.py            # Radar de setups (pin bar/envolv + divergencia + SL cap) + cross-check con scanner
│   │   └── storage.py          # Dual-mode: PostgreSQL (Supabase) / SQLite
│   ├── tests/
│   │   └── test_radar.py       # 46 tests unitarios del radar (pivots, rechazo, SL, alignment, market_closed)
│   ├── requirements.txt
│   ├── render.yaml             # Config deploy Render
│   ├── supabase_init.sql       # SQL inicial para tabla signals en Supabase
│   ├── .env.example
│   └── signals.db              # solo en dev local
├── frontend/
│   ├── app/
│   │   ├── page.tsx            # Dashboard + scanner + radar + sessions + kill zones + news + journal
│   │   ├── radarChart.ts       # drawRadarChart(canvas, setup) — minigráfico Canvas 2D (7 capas)
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
| GET | `/scanner/pairs?pairs=XAUUSD,EURUSD` | Scanner en vivo (consume Twelve Data). Devuelve `market_closed` para pausar polling |
| GET | `/scanner/debug` | Diagnóstico de API key + `last_error` del scanner |
| GET | `/api/radar?pairs=XAUUSD,EURUSD` | Radar de setups con active/expired separados, candles, alignment, market_closed |

`?ai=1` activa el refinamiento OpenRouter (si está configurado). El motor heurístico siempre corre primero; si la IA falla, cae a heurística.

**Solo `/scanner/pairs` y `/api/radar` consumen créditos de Twelve Data**. El resto de endpoints son gratis.

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
7. `_estimate_sl` → SL = soporte/resistencia ± 0.5·ATR. Distancia en pips con cap por instrumento.
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

### Cross-check con scanner (reclasificación)

En `get_radar_response`, tras armar los setups, se llama `scanner.scan_pairs()` (cache compartido → sin fetch extra) y se cruza el bias macro:

- Radar B1 LONG + scanner bias LONG → ✓ `alignment="aligned"`, mantener B1.
- **Radar B1 LONG + scanner bias SHORT → ⚠ reclasificar a B2 TRAP_LONG** (conflict) — el setup técnico existe pero va contra el sesgo macro.
- Scanner NEUTRAL → `alignment="neutral"`, mantener clasificación (no contradice ni respalda).
- Sin data del scanner → `alignment="unknown"`.

Reclasificar = `bloque` cambia, `strength="WARN"`, `sl=None`, `alignment.reclassified=true`, `alignment.original_bloque=1|3`.

### SL caps (pips absolutos por instrumento)

```python
SL_MAX_PIPS = {
    "XAUUSD": 40,   # 40 pips × $0.25 (0.25 lotes) = $10
    "EURUSD": 25,   # 25 pips × $1.00 (1 lote)    = $25
    "default": 20,
}
```

Si `distance_pips > cap` → `too_wide=true`, la card se pinta dimmed con badge "SL EXCEDE" y NO cuenta en `total_setups`.

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

### Minigráfico frontend (`radarChart.ts`)

Canvas 2D puro, **sin librerías**. Función pura `drawRadarChart(canvas, setup)`. 7 capas en orden: fondo, soporte (verde), resistencia (roja), SL (naranja punteado), 20 velas japonesas, triángulo marcador en la vela de rechazo, zona TP sombreada (solo B1/B3). Responsive vía `ResizeObserver` sobre el parent. Labels mínimos (10px mono): precio S/R solo si `near_*`, texto "SL" solo si no too_wide.

### Watchlist operativa

`WATCHLIST = ["XAUUSD", "EURUSD"]` en frontend. Toggle "Solo mis pares" (default OFF) filtra los cards. Los pares operativos muestran badge `● Operativo` sutil. El radar por backend escanea los 11 pares por defecto para tener contexto de reclasificación aunque no operes esos pares.

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
- **Scanner + Radar comparten cache de OHLC**: `scanner._ohlc_cache` (TTL 15 min) usado por ambos — una fetch por par por 15 min, independiente de cuántas vistas lo consulten.
- **Radar de setups (pestaña "Radar")**: ✓ detecta pin bars / envolventes en soporte/resistencia, filtra rango comprimido (MIN_RANGE_PCT), SL estimado con cap por instrumento en pips absolutos (XAU=40, EUR=25), reclasificación automática a trampa si hay conflicto con sesgo del scanner, separación active/expired en el payload, minigráfico Canvas 2D por card.
- **Market closed pause**: ✓ backend detecta vela cacheada >30min (fin de semana o feed caído), frontend pausa `setInterval` → cero tráfico upstream en finde. Banner distintivo 🌙 en radar, indicador sutil en scanner.
- **46 tests unitarios del radar**: ✓ `backend/tests/test_radar.py` cubre pivots, rejection en 3 velas, divergencia, SL cap, alignment, compression, stale data, normalización ISO. Ejecutable con `python tests/test_radar.py`.
- **Decisión operativa confirmada**: watchlist del radar = XAUUSD + EURUSD (toggle frontend default OFF). Los demás pares se escanean por contexto para el cross-check de sesgo, no para operar.

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
- **Render free spin-down**: tras 15min de inactividad el servicio se apaga, cold start ~30-50s. Mitigación: UptimeRobot/cron-job.org pinging `/health` cada 5min. **CRÍTICO**: el pinger debe apuntar a `/health` (gratis) — NUNCA a `/scanner/pairs` o `/api/radar` (queman ~11 créditos por ping × 288 pings/día = ~3168 créditos/día, muy por encima del cap 800).
- **Consumo de créditos Twelve Data**: el backend es 100% reactivo — no tiene cron propio. Solo consume al llamar `/scanner/pairs` o `/api/radar`. TTL 15 min + market_closed pause hace el resto. Si ves créditos subir con frontend cerrado, revisa (1) pinger, (2) otra sesión abierta, (3) logs de Render.
- **Cold start borra cache**: tras spin-down Render arranca con cache vacío. Primera llamada a endpoint de datos tras el wake refetchea todos los pares. Pinger `/health` evita este escenario.
- **Supabase password con caracteres especiales**: `@`, `#`, `:`, etc. rompen el parsing del `DATABASE_URL`. Resetear con solo letras y números.
- **Supabase Direct Connection no funciona en Render** (IPv4 only). Usar **Transaction pooler** (port 6543, user `postgres.PROJECT_REF`).
- **`zoneinfo` en Windows**: requiere paquete `tzdata` (está en `requirements.txt`). Linux/Render trae la base IANA del sistema.
- **`/webhook/tradingview` no aparece en `/docs`** con schema de body: usa `Request` crudo (para aceptar también texto legacy). Para probar desde `/docs`, usar `/analyze`.
- **`.env.local` del frontend apunta a Render**: si el backend local tiene código nuevo, el frontend no lo verá hasta hacer push a Render o cambiar temporalmente `NEXT_PUBLIC_API_URL` a `http://127.0.0.1:8000`.
