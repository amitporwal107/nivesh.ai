import React from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { TrendingUp, TrendingDown } from "lucide-react";
import HeroCard from "../../components/HeroCard";
import HeroVizPanel from "../../components/HeroVizPanel";
import CompactCard from "../../components/CompactCard";
import SectionHead from "../../components/SectionHead";
import PersonaStrip from "../../components/PersonaStrip";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { PerformanceLine, OverlapDonut, TaxPyramid, GoalBars, HealthGauge } from "../../components/viz";
import { usePersona, usePortfolioSummary } from "../../adapters";
import SourceBanner from "../../components/SourceBanner";
import { inrCompact, pct, dateLabel } from "../../lib/format";

export default function Dashboard() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const { persona } = usePersona();
  const portfolioState = usePortfolioSummary();
  const p = portfolioState.data;

  const positiveDelta = p.summary.delta1d >= 0;

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      {isDesktop ? (
        <TopBar variant="desktop" eyebrow={dateLabel().toUpperCase()} title={`${p.user.greeting}, ${p.user.name.split(" ")[0]}`} />
      ) : (
        <TopBar variant="mobile" />
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 40 }}>
        <SourceBanner source={p?._source} error={portfolioState.error} loading={portfolioState.loading} onRefresh={portfolioState.refetch} />
        <PersonaStrip persona={persona} onChange={() => navigate("/profile")} />

        <section>
          <SectionHead title="Portfolio" count="Live" />
          <HeroCard
            layout={isDesktop ? "desktop" : "mobile"}
            category="health"
            priorityLabel="Live"
            title={inrCompact(p.summary.totalValue)}
            description={isDesktop ? `Invested ${inrCompact(p.summary.investedValue)} · XIRR ${p.summary.xirr}%. Today's net change is ${inrCompact(p.summary.delta1d)} (${pct(p.summary.delta1dPct, 2)}).` : null}
            viz={
              <HeroVizPanel
                eyebrow="Today's change"
                value={
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: positiveDelta ? "var(--v3-moss)" : "var(--v3-crimson)" }}>
                    {positiveDelta ? <TrendingUp size={20} /> : <TrendingDown size={20} />}
                    {pct(p.summary.delta1dPct, 2)}
                  </span>
                }
                unit={`(${inrCompact(p.summary.delta1d)})`}
                size={isDesktop ? "desktop" : "mobile"}
              >
                <PerformanceLine size={isDesktop ? 144 : 96} />
              </HeroVizPanel>
            }
            ctaText="Open portfolio detail →"
            onClick={() => navigate("/portfolio")}
          />
        </section>

        <section>
          <SectionHead title="Today's analyses" count="6 cards" />
          <div
            style={{
              display: "grid",
              gridTemplateColumns: isDesktop ? "repeat(3, 1fr)" : "1fr 1fr",
              gap: isDesktop ? 14 : 10,
            }}
          >
            <CompactCard
              category="health"
              label="Portfolio health score"
              meta={`SCORE ${p.risk.score}/100`}
              viz={<HealthGauge score={p.risk.score} />}
              onClick={() => navigate("/risk")}
            />
            <CompactCard
              category="risk"
              label="Fund overlap"
              meta={`${p.overlap.pairs} PAIRS · MAX ${p.overlap.maxPct}%`}
              viz={<OverlapDonut value={p.overlap.maxPct} color="var(--v3-crimson)" />}
              onClick={() => navigate("/portfolio/diversification")}
            />
            <CompactCard
              category="performance"
              label="YTD vs benchmark"
              meta={`+${(p.performance.ytd - p.performance.benchmarkYtd).toFixed(1)}% ALPHA`}
              viz={<PerformanceLine />}
              onClick={() => navigate("/performance")}
            />
            <CompactCard
              category="goal"
              label="Retirement progress"
              meta={`${p.goals[0].progress}% · ${inrCompact(p.goals[0].current)}`}
              viz={<GoalBars />}
              onClick={() => navigate("/portfolio")}
            />
            <CompactCard
              category="tax"
              label="Unrealized LTCG"
              meta={`HARVEST ${inrCompact(p.tax.harvestable)}`}
              viz={<TaxPyramid />}
              onClick={() => navigate("/tax")}
            />
            <CompactCard
              category="risk"
              label="Drawdown · 1Y"
              meta={`${p.risk.drawdown}% MAX`}
              viz={<OverlapDonut value={Math.abs(p.risk.drawdown) * 4} color="var(--v3-crimson)" />}
              onClick={() => navigate("/risk")}
            />
          </div>
        </section>

        <section>
          <SectionHead title="Top holdings" count={`${p.topHoldings.length} funds`} />
          <div style={{ display: "flex", flexDirection: "column", gap: 1, background: "var(--v3-line)", border: "1px solid var(--v3-line)", borderRadius: 14, overflow: "hidden" }}>
            {p.topHoldings.map((h, i) => (
              <div
                key={i}
                style={{
                  background: "var(--v3-bg-2)",
                  padding: "14px 16px",
                  display: "grid",
                  gridTemplateColumns: isDesktop ? "2fr 1fr 1fr 1fr" : "1.6fr 1fr 1fr",
                  alignItems: "center",
                  gap: 12,
                }}
              >
                <div>
                  <div style={{ color: "var(--v3-ink-1)", fontSize: 14, fontWeight: 500 }}>{h.name}</div>
                  <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", marginTop: 3, letterSpacing: "0.08em" }}>{h.category}</div>
                </div>
                {isDesktop && (
                  <div className="v3-data" style={{ color: "var(--v3-ink-2)", fontSize: 13, textAlign: "right" }}>
                    {inrCompact(h.value * 0.78)}
                  </div>
                )}
                <div className="v3-data" style={{ color: "var(--v3-ink-1)", fontSize: 13, textAlign: "right" }}>
                  {inrCompact(h.value)}
                </div>
                <div className="v3-data" style={{ color: h.return1y >= 20 ? "var(--v3-moss)" : "var(--v3-ink-1)", fontSize: 13, textAlign: "right" }}>
                  +{h.return1y}%
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </ScreenContainer>
  );
}
