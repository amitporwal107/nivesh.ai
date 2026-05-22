import React from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { TrendingUp, TrendingDown } from "lucide-react";
import HeroCard from "../../components/HeroCard";
import HeroVizPanel from "../../components/HeroVizPanel";
import CompactCard from "../../components/CompactCard";
import CardStrip from "../../components/CardStrip";
import SectionHead from "../../components/SectionHead";
import PersonaStrip from "../../components/PersonaStrip";
import TinyChip from "../../components/TinyChip";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { PerformanceLine, OverlapDonut, TaxPyramid, GoalBars, HealthGauge } from "../../components/viz";
import { usePersona, usePortfolioSummary, usePortfolioTrend, useGoals } from "../../adapters";
import SourceBanner from "../../components/SourceBanner";
import { inrCompact, pct, dateLabel } from "../../lib/format";

export default function Dashboard() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const { persona } = usePersona();
  const portfolioState = usePortfolioSummary();
  const p = portfolioState.data;
  const trendState = usePortfolioTrend(30);
  const trendPoints = trendState.data?.points || [];
  const benchmarkPoints = trendState.data?.benchmark || [];
  const goalsState = useGoals();
  const primaryGoal = goalsState.data?.goals?.[0] || null;
  const taxFilled = p.tax.unrealizedLtcg && p.tax.harvestable
    ? Math.min(1, p.tax.harvestable / Math.max(1, p.tax.unrealizedLtcg))
    : null;
  const taxWarn = (p.tax.stcg ?? 0) > (p.tax.unrealizedLtcg ?? 0);

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
            description={isDesktop ? `Invested ${inrCompact(p.summary.investedValue)} · XIRR ${p.summary.xirr ? p.summary.xirr + "%" : "—"}. Today's net change is ${inrCompact(p.summary.delta1d)} (${pct(p.summary.delta1dPct, 2)}).` : null}
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
                <PerformanceLine
                  points={trendPoints.length ? trendPoints : undefined}
                  benchmark={benchmarkPoints.length ? benchmarkPoints : undefined}
                  size={isDesktop ? 144 : 96}
                />
              </HeroVizPanel>
            }
            ctaText="Open portfolio detail →"
            onClick={() => navigate("/portfolio")}
          />
        </section>

        <section>
          <SectionHead title="Today's analyses" count="6 cards" />
          <CardStrip ariaLabel="Today's analyses" desktopColumns={3}>
            <CompactCard
              category="health"
              label="Portfolio health score"
              meta={p.risk.score != null ? `SCORE ${p.risk.score}/100` : "—"}
              viz={<HealthGauge score={p.risk.score ?? 0} />}
              onClick={() => navigate("/risk")}
            />
            <CompactCard
              category="risk"
              label="Fund overlap"
              meta={p.overlap.maxPct != null ? `${p.overlap.pairs} PAIRS · MAX ${p.overlap.maxPct}%` : "—"}
              viz={<OverlapDonut value={p.overlap.maxPct ?? 0} color="var(--v3-crimson)" />}
              onClick={() => navigate("/portfolio/exposure?tab=diversification")}
            />
            <CompactCard
              category="performance"
              label="YTD vs benchmark"
              meta={p.performance.ytd != null ? `+${(p.performance.ytd - p.performance.benchmarkYtd).toFixed(1)}% ALPHA` : "—"}
              viz={<PerformanceLine
                points={trendPoints.length ? trendPoints : undefined}
                benchmark={benchmarkPoints.length ? benchmarkPoints : undefined}
              />}
              onClick={() => navigate("/performance")}
            />
            <CompactCard
              category="goal"
              label="Retirement progress"
              meta={p.goals.length ? `${p.goals[0].progress}% · ${inrCompact(p.goals[0].current)}` : "No goals set"}
              viz={<GoalBars goal={primaryGoal} />}
              onClick={() => navigate("/goals")}
            />
            <CompactCard
              category="tax"
              label="Unrealized LTCG"
              meta={p.tax.harvestable != null ? `HARVEST ${inrCompact(p.tax.harvestable)}` : "—"}
              viz={<TaxPyramid filled={taxFilled} warn={taxWarn} />}
              onClick={() => navigate("/tax")}
            />
            <CompactCard
              category="risk"
              label="Drawdown · 1Y"
              meta={p.risk.drawdown != null ? `${p.risk.drawdown}% MAX` : "—"}
              viz={<OverlapDonut value={p.risk.drawdown != null ? Math.abs(p.risk.drawdown) * 4 : 0} color="var(--v3-crimson)" />}
              onClick={() => navigate("/risk")}
            />
          </CardStrip>
        </section>

        <section>
          <SectionHead title="Top holdings" count={p.topHoldings.length ? `${p.topHoldings.length} funds` : "loading…"} />
          {p.topHoldings.length === 0 ? (
            <div
              style={{
                padding: "28px 20px",
                background: "var(--v3-bg-2)",
                border: "1px solid var(--v3-line)",
                borderRadius: 14,
                textAlign: "center",
                color: "var(--v3-ink-3)",
                fontSize: 13,
              }}
            >
              {portfolioState.loading ? "Loading holdings…" : "No holdings — upload a CAS statement."}
            </div>
          ) : (
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
          )}
        </section>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          <TinyChip onClick={() => navigate("/chat?q=What%27s+my+best+fund%3F")}>What's my best fund?</TinyChip>
          <TinyChip onClick={() => navigate("/chat?q=What+changed+today%3F")}>What changed today?</TinyChip>
          <TinyChip onClick={() => navigate("/chat?q=Where+am+I+overexposed%3F")}>Where am I overexposed?</TinyChip>
        </div>
      </div>
    </ScreenContainer>
  );
}
