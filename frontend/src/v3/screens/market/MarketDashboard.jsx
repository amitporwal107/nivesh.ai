import React from "react";
import { useOutletContext } from "react-router-dom";
import HeroCard from "../../components/HeroCard";
import HeroVizPanel from "../../components/HeroVizPanel";
import CompactCard from "../../components/CompactCard";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { PerformanceLine } from "../../components/viz";
import { usePortfolioSummary, useMarketBrief } from "../../adapters";
import SourceBanner from "../../components/SourceBanner";
import { pct } from "../../lib/format";

export default function MarketDashboard() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const portfolioState = usePortfolioSummary();
  const p = portfolioState.data;
  const briefState = useMarketBrief();
  const brief = briefState.data;
  const niftyValue = brief?.nifty?.value ?? p.market.nifty;
  const niftyDelta = brief?.nifty?.change_pct ?? p.market.niftyDeltaPct;
  const sectors = brief?.sectors?.length
    ? brief.sectors.slice(0, 8).map((s) => ({ name: s.name || s.sector, d: s.change_pct ?? s.return_pct ?? 0 }))
    : [
        { name: "IT", d: 1.42 },
        { name: "Financials", d: 0.68 },
        { name: "Pharma", d: -0.22 },
        { name: "Auto", d: 1.14 },
        { name: "Energy", d: -0.46 },
        { name: "Consumer", d: 0.32 },
        { name: "Metals", d: -1.08 },
        { name: "Realty", d: 2.18 },
      ];

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Market" title="Today's market read" />
      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 40 }}>
        <SourceBanner source={brief ? "live" : "placeholder"} error={briefState.error} loading={briefState.loading} onRefresh={briefState.refetch} />
        <HeroCard
          layout={isDesktop ? "desktop" : "mobile"}
          category="performance"
          priorityLabel="Live"
          title={`Nifty 50 · ${(typeof niftyValue === "number" ? niftyValue : 0).toLocaleString("en-IN")}`}
          description={isDesktop ? (brief?.narrative || "Sensex up 0.38%, breadth positive (1240 adv / 870 dec). FII net buyers ₹1,840 Cr. DII net buyers ₹620 Cr.") : null}
          viz={
            <HeroVizPanel eyebrow="Today" value={pct(niftyDelta, 2)} size={isDesktop ? "desktop" : "mobile"}>
              <PerformanceLine size={isDesktop ? 144 : 96} />
            </HeroVizPanel>
          }
          ctaText="Open index detail →"
        />

        <SectionHead title="Sectors today" count={`${sectors.length} sectors`} />
        <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(4, 1fr)" : "1fr 1fr", gap: 12 }}>
          {sectors.map((s, i) => (
            <CompactCard
              key={i}
              category={s.d >= 0 ? "performance" : "risk"}
              label={s.name}
              meta={pct(s.d, 2)}
              viz={<PerformanceLine color={s.d >= 0 ? "var(--v3-moss)" : "var(--v3-crimson)"} />}
            />
          ))}
        </div>

        <SectionHead title="Flows" count="2 charts" />
        <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(2, 1fr)" : "1fr", gap: 12 }}>
          <CompactCard category="performance" label="FII net (₹ Cr · 30d)" meta="+12,400" viz={<PerformanceLine color="var(--v3-moss)" />} />
          <CompactCard category="performance" label="DII net (₹ Cr · 30d)" meta="+8,100" viz={<PerformanceLine color="var(--v3-indigo)" />} />
        </div>
      </div>
    </ScreenContainer>
  );
}
