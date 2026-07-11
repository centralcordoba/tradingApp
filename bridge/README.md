# Bridge MT5 (FTMO)

Proceso local (Windows) que ejecuta en MetaTrader 5 las decisiones del backend. **Solo opera AUDUSD y USDCAD** (whitelist por defecto):

- **Marco de Zonas S/R en OPERAR + fuerte** (AUDUSD/USDCAD) → orden a mercado con el entry/SL/TP del marco (poll `/api/zones` cada 5 min, misma cache que el frontend). Es la fuente ejecutora principal.
- **Señales del Pine con decision ENTER** (vía SSE `/signals/stream`, latencia ~2s) → se registran en el log, pero como el Pine opera EURUSD (fuera de la whitelist) **no se ejecutan**. Para activarlas: añadir EURUSD a `ALLOWED_SYMBOLS` y su ventana a `SYMBOL_WINDOWS`.
- **Auto-resolución**: cuando MT5 cierra un trade del bridge (TP/SL/manual), reporta WIN/LOSS/BE + exit_price a `POST /signals/{id}/result` → alimenta `/stats` y `scripts/calibrate.py` sin marcar nada a mano.

## Requisitos

1. **Terminal MT5 instalado y abierto en este PC**, logueado en la cuenta FTMO.
2. Botón **"Algo Trading" activado** en el terminal (si está apagado, `order_send` falla con "AutoTrading disabled by client").
3. Python 3.11+ y dependencias:

```powershell
cd bridge
pip install -r requirements.txt
```

## Configuración

Crear `bridge/.env` (o variables de entorno; el entorno tiene prioridad). Defaults pensados para FTMO 50k:

```ini
DRY_RUN=1                    # 1 = solo registra, no envía órdenes (DEFAULT)
API_BASE=https://tradingapp-2glz.onrender.com

RISK_PCT=0.5                 # % de equity arriesgado por trade (sizing por SL)
MAX_TRADES_PER_DAY=2         # regla del playbook
MAX_DAILY_LOSS_USD=2500      # límite FTMO 50k (5%)
MAX_TOTAL_LOSS_USD=5000      # límite FTMO 50k (10%)
INITIAL_BALANCE=50000

ALLOWED_SYMBOLS=AUDUSD,USDCAD                  # añadir EURUSD para ejecutar el Pine
SYMBOL_WINDOWS=AUDUSD=9-14,USDCAD=14-21        # hora Madrid, [inicio, fin)
SYMBOL_SUFFIX=               # solo si el broker usa sufijos (p.ej. ".r")

MT5_LOGIN=                   # vacíos = usa la sesión ya logueada en el terminal
MT5_PASSWORD=
MT5_SERVER=
```

## Uso

```powershell
cd bridge
python main.py
```

Log en consola y en `bridge/bridge.log`. Estado persistido en `bridge_state.json` (baseline de señales, cooldowns, contador de trades, mapa posición→señal).

### Kill switch

Crear un archivo vacío llamado `STOP` en `bridge/` bloquea **nuevas** órdenes al instante (no toca posiciones abiertas). Borrarlo reactiva.

```powershell
ni bridge\STOP              # activar
rm bridge\STOP              # desactivar
```

### Checklist para pasar a real

1. Correr en `DRY_RUN=1` varios días de mercado; comparar cada línea `[DRY-RUN]` contra el chart: ¿habrías tomado ese trade? ¿el sizing es razonable?
2. Verificar en el log que las guardas bloquean lo que deben (ventanas, máx trades, cooldown).
3. Cambiar a una cuenta **FTMO Free Trial** con `DRY_RUN=0` y validar ejecución real (fills, SL/TP colocados, resultado reportado al cerrar).
4. Solo entonces apuntar al challenge/funded.

## Guardarraíles integrados

- Nunca ejecuta señales históricas (baseline por id en el primer arranque + descarte de señales con >3 min de edad tras reconexión).
- Una posición del bridge por símbolo como máximo; cooldown de 15 min por símbolo+lado en el marco.
- No coloca una orden si su **SL completo** breachearía el límite diario o total (no espera a que la pérdida ocurra).
- Si el lote mínimo del broker ya excede el presupuesto de riesgo → no opera.
- Con `DRY_RUN=0` y sin conexión MT5 verificada, aborta el arranque.
- `magic` propio (20260711): el bridge solo gestiona y contabiliza sus posiciones; tus trades manuales no se tocan (pero SÍ cuentan en el PnL diario de la guarda, igual que en FTMO).

## Limitaciones conocidas

- El cálculo del PnL diario (medianoche Europe/Prague, realizado + flotante) es una **aproximación** del cómputo de FTMO — el dashboard de FTMO es la fuente autoritativa. Los límites por defecto llevan el margen de que ninguna orden nueva puede llevarte al límite ni en su peor caso.
- El PC debe estar encendido con el terminal MT5 abierto durante las ventanas operativas. Si eso falla a menudo, considerar un VPS Windows.
- Los trades del marco de Zonas no tienen `signal_id`, así que no se auto-reportan a `/stats` (solo quedan en el historial de MT5 y en `bridge.log`).
- FTMO permite trading algorítmico, pero revisa sus términos vigentes — la responsabilidad del cumplimiento es del titular de la cuenta.
