import React from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import HeroCard from "../../components/HeroCard";
import CompactCard from "../../components/CompactCard";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { OverlapDonut } from "../../components/viz";

export default function Concentration() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();

  const sectors = [
    { name: "Financials", pct: 32, color: "var(--v3-saffron)" },
    { name: "IT", pct: 21, color: "var(--v3-indigo)" },
    { name: "Consumer", pct: 14, color: "var(--v3-moss)" },
    { name: "Industrials", pct: 12, color: "var(--v3-gold)" },
    { name: "Healthcare", pct: 9, color: "var(--v3-crimson)" },
    { name: "Other", pct: 12, color: "var(--v3-ink-4)" },
  ];

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Portfolio · Risk" title="Concentration" />

      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 40 }}>
        <HeroCard
          layout={isDesktop ? "desktop" : "mobile"}
          category="risk"
          priorityLabel="HHI alert"
          title="Sector HHI is 1840 — above the 1500 caution threshold"
          description={isDesktop ? "Your largest sector is Financials at 32%. The Herfindahl-Hirschman index is a single number for portfolio concentration; above 1500 means meaningful single-sector risk." : null}
          viz={
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, alignItems: "center" }}>
              <OverlapDonut value={32} color="var(--v3-saffron)" size={120} />
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {sectors.slice(0, 4).map((s, i) => (
                  <SectorRow key={i} {...s} />
                ))}
              </div>
            </div>
          }
          ctaText="Suggest a concentration fix →"
          onClick={() => navigate("/chat?q=How%20do%20I%20reduce%20concentration%20risk")}
        />

        <section>
          <SectionHead title="Sector breakdown" count={`${sectors.length} sectors`} />
          <div style={{ display: "flex", flexDirection: "column", gap: 1, background: "var(--v3-line)", border: "1px solid var(--v3-line)", borderRadius: 14, overflow: "hidden" }}>
            {sectors.map((s, i) => (
              <SectorRow key={i} {...s} variant="row" />
            ))}
          </div>
        </section>

        <section>
          <SectionHead title="By dimension" count="4 cards" />
          <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(4, 1fr)" : "1fr 1fr", gap: 12 }}>
            <CompactCard category="risk" label="Top single stock" meta="RIL · 7.8%" viz={<OverlapDonut value={78} color="var(--v3-crimson)" />} />
            <CompactCard category="risk" label="Top AMC" meta="HDFC · 38%" viz={<OverlapDonut value={38} color="var(--v3-indigo)" />} />
            <CompactCard category="risk" label="Cap concentration" meta="LC 52%" viz={<OverlapDonut value={52} color="var(--v3-moss)" />} />
            <CompactCard category="risk" label="Geography" meta="India 92%" viz={<OverlapDonut value={92} color="var(--v3-saffron)" />} />
          </div>
        </section>
      </div>
    </ScreenContainer>
  );
}

function SectorRow({ name, pct, color, variant = "compact" }) {
  if (variant === "row") {
    return (
      <div style={{ background: "var(--v3-bg-2)", padding: "14px 16px", display: "flex", alignItems: "center", gap: 14 }}>
        <span style={{ width: 10, height: 10, borderRadius: 999, background: color }} />
        <span style={{ flex: 1, color: "var(--v3-ink-1)", fontSize: 14 }}>{name}</span>
        <span className="v3-data" style={{ color: "var(--v3-ink-1)", fontSize: 13 }}>{pct}%</span>
        <div style={{ width: 140, height: 6, background: "var(--v3-bg-3)", borderRadius: 3, overflow: "hidden" }}>
          <div style={{ width: `${Math.min(pct * 2.5, 100)}%`, background: color, height: "100%" }} />
        </div>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ width: 8, height: 8, borderRadius: 999, background: color }} />
      <span style={{ flex: 1, color: "var(--v3-ink-2)", fontSize: 12 }}>{name}</span>
      <span className="v3-data" style={{ color: "var(--v3-ink-1)", fontSize: 12 }}>{pct}%</span>
    </div>
  );
}
