import React, { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import HeroCard from "../../components/HeroCard";
import HeroVizPanel from "../../components/HeroVizPanel";
import CompactCard from "../../components/CompactCard";
import CategoryChip from "../../components/CategoryChip";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { PerformanceLine } from "../../components/viz";
import { usePortfolioSummary } from "../../adapters";
import { pct } from "../../lib/format";

const PERIODS = [
  { id: "1m", label: "1M" },
  { id: "3m", label: "3M" },
  { id: "6m", label: "6M" },
  { id: "ytd", label: "YTD" },
  { id: "1y", label: "1Y" },
  { id: "3y", label: "3Y" },
];

export default function Performance() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const { data: p } = usePortfolioSummary();
  const [period, setPeriod] = useState("ytd");

  const value = period === "ytd" ? p.performance.ytd : period === "1y" ? p.performance.oneY : period === "3y" ? p.performance.threeY : 8.2;
  const benchmark = period === "ytd" ? p.performance.benchmarkYtd : period === "1y" ? 18.4 : period === "3y" ? 12.6 : 6.4;
  const alpha = value - benchmark;

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Performance" title="Returns and benchmarking" />
      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 40 }}>
        <div className="v3-hscroll" style={{ display: "flex", gap: 6 }}>
          {PERIODS.map((pr) => (
            <CategoryChip
              key={pr.id}
              category="performance"
              label={pr.label}
              active={period === pr.id}
              onClick={() => setPeriod(pr.id)}
            />
          ))}
        </div>

        <HeroCard
          layout={isDesktop ? "desktop" : "mobile"}
          category="performance"
          priorityLabel={period.toUpperCase()}
          title={`${pct(value, 1)} vs benchmark ${pct(benchmark, 1)}`}
          description={isDesktop ? `Alpha for the period is ${pct(alpha, 1)}. Your top contributors are small-cap and flexi-cap; the laggards are a sectoral fund and a short-duration debt.` : null}
          viz={
            <HeroVizPanel eyebrow="Alpha" value={pct(alpha, 1)} size={isDesktop ? "desktop" : "mobile"}>
              <PerformanceLine size={isDesktop ? 144 : 96} />
            </HeroVizPanel>
          }
          ctaText="Show me the laggards →"
          onClick={() => navigate("/chat?q=Which%20funds%20are%20dragging%20performance")}
        />

        <SectionHead title="Breakdown" count="6 cards" />
        <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(3, 1fr)" : "1fr 1fr", gap: 12 }}>
          <CompactCard category="performance" label="Top contributor" meta="Nippon SC · +42.6%" viz={<PerformanceLine color="var(--v3-moss)" />} />
          <CompactCard category="performance" label="Worst drag" meta="DSP Pharma · −4.1%" viz={<PerformanceLine color="var(--v3-crimson)" />} />
          <CompactCard category="performance" label="Best risk-adjusted" meta="PPFAS · SR 1.12" viz={<PerformanceLine color="var(--v3-gold)" />} />
          <CompactCard category="performance" label="vs category top quartile" meta="3 above · 2 below" viz={<PerformanceLine />} />
          <CompactCard category="performance" label="SIP IRR" meta="14.2%" viz={<PerformanceLine />} />
          <CompactCard category="performance" label="Realized P&L (FY)" meta="₹38,200 · STCG" viz={<PerformanceLine color="var(--v3-saffron)" />} />
        </div>
      </div>
    </ScreenContainer>
  );
}
