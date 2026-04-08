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
ngrok (túnel público)
    │
    ▼
FastAPI backend  ──→  SQLite (signals.db)
    │  ▲
    │  └─── (opcional) OpenRouter LLM refina la decisión
    ▼
Next.js frontend (dashboard + tracking)
```

- **`backend/`** — FastAPI, motor de decisión, persistencia SQLite, endpoint webhook.
- **`frontend/`** — Next.js, dashboard con tabla, tabs por símbolo, stats agregadas, botones W/L/BE.
- **`scriptsTradingView/`** — Pine scripts modificados para emitir JSON al webhook.

---

## Requisitos

- Python 3.11+
- Node.js 18+
- ngrok (cuenta gratis: https://ngrok.com)
- Cuenta de TradingView con plan que permita alertas con webhook (Pro+)

---

## Setup inicial (solo la primera vez)

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
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
USE_AI=1
```

Sin estas variables, el motor funciona en modo heurística pura (sin IA).

### 2) Frontend

```bash
cd frontend
npm install
```

(opcional) Si quieres apuntar el frontend a un backend remoto, crea `frontend/.env.local`:

```
NEXT_PUBLIC_API_URL=https://tu-backend.com
```

Por defecto usa `http://localhost:8000`.

### 3) ngrok

1. Descarga `ngrok.exe` desde https://ngrok.com/download
2. Crea cuenta gratis y copia tu authtoken de https://dashboard.ngrok.com/get-started/your-authtoken
3. Regístralo (una sola vez):

```bash
ngrok.exe config add-authtoken TU_TOKEN
```

---

## Cómo levantar el proyecto

Necesitas **3 terminales** corriendo a la vez.

### Terminal 1 — Backend

```bash
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload
```

Verifica: http://127.0.0.1:8000/health → `{"ok":true}`
Docs API: http://127.0.0.1:8000/docs

### Terminal 2 — Frontend

```bash
cd frontend
npm run dev
```

Abre: http://localhost:3000

### Terminal 3 — ngrok

```bash
ngrok.exe http 8000
```

Copia la URL `https://xxx-xxx.ngrok-free.dev` que aparece en `Forwarding`.

> ⚠️ Esa URL **cambia cada vez que reinicias ngrok** en el plan free. Si la cambias,
> tienes que actualizar el webhook en TradingView.

Inspector de requests en vivo: http://127.0.0.1:4040

---

## Conectar TradingView (una sola vez por símbolo)

Tienes que crear una alerta por cada par. Repite el proceso en el chart de
**XAUUSD** y en el de **EURUSD** con sus respectivos scripts.

1. Aplica el script Pine modificado (`SMS_XAUUSD_v8_9_1.pine` o `SMS_EURUSD_v8_10_1.pine`) al chart.
2. Click en el icono del **reloj** → **Create Alert** (o `Alt+A`).
3. **Condition** (primer dropdown): selecciona el indicador (`SMS-XAU v8.9.1`).
4. **Segundo dropdown**: selecciona **`Any alert() function call`** ⚠️ crítico.
   - Esto hace que TradingView mande exactamente el JSON que el script genera.
5. **Alert name**: algo como `XAUUSD → Backend`.
6. **Expiration**: marca **Open-ended** si está disponible.
7. Pestaña **Notifications** → checkbox **Webhook URL** → pega:
   ```
   https://TU-URL-NGROK.ngrok-free.dev/webhook/tradingview
   ```
8. **Create**.

Repite para EURUSD usando la misma URL de webhook.

---

## Probar el flujo sin esperar a TradingView

### Desde `/docs` (más fácil)

1. Abre http://127.0.0.1:8000/docs
2. Expande **`POST /analyze`** → **Try it out**
3. Pega:

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

4. **Execute** → debe devolver `decision: ENTER` y aparecer en el dashboard.

### Desde PowerShell

```powershell
$body = @{
  signal="SHORT"; symbol="EURUSD"; price=1.16681
  sl=1.16798; be=1.16564; tp=1.16447
  conf=15; quality="PREMIUM"; pattern="BAJA DESDE AQUI"
  fvg=$true; vol_high=$true; vol_ratio=2.1
  rsi=62; mtf="BEAR"; zona="VENDE"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8000/webhook/tradingview" -Method POST -ContentType "application/json" -Body $body
```

---

## Cómo se usa el dashboard

1. Cuando llega una señal, aparece automáticamente en la tabla (auto-refresh 5s).
2. **Tabs arriba** filtran por símbolo (`TODOS / XAUUSD / EURUSD`).
3. La columna **Decisión** marca:
   - 🟢 **ENTER** — setup alineado, R:R favorable. Operar.
   - 🟡 **WAIT** — contexto aceptable pero falta confirmación.
   - 🔴 **AVOID** — setup débil, extendido o contraproducente.
4. Cuando cierres el trade en tu broker, marca el resultado con los botones:
   - **W** (verde) → WIN
   - **L** (rojo) → LOSS
   - **BE** (amarillo) → break-even
5. Las **stats arriba** se actualizan en vivo: win rate global, PnL acumulado,
   y desgloses por símbolo/decisión/fuente/calidad para descubrir qué tipos de
   setup realmente ganan en tu instrumento.

---

## Lógica del motor de decisión

**Vetos duros (descartan al instante → AVOID):**

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

## Endpoints del backend

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Healthcheck |
| `POST` | `/analyze?ai=1` | Evalúa una señal estructurada (Pydantic) |
| `POST` | `/webhook/tradingview?ai=1` | Webhook que TradingView llama (acepta JSON o texto) |
| `GET` | `/signals?limit=100&symbol=XAUUSD` | Lista señales (filtrable) |
| `GET` | `/symbols` | Símbolos únicos vistos |
| `POST` | `/signals/{id}/result` | Marca resultado: `{"result":"WIN\|LOSS\|BE","exit_price":opc}` |
| `GET` | `/stats` | Métricas agregadas (overall + breakdowns) |

`?ai=1` activa el refinamiento opcional vía OpenRouter (requiere `OPENROUTER_API_KEY`).

---

## Estructura del proyecto

```
tradingApp/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI: rutas
│   │   ├── schemas.py         # Pydantic: TVSignal, AnalyzeResponse
│   │   ├── decision_engine.py # Vetos + scoring → decisión
│   │   ├── tv_parser.py       # Parser tolerante (JSON o texto)
│   │   ├── ai_client.py       # OpenRouter (opcional)
│   │   └── storage.py         # SQLite + stats
│   ├── requirements.txt
│   ├── .env.example
│   └── signals.db             # se crea solo
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

**TradingView no llega al backend**
→ Verifica en http://127.0.0.1:4040 si el request está llegando a ngrok.
Si no, la URL del webhook en la alerta está mal o ngrok se reinició y cambió de URL.

**La señal aparece pero todo dice AVOID**
→ Es la decisión correcta del motor: faltan confluencias o hay un veto duro
(ver columna "Razón"). No es un bug.

**Reinicio backend y se borran las señales**
→ La DB SQLite (`backend/signals.db`) persiste entre reinicios. Si la borraste
manualmente o estás corriendo uvicorn desde otra carpeta, se crea una nueva.

---

## Próximos pasos posibles

- Migrar SQLite a Postgres (Supabase) para historial permanente entre dispositivos.
- Deploy del backend en Render/Fly.io para no depender de ngrok ni del PC encendido.
- Notificaciones a Telegram cuando llega un ENTER.
- Filtros por hora del día / kill zone.
- Gráfico de equity curve.
- Backtest del motor sobre el historial acumulado.
