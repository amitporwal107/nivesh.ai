import React from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import HeroCard from "../../components/HeroCard";
import HeroVizPanel from "../../components/HeroVizPanel";
import CompactCard from "../../components/CompactCard";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { OverlapDonut, HealthGauge, PerformanceLine } from "../../components/viz";
import { usePortfolioSummary } from "../../adapters";
import { inrCompact, pct } from "../../lib/format";

export default function RiskAnalysis() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const { data: p } = usePortfolioSummary();

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Risk" title="How much risk are you taking?" />
      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 40 }}>
        <HeroCard
          layout={isDesktop ? "desktop" : "mobile"}
          category="risk"
          priorityLabel="Score"
          title={`${p.risk.level} · score ${p.risk.score}/100`}
          description={isDesktop ? `1-year max drawdown was ${p.risk.drawdown}%. Your portfolio's beta is roughly 1.08 against Nifty 500 — moderately aggressive. Suitability check vs your profile passes; concentration alert is active.` : null}
          viz={
            <HeroVizPanel eyebrow="Drawdown · 1Y" value={pct(p.risk.drawdown, 1)} size={isDesktop ? "desktop" : "mobile"}>
              <PerformanceLine size={isDesktop ? 144 : 96} color="var(--v3-crimson)" />
            </HeroVizPanel>
          }
          ctaText="Run a stress test →"
          onClick={() => navigate("/risk/stress")}
        />

        <SectionHead title="Risk dimensions" count="6 cards" />
        <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(3, 1fr)" : "1fr 1fr", gap: 12 }}>
          <CompactCard category="risk" label="Volatility (1Y)" meta="22.4% ANNUALIZED" viz={<OverlapDonut value={62} color="var(--v3-saffron)" />} />
          <CompactCard category="risk" label="Sharpe (1Y)" meta="0.81 · GOOD" viz={<HealthGauge score={68} />} />
          <CompactCard category="risk" label="Beta vs Nifty 500" meta="1.08 · slightly aggressive" viz={<OverlapDonut value={54} color="var(--v3-gold)" />} />
          <CompactCard category="risk" label="Concentration HHI" meta="1840 · ABOVE 1500" viz={<OverlapDonut value={74} color="var(--v3-crimson)" />} />
          <CompactCard category="risk" label="Drawdown (1Y)" meta={`${pct(p.risk.drawdown, 1)} · acceptable`} viz={<OverlapDonut value={Math.abs(p.risk.drawdown) * 4} color="var(--v3-crimson)" />} />
          <CompactCard category="risk" label="Liquidity score" meta="92 · STRONG" viz={<HealthGauge score={92} />} />
        </div>

        <SectionHead title="Suitability" count="vs your profile" />
        <div style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 14, padding: 18, display: "flex", flexDirection: "column", gap: 10 }}>
          <SuitRow label="Equity allocation" current={64} target={60} band={10} />
          <SuitRow label="Debt allocation" current={22} target={30} band={10} />
          <SuitRow label="Gold allocation" current={8} target={5} band={5} />
          <SuitRow label="International allocation" current={6} target={5} band={5} />
        </div>
      </div>
    </ScreenContainer>
  );
}

function SuitRow({ label, current, target, band }) {
  const inBand = Math.abs(current - target) <= band;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr", alignItems: "center", gap: 12 }}>
      <span style={{ color: "var(--v3-ink-1)", fontSize: 13 }}>{label}</span>
      <span className="v3-data" style={{ color: "var(--v3-ink-2)", fontSize: 13 }}>{current}% / target {target}%</span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6, justifySelf: "end", fontSize: 12, color: inBand ? "var(--v3-moss)" : "var(--v3-crimson)" }}>
        <span style={{ width: 7, height: 7, borderRadius: 999, background: "currentColor" }} />
        {inBand ? "In band" : "Drift"}
      </span>
    </div>
  );
}
