import React, { useMemo, useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { AlertCircle, Target as TargetIcon } from "lucide-react";
import PersonaStrip from "../../components/PersonaStrip";
import CategoryChip from "../../components/CategoryChip";
import CardStrip from "../../components/CardStrip";
import HeroCard from "../../components/HeroCard";
import HeroVizPanel from "../../components/HeroVizPanel";
import CompactCard from "../../components/CompactCard";
import MoreQuestions from "../../components/MoreQuestions";
import Composer from "../../components/Composer";
import SectionHead from "../../components/SectionHead";
import SourceBanner from "../../components/SourceBanner";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { FundCountHistogram, OverlapDonut, PerformanceLine, GoalBars, TaxPyramid } from "../../components/viz";
import { usePersona, usePortfolioSummary, usePortfolioTrend, useSuggestedPrompts, countsByCategory, useInsights, topActions, intelligenceFeed, useGoals } from "../../adapters";
import { loadPortfolio } from "../../adapters/portfolio";
import { dateLabel, inrCompact } from "../../lib/format";

const CATEGORIES = [
  { id: "all", label: "All" },
  { id: "health", label: "Health" },
  { id: "performance", label: "Performance" },
  { id: "risk", label: "Risk" },
  { id: "tax", label: "Tax" },
  { id: "goal", label: "Goal" },
];

export default function CopilotHome() {
  const navigate = useNavigate();
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const { persona } = usePersona();
  const portfolioState = usePortfolioSummary();
  const portfolio = portfolioState.data || loadPortfolio();
  const { data: catalogData } = useSuggestedPrompts(persona.id);
  const catalog = useMemo(
    () => catalogData || { primary: null, secondary: [], advanced: [] },
    [catalogData]
  );
  const [activeCat, setActiveCat] = useState("all");
  const counts = useMemo(() => countsByCategory(catalog), [catalog]);
  const insightsState = useInsights();
  const insights = useMemo(() => insightsState.data?.insights || [], [insightsState.data]);
  const topActionList = useMemo(() => topActions(insights), [insights]);
  const feedList = useMemo(() => intelligenceFeed(insights), [insights]);
  const goalsState = useGoals();
  const goals = goalsState.data?.goals || [];
  const primaryGoal = goals[0] || null;
  const trendState = usePortfolioTrend(30);
  const trendPoints = trendState.data?.points || [];
  const benchmarkPoints = trendState.data?.benchmark || [];
  const taxFilled = portfolio.tax?.unrealizedLtcg && portfolio.tax?.harvestable
    ? Math.min(1, portfolio.tax.harvestable / Math.max(1, portfolio.tax.unrealizedLtcg))
    : null;
  const taxWarn = (portfolio.tax?.stcg ?? 0) > (portfolio.tax?.unrealizedLtcg ?? 0);

  const onPromptSubmit = ({ text }) => {
    const params = new URLSearchParams({ q: text });
    navigate(`/chat?${params.toString()}`);
  };

  const filteredSecondary = useMemo(() => {
    if (activeCat === "all") return catalog.secondary;
    return catalog.secondary.filter((p) => p.category === activeCat);
  }, [catalog, activeCat]);

  const filteredAdvanced = useMemo(() => {
    if (activeCat === "all") return catalog.advanced;
    return catalog.advanced.filter((p) => p.category === activeCat);
  }, [catalog, activeCat]);

  const hero = catalog.primary || { label: persona.heroQuestion, category: persona.heroCategory || "health" };
  const heroViz = renderHeroViz(hero.category, portfolio, isDesktop, {
    trendPoints, benchmarkPoints, primaryGoal, taxFilled, taxWarn,
  });
  const heroDescription = pickHeroDescription(persona.id);

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      {isDesktop ? (
        <TopBar
          variant="desktop"
          eyebrow={dateLabel().toUpperCase()}
          title={`${portfolio.user.greeting}, ${portfolio.user.name.split(" ")[0]}`}
        />
      ) : (
        <TopBar variant="mobile" onMenu={() => navigate("/settings")} onHistory={() => navigate("/chat")} />
      )}

      <div style={{ padding: isDesktop ? 0 : 0, display: "flex", flexDirection: "column", gap: isDesktop ? 24 : 18 }}>
        <SourceBanner
          source={portfolio?._source}
          error={portfolioState.error}
          loading={portfolioState.loading}
          onRefresh={portfolioState.refetch}
        />

        <PersonaStrip
          persona={persona}
          onChange={() => navigate("/profile")}
          tagline={composeTagline(persona.id, portfolio)}
          highlight={composeHighlight(persona.id, portfolio)}
        />

        <div className="v3-hscroll" style={{ display: "flex", gap: 6 }}>
          {CATEGORIES.map((c) => (
            <CategoryChip
              key={c.id}
              category={c.id}
              label={c.label}
              count={counts[c.id]}
              active={activeCat === c.id}
              onClick={() => setActiveCat(c.id)}
            />
          ))}
        </div>

        <section>
          <SectionHead title="Start here" count="1 priority" />
          <HeroCard
            layout={isDesktop ? "desktop" : "mobile"}
            category={hero.category}
            priorityLabel="For you"
            title={hero.label}
            description={isDesktop ? heroDescription : null}
            viz={heroViz}
            ctaText={pickCtaText(hero.category)}
            onClick={() => onPromptSubmit({ text: hero.label })}
          />
        </section>

        {topActionList.length > 0 && (
          <section>
            <SectionHead title="Top actions" count={`${topActionList.length} priorities`} />
            <CardStrip ariaLabel="Top actions" desktopColumns={3}>
              {topActionList.map((ins, i) => (
                <CompactCard
                  key={ins.insight_id || i}
                  category={mapInsightCategory(ins.category)}
                  label={ins.title || ins.action || "Action"}
                  meta={ins.current_value && ins.target_value
                    ? `${ins.current_value} → ${ins.target_value}`
                    : (ins.action || ins.impact || "").toString().toUpperCase()}
                  onClick={() => onPromptSubmit({ text: ins.action || ins.title || "Tell me more" })}
                />
              ))}
            </CardStrip>
          </section>
        )}

        <section>
          <SectionHead title="Quick analyses" count={`${filteredSecondary.length} cards`} />
          <div
            style={{
              display: "grid",
              gridTemplateColumns: isDesktop ? "repeat(3, 1fr)" : "1fr 1fr",
              gap: isDesktop ? 14 : 10,
            }}
          >
            {filteredSecondary.map((p, i) => (
              <CompactCard
                key={i}
                category={p.category}
                label={p.label}
                meta={pickMeta(p.category, portfolio)}
                viz={renderCompactViz(p.category, portfolio, { trendPoints, benchmarkPoints, primaryGoal, taxFilled, taxWarn })}
                onClick={() => onPromptSubmit({ text: p.label })}
              />
            ))}
          </div>
        </section>

        {feedList.length > 0 && (
          <section>
            <SectionHead title="Intelligence feed" count={`${feedList.length} insights`} />
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {feedList.map((ins, i) => (
                <FeedRow
                  key={ins.insight_id || i}
                  insight={ins}
                  onClick={() => onPromptSubmit({ text: ins.action || ins.title || "Tell me more" })}
                />
              ))}
            </div>
          </section>
        )}

        {goals.length > 0 && (
          <section>
            <SectionHead title="Goals progress" count={`${goals.length} goal${goals.length === 1 ? "" : "s"}`} />
            <div style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 14, padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
              {goals.slice(0, 4).map((g, i) => (
                <GoalRow key={g.id || i} goal={g} onClick={() => navigate("/goals")} />
              ))}
              <button
                type="button"
                onClick={() => navigate("/goals")}
                style={{ marginTop: 4, fontSize: 12, color: "var(--v3-saffron)", background: "none", border: "none", cursor: "pointer", padding: 0, alignSelf: "flex-start" }}
              >
                Open Goals →
              </button>
            </div>
          </section>
        )}

        <section>
          <MoreQuestions
            items={filteredAdvanced.map((p) => ({ label: p.label, category: p.category }))}
            onPick={(item) => onPromptSubmit({ text: item.label })}
          />
        </section>
      </div>

      <Composer
        onSubmit={onPromptSubmit}
        pickerMode={isDesktop ? "popover" : "sheet"}
        personaId={persona.id}
        sticky
      />
    </ScreenContainer>
  );
}

function renderHeroViz(category, portfolio, isDesktop, vizData = {}) {
  const { trendPoints = [], benchmarkPoints = [], primaryGoal = null, taxFilled = null, taxWarn = false } = vizData;
  switch (category) {
    case "health":
      return (
        <HeroVizPanel
          eyebrow="Fund count"
          value={portfolio.funds.count}
          unit={`/ ideal ${portfolio.funds.idealMin}–${portfolio.funds.idealMax}`}
          size={isDesktop ? "desktop" : "mobile"}
        >
          <FundCountHistogram
            count={portfolio.funds.count}
            idealMin={portfolio.funds.idealMin}
            idealMax={portfolio.funds.idealMax}
            height={isDesktop ? 92 : 64}
            showIdealLabel={isDesktop}
            showYouLabel={isDesktop}
          />
        </HeroVizPanel>
      );
    case "risk":
      return (
        <HeroVizPanel eyebrow="Risk score" value={portfolio.risk.score ?? "—"} unit="/ 100" size={isDesktop ? "desktop" : "mobile"}>
          <div style={{ display: "flex", justifyContent: "center", padding: "12px 0" }}>
            <OverlapDonut value={portfolio.risk.score ?? 0} color="var(--v3-saffron)" size={isDesktop ? 96 : 72} label="Risk gauge" />
          </div>
        </HeroVizPanel>
      );
    case "performance":
      return (
        <HeroVizPanel eyebrow="YTD return" value={portfolio.performance.ytd != null ? `${portfolio.performance.ytd}%` : "—"} size={isDesktop ? "desktop" : "mobile"}>
          <PerformanceLine
            points={trendPoints.length ? trendPoints : undefined}
            benchmark={benchmarkPoints.length ? benchmarkPoints : undefined}
            size={isDesktop ? 144 : 96}
          />
        </HeroVizPanel>
      );
    case "tax":
      return (
        <HeroVizPanel
          eyebrow="Unrealized LTCG"
          value={portfolio.tax.unrealizedLtcg != null ? `₹${(portfolio.tax.unrealizedLtcg / 1000).toFixed(0)}k` : "—"}
          size={isDesktop ? "desktop" : "mobile"}
        >
          <div style={{ display: "flex", justifyContent: "center", padding: 8 }}>
            <TaxPyramid filled={taxFilled} warn={taxWarn} size={isDesktop ? 96 : 64} />
          </div>
        </HeroVizPanel>
      );
    case "goal":
      return (
        <HeroVizPanel
          eyebrow="Retirement progress"
          value={portfolio.goals.length ? `${portfolio.goals[0].progress}%` : "—"}
          size={isDesktop ? "desktop" : "mobile"}
        >
          <GoalBars goal={primaryGoal} size={isDesktop ? 96 : 64} />
        </HeroVizPanel>
      );
    default:
      return null;
  }
}

function renderCompactViz(category, portfolio, vizData = {}) {
  const { trendPoints = [], benchmarkPoints = [], primaryGoal = null, taxFilled = null, taxWarn = false } = vizData;
  switch (category) {
    case "risk":
      return <OverlapDonut value={portfolio.overlap.maxPct ?? 0} color="var(--v3-crimson)" />;
    case "performance":
      return <PerformanceLine
        points={trendPoints.length ? trendPoints : undefined}
        benchmark={benchmarkPoints.length ? benchmarkPoints : undefined}
      />;
    case "goal":
      return <GoalBars goal={primaryGoal} />;
    case "tax":
      return <TaxPyramid filled={taxFilled} warn={taxWarn} />;
    case "health":
      return <OverlapDonut value={portfolio.risk.score ?? 0} color="var(--v3-moss)" />;
    default:
      return null;
  }
}

function pickMeta(category, p) {
  switch (category) {
    case "risk":
      return p.overlap.maxPct != null ? `${p.overlap.pairs} PAIRS · MAX ${p.overlap.maxPct}%` : "—";
    case "performance":
      return p.performance.ytd != null ? `YTD ${p.performance.ytd}% · BENCH ${p.performance.benchmarkYtd}%` : "—";
    case "goal":
      return p.sip.monthly ? `₹${(p.sip.monthly / 1000).toFixed(0)}K/MO · GAP ₹${(p.sip.gap / 1000).toFixed(0)}K` : "—";
    case "tax":
      return p.tax.harvestable != null ? `HARVEST ₹${(p.tax.harvestable / 1000).toFixed(0)}K` : "—";
    case "health":
      return p.risk.score != null ? `SCORE ${p.risk.score}/100` : "—";
    default:
      return null;
  }
}

function pickCtaText(category) {
  switch (category) {
    case "health":
      return "Show me the overlap heatmap →";
    case "risk":
      return "Show me the downside scenarios →";
    case "performance":
      return "Show me the benchmark drill-down →";
    case "tax":
      return "Show me harvest candidates →";
    case "goal":
      return "Show me the projection →";
    default:
      return "Open analysis →";
  }
}

// Compose the persona tagline using the user's REAL portfolio numbers.
// Falls back to the static persona.tagline (via PersonaStrip default) only
// when we don't have a personalised template for that persona id.
function composeTagline(personaId, p) {
  if (!p) return null;
  const inr = (n) => {
    if (n == null) return "—";
    if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
    if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
    return `₹${Math.round(n).toLocaleString("en-IN")}`;
  };
  switch (personaId) {
    case "mf_focused":
      if (p.funds?.count == null) return null;
      return `You hold ${p.funds.count} funds across ${p.funds.amcCount} AMCs. We'll focus on overlap, fund quality, and expense-ratio leakage.`;
    case "hni":
      if (p.summary?.totalValue == null) return null;
      return `${inr(p.summary.totalValue)} portfolio — multi-asset wealth with tax, estate, and alternative-asset overlays.`;
    case "tax_conscious":
      if (p.tax?.unrealizedLtcg == null) return null;
      return `${inr(p.tax.unrealizedLtcg)} unrealized LTCG · Tax-impact lens on every recommendation, FY-aware harvesting.`;
    case "direct_equity":
      if (!p.topHoldings?.length) return null;
      return `${p.topHoldings.length} positions on the watchlist. Valuation, fundamentals, sector views, and concentration discipline.`;
    case "retirement_planner": {
      const ret = p.goals?.find((g) => /retire/i.test(g.name || ""));
      if (!ret) return null;
      return `${ret.progress}% of the retirement corpus secured. Income, withdrawal, and inflation lens with downside emphasis.`;
    }
    case "parents_for_kids": {
      const ed = p.goals?.find((g) => /child|edu/i.test(g.name || ""));
      if (!ed) return null;
      return `Child education goal: ${ed.progress}% funded. Goal-progress first, shortfall surfacing, insurance overlay.`;
    }
    case "active_trader":
      if (p.performance?.ytd == null) return null;
      return `YTD ${p.performance.ytd}% — realized P&L, momentum, sector rotation, position-level depth.`;
    case "conservative":
      if (!p.allocation?.length) return null;
      const equityPct = p.allocation.find((a) => /equity/i.test(a.label))?.value ?? 0;
      return `${equityPct}% in equity · Downside-first, FD-comparable framing, debt-and-hybrid focus.`;
    default:
      return null;
  }
}

// Highlight phrase inside the dynamic tagline (the phrase rendered in the
// persona accent colour). Must be a literal substring of composeTagline.
function composeHighlight(personaId, p) {
  if (!p) return null;
  switch (personaId) {
    case "mf_focused":
      return p.funds?.count != null ? `${p.funds.count} funds across ${p.funds.amcCount} AMCs` : null;
    case "hni":
      return p.summary?.totalValue != null
        ? (p.summary.totalValue >= 1e7
            ? `₹${(p.summary.totalValue / 1e7).toFixed(2)} Cr`
            : `₹${(p.summary.totalValue / 1e5).toFixed(2)} L`)
        : null;
    case "tax_conscious":
      return p.tax?.unrealizedLtcg != null
        ? (p.tax.unrealizedLtcg >= 1e5
            ? `₹${(p.tax.unrealizedLtcg / 1e5).toFixed(2)} L`
            : `₹${Math.round(p.tax.unrealizedLtcg).toLocaleString("en-IN")}`)
        : null;
    default:
      return null;
  }
}

// Map backend `insight.category` strings (risk / tax / performance / goal /
// cost / health) into V3's CompactCard category palette.
function mapInsightCategory(c) {
  const k = (c || "").toLowerCase();
  if (["risk", "tax", "goal", "performance", "health"].includes(k)) return k;
  if (k === "cost") return "tax";
  return "health";
}

function FeedRow({ insight, onClick }) {
  const impact = (insight.impact || "").toLowerCase();
  const tone = impact === "high"   ? { bg: "var(--v3-crimson-soft)", color: "var(--v3-crimson)" }
             : impact === "medium" ? { bg: "#D4AF3726",              color: "var(--v3-gold)" }
             :                       { bg: "var(--v3-bg-3)",         color: "var(--v3-ink-3)" };
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: "var(--v3-bg-2)",
        border: "1px solid var(--v3-line)",
        borderRadius: 10,
        padding: "12px 14px",
        textAlign: "left",
        display: "flex",
        alignItems: "flex-start",
        gap: 12,
        cursor: "pointer",
        width: "100%",
        fontFamily: "inherit",
      }}
    >
      <span style={{ width: 28, height: 28, borderRadius: 8, background: tone.bg, color: tone.color, display: "grid", placeItems: "center", flexShrink: 0 }}>
        <AlertCircle size={14} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: "var(--v3-ink-1)", fontWeight: 500, lineHeight: 1.3 }}>
          {insight.title || "—"}
        </div>
        {insight.description && (
          <div style={{ fontSize: 11, color: "var(--v3-ink-4)", marginTop: 4, lineHeight: 1.4 }}>
            {insight.description.length > 140 ? `${insight.description.slice(0, 140)}…` : insight.description}
          </div>
        )}
      </div>
      {insight.impact && (
        <span className="v3-data" style={{ padding: "2px 7px", borderRadius: 999, background: tone.bg, color: tone.color, fontSize: 9, fontWeight: 600, letterSpacing: "0.05em", whiteSpace: "nowrap", flexShrink: 0 }}>
          {insight.impact.toUpperCase()}
        </span>
      )}
    </button>
  );
}

function GoalRow({ goal, onClick }) {
  const target = Number(goal.target_amount_rs ?? goal.target_amount ?? 0);
  const current = Number(goal.current_amount_rs ?? goal.current_amount ?? 0);
  const pctOn = goal.on_track_pct ?? goal.progress ?? (target > 0 ? Math.round((current / target) * 100) : null);
  const accent = pctOn == null ? "var(--v3-ink-3)"
    : pctOn >= 80 ? "var(--v3-moss)"
    : pctOn >= 50 ? "var(--v3-gold)"
    : "var(--v3-crimson)";
  return (
    <button
      type="button"
      onClick={onClick}
      style={{ background: "transparent", border: "none", padding: 0, textAlign: "left", cursor: "pointer", fontFamily: "inherit" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <span style={{ width: 24, height: 24, borderRadius: 6, background: "var(--v3-bg-3)", display: "grid", placeItems: "center", color: accent, flexShrink: 0 }}>
          <TargetIcon size={12} />
        </span>
        <span style={{ flex: 1, fontSize: 13, color: "var(--v3-ink-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {goal.goal_name || goal.name || "Goal"}
        </span>
        <span className="v3-data" style={{ fontSize: 12, color: accent, fontWeight: 600 }}>
          {pctOn != null ? `${pctOn}%` : "—"}
        </span>
      </div>
      <div style={{ height: 5, background: "var(--v3-bg-3)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${Math.max(0, Math.min(100, pctOn ?? 0))}%`, height: "100%", background: accent, borderRadius: 3 }} />
      </div>
      {target > 0 && (
        <div style={{ fontSize: 10, color: "var(--v3-ink-4)", marginTop: 4 }}>
          {inrCompact(current)} of {inrCompact(target)}
        </div>
      )}
    </button>
  );
}

function pickHeroDescription(personaId) {
  const MAP = {
    salaried_beginner: "We'll compare your line-up against an ideal diversified portfolio and call out anything that increases risk or eats into long-term returns.",
    mf_focused: "Most retail portfolios over 7 funds suffer overlap and diluted alpha. We'll compare your line-up against ideal counts and surface the redundant ones.",
    direct_equity: "We'll flag positions where current valuation exceeds historical median by more than one standard deviation — your candidates for trimming.",
    hni: "We'll cross-check your equity / debt / gold / international mix against your risk profile and target allocation, then surface the largest drifts.",
    retirement_planner: "We'll project your retirement corpus against your monthly need, show the probability of running out of money, and flag any shortfall.",
    parents_for_kids: "We'll compare your current trajectory against the education-goal target and call out the monthly SIP gap.",
    tax_conscious: "We'll surface every unrealized LTCG/STCG position, harvest candidates, and the optimal sequence for FY-end execution.",
    conservative: "We'll quantify your downside in a 20% market drop, your debt allocation, and how it stacks against an FD-comparable baseline.",
    active_trader: "We'll rank every position by realized P&L, flag drawdown-bearing holdings, and surface the sectors with the strongest momentum this quarter.",
    nri_global: "We'll show your India vs international split, currency exposure, and tax-treaty-aware optimization opportunities.",
    universal: "A 60-second health check across diversification, drift, and downside — with the single best next action.",
  };
  return MAP[personaId] || MAP.universal;
}
