import React from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { AlertTriangle, RefreshCw, Layers } from "lucide-react";
import HeroCard from "../../components/HeroCard";
import CompactCard from "../../components/CompactCard";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { OverlapDonut, FundCountHistogram } from "../../components/viz";
import { usePortfolioSummary, useFundOverlap } from "../../adapters";

function heatColor(v) {
  if (v >= 80) return "var(--v3-crimson)";
  if (v >= 65) return "rgba(217, 79, 79, 0.55)";
  if (v >= 45) return "rgba(212, 175, 55, 0.45)";
  if (v >= 25) return "rgba(123, 160, 91, 0.35)";
  return "var(--v3-bg-3)";
}

function ErrorState({ onRetry }) {
  return (
    <div style={{ textAlign: "center", padding: "48px 24px", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 14, display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
      <AlertTriangle size={28} color="var(--v3-ink-4)" />
      <p style={{ color: "var(--v3-ink-3)", fontSize: 14, margin: 0 }}>Couldn't load fund overlap matrix</p>
      <button onClick={onRetry} style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 16px", background: "var(--v3-bg-3)", border: "1px solid var(--v3-line)", borderRadius: 999, fontSize: 13, color: "var(--v3-ink-2)", cursor: "pointer" }}>
        <RefreshCw size={13} /> Retry
      </button>
    </div>
  );
}

function EmptyState({ funds }) {
  const reason = funds.length === 0
    ? "No mutual fund holdings to compare."
    : funds.length === 1
    ? "Need at least 2 mutual funds to compute overlap."
    : "Fund stock-composition data isn't available for any of your funds yet.";
  return (
    <div style={{ textAlign: "center", padding: "48px 24px", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 14, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
      <Layers size={28} color="var(--v3-ink-4)" />
      <p style={{ color: "var(--v3-ink-2)", fontSize: 14, margin: 0 }}>{reason}</p>
    </div>
  );
}

export default function Diversification() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const portfolioState = usePortfolioSummary();
  const p = portfolioState.data;
  const overlapState = useFundOverlap();
  const overlap = overlapState.data || {};
  const { funds = [], matrix = [], pairs = 0, maxPct = 0, coverage_pct = 0, topPairs = [], empty } = overlap;

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Portfolio · Risk" title="Diversification" />

      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 80 }}>
        <HeroCard
          layout={isDesktop ? "desktop" : "mobile"}
          category="risk"
          priorityLabel={overlapState.loading ? "Loading…" : empty ? "No overlap data" : "Concentration"}
          title={
            overlapState.loading
              ? "Computing fund overlap…"
              : empty
              ? "Add 2+ mutual funds to see overlap"
              : `${pairs} fund pair${pairs === 1 ? "" : "s"} overlap above 65%`
          }
          description={
            isDesktop && !empty
              ? `The highest overlap pair shares roughly ${maxPct}% of underlying stocks. ${pairs > 0 ? "Consolidating may reduce concentration without losing diversification." : "Healthy spread across SEBI categories."}`
              : null
          }
          viz={
            <div>
              <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", marginBottom: 8 }}>Fund count vs ideal</div>
              <FundCountHistogram count={p?.funds?.count ?? funds.length} height={isDesktop ? 96 : 72} showIdealLabel={isDesktop} />
            </div>
          }
          ctaText={empty ? null : "Show me the consolidation plan →"}
          onClick={empty ? null : () => navigate("/v3/chat?q=Build%20me%20a%20consolidation%20plan")}
        />

        <section>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <SectionHead title="Overlap heatmap" count={funds.length ? `${funds.length} × ${funds.length}` : "—"} />
            {coverage_pct > 0 && coverage_pct < 100 && (
              <span className="v3-data" style={{ fontSize: 10, color: "var(--v3-ink-4)" }}>
                Coverage {coverage_pct}% of AUM
              </span>
            )}
          </div>

          {overlapState.error && !overlapState.loading ? (
            <ErrorState onRetry={overlapState.refetch} />
          ) : empty && !overlapState.loading ? (
            <EmptyState funds={funds} />
          ) : (
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
                      <th key={i} style={{ padding: "4px 6px", color: "var(--v3-ink-3)", textAlign: "left", fontWeight: 500, whiteSpace: "nowrap" }}>{f}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {matrix.map((row, i) => (
                    <tr key={i}>
                      <td style={{ color: "var(--v3-ink-3)", padding: "4px 6px", whiteSpace: "nowrap" }}>{funds[i]}</td>
                      {row.map((v, j) => (
                        <td key={j} style={{ width: 44, height: 36, padding: 0 }}>
                          <div
                            title={i === j ? "Same fund" : `${funds[i]} ↔ ${funds[j]}: ${v}% overlap`}
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
          )}
        </section>

        {!empty && topPairs.length > 0 && (
          <section>
            <SectionHead title="Highest-overlap pairs" count={`Top ${Math.min(topPairs.length, 5)}`} />
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {topPairs.slice(0, 5).map((pair, i) => (
                <div key={i} style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 10, padding: "10px 14px", display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ width: 44, height: 32, background: heatColor(pair.overlap_pct), borderRadius: 6, display: "grid", placeItems: "center", fontFamily: "var(--v3-font-mono)", fontSize: 12, fontWeight: 600, color: pair.overlap_pct > 60 ? "var(--v3-ink-1)" : "var(--v3-ink-3)" }}>
                    {pair.overlap_pct}%
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, color: "var(--v3-ink-1)", lineHeight: 1.3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {pair.a_name} <span style={{ color: "var(--v3-ink-4)" }}>↔</span> {pair.b_name}
                    </div>
                    <div className="v3-data" style={{ fontSize: 10, color: "var(--v3-ink-4)", marginTop: 2 }}>
                      {pair.shared_count} shared stocks
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <section>
          <SectionHead title="Breakdown" count="4 lenses" />
          <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(4, 1fr)" : "1fr 1fr", gap: 12 }}>
            <CompactCard category="risk" label="Fund count" meta={`${p?.funds?.count ?? 0} funds`} viz={<OverlapDonut value={Math.min(100, (p?.funds?.count ?? 0) * 10)} color="var(--v3-saffron)" />} />
            <CompactCard category="risk" label="AMC concentration" meta={`${p?.funds?.amcCount ?? 0} AMCs`} viz={<OverlapDonut value={(p?.funds?.amcCount ?? 0) * 12} color="var(--v3-indigo)" />} />
            <CompactCard category="risk" label="Max pair overlap" meta={`${maxPct}%`} viz={<OverlapDonut value={maxPct} color={maxPct >= 65 ? "var(--v3-crimson)" : "var(--v3-moss)"} />} />
            <CompactCard category="risk" label="High-overlap pairs" meta={`${pairs} pair${pairs === 1 ? "" : "s"} ≥65%`} viz={<OverlapDonut value={Math.min(100, pairs * 25)} color={pairs > 0 ? "var(--v3-crimson)" : "var(--v3-moss)"} />} />
          </div>
        </section>
      </div>
    </ScreenContainer>
  );
}
