# CLAUDE.md

Contexto operativo del proyecto para futuras sesiones de Claude Code.

## Qué es esto

**AI Trading Assistant**: motor de decisión contextual sobre señales de TradingView para scalp intradía (0–15 min) en EURUSD (XAUUSD removido del scanner por límite de 8 req/min en Twelve Data free tier — el script Pine de oro permanece pero no se consulta su OHLC). **No genera señales** — recibe las del Pine del usuario y decide **ENTER / WAIT / AVOID** según calidad, contexto y timing. Cuando una señal está fuerte pero el precio está extendido, degrada a WAIT y emite plan operativo (zona de espera, trigger, invalidación, instrucciones) para evitar entradas tardías.

**Capas independientes que complementan al Pine**:
- **Scanner en vivo** ("Análisis de zonas", view `zones`): sesgo macro multi-factor (EMA9/21/50, RSI, rango, impulso) **sobre M5** (intervalo configurable, hoy `5min`). Veredicto LONG/SHORT/NEUTRAL por par + 3 bloques (trend / sin edge / reversión). Es la señal de ENTRADA de corto plazo.
- **Zonas S/R Activas** (view `sr`, `zones.py`): niveles soporte/resistencia por pivots + clustering sobre M15 + **bias direccional M30** (EMA50 vs EMA100 sobre velas M30 resampleadas de M15; tercer estado RANGO). Es el sesgo DIRECCIONAL de medio plazo. Lenguaje neutro — marca el terreno, no recomienda.
- **Veredicto cruzado M30+M5** (`cross_verdict.py`): reconcilia el bias M30 con el side del scanner → A FAVOR / FADE EN RANGO / CONFLICTO / SIN SETUP. **Mismo veredicto en ambas pantallas** (scanner + Zonas S/R). Filosofía: el M30 manda, el M5 ejecuta dentro de lo que el M30 permite. Detalle más abajo.
- **Radar de setups** (UI oculta): puntos concretos de entrada (pin bar / envolvente sobre soporte/resistencia + divergencia RSI). Tab eliminada del Topbar; código backend + `/api/radar` siguen disponibles. Detalle del motor más abajo.
- **Playbook** (estático): hoja de reglas operativas AUDUSD (09–14h Madrid) + USDCAD (14–21h Madrid). Quick cards con stats históricos, timeline visual 09–21h, detalle franja por franja, resumen por par, reglas globales. No consume APIs.

## Stack

- **Backend**: FastAPI (`backend/`), Python 3.11+. Render free tier → `https://tradingapp-2glz.onrender.com`.
- **DB**: dual-mode — Supabase PostgreSQL en prod (via `DATABASE_URL` + transaction pooler port 6543), SQLite en dev local. `storage.py` ramifica.
- **Frontend**: Next.js 14 App Router + TypeScript (`frontend/`). Local apuntando a Render via `NEXT_PUBLIC_API_URL` en `.env.local`.
- **Pine**: `scriptsTradingView/SMS_XAUUSD_v8_9_1.pine` y `SMS_EURUSD_v8_10_1.pine`.
- **IA opcional**: OpenRouter via urllib si `USE_AI=1` y `OPENROUTER_API_KEY`. Sin key, motor heurístico puro.
- **News**: ForexFactory JSON gratis. `news_client.py` cachea 1h en memoria.
- **Datos de mercado**: Twelve Data (free 800 créditos/día, 8 req/min). API key compartida entre scanner forex y módulo stocks.

## Arquitectura del flujo

```
TradingView (Pine) ─alert()→ Render ─POST→ FastAPI ─→ Supabase
                                              ├─→ decision_engine (vetos + score)
                                              ├─→ entry_planner (plan operativo)
                                              ├─→ news_client (warnings, NO bloquea)
                                              ├─→ ai_client (OpenRouter, opcional)
                                              ├─→ scanner ──┐
                                              └─→ radar  ───┴─→ Twelve Data (OHLC 15m)
                                                              via _ohlc_cache compartido (TTL 15min)
Frontend Next.js (local) ←─polling── Render
   ├── dashboard: 5s   (/signals, /stats, /news/warnings)
   └── scanner:  5min  (/scanner/pairs)  — pausa si market_closed
   (playbook estático · radar backend-only sin polling desde la UI)
```

**Cache OHLC compartido**: scanner/zones/radar llaman `scanner._fetch_chart()` → key `f"{pair}:{interval}:{outputsize}"` en `_ohlc_cache`. Una fetch por par/interval cada 15min independiente de cuántas vistas la consulten. **Fase 3**: el fetch pasa por `td_client` (token-bucket global 8/min compartido con stocks + single-flight por key — dos requests concurrentes con cache frío ya no duplican el fetch) y se persiste en la tabla `ohlc_cache` de la DB: tras un spin-down de Render, el primer request rehidrata desde DB si el TTL sigue vivo → **el cold start ya no cuesta un burst de 429s**. `/scanner/debug` expone `td.credits_today` / `requests_last_minute`.

## Estructura

```
backend/app/
  main.py             # FastAPI: rutas (forex + stocks) + CORS abierto
  schemas.py          # TVSignal, AnalyzeResponse, EntryPlan (Pydantic)
  decision_engine.py  # Vetos + scoring → decisión
  entry_planner.py    # Plan operativo (PULLBACK/RETEST/MOMENTUM/SWEEP)
  tv_parser.py        # Acepta JSON o texto legacy multilínea
  ai_client.py        # OpenRouter via urllib
  news_client.py      # ForexFactory + cache + warnings
  scanner.py          # Scanner Twelve Data M5 (SCANNER_INTERVAL="5min") + _ohlc_cache
  zones.py            # Zonas S/R + bias M30 (EMA50 vs EMA100, M15→M30). Fetch M15 propio
  cross_verdict.py    # Veredicto cruzado M30+M5 (reconcile + build_cross_map). Fuente única
  radar.py            # Setups (pin bar/envolv + divergencia + SL cap) + cross-check
  stocks_client.py    # Twelve Data stocks (fetch vía td_client) + bundle de indicadores
  indicators.py       # Implementación ÚNICA de EMA/RSI/ATR/SMA/MACD/BBANDS/ADX (antes 3 copias)
  td_client.py        # Gate único a Twelve Data: token-bucket 8/min global (forex+stocks),
                      # single-flight por cache key, contador diario de créditos, retry con Retry-After
  correlations.py     # Mapa estático 6 pares + system prompt + query() OpenRouter
  constants.py        # Valores mágicos centralizados (intervalos, TTLs, EMA periods, pares)
  storage.py          # Dual-mode PG/SQLite. Tablas: signals + investor_profile + stocks_watchlist
backend/scripts/calibrate.py # Calibración offline (WR por factor + sweep de umbral)
backend/tests/       # test_radar + test_zone_marco + test_phase2 + test_phase3 (97 tests)
backend/{requirements.txt, render.yaml, supabase_init.sql, .env.example}

frontend/
  app/{page.tsx, radarChart.ts, layout.tsx (next/font: Space Grotesk + Mono), globals.css}
  components/{shell/, dashboard/, icons/, stocks/{onboarding/, dashboard/, ...}, correlations/, playbook/, zones/ (ZonasSRView), cross/ (CrossBadge — compartido scanner+zonas)}
  hooks/{useTick, useFavoritePairs, stocks/{useInvestorProfile, useStockSignal, useStocksWatchlist}}
  lib/{api, types, sessions, killZones, format, dates, zones, symbols, blockLegend, config, correlations,
       alerts (chime ~5s + Notification, partitura pura testeada en alerts.test.ts),
       radar/{labels, blocks, aplus},
       stocks/{types, signalEngine(.test), twelvedata, profileStorage, watchlistStorage, marketHours}}
  public/patterns.html # Referencia estática de patrones (link "Patrones ↗" del Topbar)
  .env.local          # NEXT_PUBLIC_API_URL → Render

scriptsTradingView/   # Pine scripts
dashboard_mockup.html # Referencia visual del rediseño AppShell
Iniciar App.cmd       # Lanzador 1-clic del frontend (+ acceso directo en Escritorio)
```

## Motor de decisión (forex)

### Vetos duros (→ AVOID)

- LONG en `VENDE YA`, MTF30 BEAR, RSI ≥ 78, overhead/resistencia inmediata.
- SHORT en `COMPRA YA`, MTF30 BULL, RSI ≤ 22, soporte inmediato.
- `conf < 5`, `congestion = true`.
- **Geometría** (Fase 2): SL del lado equivocado · `risk_pips > SL_MAX_PIPS[symbol]` (25 EURUSD) · `R:R (tp vs sl) < 1.5`.
- **Staleness** (Fase 2): edad de la señal > 10 min → AVOID (usa el campo `time` del Pine, epoch ms de `time_close`; sin `time`, no aplica).

**News NO es veto**: banner de aviso en frontend, pero la señal se evalúa normalmente. Decisión explícita del usuario.

### Score (después de pasar vetos)

| Factor | Pts |
|---|---|
| Quality PREMIUM / STRONG / NORMAL | +4 / +3 / +1 |
| MTF30 alineado | +2 |
| Zona favorable (`COMPRA*` LONG, `VENDE*` SHORT) | +2 |
| Patrón direccional presente (NR7/Inside Bar NO puntúan: son neutros) | +1 |
| `vol_high` | +1 |
| FVG presente | +1 |
| IFVG (retest de FVG invertido) presente | +1 |
| Kill zone Madrid (mismas ventanas que `lib/killZones.ts`) | FIRE +1 / WARN −1 / AVOID −2 |

**`conf` NO se puntúa aparte** (Fase 2): en el Pine `quality` ES función determinista de `conf` (`>=14 PREMIUM, >=10 STRONG, >=5 NORMAL`) — puntuar ambas contaba la misma variable dos veces y el score era ~una transformación afín de conf.

**Mapeo** (provisional hasta calibrar con `scripts/calibrate.py`): ≥7 → ENTER (degrada a WAIT si el plan exige esperar [PULLBACK/EXTENDED/SWEEP_REVERSAL/RETEST], si la señal tiene edad >3 min, o si la kill zone es AVOID); ≥4 → WAIT; <4 → AVOID.

### Entry planner

Calcula `wait_zone`, `trigger_price`, `invalidation`, `instructions` (español) + `expires_after` (velas M5 de validez — los triggers usan referencias congeladas al momento de la señal). Requiere campos del Pine: `ema9`, `ema21`, `atr`, `swing_high`, `swing_low`, `high`, `low`.

| Tipo | Cuándo | Vigencia | ¿Degrada ENTER? |
|---|---|---|---|
| `SWEEP_CONFIRMED` | El Pine detectó sweep EN la vela de señal (flags `sweep_low/high`) → la reversión ya confirmó | 2 | No (entrada inmediata) |
| `SWEEP_REVERSAL` | Zona extrema, sweep aún NO ocurrió → esperar barrida + vuelta | 6 | Sí |
| `RETEST` | Romper swing reciente → esperar retest (va ANTES del chequeo de extensión; antes era inalcanzable porque la vela de ruptura casi siempre está >1×ATR del EMA9) | 8 | Sí |
| `PULLBACK_EMA9` | >1× ATR del EMA9 → esperar retroceso | 6 | Sí |
| `EXTENDED_SKIP` | >2.5× ATR del EMA9 → mejor saltar | 0 | Sí |
| `IMMEDIATE` | Cerca del EMA9 con cierre fuerte (reemplazó a `MOMENTUM_CONFIRM`, cuya premisa era falsa: el Pine SOLO señala con isStrongBull/Bear) | 1 | No |

Filosofía pro-scalper: nunca entrar en la vela de señal extendida; los pros esperan pullback al EMA9, retest del nivel, o sweep + reversión. Cuando la señal NO está extendida, el cierre fuerte del Pine ya es la confirmación → ENTER inmediato coherente (antes el motor decía ENTER y el plan decía "espera").

### TVSignal (lo que envía el Pine)

- **Obligatorios**: `signal`, `symbol`, `price`, `sl`, `be`, `tp`, `conf`, `quality`.
- **Contextuales**: `pattern`, `fvg`, `ifvg`, `vol_high`, `vol_ratio`, `rsi`, `kz`, `mtf`, `zona`, `overhead`, `congestion`. `ifvg` = retest de FVG invertido (el Pine EURUSD invierte el rol de un FVG violado por cierre — la zona rota pasa a oferta/demanda — y elimina los FVG rotos de la confluencia clásica, que antes seguían contando; requiere re-pegar el Pine).
- **Planner (recomendados)**: `ema9`, `ema21`, `atr`, `swing_high`, `swing_low`, `high`, `low`.
- **Fase 2**: `time` (epoch ms de `time_close` — staleness), `sweep_low`, `sweep_high` (bool — sweep en la vela de señal). **Requiere re-pegar el Pine actualizado en TradingView** — sin estos campos el motor funciona igual pero sin veto de staleness ni SWEEP_CONFIRMED.
- Categóricos: `signal: LONG|SHORT|BUY|SELL` · `quality: PREMIUM|STRONG|NORMAL|LOW` · `mtf: BULL|BEAR|MIX` · `zona: COMPRA YA|COMPRA|VENDE|VENDE YA` (opcional — sin default direccional).

## Endpoints

| Método | Ruta | Notas |
|---|---|---|
| GET | `/health` | `{ok:true}` (target del pinger) |
| POST | `/analyze?ai=0\|1` | Evalúa señal Pydantic |
| POST | `/webhook/tradingview?ai=0\|1` | Recibe del Pine (JSON o texto legacy) |
| GET | `/signals?limit=&symbol=` | Lista paginada filtrable |
| GET | `/signals/stream` | **SSE**: `event: signal` al llegar señal nueva (chequeo cada 2s del max id; keep-alive 30s). Frontend lo usa para load inmediato; polling 5s queda de fallback |
| GET | `/symbols` | Símbolos únicos vistos |
| POST | `/bridge/trades` | El bridge MT5 registra una apertura (real o dry-run). Token opcional vía `WEBHOOK_TOKEN` |
| POST | `/bridge/trades/{ticket}/close` | Cierre por mt5_ticket: `{result, exit_price?, pnl_usd?}`. 404 si no hay fila abierta |
| GET | `/bridge/trades?limit=&offset=` | Historial de trades del bridge (contexto + resultado) |
| POST | `/signals/{id}/result` | `{result, exit_price?, journal_*?}` |
| DELETE | `/signals/{id}` | Borrar (limpiar data sucia) |
| GET | `/stats` | Overall + by_symbol/decision/source/quality/side/zona/mtf/pattern/**score/conf** + taken/rated/execution_rate |
| GET | `/news?symbol=&hours=` | Próximas high-impact relevantes |
| GET | `/news/warnings?currencies=&now=` | Warnings activos (polling 5s, `now` para simular) |
| GET | `/news/calendar?date=&impact=` | Eventos de un día en hora Madrid |
| GET | `/scanner/pairs?pairs=` | **Consume TD** (M5). Devuelve `market_closed`. Cada item trae `cross` (veredicto M30+M5) |
| GET | `/scanner/debug` | API key + `last_error` |
| GET | `/api/zones?pairs=&window=&...` | **Consume TD** (M15). Niveles S/R + `bias_m30` + `cross` + `marco` por par. Params override (rango_atr_mult, active_range_pips, etc.) |
| GET | `/api/zones/gate-stats` | Telemetría del marco (16-jul): por par, evals + decisiones + gate duro que bloquea. En memoria, **NO consume TD** |
| POST | `/api/zones/gate-stats/reset` | Limpia el acumulador de gate-stats |
| GET | `/api/radar?pairs=` | **Consume TD**. Active/expired separados, candles, alignment, market_closed |
| GET | `/stocks/search?q=` | TD `symbol_search` (gratis). Cache 24h |
| GET | `/stocks/quote?symbol=` | **1 crédito TD**. Cache 5min |
| GET | `/stocks/indicators?symbol=&interval=` | **2 créditos TD**. IndicatorBundle. Intervalos: 15min/1h/4h/1day |
| GET/POST/DELETE | `/stocks/profile` | Singleton id=1. POST validado |
| GET/POST/DELETE/PATCH | `/stocks/watchlist[/{symbol}]` | POST idempotente. PATCH para `{lastDecision?, lastConfidence?}` |
| GET | `/correlations` | Matriz estática 6×6. No consume TD ni AI |
| POST | `/correlations/query` | Body `{question}` → OpenRouter haiku. 503 si falta key, 502 si OR falla |

`?ai=1` activa OpenRouter; el motor heurístico siempre corre primero, fallback a heurística si la IA falla.

**Endpoints que consumen créditos TD**: `/scanner/pairs`, `/api/zones`, `/api/radar`, `/stocks/quote`, `/stocks/indicators`. `/stocks/search` es gratis.

## Tablas DB (idénticas en SQLite y PostgreSQL)

```
signals (
  id PK, received_at, signal_json, response_json, decision, symbol, side,
  result (WIN|LOSS|BE|NULL), exit_price, pnl, closed_at, source (heuristic|ai),
  taken (yes|no|NULL),
  journal_respected_plan, journal_closed_early, journal_emotion  -- solo si taken=yes
)

investor_profile (  -- singleton id=1
  id PK, horizon (day_trader|swing|long_term), risk_tolerance (1-5),
  capital_range (<1k|1k-10k|10k-50k|50k+), experience (novice|intermediate|advanced),
  sectors_json, updated_at
)

stocks_watchlist (
  symbol PK (UPPERCASE), last_decision (BUY|SELL|HOLD|NULL), last_confidence (0-1), added_at
)

ohlc_cache (  -- persistencia del cache OHLC (Fase 3): rehidrata tras cold start
  key PK ("PAIR:interval:outputsize"), fetched_at (epoch float), payload (JSON raw de TD)
)

bridge_trades (  -- historial del bridge MT5: contexto de la señal + resultado real del broker
  id PK, opened_at, symbol, side (LONG|SHORT), source (marco|pine),
  lots, entry_price, sl_price, tp_price, risk_usd, rrr,
  signal_id (NULL salvo trades del Pine), mt5_ticket (NULL en dry-run),
  dry_run (1|0), context_json (score/nivel/sesión/cross),
  result (WIN|LOSS|BE|NULL), exit_price, pnl_usd, closed_at
)
```

**Migración auto en `init_db()`**: PG usa `ALTER TABLE ADD COLUMN IF NOT EXISTS`; SQLite hace `PRAGMA table_info` + ALTER condicional. Al añadir columnas, agregarlas a ambos branches. Upsert profile via `ON CONFLICT (id) DO UPDATE` / `INSERT OR REPLACE`. Add watchlist idempotente via `ON CONFLICT DO NOTHING` / `INSERT OR IGNORE`.

CRUD en `storage.py`: `get/save/clear_investor_profile`, `get/add/remove/update_stocks_watchlist*`.

## Variables de entorno

```bash
DATABASE_URL=postgresql://postgres.XXX:PASS@aws-1-us-east-2.pooler.supabase.com:6543/postgres  # vacío = SQLite
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=anthropic/claude-sonnet-4                # forex decision_engine
OPENROUTER_MODEL_CORRELATIONS=anthropic/claude-haiku-4.5  # cheap, deterministic
OPENROUTER_REFERER=http://localhost
USE_AI=0
NEWS_FILTER_ENABLED=1
NEWS_WINDOW_BEFORE_MIN=30
NEWS_WINDOW_AFTER_MIN=5
TWELVEDATA_API_KEY=  # compartida scanner forex + módulo stocks
WEBHOOK_TOKEN=       # opcional: si está set, /webhook/tradingview exige ?token= o campo "token" en el payload (401 si no coincide)
ADMIN_API_KEY=       # opcional: si está set, DELETE /signals y /signals/{id} exigen header X-Admin-Key
```

## Scanner en vivo

Análisis independiente del Pine. Lectura técnica multi-factor sobre **OHLC M5** (`SCANNER_INTERVAL="5min"`, `SCANNER_OUTPUTSIZE=200` en `constants.py`), devuelve pares rankeados por confluencia.

- **Twelve Data** (`api.twelvedata.com/time_series`). Yahoo Finance no funciona desde Render (bloquea IPs datacenter).
- **Símbolos**: conversión auto `EURUSD → EUR/USD` etc. `_parse_ohlc` extrae `open/high/low/close/ts` (el `open` lo usa el radar para pin bars). **Excluye la vela en formación** (si `meta.interval` presente y `open_ts + interval > now`): solo velas cerradas alimentan indicadores — antes el side/bias repintaba intrabar y quedaba congelado 15 min por el TTL. Fixtures sintéticas sin `meta` no se ven afectadas.
- **Cache**: `CACHE_TTL_OHLC_SCANNER=900` (15min). `_cache` (cards scored) + `_ohlc_cache` (OHLC crudo). Key `f"{pair}:{interval}:{outputsize}"` → scanner usa `pair:5min:200`, radar `pair:15min:200`, zones `pair:15min:200`.
- **Indicadores**: EMA9/21/50, RSI14, ATR14, posición rango 50v, impulso 5v.
- **Scoring**: 7 factores ±1/0. `bias = Σ`. `side: LONG si bias≥3, SHORT si ≤-3, NEUTRAL`. `confluence = |bias|` (0-7).
- **Endpoint**: `/scanner/pairs?pairs=...` (default 6 majors; `?pairs=` se filtra contra `ALLOWED_PAIRS` en `main.py` — símbolos fuera de whitelist se ignoran para no drenar créditos TD). Devuelve `{items, count, brief, last_error, market_closed, data_age_minutes}`. Cada item lleva `cross` (veredicto M30+M5). `market_closed=true` si vela más reciente >45min (`RADAR_MARKET_STALE_THRESHOLD_MIN=45`: intervalo M15 + TTL 15min + margen, necesario desde que se excluye la vela en formación) → frontend pausa polling. `/scanner/debug` para diagnóstico — errores por par en `_last_errors` (dict), un fetch exitoso limpia el error de su par (antes un string global quedaba stale para siempre).

## Zonas S/R Activas + bias M30 (`zones.py` · view `sr`)

Tercera capa: niveles soporte/resistencia operables (scalp M5/M15) + **bias direccional M30**. Lenguaje estrictamente descriptivo.

- **Fetch M15 propio**: `zones.analyze_zones` llama `scanner._fetch_chart(pair, interval="15min", outputsize=200)` → cache key `pair:15min:200`, **independiente del scanner M5**. (El scanner pasó a M5 en commit `e7827e4`; antes zones compartía su caché — al cambiar a M5 zones recibía solo ~34 velas M30 y el bias caía a "insuficiente". El fix devolvió a zones su fetch M15: 200 M15 → ~100 M30.)
- **Bias M30** (`_compute_m30_bias`): resample M15→M30 (`_resample_m15_to_m30`, `closed="left", label="left"` — los ts de TD son la APERTURA de la vela; con `right` las M30 quedaban desfasadas 15 min de cualquier M30 de broker. Descarta la última M30 si solo tiene 1 hija M15), EMA50 vs EMA100. Fetch `ZONES_OUTPUTSIZE=600` M15 → ~300 M30 (con 200 la EMA100 quedaba en su seed SMA sin converger; mismo coste TD). Guard `len(m30) < EMA_PERIOD_100` (100) → `insufficient_m30_bars`. Estados: BULL (ema50>ema100), BEAR (ema50<ema100), RANGO (|ema50-ema100| < `rango_atr_mult`×ATR_M30, default 0.3) **con histéresis** (`_BIAS_STATE` por par+mult: entrar en RANGO exige sep < 0.8×umbral, salir > 1.2× — mata el flip-flop del cross verdict en la frontera). `available=false` con `reason` si no calculable.
- **Rango asiático** (`_asia_range`, Fase 2): high/low de la sesión Asia (02–09h Madrid) desde las M15 + flags `swept_high/swept_low` (mecha post-09h que excede el extremo). Expuesto como `asia_range` por par en `/api/zones` y renderizado en `PairCard` — la liquidez que London Open suele barrer, niveles de referencia para la ventana AUDUSD 09–14h del playbook.
- **Wick ratio**: cap en `WICK_RATIO_CAP=5.0` + dirección `neutral` si el cuerpo es <15% del rango — antes un doji con cuerpo de 1 tick daba ratio 10 y satisfacía trivialmente el gate de rechazo del marco.
- **Niveles**: pivots fractales (ventana 3) + clustering single-linkage por pips. Cada nivel: precio, tipo (support/resistance), fuerza 1-5, toques, antigüedad, distancia, `active` (dentro de rango + coherente con bias; `ZONES_ACTIVE_RANGE_PIPS=40` desde 16-jul), wick ratio del último toque. **Nota (16-jul)**: el marco ya NO usa el flag `active` para elegir nivel — `_best_level_for_side` filtra por tipo+distancia+fuerza (el `active` = within_range ∧ coherent_with_bias era auto-contradictorio en tendencia: el soporte coherente con bias BULL queda fuera del rango cuando el precio corre). El flag sigue existiendo para el orden/render.
- **Endpoint** `/api/zones`: `{items, count, market_closed}`. Cada item: `bias_m30`, `levels[]`, `recent_wicks`, `cross`, `marco`, `params`. Params override vía query (window, merge_distance_pips, active_range_pips, min_bars_between, touch_tolerance_pips, level_selector, rango_atr_mult). Cache `_zones_cache` por (pairs, params), TTL 15min. **No cachea respuestas con `items` vacío** (`get_zones_response`): si todos los pares fallan (típicamente un 429 transitorio de TD por el cap 8 req/min), cachear el vacío congelaría "Sin datos disponibles" durante el TTL entero; dejándolo sin cachear, el siguiente poll (5 min) reintenta.
- **Pares default** (`ZONES_DEFAULT_PAIRS`): AUDUSD, USDCAD. Frontend `ZonasSRView` poll 5min, pausa si `market_closed`.
- **Marco teórico** (`zone_signal_engine.generate_zone_marco`, `MarcoCard` en `ZonasSRView`): reemplazó a la antigua "señal" (FUERTE_COMPRA/COMPRA/VENTA) y su sistema de alertas (sonido + `Notification`), **eliminados por completo** (nunca funcionaron de forma fiable). El motor mantiene sus dos capas pero reencuadradas: CAPA 1 = **gates** (mercado abierto, MTF coherente M30/M5, sesión, no-extendido, volatilidad, estructura con impulso, nivel S/R operable, rechazo, RRR≥2, cuenta) como checklist ✓/✗; CAPA 2 = **confluencia** (score 0–18). **Gate 9 (RRR+SL cap) es fallable desde Fase 2**: `_calculate_sl_tp` ya NO recorta el SL estructural al cap (si excede → gate falla; recortarlo dejaba el SL dentro del nivel = stop-out garantizado) ni fabrica TP sintético 2:1 a través de niveles (el TP es el nivel opuesto real; si da RRR<2 → gate falla; 2:1 solo cuando no hay nivel opuesto que obstruya). Antes el gate solo podía fallar con risk=0 — era teatro. Decisión final: **OPERAR** (gates duros OK + score ≥ `min_score_normal`), **ESPERAR** (gates OK pero confluencia floja, o degradado por noticia), **NO OPERAR** (falla algún gate duro). **Noticias = gate blando**: `news_client.get_active_warnings` por par; un high-impact en ventana degrada OPERAR→ESPERAR (banner ámbar), nunca veta. `main.py::/api/zones` inyecta `marco` por par. Test: `backend/tests/test_zone_marco.py`.
  - **Aflojado 2026-07-16** (tras 4 días de dry-run con 0 trades — el marco casi nunca llegaba a ejecutable): (1) `veto_avoid_session=False` en **ambos** pares → la sesión solo puntúa (+2/+1/0), ya no es gate duro (antes USDCAD fuera de NY era veto); (2) `veto_bloque2_in_trend=False` en ambos → un scanner Bloque 2 bajo cross A FAVOR ya no veta (la tendencia de 2 TF confirma); (3) `max_entry_distance_pips` AUD 12→20, CAD 10→18 y el nivel se elige sin exigir `active` (ver arriba). El resto de gates duros (mercado, MTF, no-extendido, volatilidad, RANGE-en-tendencia, RRR≥2, cuenta) intactos. **Telemetría** (`_GATE_STATS`): cada evaluación registra decisión + gate duro que bloqueó; expuesto en `GET /api/zones/gate-stats` y `POST /api/zones/gate-stats/reset` (en memoria, se resetea con el cold start de Render). Para calibrar el siguiente ajuste con datos, no a ojo.
- **Alertas de señal FUERTE** (`ZonasSRView`): sonido Web Audio (chime ascendente LONG / descendente SHORT, **~5s de duración**: motif de 3 notas × 5 repeticiones — `CHIME_TARGET_SEC=5` en `lib/alerts.ts`; la partitura es la función pura `chimeSchedule(side)` y `playChime` solo la programa en el `AudioContext`, testeable sin navegador en `lib/alerts.test.ts` vía `npx tsx`) + `Notification` del navegador **solo** cuando un par transiciona a `OPERAR` + `strength="fuerte"` (`strongSide()`). Botón header `🔔/🔕` toggle; `enableAlerts()` desbloquea el `AudioContext` y pide permiso de notificación **desde el clic** (gesto de usuario — obligatorio o el navegador bloquea audio/permiso). Estado persistido en `localStorage` `tradingapp:zones_alerts_on`. Detección por `prevStrongRef` (Map por par, transición = aparece o cambia de lado) gateada por un registro persistido en `localStorage` `tradingapp:zones_last_alerts` (par→{lado, timestamp}): **cooldown 15 min por par+lado** que sobrevive recargas — una señal activa al montar suena si aún no se alertó (antes el baseline se la tragaba) y el flip-flop en la frontera del score no re-dispara. Si `data_age_minutes > 10` **no suena el chime** — solo Notification con "⚠ Señal de hace X min" (no invitar a entrada tardía; la notificación siempre incluye la edad). En backend, `zone_signal_engine._STRENGTH_STATE` añade **histéresis al strength**: una vez "fuerte" se mantiene mientras `score >= min_score_strong - 1` (se resetea con gate duro fallado, ESPERAR o degradación por noticia). **Gotcha**: la versión anterior (alertas en cada cambio de señal) no sonaba porque creaba el `AudioContext` sin gesto previo → suspendido. Frontend-only: `marco.strength` ya viene del backend; no requiere deploy.

## Veredicto cruzado M30+M5 (`cross_verdict.py`)

Reconcilia el bias M30 (Zonas S/R) con el side del scanner M5. **Una sola fuente de verdad**: la función pura `reconcile()` (las reglas) + las cachés OHLC/scored compartidas (los inputs). Ambos endpoints llaman `build_cross_map()` → veredicto **idéntico** en scanner y Zonas S/R. Sin caché propia (reconcile es puro y barato; no queda stale respecto a sus inputs).

| Estado | Condición | Tono | Etiqueta |
|---|---|---|---|
| A "A FAVOR" | BULL+LONG · BEAR+SHORT | verde | `A FAVOR M30 · [LONG/SHORT] de tendencia` (confluencia vale completa) |
| B "FADE EN RANGO" | RANGO + (LONG\|SHORT) | ámbar | `FADE EN RANGO · objetivo extremo opuesto` (objetivo = S/R activo opuesto + precio; mean-reversion con caducidad) |
| C "CONFLICTO" | BULL+SHORT · BEAR+LONG | rojo | `⚠ CONFLICTO M30/M5` (aviso fuerte, **NO bloquea**; decisión del usuario) |
| D "SIN SETUP" | scanner NEUTRAL | gris | `Sin señal M5` |
| NA | bias M30 no disponible | gris | `Bias M30 no disponible` (no se asume dirección) |
| OUT | par fuera de `CROSS_PAIRS` | gris | `M30 fuera de alcance` (sin fetch) |

- **Precedencia**: D (scanner NEUTRAL) → NA (bias no disponible) → A/B/C.
- **`CROSS_PAIRS`** = `set(ZONES_DEFAULT_PAIRS)` = AUDUSD, USDCAD. Solo estos reciben cruce real; el resto del scanner cae en OUT sin consumir TD.
- **Objetivo FADE**: `_nearest_opposite_level` saca el soporte (si SHORT) o resistencia (si LONG) activo más cercano de los `levels` de zones; el precio va en el texto `summary` (todo el texto se arma en backend → idéntico en ambas vistas).
- **Params**: `/api/zones` propaga sus `params` (p.ej. `rango_atr_mult`) a `build_cross_map` para que el cruce use el mismo bias que el chip M30 de esa vista. `/scanner/pairs` usa defaults. Solo divergen en un par justo en la frontera RANGO con el slider movido.
- **Frontend**: `CrossBadge` (componente compartido `components/cross/`) — compacto para A/D/NA/OUT (summary en tooltip), `summary` visible para B (FADE), bloque rojo pulsante para C (`role="alert"`).

## Radar de setups (UI oculta · backend activo)

Segunda capa: puntos concretos de entrada en zonas clave (M15) con price action puro. **La tab del Topbar fue eliminada**; toda la lógica de `backend/app/radar.py`, el endpoint `/api/radar`, los tests (`backend/tests/test_radar.py`), `radarChart.ts` y `lib/radar/` permanecen. **`RadarView` y sus ~830 líneas de componentes muertos fueron BORRADOS de `page.tsx` en Fase 3** (inalcanzables; inflaban el archivo de 2722 a ~1890 líneas). Para reactivar: recuperar `RadarView`/`RadarCard`/`RadarSemaforo` y los tipos `RadarSetup`/`GeometryAnalysis`/`SmcAnalysis` del historial de git (commit previo a Fase 3), colocarlos en `components/radar/`, y añadir la entrada en `Topbar.tsx::TABS` + el caso `view === "radar"`.

### Pipeline (`radar._analyze_symbol`)

1. `scanner._fetch_chart(symbol, interval=RADAR_INTERVAL, outputsize=RADAR_OUTPUTSIZE)` → reutiliza `_ohlc_cache` (key `pair:15min:200`). **Gotcha corregido**: se llamaba sin args → heredaba los defaults M5 del scanner y todo el radar (niveles, M30 sintético, MTF-LOCK, market_closed) corría sobre un timeframe falso.
2. `_find_key_levels` → pivots fractales (2 velas a cada lado) + clustering 0.2% → S/R más cercanos.
3. **Filtro rango comprimido**: si `(R-S)/price < MIN_RANGE_PCT` (0.15% XAU / 0.10% EUR / 0.12% default) → `return None` (consolidación).
4. `_detect_recent_rejection` → últimas 3 velas: pin bar / envolvente. `candle_age (1/2/3)`, `candle_ts`. Si age=3 → `expired=True`.
5. `_detect_rsi_divergence` → alcista (precio nuevo mín + RSI sube + RSI<50) o bajista (simétrico).
6. `_classify_reversal_setup` → 5 bloques.
7. `_estimate_sl` → SL = S/R ± 0.5·ATR. Distancia en pips con cap por instrumento. Calcula RRR contra nivel opuesto: LONG `tp=resistance`, SHORT `tp=support`. Devuelve `rrr`, `rrr_below_min` (true si <`MIN_RRR=2.0`), `reward_pips`, `tp_price`, `rrr_min`.
8. **Stale data**: si última vela cerró hace >30min, fuerza `rejection.expired=True`.
9. Adjunta `candles` = últimas 20 OHLC ISO 8601 para minigráfico.

### Bloques

| Bloque | Condición | Side | Strength |
|---|---|---|---|
| B1 STRONG | soporte + rechazo LONG + range_pos<0.35 + divergencia alcista | LONG | STRONG |
| B1 NORMAL | soporte + rechazo LONG + range_pos<0.35 | LONG | NORMAL |
| B3 STRONG | resistencia + rechazo SHORT + range_pos>0.65 + divergencia bajista | SHORT | STRONG |
| B3 NORMAL | resistencia + rechazo SHORT + range_pos>0.65 | SHORT | NORMAL |
| B2 TRAP | soporte + rechazo SHORT (soporte va a ceder) | TRAP_LONG | WARN |
| B4 TRAP | resistencia + rechazo LONG (resistencia va a ceder) | TRAP_SHORT | WARN |

`quality` = cuenta de positivas (near_level + rejection + divergence), máx 3.

### MTF LOCK explícito (sin reclasificar)

`get_radar_response` cruza el bias del scanner. **No muta `bloque/side/strength/sl`**. Solo flags en `alignment`:
- `mtf_lock_passed: bool|null` (true=aligned, false=conflict, null=neutral/unknown).
- `mtf_lock_failed: bool` (true solo en conflicto claro). Frontend muestra badge rojo "⛔ NO CUMPLE MTF LOCK" + dimea card.
- `reclassified: false` siempre (compat).

Casos: aligned (LONG vs LONG), conflict (LONG vs SHORT), neutral (scanner NEUTRAL → mtf_lock_passed=null), unknown (sin data).

**Por qué**: reclasificar ocultaba info operativa. Mejor mostrar señal completa + razón explícita de rechazo.

### SL caps (pips absolutos)

```python
SL_MAX_PIPS = {"XAUUSD": 40, "EURUSD": 25, "default": 20}
```

Si `distance_pips > cap` → `too_wide=true`, card dimmed con badge "SL EXCEDE", **no cuenta en `total_setups`**.

### RRR

LONG: `risk = price - sl_price`, `reward = resistance - price`. SHORT: simétrico. `MIN_RRR = 2.0`. Sin nivel opuesto → `rrr=None, rrr_below_min=false`.

Frontend: cards con `rrr_below_min=true` se dimean (opacity 0.55), valores tachados, badge naranja `RRR < 2`. Fila TP/RRR bajo SL.

### Semáforo consolidado (`RadarSemaforo`)

5 filtros A+ por setup:

| Filtro | Cumple si... |
|---|---|
| Kill zone activa | sesión actual (Madrid) es `fire` u `ok` |
| MTF LOCK | `alignment.mtf_lock_passed === true` |
| Fuerza STRONG | `strength === "STRONG"` |
| RRR ≥ 2:1 | `sl.rrr >= sl.rrr_min` |
| SL dentro del cap | `sl.too_wide === false` |

Decisión global por **mejor** setup: 5/5 → OPERAR (verde pulsing) · 3-4/5 → ESPERAR (amarillo) · <3/5 → EVITAR (rojo) · `market_closed` → EVITAR override. Chips ✓/· bajo la decisión.

### Mercado cerrado

`_minutes_since_candle_close(ts) > 30` → `market_closed=true`. Frontend: banner 🌙 "Mercado cerrado · última vela hace Xd Yh", empty state distintivo, **pausa `setInterval`** (cero tráfico TD en finde).

### Payload `/api/radar`

```json
{
  "timestamp": "...",
  "active_setups": [/* age ≤ 2, con `candles` */],
  "expired_setups": [/* age=3 ó stale, sin `candles` */],
  "total_setups": N,    // activos sin too_wide
  "strong_setups": N,
  "total_expired": N,
  "market_closed": bool,
  "data_age_minutes": N,
  "last_candle_ts": "ISO"
}
```

Cada setup incluye `sl: {price, distance_pips, cap_pips, too_wide, tp_price, reward_pips, rrr, rrr_below_min, rrr_min}` y `alignment: {status, scanner_bias, scanner_confluence, mtf_lock_passed, mtf_lock_failed, reclassified}`.

### Minigráfico (`radarChart.ts`)

Canvas 2D puro, **sin librerías**. `drawRadarChart(canvas, setup)` — 7 capas: fondo, soporte (verde), resistencia (roja), SL (naranja punteado), 20 velas, triángulo en vela de rechazo, zona TP sombreada (B1/B3). `ResizeObserver`. Labels mínimos 10px mono.

### Watchlist operativa

`WATCHLIST = ["EURUSD"]` solo pinta badge `● Operativo`. **No hay filtro** (toggle "Solo mis pares" eliminado). Scanner y radar comparten `DEFAULT_PAIRS` = 6 majors operativos del usuario (USDJPY, USDCAD, AUDUSD, EURUSD, USDCHF, GBPUSD). Otros pares NO se consultan a Twelve Data — diseñado para caber holgado en el cap 8 req/min del free tier.

## Bridge MT5 (FTMO) — `bridge/`

Proceso **local Windows** (el paquete `MetaTrader5` no funciona en Render/Linux) que ejecuta en el terminal MT5 las decisiones del backend. `python bridge/main.py`. **`DRY_RUN=1` por defecto** — solo registra; ejecución real requiere apagarlo explícitamente y conexión MT5 verificada (aborta si no).

- **Fuentes**: (A) señales del Pine con `decision=ENTER` vía SSE `/signals/stream` + catch-up por id, orden a mercado con SL/TP del motor; (B) marco de Zonas en **OPERAR** (cualquier strength por defecto — ver abajo) vía poll `/api/zones` 5 min (misma semántica de transición+cooldown que las alertas del frontend, y skip si `data_age_minutes>10`). **Whitelist default: solo AUDUSD+USDCAD** (decisión del usuario jul-2026) → en la práctica ejecuta el marco de Zonas; las señales del Pine (EURUSD) se loguean pero no se ejecutan salvo añadir EURUSD a `ALLOWED_SYMBOLS`.
- **Barra de ejecución del marco** (`MARCO_MIN_STRENGTH`, default `normal` desde 16-jul): ejecuta cualquier `OPERAR`; con `fuerte` volvería a exigir solo OPERAR+fuerte. Se bajó de `fuerte`→`normal` porque en 4 días de dry-run el marco nunca llegó a fuerte-ejecutable.
- **Sizing**: riesgo fijo `RISK_PCT` (default 0.5%) del equity contra la distancia del SL, usando tick_value/volume_step reales del broker; si el lote mínimo excede el presupuesto → no opera.
- **Guardas** (`risk.py`, puro y testeado en `test_bridge.py`): kill switch (archivo `bridge/STOP`), máx 2 trades/día, y límites diario $2500/total $5000 evaluados **asumiendo el SL completo del trade nuevo** (nunca coloca una orden cuyo peor caso breachearía FTMO). PnL diario = cuenta completa (realizado desde medianoche Europe/Prague + flotante) — aproximación; el dashboard FTMO manda.
- **Historial en DB**: cada apertura (real o dry-run) se registra en la tabla `bridge_trades` vía `POST /bridge/trades` con el contexto de la señal (score, nivel, sesión, cross) — best-effort, un fallo del POST no frena la operativa. Al cerrar (magic 20260711), el reporter actualiza la fila vía `POST /bridge/trades/{ticket}/close` con WIN/LOSS/BE + exit + PnL real, y si el trade vino del Pine además hace `POST /signals/{id}/result` → base para calibrar el marco con resultados reales.
- **Estado** en `bridge/bridge_state.json` (baseline de ids — nunca ejecuta señales históricas —, cooldowns, contador diario, open_map). Config en `bridge/.env` (ver `bridge/README.md`). **Ventana horaria ELIMINADA desde 16-jul**: `SYMBOL_WINDOWS` default `AUDUSD=0-24,USDCAD=0-24` (sin restricción de sesión — el marco filtra por confluencia, no por hora). Para re-activar una ventana, setear `SYMBOL_WINDOWS` en el entorno (ej: `AUDUSD=9-14,USDCAD=14-21`). El Playbook del frontend sigue mostrando las ventanas históricas 9-14/14-21 como referencia estadística, pero **ya no se hacen cumplir**.

## News warnings (ForexFactory)

Aviso visual, no veto. Banner cuando hay high-impact en ventana.

- Fuente: `https://nfs.faireconomy.media/ff_calendar_thisweek.json` (sin auth).
- Cache 1h en memoria (`news_client._cache`). Si fetch falla, mantiene cache viejo o `[]`.
- Ventana default: 30min antes / 5min después.
- Mapeo: `XAUUSD/XAGUSD → USD`, `EURUSD → EUR+USD`, genérico parte string en 2 códigos 3 letras.
- Estados: `upcoming` (amarillo), `imminent` (rojo pulsante ≤5min), `past` (gris en ventana).
- Desactivar: `NEWS_FILTER_ENABLED=0`.

**Calendario en frontend**: sección colapsable con date picker + hora Madrid (`zoneinfo` + `tzdata`). `tzdata` requerido en `requirements.txt` porque Windows no trae base IANA.

## Sessions + Kill Zones (frontend)

### 4 cards de sesión (tick 1s)

Tokyo, Londres, NY, Madrid. Hora local + ABIERTO/CERRADO + barra de progreso + countdown. Overlap detection (LDN+NYC, ASIA+LDN). Definidas en `SESSIONS[]` (UTC). Helpers: `isSessionOpen()`, `sessionProgress()`, `sessionCountdown()`.

### Kill Zones (hora Madrid, `KILL_ZONES[]`)

| Madrid | Sesión | Status | Acción |
|---|---|---|---|
| 02:00–05:00 | Asia | avoid | No operar |
| 05:00–09:00 | Pre-London | avoid | No operar |
| 09:00–10:30 | London Open | fire | Setup principal |
| 10:30–12:00 | London Cont. | ok | Solo continuación |
| 12:00–14:00 | Pre-NY | warn | Pullbacks (avanzado) |
| 14:00–17:00 | Overlap LDN-NY | fire | **MEJOR VENTANA** |
| 17:00–19:00 | NY Mid | warn | Selectivo |
| 19:00–22:00 | NY Close | avoid | Evitar |

`getMadridHourMin()` usa `Intl.DateTimeFormat('Europe/Madrid')`. Activa con dot animado + tag "AHORA"; inactivas con opacity 0.55. Badge en header del toggle. Colores: fire (naranja), ok (verde), warn (amarillo), avoid (gris).

### Zona chips coloreados (tabla señales)

| Zona | Clase | Color |
|---|---|---|
| `COMPRA YA` | `zona-deep-discount` | Verde intenso + glow |
| `COMPRA` | `zona-discount` | Verde suave |
| `VENDE` | `zona-premium` | Naranja |
| `VENDE YA` | `zona-deep-premium` | Rojo + glow |

`zonaTooltip(zona, side)` genera texto contextual (e.g., `VENDE YA`+LONG → "Premium extremo — NO comprar aquí").

**Decisión**: descartado panel independiente de zonas (redundante con motor + principio "menos indicadores = mejor ejecución").

## Taken vs Rated + Journal — **UI RETIRADA (jul-2026)**

**El usuario ya no marca resultados W/L/BE.** Los botones W/L/BE y el `JournalModal` fueron eliminados de `page.tsx`; la columna Resultado muestra los badges históricos (WIN/LOSS/BE + EJEC/CAL) en señales viejas y "—" en las nuevas. **El backend queda intacto**: `POST /signals/{id}/result`, las columnas `taken`/`journal_*` en la tabla `signals` y los breakdowns de `/stats` siguen funcionando por si el flujo vuelve o se automatiza.

**Implicación**: `scripts/calibrate.py` no recibirá datos nuevos vía journal. La vía realista para calibrar umbrales pasa a ser la **auto-resolución de resultados** (evaluar cada señal contra el OHLC posterior: qué tocó primero, TP o SL — pendiente, no construido). Los KPIs (PnL/WR/ExecRate) y EquityCurve muestran solo el histórico congelado.

Diseño original (referencia si se reactiva): separaba **calidad del sistema** (rated) de **calidad de ejecución** (taken); modal obligatorio al marcar W/L/BE.

- **No, solo calificar** → `taken='no'`. Solo resultado. Mide edge del sistema.
- **Sí, la operé** → `taken='yes'` + obligatorio: ¿Respetaste plan? ¿Cerraste antes TP/SL? Emoción (Confianza/Miedo/FOMO/Venganza).

Botón Guardar deshabilitado hasta completar.

**Stats** (`/stats`): `overall` (legacy, todas closed) · `overall_taken` (PnL real) · `overall_rated` (PnL hipotético) · `execution_rate = len(taken)/len(closed)` · `by_emotion`, `by_respected_plan` (solo taken).

**Lectura pro**: si `rated.WR > taken.WR` → sistema tiene edge, ejecución lo destruye. Si ambas similares y bajas → sistema débil. Si `execution_rate` bajo → indeciso/selectivo.

Tabla señales: badge `EJEC` (verde) o `CAL` (azul) junto al resultado.

## Frontend AppShell de 3 columnas

```
┌──────────────────────────────────────────────────┐
│ Topbar  Brand  [Dashboard|Zonas|Stocks|Correlaciones|Playbook] [⟳ ☼ ⚙]
├─────────┬──────────────────────────┬─────────────┤
│ Sidebar │ Main                     │ RightBar    │
│ 232px   │ flexible                 │ 320px       │
└─────────┴──────────────────────────┴─────────────┘
```

- **`AppShell`**: grid CSS `grid-template-areas`. `body[data-shell="active"]` → `overflow:hidden; height:100vh`, scroll por columna. Responsive: <1024 oculta rightbar, <768 oculta sidebar.
- **`VerdictStrip`** (Fase 3, `components/shell/`): strip global bajo el Topbar (todas las vistas salvo stocks) — una línea por par operado con decisión del marco (OPERAR/ESPERAR/NO OPERAR + side, color por lado), estado del cross (A FAVOR/FADE/⚠ CONFLICTO) y kill zone actual. Responde "qué hago ahora" sin cruzar 3 pantallas. Poll propio a `/api/zones` cada 5min (misma cache backend → 0 créditos extra), pausa con mercado cerrado o pestaña oculta.
- **Dedup Fase 3**: `page.tsx` pasó de 2722 a ~1890 líneas — sessions/kill zones/useTick ahora se importan de `lib/` (antes duplicados línea por línea), RadarView muerto eliminado, `WATCHLIST`/`MY_PAIRS` viven en `lib/config.ts` (fuente única: RightBar A+ ya no sugiere pares que el playbook prohíbe), `EquityCurve` poll 60s (la curva solo cambia al cerrar trades) y conserva la última curva buena ante errores.
- **`Topbar`**: brand + tabs + spacer + session pill + iconos. Tabs: **Dashboard (D)** · Zonas S/R (R) · Análisis de zonas (Z) · Stocks (S) · Correlaciones (C) · Playbook (P) — atajos ignoran si foco en input. La tab Dashboard fue **restaurada** (antes era inalcanzable: el branch else de `page.tsx` con KpiHero/tabla/journal existía pero ningún `setView("dashboard")`). Incluye botón 🔔/🔕 global de **alertas de señal del Pine** (sonido + Notification cuando llega una señal nueva con decision ENTER/WAIT — **ENTER = chime completo ~5s, WAIT = un solo motif ~1s** vía `playChime(ctx, side, repeats)`; detección por ids nuevos vs `seenSignalIdsRef`, baseline al montar sin alertar; estado en `localStorage` `tradingapp:signal_alerts_on`; helpers compartidos en `lib/alerts.ts` — mismos que usa ZonasSRView). Pill usa `useTick(60_000)`. La tab `Radar de setups` sigue removida; `RadarView` fue borrado de `page.tsx` en Fase 3 (recuperable del historial de git). Junto a la tab Playbook hay un enlace externo **"Patrones ↗"** (`<a>` estilizado como tab, color ámbar `.tab-link`) que abre `/patterns.html` en pestaña nueva — NO es un `View` ni tiene atajo de teclado.
- **`Sidebar` (context-aware)**: prop `context: 'forex'|'stocks'`. Las vistas `correlations` y `playbook` también usan `forex`.
  - forex: search + lista de pares (favoritos en `useFavoritePairs`) + calendario mini-list.
  - stocks: `StocksSidebarSection` (search ticker + watchlist con pills BUY/SELL/HOLD).
- **`RightBar` (context-aware)**:
  - forex: Next A+ Setup (countdown overlap LDN-NY) + Active Signals + Próxima ventana (Madrid) + disclaimer.
  - stocks: `MarketHoursCard` (NYSE pre/regular/post/closed + countdown ET) + `StocksActiveSignalsPanel` (top 5 BUY/SELL conf ≥40%) + disclaimer.

**Banners forex ocultos** (NewsAlertBar, NYPreOpenBanner, SessionsPanel, SessionsTimeline, news-banner) en `view === "stocks" | "correlations" | "playbook"`. Solo Dashboard y Zonas los muestran.

### Dashboard view

- **`SessionsTimeline`**: 24h en hora Madrid. `madridOffsetHours()` + `utcToMadrid()` (DST-safe vía `Intl.DateTimeFormat`). Bandas + overlap A+ + now-marker + axis. `projectToMadrid()` para sesiones que cruzan medianoche.
- **`KillZonesTrack`**: barra 14px alineada con timeline. `getKillZonesMadrid()` passthrough.
- **`KpiHero`**: 4 KPIs en mono grandes (PnL, WR, ExecRate, Open Positions).
- **`EquityCurve`**: SVG puro. Serie cumulativa desde `/signals?limit=500` filtrando `result+pnl`. Toggle 1D/7D/30D/ALL. Empty state minimal.

### Lecciones aplicadas (no repetir)

- **Promesas laterales en `load()`**: `Home.load()` crea la promesa `slow` (`/stats`+`/symbols`) antes de esperar el `Promise.all` rápido; si éste lanza (típicamente el `abort()` del siguiente tick sobre un cold start de Render), el `await slow` nunca se alcanza → unhandled rejection y overlay de error en dev apuntando al `abort()`. Fix: `slow?.catch(() => {})` justo tras crearla (marca la rama como manejada; el `await` del try sigue lanzando normal). Patrón a repetir con cualquier promesa creada-pero-aún-no-esperada dentro de un try abortable.
- **Madrid TZ consistency**: helpers `madridHourOf/madridOffsetHours/utcToMadrid` viven en `lib/sessions.ts`. Antes había mezcla UTC/Madrid en distintos componentes.
- **Topbar pill float**: `next.minutesUntil` puede venir float (`48.95`). Usar `Math.floor()` antes de hh/mm.
- **openSignals dedicado**: `Home.load()` hace fetch separado a `/signals?limit=50` (state `openSignals`); RightBar recibe `openCount={stats?.open}` (verdad) + lista (UI). Antes `items.filter(result==null)` paginado a 10 daba contador inconsistente.
- **No exponer webhook URL** en empty states de UI.
- **`activeStockSymbol` lifted a `Home`**: persistencia en `localStorage` (`tradingapp:stocks_last_ticker`). Sidebar y Dashboard son consumidores controlados.

## Identidad visual — Bloomberg moderno

### Tipografía (`next/font/google` en `layout.tsx`)

- Sans UI: **Space Grotesk** (400/500/600/700) → `--font-sans` → `--font-ui`.
- Mono/números: **Space Mono** (400/700) → `--font-mono-prim` → `--font-mono`. Tabular-nums en `.num`/`.mono`.

### Type scale (+30%)

```css
--fs-label: 16px; --fs-body: 18px;  --fs-sub: 21px;
--fs-section: 26px; --fs-kpi: 42px; --fs-hero: 57px;
```

Hero numbers hardcoded: SignalCard 57.2px, KPI 39px, symbol 33.8px (decimales por `*1.3` directo, browsers renderizan sub-pixel).

### Paleta (acento ámbar)

| Token | Antes | Ahora |
|---|---|---|
| `--accent` | `#6366F1` indigo | **`#F59E0B` ámbar** |
| `--warn` | `#F59E0B` ámbar | `#FB923C` naranja |
| `--info` | `#3B82F6` azul | `#38BDF8` cyan |
| `--bg` | `#0A0E14` slate frío | `#0B0D12` slate cálido |

Light theme: ámbar oscuro `#B45309`. Brand mark gradient: `var(--accent) → #EF4444` (sunset trader).

**Por qué**: Inter + JetBrains Mono + slate + indigo es indistinguible de Linear/Cursor/Vercel post-2018. Ámbar evoca terminal Bloomberg, referencia cultural en trading.

## Módulo Stocks

Cuarta pestaña para acciones US (NYSE/NASDAQ) con perfil de inversor. Single-user MVP.

### Flujo

```
Click tab Stocks → ¿Tiene perfil?
   ├─ NO → ProfileWizard (5 steps) → guarda → Dashboard
   └─ SÍ → StocksDashboard
            ├─ ProfileBadge (clickeable → reabre wizard precargado)
            ├─ TickerSearch (debounce 300ms → /stocks/search)
            ├─ SignalCard (decisión BUY/SELL/HOLD + confianza + 3 razones)
            └─ IndicatorBreakdown (tabla votos/pesos)
```

### Backend (`stocks_client.py`)

Comparte API key con scanner forex (mismo `TWELVEDATA_API_KEY` y cap 800/día). Indicadores en Python puro (`_sma`, `_ema_series`, `_rsi_last`, `_macd_hist`, `_bbands`, `_adx`): 1 fetch `/time_series` (1 cr) + 1 `/quote` (1 cr) = 2 cr por bundle vs ~7 si fueran endpoints individuales.

Cache propio (separado del scanner): `_cache: dict[str, tuple[float, dict]]` TTL 5min intraday / 1h diario / 24h `symbol_search`. `clear_cache(prefix)`.

`StocksUpstreamError` tipada (404/429/400/5xx) → `_raise_upstream()` mapea a `HTTPException`.

### Signal engine (`lib/stocks/signalEngine.ts`)

6 votos por bundle (puros, testeables):

```
voteMaShort(price, ma20)    -1/0/+1   margen 0.5%
voteMaLong(price, ma200)    -1/0/+1   margen 1%
voteRsi(rsi14)              -1/0/+1   <30 +1, >70 -1
voteMacd(hist[])            -1/0/+1   cruce o magnitud >0.1
voteBbands(price, up, lo)   -1/0/+1   touch 5% del rango
voteAdx(adx, +DI, -DI)      -1/0/+1   ADX≥25 + |DI diff|≥2
```

Pesos por horizonte (suman 1.0):

```
day_trader: ma_short .10, ma_long .05, rsi .30, macd .30, bbands .15, adx .10
swing:      ma_short .20, ma_long .15, rsi .20, macd .20, bbands .15, adx .10
long_term:  ma_short .05, ma_long .35, rsi .10, macd .15, bbands .10, adx .25
```

`score = Σ(vote × weight)`. `>0.4 → BUY`, `<-0.4 → SELL`, else HOLD. Confianza: `min(|score|,1)` para BUY/SELL, `1-|score|` para HOLD. `topReasons` = top 3 por `|vote × weight|`.

Intervalo recomendado: day=15min, swing=4h, long_term=1day.

### Storage hooks (`profileStorage.ts`, `watchlistStorage.ts`)

Únicas superficies que hablan con `${API}/stocks/profile` y `/stocks/watchlist`. Patrón:

- **Cache-first**: `getCachedX()` lee localStorage instantáneamente.
- **Background fetch**: async sincroniza cache; **fallback a cache si backend falla** (offline-tolerant).
- **Mutaciones optimistas**: cache primero (UI snappy) + async backend; response autoritativo reemplaza optimistic.

**Sync entre instancias del mismo tab**: `window.dispatchEvent(new Event(PROFILE_CHANGE_EVENT))` y `WATCHLIST_CHANGE_EVENT`. `StorageEvent` solo dispara en otros tabs, no same-tab. Cross-tab sync via `StorageEvent` estándar.

`activeStockSymbol` NO va al backend — vive en `Home` con persistencia en `localStorage` (`tradingapp:stocks_last_ticker`).

### Detalles operativos

- **Cuota TD**: ~70 cr/día por sesión típica (~10 tickers). Margen sobre 800.
- **`marketStatus` stale override**: si última vela >24h, frontend fuerza `marketStatus="closed"` (`isStaleData()` en `twelvedata.ts`).
- **NYSE holidays NO modelados** en `marketHours.ts`. Christmas en día hábil aparecerá "abierto" en la card; TD igual devuelve `closed` en el bundle real.
- **`MarketPulse` (DXY/VIX/SPX/US10Y) NO construido** — pendiente futuro.
- **Errores tipados**: `StocksApiError.code = NOT_FOUND|RATE_LIMIT|NETWORK|INVALID|UPSTREAM`. SignalCard traduce. Retry exponencial 1s/2s/4s en 429.
- **Race en mutaciones rápidas**: 2-3 tickers seguidos puede causar parpadeo ~50-100ms. Self-correcting.
- **`clearWatchlist()` solo limpia cache local** — backend no tiene clear-all.

## Correlaciones FX

Quinta pestaña (atajo `C`). Mapa fijo de correlaciones entre los 6 pares operables + chat asistente para preguntas en lenguaje natural. No consume Twelve Data.

### Datos

15 cruces estáticos (≈ media histórica M15-H1) hardcoded en backend (`correlations.py`) y frontend (`lib/correlations.ts`). **Mantener ambos sincronizados**: si cambias un valor, edita los dos archivos.

```
EURUSD ↔ USDCHF: -0.95   (espejo perfecto)
EURUSD ↔ GBPUSD: +0.85
GBPUSD ↔ USDCHF: -0.75
EURUSD ↔ AUDUSD: +0.65
AUDUSD ↔ USDCHF: -0.65
EURUSD ↔ USDJPY/USDCAD: -0.60
GBPUSD ↔ AUDUSD: +0.60
USDCHF ↔ USDJPY: +0.60
GBPUSD ↔ USDJPY: -0.55
USDCHF ↔ USDCAD: +0.55
AUDUSD ↔ USDCAD: -0.55
GBPUSD ↔ USDCAD: -0.50
USDJPY ↔ USDCAD: +0.50
USDJPY ↔ AUDUSD: -0.50
```

### Tiers (`getTier`)

| Tier | Umbral `\|v\|` | Emoji | Uso |
|---|---|---|---|
| extreme | ≥ 0.85 | 🔴 | mismo trade duplicado |
| high | ≥ 0.70 | 🟠 | riesgo elevado |
| moderate | ≥ 0.50 | 🟡 | vigilar |
| low | < 0.50 | ⚪ | independientes |

### Frontend (`components/correlations/CorrelationsView.tsx`)

- Matriz 6×6 color-coded por tier. Diagonal en blanco. Click en celda abre detalle (par, valor, tipo, interpretación). Click en row-header cambia el par activo de la lista lateral.
- Lista per-pair: ordenada por `|correlación|` desc, click → abre detalle.
- Chat box: textarea + Enter para enviar, Shift+Enter newline. Quick prompts en chips. Render del answer en `<pre>` mono respetando los `═══`.
- Sin polling, sin sidebar especial — usa context `forex` (lista de pares + calendario).

### Endpoint AI (`/correlations/query`)

Body `{question: str}`. System prompt con el rol del Correlation Checker (formatos `═══`, regla "solo correlaciones, sin opiniones de mercado", redirige preguntas fuera de scope). Errores: 400 (falta `question`), 503 (sin `OPENROUTER_API_KEY`), 502 (OpenRouter falla).

**Modelo separado del motor forex**: `OPENROUTER_MODEL_CORRELATIONS` (default `claude-haiku-4.5`) → ~4× más barato que sonnet-4 que usa `ai_client.py`. Si la env var no está, cae a `OPENROUTER_MODEL`.

### Gotchas

- **Headers ASCII-only**: urllib codifica headers en latin-1. El header `X-Title` no puede llevar em-dash (`—`) ni acentos — usar guión normal.
- **`os.getenv` evaluado al import**: cambiar la env var en runtime no refresca el modelo. Reinicia el proceso.

## Playbook

Sexta pestaña (atajo `P`). Guía operativa estática AUDUSD + USDCAD. Sin polling, sin APIs, sin estado — pura información renderizada como hoja de reglas imprimible.

### Contenido

- **Quick cards**: AUDUSD ventana mañana (09–14h Madrid, 9/9 wins +$615) · USDCAD ventana tarde (14–21h Madrid, 8/8 wins +$679).
- **Timeline visual** 13 celdas (09–21h Madrid arriba, 03–15h NY abajo) coloreadas por par habilitado: AUD verde, CAD cyan, cruce (14h) gradient, lunch NY (18h) gris.
- **Hour blocks**: 6 franjas detalladas con `Sí operar` / `No operar` / `PROHIBIDO` por par + contexto explicativo (rotación de flujo, sesiones, históricos).
- **Resumen por par + reglas globales**: SÍ/NO/NUNCA en cards verde/rojo. Reglas globales (no mover SL, máx 2 trades/día, no tras pérdida, etc).

### Implementación

- `frontend/components/playbook/PlaybookView.tsx` + `.css` — namespace `.playbook` con prefijo `.pb-*`.
- Adapta a tokens del app via aliases CSS: `--pb-aud=--buy`, `--pb-cad=--info`, `--pb-no=--sell`, `--pb-warn=--warn`. Funciona en dark/light.
- Tipografía aumentada ~30% vs resto del app (hero 44px, h2 30px, body 17px) — es una página de lectura, no de monitoreo.
- Botón `Imprimir / PDF` llama `window.print()`. Media query `@media print` oculta `.pb-no-print` y desactiva hovers.

### Cuándo editarla

El contenido es snapshot de las estadísticas del usuario al momento de creación (mayo 2026). Si cambian las reglas operativas (ventanas, pares operados, P&L histórico, prohibiciones), actualizar `PlaybookView.tsx` directamente — no hay backend ni config externo.

## Patrones (referencia estática)

`frontend/public/patterns.html` — hoja de referencia de 28 patrones (Estructura SMC, figuras chartistas, velas) con minigráficos SVG inline puros (sin librerías) y, por cada patrón, `NO entrar` / `Entrada válida` / `Invalidación`. **No es parte del app React**: es HTML+CSS+JS standalone servido por Next desde `public/` en `/patterns.html`. Se abre con el enlace "Patrones ↗" del Topbar (pestaña nueva).

- **Agrupación conmutable** (control segmentado en la toolbar): **Por sesgo** (default) → 3 bloques 🟢 Alcista / 🔴 Bajista / ⏳ Sin decisión·esperar · **Por metodología** → grupos originales (SMC / figuras / velas).
- El sesgo de cada card lo deriva el JS del `.bias-tag:not(.rel-tag)` ya presente en el markup (`bias-bull`→bull, `bias-bear`→bear, `bias-neutral`/`bias-warn`→wait). El regrupado mueve nodos DOM (no clona); iterar en orden de documento preserva el orden dentro de cada bloque.
- Buscador por nombre (`data-name`) funciona en ambos modos; los grupos vacíos se ocultan solos vía `applyFilter`.
- Para editar patrones: cada uno es un `<article class="card">` con `data-name`, un `bias-tag` (define a qué bloque cae), un `<svg>` y el `<dl>` de info. Para añadir uno nuevo basta con seguir ese molde — el JS lo recoge automáticamente.

## Polling y créditos Twelve Data

- Frontend scanner: 5min. TTL backend 15min → 2 de 3 polls = cache hit (0 cr). Radar ya no se consulta desde la UI; `/api/radar` sigue accesible pero sin tráfico orgánico.
- **Fase 3**: `td_client` es el gate único (token-bucket 7/min con margen bajo el cap 8, single-flight, contador de créditos en `/scanner/debug`); el cache OHLC persiste en DB (`ohlc_cache`) → cold start rehidrata sin fetches. Polling del dashboard estratificado: `/signals`+`/news/warnings` cada 5s, `/stats`+`/symbols` cada ~60s, todo pausado con la pestaña oculta (`visibilitychange`); SSE `/signals/stream` dispara load inmediato al llegar señal. `VerdictStrip` (strip global) consume `/api/zones` cada 5min con los pares default → misma cache que la vista Zonas S/R, 0 créditos extra.
- **Veredicto cruzado**: el cruce añade ~+2 fetches TD por pantalla y ciclo (M15 al abrir el scanner para AUDUSD/USDCAD, M5 al abrir Zonas S/R) — solo los 2 pares de `CROSS_PAIRS`. Holgado bajo el cap 8 req/min. El cruce reutiliza cachés compartidas, así que abrir ambas vistas no duplica fetches dentro del TTL.
- `market_closed` pausa `setInterval` (cero tráfico finde).
- `/health`, `/signals`, `/stats`, `/news/*`, webhook **NO consumen TD**.
- **Backend NO tiene cron propio** — 100% reactivo. Si créditos suben sin nadie usando: (1) pinger mal configurado, (2) otra sesión abierta, (3) bot en URL pública. Verificar en Render Logs.

## Convenciones del usuario

- **Idioma**: español. Toda salida visible en español.
- **Estilo de código**: directo, sin comentarios obvios, sin abstracciones especulativas.
- **Stack**: Windows 11, PowerShell. `curl` es alias de `Invoke-WebRequest` → usar `curl.exe` o `Invoke-RestMethod`.
- **`localhost` vs `127.0.0.1`**: en Windows, `localhost` resolvía a IPv6 y uvicorn solo IPv4 → usar `127.0.0.1` o `--host 0.0.0.0`.
- **Horario**: opera en hora Madrid. Toda UI muestra Madrid o ET según contexto del mercado.
- **Dirección visual**: NO preset "AI-built dashboard" (Inter+slate+indigo). Identidad: Space Grotesk + Space Mono + ámbar `#F59E0B`. Body 18px, hero 40-57px.
- **Single-user**: cero auth. `investor_profile` singleton id=1. Multi-user requiere migrar a `user_id`.

## Calibración offline (`backend/scripts/calibrate.py`)

Cruza la tabla `signals` (Supabase o SQLite) con resultados reales: WR/PnL por decisión, score, quality, conf-bucket, zona-vs-lado, MTF-vs-lado, patrón, vol, FVG y hora Madrid, con intervalo de Wilson para n pequeño + **sweep de umbral ENTER** (qué threshold de score habría maximizado expectancy). Los umbrales 7/4 del motor son provisionales hasta que este script diga otra cosa con ≥50 cierres.

```bash
cd backend
.venv\Scripts\python.exe -m scripts.calibrate            # todo
.venv\Scripts\python.exe -m scripts.calibrate --taken    # solo operadas
```

Ojo: los scores históricos previos al fix del double-counting eran ~1-2 pts más altos — comparar cohortes de la misma época del motor.

## Cómo se levanta

### Producción
- Backend: Render auto-deploy en push a `main`.
- Frontend: local (`npm run dev`) → Render via `.env.local`.
- DB: Supabase persistente.
- Webhook TV: `https://tradingapp-2glz.onrender.com/webhook/tradingview`.

### Dev local
```bash
# Backend (SQLite si sin DATABASE_URL)
cd backend; .venv\Scripts\activate; uvicorn app.main:app --reload

# Frontend (editar .env.local para apuntar a localhost)
cd frontend; npm run dev   # next dev -p 3001

# ngrok si quieres webhook TV en local
ngrok.exe http 8000
```

Frontend http://localhost:3001 · Docs API http://127.0.0.1:8000/docs.

**Lanzador 1-clic**: `Iniciar App.cmd` en la raíz (+ acceso directo "Trading App" en el Escritorio). Verifica/instala deps, corre `npm run dev` (frontend → Render) y abre el navegador en `http://localhost:3002` cuando el server responde. Para el flujo normal del usuario (frontend local contra backend en Render) no hace falta levantar backend ni tocar `.env.local`.

## Próximos pasos posibles (no hechos)

**Forex**: notificaciones Telegram en ENTER · calculadora tamaño posición · daily loss limit + cooldown · backtest sobre histórico Supabase · stats por journal (emociones, plan respetado). ~~R:R floor como veto~~, ~~kill zone en el motor~~ y ~~heatmap hora-vs-PnL~~ (tabla "Por hora Madrid" en `scripts/calibrate.py`) hechos en Fase 2 (jul-2026).

**Stocks**: `MarketPulse` (DXY/VIX/SPX/US10Y) · NYSE holidays en `marketHours.ts` · `DELETE /stocks/watchlist` clear-all · loading/error UI states · stocks signals tracking + journal análogo a forex.

**Operativo**: migrar frontend a Vercel · auth multi-user (migrar `investor_profile` de singleton a `user_id`).

## Gotchas conocidos

- **PowerShell + curl**: ver convenciones.
- **`localhost` vs `127.0.0.1`**: ver convenciones.
- **Render free spin-down**: 15min inactividad → cold start ~30-50s. Mitigar con UptimeRobot/cron-job.org pinging `/health` cada 5min. **CRÍTICO**: pinger debe apuntar a `/health` (gratis) — NUNCA a `/scanner/pairs` o `/api/radar` (~11 cr × 288 pings = 3168 cr/día, muy sobre cap 800).
- **Créditos TD**: backend 100% reactivo. Solo `/scanner/pairs` y `/api/radar` consumen. Si suben sin uso: pinger / sesión abierta / bot.
- **Cold start borra cache**: tras spin-down arranca vacío. Pinger `/health` evita.
- **"Sin datos disponibles" en Zonas S/R**: NO es backend caído ni créditos diarios agotados — casi siempre es el cap **8 req/min** de TD (free). Un 429 hace que `_fetch_chart`→`None`→`analyze_zones`→`None`; si fallan todos los pares, `/api/zones` sale con `items: []` y el frontend muestra el mensaje. Es transitorio (se limpia al minuto). Se agrava cuando el burst supera 8/min (Dashboard poleando 6 majors + abrir Zonas + cold-start). Diagnóstico: `/scanner/debug` → `last_error` muestra el 429 real. Fix aplicado: `get_zones_response` ya no cachea el vacío (antes lo congelaba 15 min).
- **Supabase password con `@`/`#`/`:`**: rompe parsing de `DATABASE_URL`. Resetear con solo letras/números.
- **Supabase Direct Connection no funciona en Render** (IPv4 only). Usar **Transaction pooler** (port 6543, user `postgres.PROJECT_REF`).
- **`zoneinfo` en Windows**: requiere `tzdata` (en `requirements.txt`).
- **`/webhook/tradingview` no aparece en `/docs`** con schema body (usa `Request` crudo para texto legacy). Probar desde `/docs` con `/analyze`.
- **`.env.local` apunta a Render**: si backend local tiene código nuevo, frontend no lo ve hasta push o cambiar `NEXT_PUBLIC_API_URL` a `http://127.0.0.1:8000`.
- **Stocks endpoints local sin `TWELVEDATA_API_KEY`**: `/stocks/quote` y `/stocks/indicators` devuelven 502. Copiar key de Render Dashboard a `backend/.env`.
- **Stocks profile/watchlist en cache local cuando backend caído**: `profileStorage.ts`/`watchlistStorage.ts` fallback a localStorage. App sigue en "modo local". Watch `console.warn`.
- **Race en mutaciones rápidas stocks**: parpadeo ~50-100ms self-correcting. Si molesta, sumar sequence numbers o queue.
- **NYSE holidays NO modelados** en `marketHours.ts`. TD igual devuelve `closed` en el bundle real.
