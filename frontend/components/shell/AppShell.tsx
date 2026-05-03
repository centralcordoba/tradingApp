"use client";

import { useEffect } from "react";
import "./AppShell.css";

type AppShellProps = {
  topbar: React.ReactNode;
  sidebar: React.ReactNode;
  main: React.ReactNode;
  rightbar: React.ReactNode;
};

export function AppShell({ topbar, sidebar, main, rightbar }: AppShellProps) {
  // Activa overflow:hidden + height:100vh sobre <body> mientras el shell
  // está montado, así cada columna maneja su propio scroll.
  useEffect(() => {
    document.body.dataset.shell = "active";
    return () => { delete document.body.dataset.shell; };
  }, []);

  return (
    <div className="app-shell">
      <div className="app-shell-topbar">{topbar}</div>
      <aside className="app-shell-sidebar" aria-label="Navegación lateral">{sidebar}</aside>
      <main className="app-shell-main" role="main">{main}</main>
      <aside className="app-shell-rightbar" aria-label="Panel secundario">{rightbar}</aside>
    </div>
  );
}
