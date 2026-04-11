# AI Trading Assistant

Motor de decisión contextual para señales de TradingView. **No genera señales** —
recibe las que dispara tu Pine script (`SMS Pro XAUUSD v8.9.1` / `SMS Pro EURUSD v8.10.1`)
y decide **ENTER / WAIT / AVOID** según calidad, contexto y timing.

Después permite marcar el resultado real de cada trade (WIN/LOSS/BE) para medir
win-rate por símbolo, calidad, decisión y fuente (heurística vs IA).

---

## Arquitectura

```
TradingView (Pine)
    │  alerta dispara → JSON
    ▼
Render (backend público, URL fija)
    │
    ▼
FastAPI backend  ──→  Supabase PostgreSQL (nube)
    │  ▲                    ó SQLite (dev local)
    │  └─── (opcional) OpenRouter LLM refina la decisión
    ▼
Next.js frontend (dashboard + tracking)
```

- **`backend/`** — FastAPI, motor de decisión, persistencia dual (PostgreSQL en prod / SQLite en dev), endpoint webhook.
- **`frontend/`** — Next.js, dashboard con tabla, tabs por símbolo, stats agregadas, botones W/L/BE.
- **`scriptsTradingView/`** — Pine scripts modificados para emitir JSON al webhook.

### Modos de ejecución

| Modo | DB | Webhook URL | Cuándo usarlo |
|---|---|---|---|
| **Producción** | Supabase PostgreSQL (via `DATABASE_URL`) | `https://tu-servicio.onrender.com/webhook/tradingview` | Trading real, señales 24/7 |
| **Local** | SQLite (`backend/signals.db`) | `http://127.0.0.1:8000/webhook/tradingview` (vía ngrok si necesitas TradingView) | Desarrollo y pruebas |

---

## Requisitos

### Para desarrollo local
- Python 3.11+
- Node.js 18+

### Para producción (cloud)
- Cuenta en [Render](https://render.com) (free tier)
- Cuenta en [Supabase](https://supabase.com) (free tier)
- Cuenta de TradingView con plan que permita alertas con webhook (Pro+)

---

## Opción 1: Deploy en producción (Render + Supabase)

### 1) Configurar Supabase

1. Crea un proyecto en [Supabase](https://supabase.com/dashboard) (plan Free, compute Micro).
2. Ve a **SQL Editor** y ejecuta el contenido de `backend/supabase_init.sql`.
3. Ve a **Connect** → **Transaction pooler** → copia el connection string:
   ```
   postgresql://postgres.XXXX:[PASSWORD]@aws-0-REGION.pooler.supabase.com:6543/postgres
   ```

### 2) Deploy en Render

1. Sube el repo a GitHub.
2. En [Render](https://dashboard.render.com) → **New +** → **Web Service** → conecta el repo.
3. Configura:
   - **Root Directory**: `backend`
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free
4. En **Environment Variables** agrega:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | Tu connection string de Supabase (transaction pooler) |
   | `PYTHON_VERSION` | `3.11.9` |
   | `USE_AI` | `0` (o `1` para activar IA) |
   | `OPENROUTER_API_KEY` | Tu key de OpenRouter (solo si `USE_AI=1`) |
   | `OPENROUTER_MODEL` | `anthropic/claude-sonnet-4` |

5. Click **Create Web Service** → espera ~2-3 min.
6. Verifica: `https://tu-servicio.onrender.com/health` → `{"ok": true}`

### 3) Conectar TradingView

1. Edita cada alerta → **Notifications** → **Webhook URL**:
   ```
   https://tu-servicio.onrender.com/webhook/tradingview
   ```

### 4) Frontend local apuntando a producción

Crea `frontend/.env.local`:
```
NEXT_PUBLIC_API_URL=https://tu-servicio.onrender.com
```

### 5) Anti cold-start (recomendado)

Render free apaga el servicio tras 15 min de inactividad. Para evitar que TradingView reciba timeout:

1. Crea cuenta gratis en [UptimeRobot](https://uptimerobot.com) o [cron-job.org](https://cron-job.org).
2. Configura un monitor HTTP que haga GET a `https://tu-servicio.onrender.com/health` cada 5 minutos.

---

## Opción 2: Setup local (desarrollo / pruebas)

### 1) Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate              # Windows
# source .venv/bin/activate         # macOS/Linux
pip install -r requirements.txt
```

(opcional) Crea `backend/.env` copiando `backend/.env.example`:

```
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=anthropic/claude-sonnet-4
USE_AI=1
```

Sin `DATABASE_URL`, usa SQLite automáticamente. Sin `OPENROUTER_API_KEY`, usa heurística pura.

### 2) Frontend

```bash
cd frontend
npm install
```

### 3) Levantar (2 terminales)

**Terminal 1 — Backend:**
```bash
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload
```
Verifica: http://127.0.0.1:8000/health → `{"ok":true}`

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```
Abre: http://localhost:3000

### 4) ngrok (solo si necesitas webhook de TradingView en local)

```bash
ngrok.exe http 8000
```

> La URL cambia cada vez que reinicias ngrok en el plan free.

---

## Conectar TradingView

1. Aplica el script Pine modificado (`SMS_XAUUSD_v8_9_1.pine` o `SMS_EURUSD_v8_10_1.pine`) al chart.
2. **Create Alert** (`Alt+A`).
3. **Condition**: selecciona el indicador → **`Any alert() function call`**.
4. **Notifications** → **Webhook URL** → pega tu URL:
   - Producción: `https://tu-servicio.onrender.com/webhook/tradingview`
   - Local: `https://TU-URL-NGROK.ngrok-free.dev/webhook/tradingview`
5. **Create**.

---

## Probar sin TradingView

### Desde `/docs`

1. Abre `https://tu-servicio.onrender.com/docs` (o `http://127.0.0.1:8000/docs` en local)
2. Expande **`POST /analyze`** → **Try it out** → pega:

```json
{
  "signal": "SHORT",
  "symbol": "EURUSD",
  "price": 1.16681,
  "sl": 1.16798,
  "be": 1.16564,
  "tp": 1.16447,
  "conf": 15,
  "quality": "PREMIUM",
  "pattern": "BAJA DESDE AQUI",
  "fvg": true,
  "vol_high": true,
  "vol_ratio": 2.1,
  "rsi": 62,
  "mtf": "BEAR",
  "zona": "VENDE"
}
```

3. **Execute** → debe devolver `decision: ENTER` y aparecer en el dashboard.

### Desde PowerShell

```powershell
$body = @{
  signal="SHORT"; symbol="EURUSD"; price=1.16681
  sl=1.16798; be=1.16564; tp=1.16447
  conf=15; quality="PREMIUM"; pattern="BAJA DESDE AQUI"
  fvg=$true; vol_high=$true; vol_ratio=2.1
  rsi=62; mtf="BEAR"; zona="VENDE"
} | ConvertTo-Json

Invoke-RestMethod -Uri "https://tu-servicio.onrender.com/webhook/tradingview" -Method POST -ContentType "application/json" -Body $body
```

---

## Cómo se usa el dashboard

1. Cuando llega una señal, aparece automáticamente en la tabla (auto-refresh 5s).
2. **Tabs arriba** filtran por símbolo (`TODOS / XAUUSD / EURUSD`).
3. La columna **Decisión** marca:
   - **ENTER** — setup alineado, R:R favorable. Operar.
   - **WAIT** — contexto aceptable pero falta confirmación.
   - **AVOID** — setup débil, extendido o contraproducente.
4. Cuando cierres el trade en tu broker, marca el resultado con los botones:
   - **W** (verde) → WIN
   - **L** (rojo) → LOSS
   - **BE** (amarillo) → break-even
5. Las **stats** se actualizan en vivo: win rate global, PnL acumulado,
   y desgloses por símbolo/decisión/fuente/calidad.

---

## News warnings (calendario económico)

El backend **no bloquea** señales por noticias, pero muestra un **banner de aviso** en el dashboard cuando hay una noticia **high-impact** próxima o recién publicada. Fuente: [ForexFactory](https://www.forexfactory.com/) (feed JSON gratis), cacheado 1h en memoria.

**Mapeo símbolo → monedas** (para el endpoint `/news` y `/news/warnings?currencies=...`):
- `XAUUSD`, `XAGUSD` → USD (oro/plata cotizan en USD)
- `EURUSD` → EUR, USD
- `GBPUSD` → GBP, USD
- Genérico: códigos de 3 letras del símbolo

**Ventana por defecto**: banner visible desde 30 min antes del evento hasta 5 min después. Configurable vía:

```
NEWS_FILTER_ENABLED=1        # 0 para ocultar todos los avisos
NEWS_WINDOW_BEFORE_MIN=30
NEWS_WINDOW_AFTER_MIN=5
```

**Estados del banner**:
- `upcoming` — más de 5 min antes del evento (amarillo)
- `imminent` — faltan ≤5 min o está ocurriendo ahora (rojo, pulsante)
- `past` — ya pasó pero sigue en la ventana de después (gris tenue)

**Endpoints**:
- `GET /news/warnings` — avisos activos ahora (los que el frontend muestra). Query opcional: `?currencies=USD,EUR`
- `GET /news/calendar?date=2026-04-10&impact=high` — eventos de un día específico, horas en hora Madrid
- `GET /news?symbol=XAUUSD&hours=24` — próximas noticias high-impact para un símbolo

El dashboard tiene una **sección colapsable "📅 Calendario económico"** con date picker que permite consultar cualquier día con las horas en hora Madrid.

---

## Kill zones (hora Madrid)

El scalping XAUUSD/EURUSD es rentable casi exclusivamente dentro de las ventanas de máxima liquidez. Fuera de estas horas, el spread sube y los movimientos son ruido. Madrid está **+1h respecto a London** (ambas siguen DST europeo simultáneamente) y **+6h respecto a NY**.

| Kill zone | Hora Madrid | Hora London | Hora NY | Por qué importa |
|---|---|---|---|---|
| **London open** | 08:00 – 11:00 | 07:00 – 10:00 | 02:00 – 05:00 | Primera expansión del día, activa stops de Asia |
| **NY AM (golden hour)** | 14:30 – 17:00 | 13:30 – 16:00 | 08:30 – 11:00 | Overlap London/NY, máxima liquidez del día |
| **NY PM** | 20:00 – 22:00 | 19:00 – 21:00 | 14:00 – 16:00 | Último push del día, cierre NY |

> **Evitar**: 22:00 – 08:00 Madrid (Asia/rollover). Spreads altos, movimientos erráticos. Toda señal que llegue fuera de kill zones se degrada automáticamente a WAIT (pendiente de implementar como veto duro).

---

## Lógica del motor de decisión

**Vetos duros (→ AVOID):**

- LONG en zona `VENDE YA` o MTF30 BEAR o RSI ≥ 78 o resistencia inmediata
- SHORT en zona `COMPRA YA` o MTF30 BULL o RSI ≤ 22 o soporte inmediato
- Conf < 5 o congestión entre order blocks

**Score (después de pasar los vetos):**

| Factor | Puntos |
|---|---|
| Quality PREMIUM / STRONG / NORMAL | +4 / +3 / +1 |
| MTF30 alineado con la señal | +2 |
| Zona favorable (`COMPRA*` para LONG, `VENDE*` para SHORT) | +2 |
| Patrón activo en dirección | +1 |
| Volumen alto confirmando | +1 |
| FVG activo en dirección | +1 |
| Conf ≥ 14 / ≥ 10 | +2 / +1 |

**Mapeo final:**
- score ≥ 8 → **ENTER**
- score ≥ 5 → **WAIT**
- score < 5 → **AVOID**

---

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Healthcheck |
| `POST` | `/analyze?ai=1` | Evalúa una señal estructurada (Pydantic) |
| `POST` | `/webhook/tradingview?ai=1` | Webhook para TradingView (JSON o texto) |
| `GET` | `/signals?limit=100&symbol=XAUUSD` | Lista señales (filtrable) |
| `GET` | `/symbols` | Símbolos únicos vistos |
| `POST` | `/signals/{id}/result` | Marca resultado: `{"result":"WIN\|LOSS\|BE","exit_price":opc}` |
| `GET` | `/stats` | Métricas agregadas (overall + breakdowns) |

---

## Estructura del proyecto

```
tradingApp/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI: rutas
│   │   ├── schemas.py         # Pydantic: TVSignal, AnalyzeResponse
│   │   ├── decision_engine.py # Vetos + scoring → decisión
│   │   ├── entry_planner.py   # Plan operativo (pullback, retest, sweep...)
│   │   ├── tv_parser.py       # Parser tolerante (JSON o texto)
│   │   ├── ai_client.py       # OpenRouter (opcional)
│   │   └── storage.py         # Dual: PostgreSQL (Supabase) o SQLite (local)
│   ├── requirements.txt
│   ├── render.yaml            # Config de deploy para Render
│   ├── supabase_init.sql      # SQL para crear tabla en Supabase
│   ├── .env.example
│   └── signals.db             # solo en modo local (se crea solo)
├── frontend/
│   ├── app/
│   │   ├── page.tsx           # Dashboard
│   │   ├── layout.tsx
│   │   └── globals.css
│   ├── package.json
│   └── next.config.mjs
├── scriptsTradingView/
│   ├── SMS_XAUUSD_v8_9_1.pine
│   └── SMS_EURUSD_v8_10_1.pine
└── README.md
```

---

## Troubleshooting

**`/docs` da 404 pero `/stats` funciona**
→ Estás usando `localhost` y se resuelve a IPv6. Usa `http://127.0.0.1:8000/docs`
o arranca uvicorn con `--host 0.0.0.0`.

**`curl` falla en PowerShell**
→ PowerShell tiene `curl` como alias de `Invoke-WebRequest`. Usa `curl.exe` o
`Invoke-RestMethod` (ver sección de pruebas).

**TradingView no llega al backend (producción)**
→ Verifica que el servicio en Render esté activo (no dormido). Abre `/health` en el navegador.

**TradingView no llega al backend (local)**
→ Verifica en http://127.0.0.1:4040 si el request está llegando a ngrok.

**La señal aparece pero todo dice AVOID**
→ Es la decisión correcta del motor: faltan confluencias o hay un veto duro
(ver columna "Razón"). No es un bug.

**Render tarda en responder la primera vez**
→ El free tier apaga el servicio tras 15 min de inactividad. El primer request tras
el apagado tarda ~30-50s (cold start). Configura un ping externo para evitarlo
(ver sección Anti cold-start).

---

## Costos

| Servicio | Plan | Costo |
|---|---|---|
| Supabase | Free (Micro compute, 500MB DB) | $0/mes |
| Render | Free (se apaga tras 15min inactivo) | $0/mes |
| UptimeRobot | Free (para anti cold-start) | $0/mes |
| **Total** | | **$0/mes** |

---

## Próximos pasos posibles

- Notificaciones a Telegram cuando llega un ENTER.
- Calculadora de tamaño de posición integrada (capital + % riesgo → lotes).
- Filtros por hora del día / kill zone.
- Gráfico de equity curve.
- Backtest del motor sobre el historial acumulado.
