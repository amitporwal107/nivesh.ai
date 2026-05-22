import React, { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { TrendingUp, TrendingDown } from "lucide-react";
import HeroCard from "../../components/HeroCard";
import HeroVizPanel from "../../components/HeroVizPanel";
import CompactCard from "../../components/CompactCard";
import CardStrip from "../../components/CardStrip";
import SectionHead from "../../components/SectionHead";
import CategoryChip from "../../components/CategoryChip";
import TinyChip from "../../components/TinyChip";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { OverlapDonut, GoalBars, TaxPyramid, PerformanceLine } from "../../components/viz";
import { usePortfolioSummary, usePortfolioTrend, useGoals } from "../../adapters";
import SourceBanner from "../../components/SourceBanner";
import { inrCompact, pct } from "../../lib/format";

const DECISION_TONE = {
  EXIT:     { bg: "var(--v3-crimson-soft)", color: "var(--v3-crimson)" },
  SELL:     { bg: "var(--v3-crimson-soft)", color: "var(--v3-crimson)" },
  REDUCE:   { bg: "#D4AF3726",              color: "var(--v3-gold)"     },
  SWITCH:   { bg: "#D4AF3726",              color: "var(--v3-gold)"     },
  REVIEW:   { bg: "var(--v3-indigo-soft)",  color: "var(--v3-indigo)"   },
  HOLD:     { bg: "var(--v3-bg-3)",         color: "var(--v3-ink-3)"    },
  BUY:      { bg: "var(--v3-moss-soft)",    color: "var(--v3-moss)"     },
  ADD:      { bg: "var(--v3-moss-soft)",    color: "var(--v3-moss)"     },
  INCREASE: { bg: "var(--v3-moss-soft)",    color: "var(--v3-moss)"     },
};

function DecisionBadge({ action, title }) {
  if (!action) return null;
  const tone = DECISION_TONE[action] || DECISION_TONE.HOLD;
  return (
    <span
      title={title || action}
      style={{
        padding: "3px 8px",
        borderRadius: 999,
        background: tone.bg,
        color: tone.color,
        fontFamily: "var(--v3-font-mono)",
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: "0.06em",
        whiteSpace: "nowrap",
      }}
    >
      {action}
    </span>
  );
}

const CATEGORIES = [
  { id: "all", label: "All" },
  { id: "performance", label: "Top return" },
  { id: "risk", label: "Volatile" },
  { id: "tax", label: "Tax candidates" },
  { id: "goal", label: "Goal-linked" },
];

export default function Portfolio() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
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
  const [activeCat, setActiveCat] = useState("all");

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Portfolio" title="Your holdings" />

      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 40 }}>
        <SourceBanner source={p?._source} error={portfolioState.error} loading={portfolioState.loading} onRefresh={portfolioState.refetch} />
        <HeroCard
          layout={isDesktop ? "desktop" : "mobile"}
          category="health"
          priorityLabel="Snapshot"
          title={inrCompact(p.summary.totalValue)}
          description={isDesktop ? `Invested ${inrCompact(p.summary.investedValue)} · ${pct(p.summary.delta1dPct, 2)} today · XIRR ${p.summary.xirr ? p.summary.xirr + "%" : "—"}.` : null}
          viz={
            <HeroVizPanel
              eyebrow="Allocation"
              value={p.allocation.length ? `${p.allocation[0].value}%` : "—"}
              unit={p.allocation.length ? p.allocation[0].label?.toLowerCase() : ""}
              size={isDesktop ? "desktop" : "mobile"}
            >
              <StackedAllocationBar data={p.allocation} />
            </HeroVizPanel>
          }
          ctaText="Compare against ideal allocation →"
          onClick={() => navigate("/portfolio/diversification")}
        />

        <section>
          <SectionHead title="Lenses" />
          <div className="v3-hscroll" style={{ display: "flex", gap: 6 }}>
            {CATEGORIES.map((c) => (
              <CategoryChip
                key={c.id}
                category={c.id}
                label={c.label}
                active={activeCat === c.id}
                onClick={() => setActiveCat(c.id)}
              />
            ))}
          </div>
        </section>

        <section>
          <SectionHead title="Quick lenses" count="6 cards" />
          <CardStrip ariaLabel="Portfolio lenses" desktopColumns={3}>
            <CompactCard
              category="risk"
              label="Diversification"
              meta={p.overlap.maxPct != null ? `${p.overlap.maxPct}% max overlap` : "See full overlap heatmap"}
              viz={<OverlapDonut value={p.overlap.maxPct ?? 0} color="var(--v3-crimson)" />}
              onClick={() => navigate("/portfolio/exposure?tab=diversification")}
            />
            <CompactCard
              category="tax"
              label="Tax candidates"
              meta={p.tax.harvestable != null ? `HARVEST ${inrCompact(p.tax.harvestable)}` : "—"}
              viz={<TaxPyramid filled={taxFilled} warn={taxWarn} />}
              onClick={() => navigate("/tax")}
            />
            <CompactCard
              category="goal"
              label="Goal-linked holdings"
              meta={`${p.goals.length} GOALS LINKED`}
              viz={<GoalBars goal={primaryGoal} />}
              onClick={() => navigate("/goals")}
            />
            <CompactCard
              category="risk"
              label="Duplicate funds"
              meta={
                p.funds.duplicateCount > 0
                  ? `${p.funds.duplicateCount} CLUSTER${p.funds.duplicateCount === 1 ? "" : "S"} · ${inrCompact(p.funds.duplicateValue)}`
                  : "No duplicates detected"
              }
              viz={<OverlapDonut value={Math.min(100, (p.funds.duplicateCount || 0) * 25)} color={p.funds.duplicateCount > 0 ? "var(--v3-crimson)" : "var(--v3-moss)"} />}
              onClick={() => navigate("/chat?q=Which+duplicate+funds+should+I+exit")}
            />
            <CompactCard
              category="tax"
              label="Regular → Direct savings"
              meta={
                p.funds.regularDirectAnnualLeak > 0
                  ? `${inrCompact(p.funds.regularDirectAnnualLeak)} / YEAR`
                  : "Already on direct plans"
              }
              viz={<TaxPyramid
                filled={p.funds.regularDirectAnnualLeak > 0 ? Math.min(1, p.funds.regularDirectAnnualLeak / 50000) : 0}
                warn={p.funds.regularDirectAnnualLeak > 25000}
              />}
              onClick={() => navigate("/chat?q=Help+me+move+regular+plans+to+direct")}
            />
            <CompactCard
              category="performance"
              label={p.topGainers[0] ? `Top gainer · ${p.topGainers[0].name}` : "Top gainer"}
              meta={p.topGainers[0] ? `${pct(p.topGainers[0].return1y)} · ${inrCompact(p.topGainers[0].value)}` : "—"}
              viz={<PerformanceLine
                points={trendPoints.length ? trendPoints : undefined}
                benchmark={benchmarkPoints.length ? benchmarkPoints : undefined}
              />}
              onClick={() => navigate("/performance")}
            />
          </CardStrip>
        </section>

        <section>
          <SectionHead title="Holdings" count={p.holdings.length ? `${p.holdings.length} positions` : "loading…"} />
          {p.holdings.length === 0 ? (
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
              {portfolioState.loading ? "Loading holdings…" : "No holdings — upload a CAS statement to see your portfolio."}
            </div>
          ) : (
            <HoldingsTable holdings={p.holdings} isDesktop={isDesktop} onAsk={(name) => navigate("/chat?q=" + encodeURIComponent(`Tell me about ${name}`))} />
          )}
        </section>

        {(p.topGainers.length > 0 || p.topLosers.length > 0) && (
          <section>
            <SectionHead title="Top gainers & losers" count={`${p.topGainers.length + p.topLosers.length} funds`} />
            <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "1fr 1fr" : "1fr", gap: 20 }}>
              <GainerLoserList title="TOP GAINERS" funds={p.topGainers} positive />
              <GainerLoserList title="TOP LOSERS"  funds={p.topLosers}  positive={false} />
            </div>
          </section>
        )}

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          <TinyChip onClick={() => navigate("/chat?q=Why+is+my+top+fund+lagging")}>Why is fund X lagging?</TinyChip>
          <TinyChip onClick={() => navigate("/chat?q=Sell+my+duplicates")}>Sell my duplicates</TinyChip>
          <TinyChip onClick={() => navigate("/chat?q=Move+regular+to+direct")}>Move regular to direct</TinyChip>
        </div>
      </div>
    </ScreenContainer>
  );
}

function HoldingsTable({ holdings, isDesktop, onAsk }) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? holdings : holdings.slice(0, 10);
  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", gap: 1, background: "var(--v3-line)", border: "1px solid var(--v3-line)", borderRadius: 14, overflow: "hidden" }}>
        {visible.map((h, i) => (
          <button
            type="button"
            key={h.holding_id || i}
            onClick={() => onAsk(h.name)}
            style={{
              textAlign: "left",
              background: "var(--v3-bg-2)",
              padding: "14px 16px",
              display: "grid",
              gridTemplateColumns: isDesktop ? "2.4fr 0.7fr 1fr 1fr" : "2fr 0.6fr 1fr",
              alignItems: "center",
              gap: 12,
              cursor: "pointer",
              border: "none",
              width: "100%",
              fontFamily: "inherit",
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ color: "var(--v3-ink-1)", fontSize: 14, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.name}</div>
              <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", marginTop: 3 }}>{h.category}</div>
            </div>
            <div style={{ textAlign: "right" }}>
              <DecisionBadge action={h.action_badge?.action} title={h.action_badge?.reason} />
            </div>
            {isDesktop && (
              <div className="v3-data" style={{ color: "var(--v3-ink-3)", fontSize: 12, textAlign: "right" }}>{inrCompact(h.invested || 0)}</div>
            )}
            <div className="v3-data" style={{ color: "var(--v3-ink-1)", fontSize: 13, textAlign: "right" }}>{inrCompact(h.value)}</div>
            <div className="v3-data" style={{ color: (h.return1y ?? 0) >= 20 ? "var(--v3-moss)" : (h.return1y ?? 0) < 0 ? "var(--v3-crimson)" : "var(--v3-ink-1)", fontSize: 13, textAlign: "right" }}>
              {h.return1y != null ? `${h.return1y >= 0 ? "+" : ""}${h.return1y.toFixed(1)}%` : "—"}
            </div>
          </button>
        ))}
      </div>
      {holdings.length > 10 && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          style={{ marginTop: 10, fontSize: 12, color: "var(--v3-saffron)", background: "none", border: "none", cursor: "pointer", padding: 0 }}
        >
          {showAll ? `Show top 10` : `View all ${holdings.length} positions →`}
        </button>
      )}
    </>
  );
}

function GainerLoserList({ title, funds, positive }) {
  if (!funds?.length) return null;
  const Icon = positive ? TrendingUp : TrendingDown;
  const tone = positive ? "var(--v3-moss)" : "var(--v3-crimson)";
  return (
    <div>
      <p className="v3-eyebrow" style={{ color: tone, fontSize: 10, marginBottom: 8 }}>{title}</p>
      {funds.slice(0, 5).map((f, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 0", borderBottom: "1px solid var(--v3-line)" }}>
          <div style={{ width: 28, height: 28, borderRadius: 8, background: positive ? "var(--v3-moss-soft)" : "var(--v3-crimson-soft)", display: "grid", placeItems: "center", flexShrink: 0 }}>
            <Icon size={13} color={tone} />
          </div>
          <span style={{ flex: 1, fontSize: 13, color: "var(--v3-ink-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</span>
          <span className="v3-data" style={{ fontSize: 12, color: tone, minWidth: 56, textAlign: "right" }}>
            {f.return1y != null ? `${f.return1y >= 0 ? "+" : ""}${f.return1y.toFixed(1)}%` : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

function StackedAllocationBar({ data }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", height: 12, borderRadius: 6, overflow: "hidden", background: "var(--v3-bg-3)" }}>
        {data.map((d, i) => (
          <span key={i} title={`${d.label} · ${d.value}%`} style={{ width: `${(d.value / total) * 100}%`, background: d.color }} />
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        {data.map((d, i) => (
          <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--v3-ink-2)" }}>
            <span style={{ width: 8, height: 8, borderRadius: 999, background: d.color }} />
            {d.label}
            <span className="v3-data" style={{ color: "var(--v3-ink-1)" }}>
              {d.value}%
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
