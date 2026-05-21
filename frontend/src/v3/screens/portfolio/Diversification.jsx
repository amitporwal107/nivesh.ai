import React from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import HeroCard from "../../components/HeroCard";
import CompactCard from "../../components/CompactCard";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { OverlapDonut, FundCountHistogram } from "../../components/viz";
import { usePortfolioSummary } from "../../adapters";

export default function Diversification() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const { data: p } = usePortfolioSummary();

  // 6x6 fake heatmap data
  const funds = ["PPFAS Flexi", "ICICI Bluechip", "Nippon SC", "HDFC MidCap", "Mirae ELSS", "DSP Small"];
  const heat = funds.map((_, i) => funds.map((_, j) => (i === j ? 100 : Math.round(20 + Math.random() * 60))));

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Portfolio · Risk" title="Diversification" />

      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 40 }}>
        <HeroCard
          layout={isDesktop ? "desktop" : "mobile"}
          category="risk"
          priorityLabel="Concentration"
          title="3 fund pairs overlap above 65%"
          description={isDesktop ? "The highest overlap is between PPFAS Flexi and HDFC MidCap — they share roughly 71% of underlying stocks. Consolidating to one will reduce concentration without losing diversification." : null}
          viz={
            <div>
              <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", marginBottom: 8 }}>Fund count vs ideal</div>
              <FundCountHistogram count={p.funds.count} height={isDesktop ? 96 : 72} showIdealLabel={isDesktop} />
            </div>
          }
          ctaText="Show me the consolidation plan →"
          onClick={() => navigate("/chat?q=Build%20me%20a%20consolidation%20plan")}
        />

        <section>
          <SectionHead title="Overlap heatmap" count={`${funds.length} × ${funds.length}`} />
          <div
            style={{
              background: "var(--v3-bg-2)",
              border: "1px solid var(--v3-line)",
              borderRadius: 14,
              padding: 16,
              overflowX: "auto",
            }}
          >
            <table style={{ borderCollapse: "separate", borderSpacing: 4, fontFamily: "var(--v3-font-mono)", fontSize: 11 }}>
              <thead>
                <tr>
                  <th style={{ width: 88 }} />
                  {funds.map((f, i) => (
                    <th key={i} style={{ padding: "4px 6px", color: "var(--v3-ink-3)", textAlign: "left", fontWeight: 500 }}>{abbreviate(f)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {heat.map((row, i) => (
                  <tr key={i}>
                    <td style={{ color: "var(--v3-ink-3)", padding: "4px 6px" }}>{abbreviate(funds[i])}</td>
                    {row.map((v, j) => (
                      <td key={j} style={{ width: 44, height: 36, padding: 0 }}>
                        <div
                          style={{
                            background: heatColor(v),
                            color: v > 60 ? "var(--v3-ink-1)" : "var(--v3-ink-3)",
                            height: "100%",
                            borderRadius: 4,
                            display: "grid",
                            placeItems: "center",
                            fontFamily: "var(--v3-font-mono)",
                            fontWeight: 600,
                            fontSize: 11,
                          }}
                        >
                          {i === j ? "·" : v}
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <SectionHead title="Breakdown" count="4 lenses" />
          <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(4, 1fr)" : "1fr 1fr", gap: 12 }}>
            <CompactCard category="risk" label="Sector concentration" meta="Top sector 32%" viz={<OverlapDonut value={32} color="var(--v3-saffron)" />} />
            <CompactCard category="risk" label="Market-cap split" meta="LC 52% · MC 28% · SC 20%" viz={<OverlapDonut value={52} color="var(--v3-moss)" />} />
            <CompactCard category="risk" label="AMC concentration" meta={`${p.funds.amcCount} AMCs · top 38%`} viz={<OverlapDonut value={38} color="var(--v3-indigo)" />} />
            <CompactCard category="risk" label="Single-stock max" meta="Reliance 7.8%" viz={<OverlapDonut value={78} color="var(--v3-crimson)" />} />
          </div>
        </section>
      </div>
    </ScreenContainer>
  );
}

function heatColor(v) {
  if (v >= 80) return "var(--v3-crimson)";
  if (v >= 65) return "rgba(217, 79, 79, 0.55)";
  if (v >= 45) return "rgba(212, 175, 55, 0.45)";
  if (v >= 25) return "rgba(123, 160, 91, 0.35)";
  return "var(--v3-bg-3)";
}

function abbreviate(name) {
  return name.split(" ").map((w) => w.slice(0, 4)).join("·");
}
