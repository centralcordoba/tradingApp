"use client";

import { useState } from "react";
import type {
  CapitalRange,
  Experience,
  Horizon,
  InvestorProfile,
  RiskTolerance,
} from "@/lib/stocks/types";
import { HorizonStep } from "./steps/HorizonStep";
import { RiskStep } from "./steps/RiskStep";
import { CapitalStep } from "./steps/CapitalStep";
import { ExperienceStep } from "./steps/ExperienceStep";
import { SectorsStep } from "./steps/SectorsStep";
import "./ProfileWizard.css";

type Props = {
  /** Si viene un perfil existente, el wizard arranca pre-cargado (modo edición). */
  initial?: InvestorProfile | null;
  onSave: (p: InvestorProfile) => void;
  onCancel?: () => void;
};

type Draft = {
  horizon: Horizon | null;
  riskTolerance: RiskTolerance | null;
  capitalRange: CapitalRange | null;
  experience: Experience | null;
  sectors: string[];
};

const STEP_TITLES = [
  "¿Qué tipo de operador sos?",
  "¿Cuánto riesgo aceptás?",
  "¿Con qué capital operás?",
  "¿Qué experiencia tenés?",
  "¿Qué sectores te interesan?",
];

const STEP_SUBTITLES = [
  "Determina el intervalo y los pesos de los indicadores que usa el motor.",
  "Influye sobre qué señales considerar accionables.",
  "Sirve de contexto en los próximos features de position sizing.",
  "Ajusta el nivel de detalle de las explicaciones.",
  "Permite filtrar tickers y priorizar por temática (opcional).",
];

const TOTAL_STEPS = 5;

export function ProfileWizard({ initial, onSave, onCancel }: Props) {
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<Draft>(() => ({
    horizon: initial?.horizon ?? null,
    riskTolerance: initial?.riskTolerance ?? null,
    capitalRange: initial?.capitalRange ?? null,
    experience: initial?.experience ?? null,
    sectors: initial?.sectors ?? [],
  }));

  const canAdvance = (() => {
    switch (step) {
      case 0: return draft.horizon !== null;
      case 1: return draft.riskTolerance !== null;
      case 2: return draft.capitalRange !== null;
      case 3: return draft.experience !== null;
      case 4: return true; // sectors es opcional
      default: return false;
    }
  })();

  const isLastStep = step === TOTAL_STEPS - 1;

  const handleNext = () => {
    if (!canAdvance) return;
    if (isLastStep) {
      // Validación final — todos los required deben estar.
      if (
        draft.horizon &&
        draft.riskTolerance !== null &&
        draft.capitalRange &&
        draft.experience
      ) {
        onSave({
          horizon: draft.horizon,
          riskTolerance: draft.riskTolerance,
          capitalRange: draft.capitalRange,
          experience: draft.experience,
          sectors: draft.sectors,
        });
      }
      return;
    }
    setStep(s => Math.min(s + 1, TOTAL_STEPS - 1));
  };

  const handleBack = () => {
    setStep(s => Math.max(s - 1, 0));
  };

  return (
    <div className="wizard" role="dialog" aria-label="Configurar perfil de inversor">
      <div className="wizard-header">
        <div className="wizard-progress" aria-hidden="true">
          {Array.from({ length: TOTAL_STEPS }).map((_, i) => (
            <div
              key={i}
              className={`wizard-progress-segment ${i <= step ? "is-done" : ""} ${i === step ? "is-active" : ""}`}
            />
          ))}
        </div>
        <div className="wizard-step-meta">
          <span className="wizard-step-num num">{step + 1}/{TOTAL_STEPS}</span>
          {onCancel && (
            <button
              type="button"
              className="wizard-cancel"
              onClick={onCancel}
              aria-label="Cancelar"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      <div className="wizard-card">
        <h2 className="wizard-title">{STEP_TITLES[step]}</h2>
        <p className="wizard-subtitle">{STEP_SUBTITLES[step]}</p>

        <div className="wizard-content">
          {step === 0 && (
            <HorizonStep
              value={draft.horizon}
              onChange={(h) => setDraft(d => ({ ...d, horizon: h }))}
            />
          )}
          {step === 1 && (
            <RiskStep
              value={draft.riskTolerance}
              onChange={(r) => setDraft(d => ({ ...d, riskTolerance: r }))}
            />
          )}
          {step === 2 && (
            <CapitalStep
              value={draft.capitalRange}
              onChange={(c) => setDraft(d => ({ ...d, capitalRange: c }))}
            />
          )}
          {step === 3 && (
            <ExperienceStep
              value={draft.experience}
              onChange={(e) => setDraft(d => ({ ...d, experience: e }))}
            />
          )}
          {step === 4 && (
            <SectorsStep
              value={draft.sectors}
              onChange={(s) => setDraft(d => ({ ...d, sectors: s }))}
            />
          )}
        </div>

        {isLastStep && (
          <p className="wizard-disclaimer">
            Las señales son análisis técnico automatizado con fines educativos.
            No constituyen asesoría financiera. Operar en mercados conlleva
            riesgo de pérdida de capital. Consultá un asesor licenciado antes
            de invertir.
          </p>
        )}

        <div className="wizard-actions">
          <button
            type="button"
            className="wizard-btn wizard-btn-back"
            onClick={handleBack}
            disabled={step === 0}
          >
            Atrás
          </button>
          <button
            type="button"
            className="wizard-btn wizard-btn-next"
            onClick={handleNext}
            disabled={!canAdvance}
          >
            {isLastStep ? "Guardar perfil" : "Siguiente"}
          </button>
        </div>
      </div>
    </div>
  );
}
