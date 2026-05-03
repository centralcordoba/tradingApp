/* A+ filter por setup. Cada filtro vale 1 punto.
   5/5 = OPERAR · 3-4 = ESPERAR · <3 = EVITAR. */

import type { RadarSetup } from "@/lib/types";
import type { KillZoneStatus } from "@/lib/killZones";

export type AplusCheck = {
  key: string;
  label: string;
  passed: boolean;
  detail?: string;
};

export type AplusEvaluation = {
  checks: AplusCheck[];
  passed: number;
  total: number;
};

export function evalSetup(s: RadarSetup, killZoneStatus: KillZoneStatus | null): AplusEvaluation {
  const checks: AplusCheck[] = [];

  const kz = killZoneStatus;
  checks.push({
    key: "killzone",
    label: "Kill zone activa",
    passed: kz === "fire" || kz === "ok",
    detail: kz ? `Actual: ${kz}` : "fuera de ventana operable",
  });

  const mtfPassed = s.alignment?.mtf_lock_passed === true;
  const mtfFailed = s.alignment?.mtf_lock_failed === true;
  checks.push({
    key: "mtf",
    label: "MTF LOCK (alineado con escáner)",
    passed: mtfPassed,
    detail: mtfFailed
      ? `Escáner dice ${s.alignment?.scanner_bias}, setup va en contra`
      : s.alignment?.status === "neutral"
      ? "Escáner neutral"
      : s.alignment?.status === "unknown"
      ? "Sin data del escáner"
      : undefined,
  });

  checks.push({
    key: "strength",
    label: "Fuerza STRONG (con divergencia)",
    passed: s.strength === "STRONG",
    detail: s.strength === "NORMAL" ? "Solo rechazo, sin divergencia" : undefined,
  });

  const rrr = s.sl?.rrr;
  const rrrMin = s.sl?.rrr_min ?? 2.0;
  checks.push({
    key: "rrr",
    label: `RRR ≥ ${rrrMin}:1`,
    passed: !!s.sl && rrr != null && rrr >= rrrMin,
    detail: rrr != null ? `Actual: ${rrr.toFixed(2)}:1` : "Sin TP calculable",
  });

  checks.push({
    key: "sl",
    label: "SL dentro del cap",
    passed: !!s.sl && !s.sl.too_wide,
    detail: s.sl?.too_wide ? `${s.sl.distance_pips} pips > cap ${s.sl.cap_pips}` : undefined,
  });

  const passed = checks.filter(c => c.passed).length;
  return { checks, passed, total: checks.length };
}

export type AplusDecision = {
  label: "OPERAR" | "ESPERAR" | "EVITAR";
  cls: string;
  ico: string;
};

export function aplusDecision(passed: number): AplusDecision {
  if (passed >= 5) return { label: "OPERAR", cls: "sem-go", ico: "✅" };
  if (passed >= 3) return { label: "ESPERAR", cls: "sem-wait", ico: "⏳" };
  return { label: "EVITAR", cls: "sem-stop", ico: "❌" };
}
