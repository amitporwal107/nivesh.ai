import React from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { AlertTriangle, RefreshCw, Shield, BarChart3 } from "lucide-react";
import HeroCard from "../../components/HeroCard";
import CompactCard from "../../components/CompactCard";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import TinyChip from "../../components/TinyChip";
import { OverlapDonut } from "../../components/viz";
import { useRiskAnalysis } from "../../adapters";

const RATING_TONE = {
  LOW:       { bg: "var(--v3-moss-soft)",    color: "var(--v3-moss)",    label: "Low" },
  MEDIUM:    { bg: "#D4AF3726",              color: "var(--v3-gold)",    label: "Medium" },
  HIGH:      { bg: "var(--v3-crimson-soft)", color: "var(--v3-crimson)", label: "High" },
  VERY_HIGH: { bg: "var(--v3-crimson-soft)", color: "var(--v3-crimson)", label: "Very High" },
  UNKNOWN:   { bg: "var(--v3-bg-3)",         color: "var(--v3-ink-3)",   label: "—" },
};

const IMPACT_TONE = {
  HIGH:   { bg: "var(--v3-crimson-soft)", color: "var(--v3-crimson)" },
  MEDIUM: { bg: "#D4AF3726",              color: "var(--v3-gold)" },
  LOW:    { bg: "var(--v3-moss-soft)",    color: "var(--v3-moss)" },
};

function ErrorState({ onRetry }) {
  return (
    <div style={{ textAlign: "center", padding: "48px 24px", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 14, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
      <AlertTriangle size={28} color="var(--v3-ink-4)" />
      <p style={{ color: "var(--v3-ink-3)", fontSize: 14, margin: 0 }}>Couldn't load risk analytics</p>
      <button onClick={onRetry} style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 16px", background: "var(--v3-bg-3)", border: "1px solid var(--v3-line)", borderRadius: 999, fontSize: 13, color: "var(--v3-ink-2)", cursor: "pointer" }}>
        <RefreshCw size={13} /> Retry
      </button>
    </div>
  );
}

function RiskScoreViz({ score, rating, viewport }) {
  const tone = RATING_TONE[rating] || RATING_TONE.UNKNOWN;
  const v = score == null ? 0 : (score / 10) * 100;
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 18 }}>
      <div style={{ position: "relative", width: viewport === "desktop" ? 120 : 96, height: viewport === "desktop" ? 120 : 96 }}>
        <OverlapDonut value={v} color={tone.color} />
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
          <div style={{ textAlign: "center" }}>
            <span style={{ fontFamily: "var(--v3-font-display)", fontSize: viewport === "desktop" ? 30 : 24, fontWeight: 600, color: "var(--v3-ink-1)", lineHeight: 1 }}>
              {score == null ? "—" : score.toFixed(1)}
            </span>
            <p style={{ fontSize: 9, color: "var(--v3-ink-4)", margin: "2px 0 0", fontFamily: "var(--v3-font-mono)" }}>/ 10</p>
          </div>
        </div>
      </div>
      <span style={{ padding: "4px 10px", borderRadius: 999, background: tone.bg, color: tone.color, fontSize: 11, fontFamily: "var(--v3-font-mono)", fontWeight: 600 }}>
        {tone.label}
      </span>
    </div>
  );
}

function MetricCard({ label, value, suffix, hint, tone }) {
  return (
    <div style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 12, padding: 14 }}>
      <p className="v3-eyebrow" style={{ fontSize: 9, color: "var(--v3-ink-4)", margin: 0 }}>{label}</p>
      <p style={{ fontFamily: "var(--v3-font-display)", fontSize: 26, fontWeight: 600, color: tone || "var(--v3-ink-1)", margin: "6px 0 2px", lineHeight: 1 }}>
        {value == null ? "—" : value}
        {value != null && suffix && <span style={{ fontSize: 13, color: "var(--v3-ink-3)", fontWeight: 400, marginLeft: 2 }}>{suffix}</span>}
      </p>
      {hint && <p style={{ fontSize: 10, color: "var(--v3-ink-4)", margin: 0 }}>{hint}</p>}
    </div>
  );
}

function DriverRow({ driver }) {
  const tone = IMPACT_TONE[driver.impact] || IMPACT_TONE.MEDIUM;
  return (
    <div style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 10, padding: "10px 14px", display: "flex", alignItems: "flex-start", gap: 12 }}>
      <span style={{ padding: "3px 8px", borderRadius: 999, background: tone.bg, color: tone.color, fontSize: 9, fontFamily: "var(--v3-font-mono)", fontWeight: 600, marginTop: 2, whiteSpace: "nowrap" }}>
        {driver.impact}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: "var(--v3-ink-1)", lineHeight: 1.3 }}>{driver.label}</div>
        {driver.detail && <div style={{ fontSize: 11, color: "var(--v3-ink-4)", marginTop: 3 }}>{driver.detail}</div>}
      </div>
    </div>
  );
}

export default function RiskAnalysis() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const { data, loading, error, refetch } = useRiskAnalysis();
  const empty = !data || data.empty;

  if (error && !loading) {
    return (
      <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
        <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Portfolio · Risk" title="Risk Analysis" />
        <ErrorState onRetry={refetch} />
      </ScreenContainer>
    );
  }

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Portfolio · Risk" title="Risk Analysis" />

      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 80 }}>
        <HeroCard
          layout={isDesktop ? "desktop" : "mobile"}
          category="risk"
          priorityLabel={loading ? "Loading…" : empty ? "No holdings yet" : `${(RATING_TONE[data.risk_rating] || RATING_TONE.UNKNOWN).label} risk`}
          title={
            loading ? "Crunching the numbers…"
            : empty ? "Add holdings to see your risk profile"
            : data.weighted_volatility != null
              ? `Annualised volatility ${(data.weighted_volatility * 100).toFixed(1)}%`
              : "Risk profile"
          }
          description={isDesktop && !empty && data.coverage_pct < 95 ? `Risk data covers ${data.coverage_pct}% of your portfolio by value.` : null}
          viz={loading
            ? <div style={{ width: "100%", height: 100, background: "var(--v3-bg-3)", borderRadius: 10 }} />
            : empty
              ? <Shield size={40} color="var(--v3-ink-4)" />
              : <RiskScoreViz score={data.risk_score} rating={data.risk_rating} viewport={viewport} />
          }
          ctaText={empty ? null : "Stress-test my portfolio →"}
          onClick={empty ? null : () => navigate("/v3/risk/stress")}
        />

        {!empty && (
          <>
            <section>
              <SectionHead title="Headline metrics" count="3 dimensions" />
              <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(3, 1fr)" : "1fr", gap: 12 }}>
                <MetricCard
                  label="Weighted beta (1Y)"
                  value={data.weighted_beta?.toFixed(2)}
                  hint={data.weighted_beta == null ? "Insufficient data" : data.weighted_beta > 1 ? "Moves more than the market" : data.weighted_beta < 0.9 ? "Moves less than the market" : "Tracks the market"}
                  tone={data.weighted_beta == null ? null : data.weighted_beta > 1.2 ? "var(--v3-crimson)" : "var(--v3-ink-1)"}
                />
                <MetricCard
                  label="Weighted Sharpe (1Y)"
                  value={data.weighted_sharpe?.toFixed(2)}
                  hint={data.weighted_sharpe == null ? "Insufficient data" : data.weighted_sharpe >= 1 ? "Good risk-adjusted returns" : data.weighted_sharpe >= 0.5 ? "Adequate" : "Below par"}
                  tone={data.weighted_sharpe == null ? null : data.weighted_sharpe < 0.5 ? "var(--v3-crimson)" : data.weighted_sharpe >= 1 ? "var(--v3-moss)" : "var(--v3-ink-1)"}
                />
                <MetricCard
                  label="Volatility (1Y, ann.)"
                  value={data.weighted_volatility == null ? null : (data.weighted_volatility * 100).toFixed(1)}
                  suffix="%"
                  hint={data.weighted_volatility == null ? "Insufficient data" : data.weighted_volatility > 0.22 ? "Above balanced" : "Within range"}
                  tone={data.weighted_volatility == null ? null : data.weighted_volatility > 0.22 ? "var(--v3-crimson)" : "var(--v3-ink-1)"}
                />
              </div>
            </section>

            <section>
              <SectionHead title="Asset allocation" count="Mix" />
              <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(4, 1fr)" : "1fr 1fr", gap: 12 }}>
                <CompactCard category="risk" label="Equity"  meta={`${data.equity_pct.toFixed(1)}%`}  viz={<OverlapDonut value={data.equity_pct} color="var(--v3-saffron)" />} />
                <CompactCard category="risk" label="Debt"    meta={`${data.debt_pct.toFixed(1)}%`}    viz={<OverlapDonut value={data.debt_pct} color="var(--v3-indigo)" />} />
                <CompactCard category="risk" label="Gold"    meta={`${data.gold_pct.toFixed(1)}%`}    viz={<OverlapDonut value={data.gold_pct} color="var(--v3-gold)" />} />
                <CompactCard category="risk" label="Other"   meta={`${data.other_pct.toFixed(1)}%`}   viz={<OverlapDonut value={data.other_pct} color="var(--v3-ink-3)" />} />
              </div>
            </section>

            {data.risk_drivers.length > 0 && (
              <section>
                <SectionHead title="Risk drivers" count={`${data.risk_drivers.length} flagged`} />
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {data.risk_drivers.map((d, i) => <DriverRow key={i} driver={d} />)}
                </div>
              </section>
            )}

            {data.top_contributors.length > 0 && (
              <section>
                <SectionHead title="Top volatility contributors" count={`${data.top_contributors.length} holdings`} />
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {data.top_contributors.map((c, i) => (
                    <div key={i} style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 10, padding: "10px 14px", display: "flex", alignItems: "center", gap: 10 }}>
                      <BarChart3 size={16} color="var(--v3-ink-3)" />
                      <span style={{ flex: 1, fontSize: 13, color: "var(--v3-ink-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</span>
                      <span className="v3-data" style={{ fontSize: 11, color: "var(--v3-ink-3)" }}>{c.weight_pct.toFixed(1)}%</span>
                      <span className="v3-data" style={{ fontSize: 11, color: "var(--v3-crimson)" }}>σ {(c.volatility_1y * 100).toFixed(1)}%</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              <TinyChip onClick={() => navigate("/v3/chat?q=Why+is+my+risk+high")}>Why is my risk high?</TinyChip>
              <TinyChip onClick={() => navigate("/v3/chat?q=How+do+I+lower+my+volatility")}>Lower my volatility</TinyChip>
              <TinyChip onClick={() => navigate("/v3/risk/stress")}>Stress test</TinyChip>
            </div>
          </>
        )}
      </div>
    </ScreenContainer>
  );
}
