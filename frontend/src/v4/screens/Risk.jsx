/**
 * V4 Risk Dashboard — ① Insight · ② Recommendations · ③ Apply
 * Endpoints:
 *   GET /api/portfolio/risk-analytics
 *   GET /api/plans/active
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api from "../api/client";
import {
  DashboardShell, StatTile, EmptyState, Skeleton,
  RecommendationCard, ApplyCard, HlBar, formatInr,
} from "../components/DashboardShell";

const IMPACT_TONE = { HIGH: "var(--v4-rust)", MEDIUM: "var(--v4-gold)", LOW: "var(--v4-moss)" };

export default function Risk() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();

  const [loading, setLoading]   = useState(true);
  const [data, setData]         = useState(null);
  const [plan, setPlan]         = useState(null);
  const [err, setErr]           = useState(null);
  const [accepted, setAccepted] = useState(new Set());

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    Promise.allSettled([
      api.get("/api/portfolio/risk-analytics"),
      api.get("/api/plans/active"),
    ]).then(([r, p]) => {
      if (r.status === "fulfilled") setData(r.value);
      else setErr(r.reason);
      if (p.status === "fulfilled") setPlan(p.value);
      setLoading(false);
    });
  }, [user]);

  if (authLoading) return null;
  if (!user) { navigate("/onboarding", { replace: true }); return null; }

  const ratingKey  = (data?.risk_rating || "").toUpperCase();
  const riskTone   = ratingKey === "HIGH" || ratingKey === "VERY_HIGH" ? "var(--v4-rust)"
    : ratingKey === "MODERATE" || ratingKey === "MEDIUM" ? "var(--v4-gold)" : "var(--v4-moss)";

  const beta      = data?.weighted_beta;
  const varPct    = data?.var_1d_pct;
  const varRs     = data?.var_1d_rs;
  const totalRs   = data?.portfolio_value_rs;

  /* ② risk-domain actions first, fallback to TRIM/HOLD */
  const allActions = plan?.plan?.actions || [];
  const riskRecs   = allActions.filter(a =>
    (a.source_domain || "").toLowerCase() === "risk"
    && (a.status || "").toUpperCase() !== "COMPLETED"
  );
  const recs = riskRecs.length > 0
    ? riskRecs.slice(0, 4)
    : allActions
        .filter(a => ["TRIM", "HOLD"].includes((a.type || "").toUpperCase())
          && (a.status || "").toUpperCase() !== "COMPLETED")
        .slice(0, 4);

  const badge     = data?.risk_rating || undefined;
  const badgeTone = ratingKey === "HIGH" || ratingKey === "VERY_HIGH" ? "rust"
    : ratingKey === "MODERATE" || ratingKey === "MEDIUM" ? "gold" : "moss";

  const projBeta = beta != null ? Number(beta).toFixed(2) : null;

  return (
    <DashboardShell title="Risk" badge={badge} badgeTone={badgeTone}>
      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[...Array(4)].map((_, i) => <Skeleton key={i} height={90} />)}
        </div>
      )}
      {!loading && err && <EmptyState icon="⚡" title="Could not load data" sub={err.message || String(err)} />}
      {!loading && data?.empty && <EmptyState title="No portfolio data" sub="Upload a CAS statement to see risk analytics." />}

      {!loading && data && !data.empty && (
        <>
          {/* ① Insight */}
          <div style={eyebrowStyle}>① Insight</div>

          <div style={insightCardStyle}>
            <div style={{ display: "flex", alignItems: "center", gap: 20, flexWrap: "wrap" }}>
              {/* VaR ring */}
              <svg viewBox="0 0 80 80" width={90} height={90} style={{ flexShrink: 0 }}>
                <circle cx="40" cy="40" r="30" fill="none" stroke="var(--v4-line-strong)" strokeWidth="8" />
                <circle
                  cx="40" cy="40" r="30" fill="none"
                  stroke={riskTone}
                  strokeWidth="8"
                  strokeDasharray={`${((data.risk_score || 0) / 10) * 188} 188`}
                  strokeLinecap="round"
                  transform="rotate(-90 40 40)"
                  style={{ transition: "stroke-dasharray .6s var(--v4-ease)" }}
                />
                <text x="40" y="36" textAnchor="middle" fontFamily="var(--v4-display)" fontSize="14" fontWeight="600" fill="var(--v4-ink)">
                  {varPct != null ? `${Number(varPct).toFixed(1)}%` : "—"}
                </text>
                <text x="40" y="50" textAnchor="middle" fontFamily="monospace" fontSize="5.5" letterSpacing="1" fill="var(--v4-ink-faint)">
                  1-DAY VAR
                </text>
              </svg>

              <div style={{ flex: 1 }}>
                <div style={{ fontFamily: "var(--v4-display)", fontSize: 20, fontWeight: 600, letterSpacing: "-.02em", color: "var(--v4-ink)", marginBottom: 5 }}>
                  {beta != null ? `Swings ${Number(beta).toFixed(2)}× the market` : "Risk analysis"}
                </div>
                <p style={{ fontSize: 12, color: "var(--v4-ink-dim)", margin: 0, lineHeight: 1.5 }}>
                  {varRs != null && totalRs != null
                    ? `A 95% one-day loss near ${formatInr(varRs)} on ${formatInr(totalRs)}.`
                    : data.risk_rating ? `Risk rating: ${data.risk_rating}` : "Volatility and beta analysis for your portfolio."}
                </p>
              </div>
            </div>
          </div>

          {/* Stat tiles — 4 across */}
          <div style={statsGridStyle}>
            <StatTile
              label="Beta"
              value={beta != null ? Number(beta).toFixed(2) : "—"}
              sub="vs market (1.0 = market)"
              tone={beta > 1.2 ? "var(--v4-rust)" : beta > 0.8 ? "var(--v4-gold)" : "var(--v4-moss)"}
            />
            <StatTile
              label="Volatility"
              value={data.weighted_volatility != null ? `${(Number(data.weighted_volatility) * 100).toFixed(0)}%` : "—"}
              sub="annualised"
            />
            <StatTile
              label="Max DD"
              value={data.max_drawdown_pct != null ? `${Number(data.max_drawdown_pct).toFixed(0)}%` : "—"}
              sub="max drawdown"
            />
            <StatTile
              label="Sharpe"
              value={data.weighted_sharpe != null ? Number(data.weighted_sharpe).toFixed(2) : "—"}
              sub="risk-adjusted return"
              tone={data.weighted_sharpe > 1 ? "var(--v4-moss)" : data.weighted_sharpe > 0 ? "var(--v4-gold)" : "var(--v4-rust)"}
            />
          </div>

          {/* What's driving the risk */}
          {data.risk_drivers?.length > 0 && (
            <div style={driverCardStyle}>
              <div style={cardHeaderStyle}>
                <span style={monoLabelStyle}>What's driving the risk</span>
              </div>
              <div style={{ padding: "14px 16px" }}>
                {data.risk_drivers.map((d, i) => (
                  <DriverBar key={i} driver={d} />
                ))}
              </div>
            </div>
          )}

          {/* ② Recommendations */}
          {recs.length > 0 && (
            <>
              <HlBar>② Recommendations · ranked by priority</HlBar>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
                {recs.map((action, i) => (
                  <RecommendationCard
                    key={action.action_id || action.id}
                    action={action}
                    index={i}
                    accepted={accepted.has(action.action_id || action.id)}
                    onAccept={() => setAccepted(s => new Set([...s, action.action_id || action.id]))}
                    onSkip={() => setAccepted(s => { const n = new Set(s); n.delete(action.action_id || action.id); return n; })}
                  />
                ))}
              </div>
            </>
          )}

          {/* ③ Apply */}
          <ApplyCard
            metricLabel="Projected beta"
            before={projBeta}
            after={projBeta}
            unit=""
            acceptedCount={accepted.size}
            onSend={() => navigate("/plan")}
          />
        </>
      )}
    </DashboardShell>
  );
}

function DriverBar({ driver }) {
  const pct  = Number(driver.pct || 0);
  const tone = IMPACT_TONE[(driver.impact || "MEDIUM").toUpperCase()] || "var(--v4-gold)";
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span style={{ fontSize: 13, color: "var(--v4-ink)" }}>{driver.label}</span>
        <span style={{ fontFamily: "var(--v4-display)", fontSize: 13, color: tone }}>{pct.toFixed(0)}%</span>
      </div>
      <div style={{ height: 4, borderRadius: 3, background: "var(--v4-line-strong)" }}>
        <div style={{ height: "100%", width: `${Math.min(pct, 100)}%`, background: tone, borderRadius: 3, transition: "width .5s var(--v4-ease)" }} />
      </div>
    </div>
  );
}

const eyebrowStyle     = { fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 10 };
const insightCardStyle = { background: "linear-gradient(168deg, var(--v4-hero-a), var(--v4-hero-b))", border: "1px solid var(--v4-line-strong)", borderRadius: 16, padding: "16px", marginBottom: 11 };
const statsGridStyle   = { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 14 };
const driverCardStyle  = { background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))", border: "1px solid var(--v4-line)", borderRadius: "var(--v4-r-lg)", overflow: "hidden", marginBottom: 14 };
const cardHeaderStyle  = { padding: "11px 16px 8px", borderBottom: "1px solid var(--v4-line)" };
const monoLabelStyle   = { fontFamily: "var(--v4-mono)", fontSize: 8.5, letterSpacing: 1.1, color: "var(--v4-ink-mute)", textTransform: "uppercase" };
