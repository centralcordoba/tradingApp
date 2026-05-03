"use client";

import { useState } from "react";
import { useInvestorProfile } from "@/hooks/stocks/useInvestorProfile";
import { ProfileWizard } from "./onboarding/ProfileWizard";
import { StocksDashboard } from "./dashboard/StocksDashboard";
import "./StocksView.css";

type Props = {
  activeSymbol: string | null;
  onSymbolChange: (symbol: string | null) => void;
};

export function StocksView({ activeSymbol, onSymbolChange }: Props) {
  const { profile, isLoaded, saveProfile } = useInvestorProfile();
  const [editing, setEditing] = useState(false);

  if (!isLoaded) {
    return (
      <div className="stocks-view">
        <div className="stocks-loading">Cargando perfil…</div>
      </div>
    );
  }

  if (!profile || editing) {
    return (
      <div className="stocks-view">
        <ProfileWizard
          initial={editing ? profile : null}
          onSave={(p) => {
            saveProfile(p);
            setEditing(false);
          }}
          onCancel={editing ? () => setEditing(false) : undefined}
        />
      </div>
    );
  }

  return (
    <div className="stocks-view">
      <StocksDashboard
        profile={profile}
        onEditProfile={() => setEditing(true)}
        activeSymbol={activeSymbol}
        onSymbolChange={onSymbolChange}
      />
    </div>
  );
}
