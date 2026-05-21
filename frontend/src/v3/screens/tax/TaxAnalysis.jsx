import React from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import HeroCard from "../../components/HeroCard";
import HeroVizPanel from "../../components/HeroVizPanel";
import CompactCard from "../../components/CompactCard";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { TaxPyramid, GoalBars } from "../../components/viz";
import { usePortfolioSummary } from "../../adapters";
import SourceBanner from "../../components/SourceBanner";
import { inrCompact } from "../../lib/format";

export default function TaxAnalysis() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const portfolioState = usePortfolioSummary();
  const p = portfolioState.data;
  const totalLtcg = (p.tax.ltcgUsed || 0) + (p.tax.ltcgFree || 0);
  const usedPct = totalLtcg > 0 ? ((p.tax.ltcgUsed || 0) / totalLtcg) * 100 : 0;
  const harvestCandidates = p.tax.candidates && p.tax.candidates.length
    ? p.tax.candidates.slice(0, 3).map((c) => ({
        name: c.name || c.fund_name,
        units: Math.round(c.units || c.quantity || 0),
        gain: Math.round(c.gain || c.unrealized_gain || 0),
        hold: c.holding_period || c.hold || "—",
      }))
    : [
        { name: "Nippon Small Cap", units: 412, gain: 42400, hold: "2y 4m" },
        { name: "PPFAS Flexi Cap", units: 280, gain: 24800, hold: "3y 8m" },
        { name: "Mirae ELSS", units: 192, gain: 10800, hold: "1y 2m" },
      ];

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Tax" title="Capital gains, harvest and FY planning" />
      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 40 }}>
        <SourceBanner source={p?._source} error={portfolioState.error} loading={portfolioState.loading} onRefresh={portfolioState.refetch} />
        <HeroCard
          layout={isDesktop ? "desktop" : "mobile"}
          category="tax"
          priorityLabel="Unrealized"
          title={`${inrCompact(p.tax.unrealizedLtcg)} unrealized LTCG`}
          description={isDesktop ? `${inrCompact(p.tax.ltcgFree)} of your FY ₹1.25L exemption is still unused. Harvesting now resets cost basis tax-free; ignore it and pay LTCG later.` : null}
          viz={
            <HeroVizPanel eyebrow="FY exemption used" value={`${usedPct.toFixed(0)}%`} size={isDesktop ? "desktop" : "mobile"}>
              <div style={{ display: "flex", justifyContent: "center", padding: 12 }}>
                <TaxPyramid size={isDesktop ? 120 : 80} />
              </div>
            </HeroVizPanel>
          }
          ctaText="Show harvest candidates →"
          onClick={() => navigate("/chat?q=Show%20me%20tax%20harvest%20candidates")}
        />

        <SectionHead title="Tax breakdown" count="4 cards" />
        <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(4, 1fr)" : "1fr 1fr", gap: 12 }}>
          <CompactCard category="tax" label="LTCG unrealized" meta={inrCompact(p.tax.unrealizedLtcg)} viz={<TaxPyramid />} />
          <CompactCard category="tax" label="STCG unrealized" meta="₹28,400" viz={<TaxPyramid />} />
          <CompactCard category="tax" label="Harvest opportunity" meta={inrCompact(p.tax.harvestable)} viz={<TaxPyramid />} />
          <CompactCard category="tax" label="FY exemption left" meta={inrCompact(p.tax.ltcgFree)} viz={<GoalBars />} />
        </div>

        <SectionHead title="Harvest candidates" count={`${harvestCandidates.length} positions`} />
        <div style={{ display: "flex", flexDirection: "column", gap: 1, background: "var(--v3-line)", border: "1px solid var(--v3-line)", borderRadius: 14, overflow: "hidden" }}>
          {harvestCandidates.map((h, i) => (
            <div key={i} style={{ background: "var(--v3-bg-2)", padding: "14px 16px", display: "grid", gridTemplateColumns: isDesktop ? "2fr 1fr 1fr 1fr" : "2fr 1fr 1fr", gap: 12, alignItems: "center" }}>
              <div>
                <div style={{ color: "var(--v3-ink-1)", fontSize: 14, fontWeight: 500 }}>{h.name}</div>
                <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", marginTop: 3 }}>HELD {h.hold}</div>
              </div>
              {isDesktop && <div className="v3-data" style={{ color: "var(--v3-ink-3)", fontSize: 12, textAlign: "right" }}>{h.units} units</div>}
              <div className="v3-data" style={{ color: "var(--v3-ink-1)", fontSize: 13, textAlign: "right" }}>{inrCompact(h.gain)}</div>
              <button
                type="button"
                onClick={() => navigate(`/chat?q=${encodeURIComponent(`Should I harvest ${h.name}?`)}`)}
                style={{
                  justifySelf: "end",
                  padding: "8px 14px",
                  borderRadius: 999,
                  background: "var(--v3-saffron)",
                  color: "var(--v3-saffron-ink)",
                  fontSize: 12,
                  fontWeight: 600,
                  border: "none",
                  cursor: "pointer",
                }}
              >
                Harvest now →
              </button>
            </div>
          ))}
        </div>
      </div>
    </ScreenContainer>
  );
}
