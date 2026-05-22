import React, { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import HeroCard from "../../components/HeroCard";
import HeroVizPanel from "../../components/HeroVizPanel";
import CompactCard from "../../components/CompactCard";
import SectionHead from "../../components/SectionHead";
import CategoryChip from "../../components/CategoryChip";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { OverlapDonut, GoalBars, TaxPyramid } from "../../components/viz";
import { usePortfolioSummary } from "../../adapters";
import SourceBanner from "../../components/SourceBanner";
import { inrCompact, pct } from "../../lib/format";

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
          <SectionHead title="Holdings" count={p.topHoldings.length ? `${p.topHoldings.length} funds` : "loading…"} />
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
              {portfolioState.loading ? "Loading holdings…" : "No holdings — upload a CAS statement to see your portfolio."}
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 1, background: "var(--v3-line)", border: "1px solid var(--v3-line)", borderRadius: 14, overflow: "hidden" }}>
              {p.topHoldings.map((h, i) => (
                <button
                  type="button"
                  key={i}
                  onClick={() => navigate("/chat?q=" + encodeURIComponent(`Tell me about ${h.name}`))}
                  style={{
                    textAlign: "left",
                    background: "var(--v3-bg-2)",
                    padding: "14px 16px",
                    display: "grid",
                    gridTemplateColumns: isDesktop ? "2fr 1fr 1fr 1fr 1fr" : "2fr 1fr 1fr",
                    alignItems: "center",
                    gap: 12,
                    cursor: "pointer",
                    border: "none",
                    width: "100%",
                    fontFamily: "inherit",
                  }}
                >
                  <div>
                    <div style={{ color: "var(--v3-ink-1)", fontSize: 14, fontWeight: 500 }}>{h.name}</div>
                    <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", marginTop: 3 }}>{h.category}</div>
                  </div>
                  {isDesktop && (
                    <div className="v3-data" style={{ color: "var(--v3-ink-3)", fontSize: 12, textAlign: "right" }}>{inrCompact(h.value * 0.78)}</div>
                  )}
                  {isDesktop && (
                    <div className="v3-data" style={{ color: "var(--v3-ink-3)", fontSize: 12, textAlign: "right" }}>units</div>
                  )}
                  <div className="v3-data" style={{ color: "var(--v3-ink-1)", fontSize: 13, textAlign: "right" }}>{inrCompact(h.value)}</div>
                  <div className="v3-data" style={{ color: h.return1y >= 20 ? "var(--v3-moss)" : "var(--v3-ink-1)", fontSize: 13, textAlign: "right" }}>+{h.return1y}%</div>
                </button>
              ))}
            </div>
          )}
        </section>

        <section>
          <SectionHead title="Quick lenses" count="3 cards" />
          <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(3, 1fr)" : "1fr 1fr", gap: 12 }}>
            <CompactCard
              category="risk"
              label="Diversification"
              meta={p.overlap.maxPct != null ? `${p.overlap.maxPct}% max overlap` : "See full overlap heatmap"}
              viz={<OverlapDonut value={p.overlap.maxPct ?? 0} color="var(--v3-crimson)" />}
              onClick={() => navigate("/portfolio/diversification")}
            />
            <CompactCard
              category="tax"
              label="Tax candidates"
              meta={`HARVEST ${inrCompact(p.tax.harvestable)}`}
              viz={<TaxPyramid />}
              onClick={() => navigate("/tax")}
            />
            <CompactCard
              category="goal"
              label="Goal-linked holdings"
              meta={`${p.goals.length} GOALS LINKED`}
              viz={<GoalBars />}
              onClick={() => navigate("/portfolio/concentration")}
            />
          </div>
        </section>
      </div>
    </ScreenContainer>
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
