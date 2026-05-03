/* Zonas premium/discount para chips de tabla de señales. */

export function zonaClass(zona: string): string {
  switch (zona) {
    case "COMPRA YA": return "deep-discount";
    case "COMPRA":    return "discount";
    case "VENDE":     return "premium";
    case "VENDE YA":  return "deep-premium";
    default:          return "neutral";
  }
}

export function zonaTooltip(zona: string, side: string): string {
  const isLong = side === "LONG" || side === "BUY";
  switch (zona) {
    case "COMPRA YA":
      return isLong
        ? "Descuento extremo — zona ideal para LONG"
        : "Descuento extremo — peligroso para SHORT (soporte fuerte)";
    case "COMPRA":
      return isLong
        ? "Zona de descuento — favorable para LONG"
        : "Zona de descuento — SHORT contra el valor";
    case "VENDE":
      return isLong
        ? "Zona premium — LONG caro, riesgo de rechazo"
        : "Zona premium — favorable para SHORT";
    case "VENDE YA":
      return isLong
        ? "Premium extremo — NO comprar aquí (resistencia fuerte)"
        : "Premium extremo — zona ideal para SHORT";
    default:
      return "Zona no definida";
  }
}
