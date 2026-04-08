# CLAUDE.md

Contexto operativo del proyecto para futuras sesiones de Claude Code.

## Qué es esto

**AI Trading Assistant**: motor de decisión contextual sobre señales de TradingView para scalp intradía (0–15 min) en XAUUSD y EURUSD.

**No genera señales** — recibe las que dispara un Pine script propio del usuario y decide **ENTER / WAIT / AVOID** según calidad, contexto y timing. Cuando una señal está fuerte pero el precio está extendido, **degrada a WAIT y emite un plan operativo concreto** (zona de espera, precio trigger, invalidación, instrucciones) para evitar entradas tardías — ese fue el dolor original del usuario: entraba en la vela explosiva y perdía.

## Stack

- **Backend**: FastAPI + SQLite (`backend/`). Python 3.11+.
- **Frontend**: Next.js 14 App Router + TypeScript (`frontend/`). Local, conectado a `http://127.0.0.1:8000`.
- **Pine scripts**: `scriptsTradingView/SMS_XAUUSD_v8_9_1.pine` y `SMS_EURUSD_v8_10_1.pine` (modificados para emitir JSON al webhook).
- **Túnel público**: ngrok free (URL cambia en cada reinicio). Hay una tarea pendiente de migrar a Render + Supabase.
- **IA opcional**: OpenRouter (Claude/cualquier modelo) refina la decisión heurística si `USE_AI=1` y `OPENROUTER_API_KEY` están en `backend/.env`. Sin API key, motor heurístico puro.

## Arquitectura del flujo

```
TradingView (Pine) ─alert()→ ngrok ─POST→ FastAPI ─→ SQLite
                                          │
                                          ├─→ decision_engine (vetos + score)
                                          ├─→ entry_planner (plan operativo)
                                          └─→ ai_client (OpenRouter, opcional)

Frontend Next.js ←─polling 5s── /signals, /stats, /symbols
                  ──POST W/L/BE──→ /signals/{id}/result
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
│   │   └── storage.py          # SQLite + stats agregadas + tracking de resultados
│   ├── requirements.txt
│   ├── .env.example
│   └── signals.db              # se crea en startup
├── frontend/
│   └── app/
│       ├── page.tsx            # Dashboard con tabs por símbolo, stats, plan visible
│       ├── layout.tsx
│       └── globals.css
├── scriptsTradingView/
│   ├── SMS_XAUUSD_v8_9_1.pine  # alert() emite JSON con todos los campos
│   └── SMS_EURUSD_v8_10_1.pine # idem (5 decimales)
├── README.md                   # Guía de usuario para levantar todo
└── CLAUDE.md                   # Este archivo
```

## Lógica del motor de decisión

### Vetos duros (→ AVOID inmediato)

- LONG en zona `VENDE YA`, MTF30 BEAR, RSI ≥ 78, overhead/resistencia inmediata.
- SHORT en zona `COMPRA YA`, MTF30 BULL, RSI ≤ 22, soporte inmediato.
- `conf < 5`, `congestion = true`.

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
| POST | `/signals/{id}/result` | Body `{result, exit_price?}` — marca WIN/LOSS/BE y calcula PnL |
| GET | `/stats` | Agregados: overall + by_symbol/decision/source/quality/side/zona/mtf/pattern |

`?ai=1` activa el refinamiento OpenRouter (si está configurado). El motor heurístico siempre corre primero; si la IA falla, cae a heurística.

## SQLite — tabla `signals`

```sql
id INTEGER PK
received_at TEXT
signal_json TEXT      -- JSON completo de TVSignal
response_json TEXT    -- JSON completo de AnalyzeResponse (incluye plan)
decision TEXT         -- ENTER | WAIT | AVOID
symbol TEXT
side TEXT             -- LONG | SHORT
result TEXT           -- WIN | LOSS | BE | NULL
exit_price REAL
pnl REAL
closed_at TEXT
source TEXT           -- heuristic | ai
```

Migración automática con `_ensure_column` idempotente en `init_db()` — al añadir columnas nuevas en el futuro, no rompe DBs viejas.

## Convenciones del usuario

- **Idioma**: español. Toda salida visible (instrucciones del planner, razones, UI) en español.
- **Estilo de código**: directo, sin comentarios obvios, sin abstracciones especulativas. Ya hay una decisión validada de evitar over-engineering.
- **Stack del usuario**: Windows 11, PowerShell. **Cuidado con `curl`** en PowerShell — es alias de `Invoke-WebRequest`. Usar `curl.exe` o `Invoke-RestMethod` con `@{}` y `ConvertTo-Json`.
- **`localhost` vs `127.0.0.1`**: en su Windows, `localhost` resolvía a IPv6 y uvicorn solo escucha IPv4 por defecto → usar `127.0.0.1` o arrancar uvicorn con `--host 0.0.0.0`.

## Cómo se levanta (3 terminales)

```bash
# 1) Backend
cd backend && .venv\Scripts\activate && uvicorn app.main:app --reload

# 2) Frontend
cd frontend && npm run dev

# 3) ngrok (URL pública para TradingView)
ngrok.exe http 8000
```

Frontend: http://localhost:3000 · Docs API: http://127.0.0.1:8000/docs · Inspector ngrok: http://127.0.0.1:4040

## Cómo se conecta TradingView

1. Aplicar el Pine modificado al chart (XAU o EUR).
2. Crear alerta → Condition = indicador + **`Any alert() function call`** (crítico, hace que TV mande exactamente el JSON del `alert()`).
3. Notifications → Webhook URL = `https://TU-NGROK.ngrok-free.dev/webhook/tradingview`.
4. Message vacío. Trigger lo controla el Pine internamente con `alert.freq_once_per_bar_close`.

## Estado actual / decisiones tomadas

- **DB**: SQLite local. Decisión consciente del usuario para empezar; migración a Supabase Postgres pendiente.
- **Hosting**: todo local + ngrok. Decisión consciente; deploy a Render pendiente.
- **IA OpenRouter**: implementada pero opcional, off por defecto hasta que el usuario quiera probarla.
- **Tracking de resultados**: ya implementado (botones W/L/BE en cada fila + breakdowns en stats).
- **Multi-símbolo**: ya soportado (tabs en frontend, breakdown by_symbol en stats, filtros en /signals).
- **Entry planner**: ya implementado, funciona si el Pine envía los campos contextuales (`ema9`, `atr`, etc.).

## Próximos pasos posibles (mencionados, no hechos)

- Migrar SQLite → Supabase Postgres.
- Deploy backend en Render (eliminar dependencia de ngrok y de PC encendido).
- Notificaciones a Telegram cuando llega ENTER.
- Calculadora de tamaño de posición integrada (capital + % riesgo → lotes).
- Filtros por hora / kill zone configurables.
- Equity curve en frontend.
- Backtest del motor sobre el historial acumulado.

## Gotchas conocidos

- **PowerShell + curl**: ver convenciones arriba.
- **`localhost` vs `127.0.0.1`**: ver convenciones arriba.
- **ngrok free**: URL cambia en cada reinicio → hay que actualizar las alertas de TradingView.
- **PC en suspensión**: ngrok cae, uvicorn pausa, TradingView pierde señales sin retry. Recomendar configuración de energía "nunca suspender" mientras esté en uso.
- **SQLite + redeploys**: si algún día se mueve a Render free, el disco es efímero — la DB se pierde en cada reinicio. Es la razón de la migración pendiente a Supabase.
- **`/webhook/tradingview` no aparece en `/docs`** con schema de body: usa `Request` crudo (para aceptar también texto legacy). Para probar desde `/docs`, usar `/analyze` que sí tiene schema Pydantic.
