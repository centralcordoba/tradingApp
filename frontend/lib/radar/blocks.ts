/* Helpers de presentación de bloques del radar (B1/B2/B3/B4). */

export function blockMeta(bloque: number, strength: string | null): {
  label: string;
  cls: string;
  tone: string;
} {
  switch (bloque) {
    case 1: return {
      label: strength === "STRONG" ? "B1 ★ STRONG" : "B1",
      cls: strength === "STRONG" ? "radar-b1-strong" : "radar-b1",
      tone: "Compra válida",
    };
    case 3: return {
      label: strength === "STRONG" ? "B3 ★ STRONG" : "B3",
      cls: strength === "STRONG" ? "radar-b3-strong" : "radar-b3",
      tone: "Venta válida",
    };
    case 2: return { label: "B2 ⚠ TRAMPA", cls: "radar-trap", tone: "Trampa long" };
    case 4: return { label: "B4 ⚠ TRAMPA", cls: "radar-trap", tone: "Trampa short" };
    default: return { label: "—", cls: "", tone: "" };
  }
}

export function trapCopy(bloque: number): { title: string; detail: string } {
  if (bloque === 2) return {
    title: "Trampa long — no comprar aquí",
    detail: "El soporte parece válido pero el rechazo es bajista. Esperar ruptura del soporte confirmada.",
  };
  if (bloque === 4) return {
    title: "Trampa short — no vender aquí",
    detail: "La resistencia parece válida pero el rechazo es alcista. Esperar ruptura confirmada.",
  };
  return { title: "", detail: "" };
}
