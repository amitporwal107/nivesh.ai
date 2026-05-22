import React, { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import HeroCard from "../../components/HeroCard";
import HeroVizPanel from "../../components/HeroVizPanel";
import CompactCard from "../../components/CompactCard";
import CategoryChip from "../../components/CategoryChip";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { PerformanceLine, OverlapDonut } from "../../components/viz";
import { usePortfolioSummary, useStressTest } from "../../adapters";
import { inrCompact, pct } from "../../lib/format";
import SourceBanner from "../../components/SourceBanner";

const SCENARIOS = [
  { id: "drop10", label: "Drop 10%" },
  { id: "drop20", label: "Drop 20%" },
  { id: "drop30", label: "Drop 30%" },
  { id: "covid", label: "COVID '20" },
  { id: "gfc", label: "GFC '08" },
];


export default function StressTest() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const portfolioState = usePortfolioSummary();
  const p = portfolioState.data;
  const [scenario, setScenario] = useState("drop20");
  const stress = useStressTest(scenario === "drop10" ? "drop_10" : scenario === "drop20" ? "drop_20" : scenario === "drop30" ? "drop_30" : scenario === "covid" ? "covid_2020" : "gfc_2008");
  const delta = stress.data?.dropPct ?? null;
  const impactValue = delta != null ? (stress.data?.portfolioImpact ?? p.summary.totalValue * (1 + delta / 100)) : null;
  const loss = impactValue != null ? p.summary.totalValue - impactValue : null;
  const stressUnavailable = !stress.loading && delta == null;

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Risk · Stress test" title="What if markets fall?" />
      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 40 }}>
        <SourceBanner source={p?._source} error={portfolioState.error} loading={portfolioState.loading} onRefresh={portfolioState.refetch} />
        <div className="v3-hscroll" style={{ display: "flex", gap: 6 }}>
          {SCENARIOS.map((s) => (
            <CategoryChip
              key={s.id}
              category="risk"
              label={s.label}
              active={scenario === s.id}
              onClick={() => setScenario(s.id)}
            />
          ))}
        </div>

        {stressUnavailable ? (
          <div
            style={{
              padding: "28px 20px",
              background: "var(--v3-bg-2)",
              border: "1px solid var(--v3-line)",
              borderRadius: 20,
              textAlign: "center",
              color: "var(--v3-ink-3)",
              fontSize: 13,
            }}
          >
            Stress test data unavailable — backend did not return scenario results.
          </div>
        ) : (
          <HeroCard
            layout={isDesktop ? "desktop" : "mobile"}
            category="risk"
            priorityLabel="Stress impact"
            title={impactValue != null ? `Your portfolio drops to ${inrCompact(impactValue)}` : "Calculating…"}
            description={isDesktop && impactValue != null && loss != null ? `Loss of ${inrCompact(loss)} (${pct(delta, 1)}). Recovery time at long-term equity CAGR of 12% is roughly ${Math.ceil(Math.log(p.summary.totalValue / impactValue) / Math.log(1.12) * 12)} months.` : null}
            viz={
              <HeroVizPanel eyebrow="Net change" value={delta != null ? pct(delta, 1) : "—"} unit={loss != null ? `(${inrCompact(loss)})` : ""} size={isDesktop ? "desktop" : "mobile"}>
                <PerformanceLine
                  points={[2, 8, 8, 12, 14, 16, 20, 22, 26, 26, 32, 30]}
                  benchmark={[2, 8, 8, 14, 14, 20, 20, 26, 26, 32, 32, 34]}
                  color="var(--v3-crimson)"
                  size={isDesktop ? 144 : 96}
                />
              </HeroVizPanel>
            }
            ctaText="Suggest mitigations →"
            onClick={() => navigate("/chat?q=How%20do%20I%20reduce%20drawdown%20risk")}
          />
        )}

        {p.allocation.length > 0 && (
          <>
            <SectionHead title="Impact by asset class" count={`${p.allocation.length} buckets`} />
            <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(4, 1fr)" : "1fr 1fr", gap: 12 }}>
              {p.allocation.map((a, i) => {
                const assetImpact = delta != null ? delta * (a.label === "Equity" ? 1 : a.label === "Debt" ? 0.1 : a.label === "Gold" ? -0.4 : 0.7) : null;
                return (
                  <CompactCard
                    key={i}
                    category="risk"
                    label={`${a.label} · ${a.value}%`}
                    meta={assetImpact != null ? `IMPACT ${pct(assetImpact, 1)}` : "—"}
                    viz={<OverlapDonut value={assetImpact != null ? Math.min(Math.abs(assetImpact) * 4, 100) : 0} color={a.color} />}
                  />
                );
              })}
            </div>
          </>
        )}
      </div>
    </ScreenContainer>
  );
}
