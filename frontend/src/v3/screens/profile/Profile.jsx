import React, { useState } from "react";
import { useOutletContext, useNavigate } from "react-router-dom";
import { Check } from "lucide-react";
import PersonaStrip from "../../components/PersonaStrip";
import PersonaAvatar from "../../components/PersonaAvatar";
import CompactCard from "../../components/CompactCard";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { OverlapDonut, HealthGauge } from "../../components/viz";
import { usePersona, usePortfolioSummary, PERSONAS } from "../../adapters";
import { inrCompact, pct } from "../../lib/format";

export default function Profile() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const { persona, setPersona } = usePersona();
  const { data: p } = usePortfolioSummary();
  const [picking, setPicking] = useState(false);

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Profile" title={p.user.name} />
      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 40 }}>
        <PersonaStrip persona={persona} onChange={() => setPicking((v) => !v)} changeLabel={picking ? "Cancel" : "Change persona"} />

        {picking && (
          <section>
            <SectionHead title="Pick a new persona" count={`${PERSONAS.length} options`} />
            <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(3, 1fr)" : "1fr", gap: 12 }}>
              {PERSONAS.map((opt) => {
                const active = opt.id === persona.id;
                return (
                  <button
                    type="button"
                    key={opt.id}
                    onClick={() => {
                      setPersona(opt.id);
                      setPicking(false);
                    }}
                    style={{
                      textAlign: "left",
                      background: active ? "var(--v3-bg-3)" : "var(--v3-bg-2)",
                      border: `1px solid ${active ? "var(--v3-saffron)" : "var(--v3-line)"}`,
                      borderRadius: 16,
                      padding: 14,
                      display: "flex",
                      alignItems: "center",
                      gap: 12,
                      cursor: "pointer",
                    }}
                  >
                    <PersonaAvatar iconKey={opt.avatarIcon} accent={opt.accent} size={36} radius={10} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ color: "var(--v3-ink-1)", fontWeight: 500, fontSize: 14 }}>{opt.name}</div>
                      <div style={{ color: "var(--v3-ink-3)", fontSize: 12, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {opt.tagline}
                      </div>
                    </div>
                    {active && (
                      <span style={{ width: 22, height: 22, borderRadius: 999, background: "var(--v3-saffron)", color: "var(--v3-saffron-ink)", display: "grid", placeItems: "center" }}>
                        <Check size={12} strokeWidth={3} />
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </section>
        )}

        <SectionHead title="Account stats" count="4 cards" />
        <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(4, 1fr)" : "1fr 1fr", gap: 12 }}>
          <CompactCard category="health" label="Net worth" meta={inrCompact(p.summary.totalValue)} viz={<HealthGauge score={72} />} />
          <CompactCard category="performance" label="XIRR · inception" meta={`${p.summary.xirr}%`} viz={<HealthGauge score={Math.min(p.summary.xirr * 4, 100)} />} />
          <CompactCard category="goal" label="Goals on track" meta="2 / 3" viz={<HealthGauge score={66} />} />
          <CompactCard category="risk" label="Risk score" meta={`${p.risk.score} · ${p.risk.level}`} viz={<OverlapDonut value={p.risk.score} color="var(--v3-saffron)" />} />
        </div>

        <SectionHead title="Quick actions" count="3" />
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <ActionButton label="Open settings" onClick={() => navigate("/settings")} />
          <ActionButton label="Re-run onboarding" onClick={() => navigate("/onboarding")} />
          <ActionButton label="Go to V2 (classic experience)" onClick={() => (window.location.href = "/v2/app")} />
        </div>
      </div>
    </ScreenContainer>
  );
}

function ActionButton({ label, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: "var(--v3-bg-2)",
        border: "1px solid var(--v3-line)",
        borderRadius: 14,
        padding: "14px 16px",
        color: "var(--v3-ink-1)",
        fontSize: 14,
        textAlign: "left",
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );
}
