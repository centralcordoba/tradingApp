// Minigráfico de velas japonesas para cada card del Radar de setups.
// Canvas 2D nativo, sin dependencias. Se llama desde RadarChart (React
// wrapper) pero la función es pura: mismo input → mismo output, sin estado.

type Candle = {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
};

type Setup = {
  symbol: string;
  price: number;
  bloque: number;
  side: string;
  candles?: Candle[];
  key_levels: {
    support: number | null;
    resistance: number | null;
    near_support?: boolean;
    near_resistance?: boolean;
  };
  rejection: {
    candle_ts: string | null;
    direction: string | null;
  };
  sl: {
    price: number;
    too_wide: boolean;
  } | null;
};

const CANDLE_GREEN = "#16a34a";
const CANDLE_RED = "#dc2626";
const SL_ORANGE = "#f97316";
const BG = "#0b0e13";
const TP_LONG_FILL = "rgba(22, 163, 74, 0.08)";
const TP_SHORT_FILL = "rgba(220, 38, 38, 0.08)";

const HEIGHT_CSS = 120;
const CANDLE_MIN = 4;
const CANDLE_MAX = 12;

export function drawRadarChart(
  canvas: HTMLCanvasElement | null,
  setup: Setup,
): void {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const dpr = (typeof window !== "undefined" && window.devicePixelRatio) || 1;
  const cssWidth = canvas.clientWidth;
  const cssHeight = canvas.clientHeight || HEIGHT_CSS;
  if (cssWidth <= 0 || cssHeight <= 0) return;

  // Reset transform antes del scale para evitar acumulación en redraws.
  canvas.width = Math.floor(cssWidth * dpr);
  canvas.height = Math.floor(cssHeight * dpr);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  // Capa 1 — fondo
  ctx.fillStyle = BG;
  ctx.fillRect(0, 0, cssWidth, cssHeight);

  const candles = setup.candles || [];
  if (candles.length === 0) return;

  // Escala Y
  const lows = candles.map(c => c.low);
  const highs = candles.map(c => c.high);
  let priceMin = Math.min(...lows);
  let priceMax = Math.max(...highs);

  if (priceMax - priceMin < 1e-9) {
    // flat market → padding artificial para no dividir por 0
    const pad = Math.max(Math.abs(priceMax) * 0.0005, 0.0001);
    priceMin -= pad;
    priceMax += pad;
  }

  const priceRange = priceMax - priceMin;
  const yMin = priceMin - priceRange * 0.10;
  const yMax = priceMax + priceRange * 0.10;
  const ySpan = yMax - yMin;

  const priceToY = (price: number) =>
    cssHeight - ((price - yMin) / ySpan) * cssHeight;

  const clampY = (y: number) => Math.max(0, Math.min(cssHeight, y));

  // Capa 2 — línea de soporte
  const support = setup.key_levels?.support ?? null;
  let ySupport: number | null = null;
  if (support != null) {
    ySupport = clampY(priceToY(support));
    ctx.strokeStyle = CANDLE_GREEN;
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(0, ySupport + 0.5);
    ctx.lineTo(cssWidth, ySupport + 0.5);
    ctx.stroke();
  }

  // Capa 3 — línea de resistencia
  const resistance = setup.key_levels?.resistance ?? null;
  let yResistance: number | null = null;
  if (resistance != null) {
    yResistance = clampY(priceToY(resistance));
    ctx.strokeStyle = CANDLE_RED;
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(0, yResistance + 0.5);
    ctx.lineTo(cssWidth, yResistance + 0.5);
    ctx.stroke();
  }

  // Capa 4 — SL punteado (solo si existe y no es too_wide)
  let ySL: number | null = null;
  if (setup.sl && !setup.sl.too_wide) {
    ySL = clampY(priceToY(setup.sl.price));
    ctx.strokeStyle = SL_ORANGE;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(0, ySL + 0.5);
    ctx.lineTo(cssWidth, ySL + 0.5);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Capa 5 — velas
  const n = candles.length;
  let candleWidth = Math.floor(cssWidth / n) - 1;
  candleWidth = Math.max(CANDLE_MIN, Math.min(CANDLE_MAX, candleWidth));
  const step = candleWidth + 1;
  const totalWidth = step * n - 1;
  const xOffset = Math.max(0, (cssWidth - totalWidth) / 2);

  const xForIndex = (i: number) => xOffset + i * step;

  for (let i = 0; i < n; i++) {
    const c = candles[i];
    const bullish = c.close >= c.open;
    const color = bullish ? CANDLE_GREEN : CANDLE_RED;
    const xLeft = xForIndex(i);
    const xCenter = xLeft + candleWidth / 2;

    const yHigh = priceToY(c.high);
    const yLow = priceToY(c.low);
    const yOpen = priceToY(c.open);
    const yClose = priceToY(c.close);

    // Mecha
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(Math.round(xCenter) + 0.5, yHigh);
    ctx.lineTo(Math.round(xCenter) + 0.5, yLow);
    ctx.stroke();

    // Cuerpo
    const bodyTop = Math.min(yOpen, yClose);
    const bodyBot = Math.max(yOpen, yClose);
    const bodyHeight = Math.max(bodyBot - bodyTop, 0);
    ctx.fillStyle = color;
    if (bodyHeight < 1) {
      ctx.fillRect(xLeft, Math.round(bodyTop), candleWidth, 1);
    } else {
      ctx.fillRect(xLeft, bodyTop, candleWidth, bodyHeight);
    }
  }

  // Capa 6 — marcador de vela de rechazo
  const rejTs = setup.rejection?.candle_ts;
  const rejDir = setup.rejection?.direction;
  if (rejTs && rejDir) {
    const rejIdx = candles.findIndex(c => c.ts === rejTs);
    if (rejIdx >= 0) {
      const c = candles[rejIdx];
      const xCenter = xForIndex(rejIdx) + candleWidth / 2;
      const base = 5;
      const heightTri = 4;
      const gap = 2;

      ctx.beginPath();
      if (rejDir === "LONG") {
        // Apex arriba (hacia la vela), base abajo
        const yLow = priceToY(c.low);
        const apexY = yLow + gap;
        ctx.fillStyle = CANDLE_GREEN;
        ctx.moveTo(xCenter, apexY);
        ctx.lineTo(xCenter - base / 2, apexY + heightTri);
        ctx.lineTo(xCenter + base / 2, apexY + heightTri);
      } else {
        // SHORT: apex abajo (hacia la vela), base arriba
        const yHigh = priceToY(c.high);
        const apexY = yHigh - gap;
        ctx.fillStyle = CANDLE_RED;
        ctx.moveTo(xCenter, apexY);
        ctx.lineTo(xCenter - base / 2, apexY - heightTri);
        ctx.lineTo(xCenter + base / 2, apexY - heightTri);
      }
      ctx.closePath();
      ctx.fill();
    }
  }

  // Capa 7 — zona TP sombreada (solo B1 LONG y B3 SHORT)
  if (setup.bloque === 1 && setup.side === "LONG" && resistance != null) {
    const yPrice = clampY(priceToY(setup.price));
    const yRes = clampY(priceToY(resistance));
    const top = Math.min(yPrice, yRes);
    const h = Math.abs(yPrice - yRes);
    if (h > 0) {
      ctx.fillStyle = TP_LONG_FILL;
      ctx.fillRect(0, top, cssWidth, h);
    }
  } else if (setup.bloque === 3 && setup.side === "SHORT" && support != null) {
    const yPrice = clampY(priceToY(setup.price));
    const ySup = clampY(priceToY(support));
    const top = Math.min(yPrice, ySup);
    const h = Math.abs(yPrice - ySup);
    if (h > 0) {
      ctx.fillStyle = TP_SHORT_FILL;
      ctx.fillRect(0, top, cssWidth, h);
    }
  }

  // Labels mínimos (10px monospace, sin fondo)
  ctx.font = "10px ui-monospace, Menlo, Consolas, monospace";
  ctx.textBaseline = "bottom";

  if (support != null && setup.key_levels?.near_support && ySupport != null) {
    ctx.fillStyle = CANDLE_GREEN;
    ctx.textAlign = "right";
    const y = Math.max(10, ySupport - 2);
    ctx.fillText(String(support), cssWidth - 4, y);
  }
  if (resistance != null && setup.key_levels?.near_resistance && yResistance != null) {
    ctx.fillStyle = CANDLE_RED;
    ctx.textAlign = "right";
    const y = Math.max(10, yResistance - 2);
    ctx.fillText(String(resistance), cssWidth - 4, y);
  }
  if (ySL != null) {
    ctx.fillStyle = SL_ORANGE;
    ctx.textAlign = "left";
    const y = Math.max(10, ySL - 2);
    ctx.fillText("SL", 4, y);
  }
}
