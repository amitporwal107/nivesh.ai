import React, { useMemo, useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import PersonaStrip from "../../components/PersonaStrip";
import CategoryChip from "../../components/CategoryChip";
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
import { usePersona, usePortfolioSummary, useSuggestedPrompts, countsByCategory } from "../../adapters";
import { loadPortfolio } from "../../adapters/portfolio";
import { dateLabel } from "../../lib/format";

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
  const heroViz = renderHeroViz(hero.category, portfolio, isDesktop);
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

        <PersonaStrip persona={persona} onChange={() => navigate("/profile")} />

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
                viz={renderCompactViz(p.category, portfolio)}
                onClick={() => onPromptSubmit({ text: p.label })}
              />
            ))}
          </div>
        </section>

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

function renderHeroViz(category, portfolio, isDesktop) {
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
        <HeroVizPanel eyebrow="Risk score" value={portfolio.risk.score} unit="/ 100" size={isDesktop ? "desktop" : "mobile"}>
          <div style={{ display: "flex", justifyContent: "center", padding: "12px 0" }}>
            <OverlapDonut value={portfolio.risk.score} color="var(--v3-saffron)" size={isDesktop ? 96 : 72} label="Risk gauge" />
          </div>
        </HeroVizPanel>
      );
    case "performance":
      return (
        <HeroVizPanel eyebrow="YTD return" value={`${portfolio.performance.ytd}%`} size={isDesktop ? "desktop" : "mobile"}>
          <PerformanceLine size={isDesktop ? 144 : 96} />
        </HeroVizPanel>
      );
    case "tax":
      return (
        <HeroVizPanel
          eyebrow="Unrealized LTCG"
          value={`₹${(portfolio.tax.unrealizedLtcg / 1000).toFixed(0)}k`}
          size={isDesktop ? "desktop" : "mobile"}
        >
          <div style={{ display: "flex", justifyContent: "center", padding: 8 }}>
            <TaxPyramid size={isDesktop ? 96 : 64} />
          </div>
        </HeroVizPanel>
      );
    case "goal":
      return (
        <HeroVizPanel
          eyebrow="Retirement progress"
          value={`${portfolio.goals[0].progress}%`}
          size={isDesktop ? "desktop" : "mobile"}
        >
          <GoalBars size={isDesktop ? 96 : 64} />
        </HeroVizPanel>
      );
    default:
      return null;
  }
}

function renderCompactViz(category, portfolio) {
  switch (category) {
    case "risk":
      return <OverlapDonut value={portfolio.overlap.maxPct} color="var(--v3-crimson)" />;
    case "performance":
      return <PerformanceLine />;
    case "goal":
      return <GoalBars />;
    case "tax":
      return <TaxPyramid />;
    case "health":
      return <OverlapDonut value={portfolio.risk.score} color="var(--v3-moss)" />;
    default:
      return null;
  }
}

function pickMeta(category, p) {
  switch (category) {
    case "risk":
      return `${p.overlap.pairs} PAIRS · MAX ${p.overlap.maxPct}%`;
    case "performance":
      return `YTD ${p.performance.ytd}% · BENCH ${p.performance.benchmarkYtd}%`;
    case "goal":
      return `₹${(p.sip.monthly / 1000).toFixed(0)}K/MO · GAP ₹${(p.sip.gap / 1000).toFixed(0)}K`;
    case "tax":
      return `HARVEST ₹${(p.tax.harvestable / 1000).toFixed(0)}K`;
    case "health":
      return `SCORE ${p.risk.score}/100`;
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
