"use client";

import { useEffect } from "react";
import { useTick } from "@/hooks/useTick";
import {
  getCurrentSession,
  sessionCountdown,
  getNextSession,
} from "@/lib/sessions";
import type { View } from "@/lib/types";
import { RefreshIcon, SettingsIcon, SunIcon, MoonIcon } from "@/components/icons";
import "./Topbar.css";

type TopbarProps = {
  view: View;
  onViewChange: (v: View) => void;
  onRefresh: () => void;
  refreshing?: boolean;
  theme: "dark" | "light";
  onThemeToggle: () => void;
  signalAlertsOn?: boolean;
  onToggleSignalAlerts?: () => void;
};

const TABS: { id: View; label: string; key: string }[] = [
  { id: "dashboard",    label: "Dashboard",         key: "D" },
  { id: "sr",           label: "Zonas S/R",         key: "R" },
  { id: "zones",        label: "Análisis de zonas", key: "Z" },
  { id: "stocks",       label: "Stocks",            key: "S" },
  { id: "correlations", label: "Correlaciones",     key: "C" },
  { id: "playbook",     label: "Playbook",          key: "P" },
];

export function Topbar({
  view,
  onViewChange,
  onRefresh,
  refreshing,
  theme,
  onThemeToggle,
  signalAlertsOn,
  onToggleSignalAlerts,
}: TopbarProps) {
  const now = useTick(60_000);

  // Atajos D/Z/R — ignoran cuando el foco está en un input/textarea
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || target?.isContentEditable) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "d") { e.preventDefault(); onViewChange("dashboard"); }
      else if (k === "r") { e.preventDefault(); onViewChange("sr"); }
      else if (k === "z") { e.preventDefault(); onViewChange("zones"); }
      else if (k === "s") { e.preventDefault(); onViewChange("stocks"); }
      else if (k === "c") { e.preventDefault(); onViewChange("correlations"); }
      else if (k === "p") { e.preventDefault(); onViewChange("playbook"); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onViewChange]);

  const currentSession = now ? getCurrentSession(now) : null;
  let pillLabel: string;
  let pillCountdown: string;
  let pillOpen: boolean;
  if (now && currentSession) {
    const cd = sessionCountdown(now, currentSession);
    pillLabel = `${currentSession.abbr} Session`;
    pillCountdown = cd.label.replace(/^Cierra en\s/, "cierra en ");
    pillOpen = true;
  } else if (now) {
    const next = getNextSession(now);
    const totalMin = Math.floor(next.minutesUntil);
    const hh = Math.floor(totalMin / 60);
    const mm = totalMin % 60;
    const time = hh > 0 ? `${hh}h ${String(mm).padStart(2, "0")}m` : `${mm}m`;
    pillLabel = `Próx: ${next.session.abbr}`;
    pillCountdown = `abre en ${time}`;
    pillOpen = false;
  } else {
    pillLabel = "—";
    pillCountdown = "";
    pillOpen = false;
  }

  return (
    <header className="topbar" role="banner">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">AI</div>
        <span className="brand-name">Trading Assistant</span>
      </div>

      <nav className="tabs" role="navigation" aria-label="Vistas principales">
        {TABS.map(t => (
          <button
            key={t.id}
            className={`tab ${view === t.id ? "active" : ""}`}
            onClick={() => onViewChange(t.id)}
            aria-current={view === t.id ? "page" : undefined}
            title={`${t.label} · ${t.key}`}
          >
            {t.label}
          </button>
        ))}
        <a
          className="tab tab-link"
          href="/patterns.html"
          target="_blank"
          rel="noopener noreferrer"
          title="Patrones · abre en pestaña nueva"
        >
          Patrones <span className="tab-link-ext" aria-hidden="true">↗</span>
        </a>
      </nav>

      <div className="topbar-spacer" />

      <div
        className={`session-pill ${pillOpen ? "is-open" : "is-closed"}`}
        role="status"
        aria-live="polite"
      >
        <span className="session-pill-dot" aria-hidden="true" />
        <span>{pillLabel} · </span>
        <span className="num">{pillCountdown}</span>
      </div>

      {onToggleSignalAlerts && (
        <button
          className="icon-btn"
          onClick={onToggleSignalAlerts}
          aria-label={signalAlertsOn ? "Silenciar alertas de señal" : "Activar alertas de señal"}
          title={signalAlertsOn
            ? "Alertas de señal ENTER/WAIT activas — clic para silenciar"
            : "Activar sonido + notificación cuando llegue una señal ENTER/WAIT"}
        >
          {signalAlertsOn ? "🔔" : "🔕"}
        </button>
      )}

      <button
        className="icon-btn"
        onClick={onRefresh}
        aria-label="Refrescar"
        title="Refrescar"
      >
        <RefreshIcon size={14} className={refreshing ? "spin" : undefined} />
      </button>

      <button
        className="icon-btn"
        onClick={onThemeToggle}
        aria-label={theme === "dark" ? "Cambiar a modo claro" : "Cambiar a modo oscuro"}
        title={theme === "dark" ? "Modo claro" : "Modo oscuro"}
      >
        {theme === "dark" ? <SunIcon size={14} /> : <MoonIcon size={14} />}
      </button>

      <button
        className="icon-btn"
        aria-label="Ajustes"
        title="Ajustes"
      >
        <SettingsIcon size={14} />
      </button>
    </header>
  );
}
