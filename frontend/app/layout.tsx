import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI Trading Assistant",
  description: "Motor de decisión contextual para señales de TradingView",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
