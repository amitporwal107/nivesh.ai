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
  RecommendationCard, ApplyCard, formatInr,
} from "../components/DashboardShell";

const RISK_TONE = {
  LOW:       "var(--v4-moss)",
  MODERATE:  "var(--v4-gold)",
  MEDIUM:    "var(--v4-gold)",
  HIGH:      "var(--v4-rust)",
  VERY_HIGH: "var(--v4-rust)",
};

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

  const ratingKey = (data?.risk_rating || "").toUpperCase();
  const riskTone  = RISK_TONE[ratingKey] || "var(--v4-ink-faint)";

  /* ② filter — TRIM/HOLD actions as risk-domain proxy */
  const allActions = plan?.plan?.actions || [];
  const recs = allActions
    .filter(a => ["TRIM", "HOLD"].includes((a.type || "").toUpperCase())
      && (a.status || "").toUpperCase() !== "COMPLETED")
    .slice(0, 4);

  /* ③ no risk-specific improvement metric → show accepted count only */
  const badge     = data?.risk_rating || undefined;
  const badgeTone = ratingKey === "HIGH" || ratingKey === "VERY_HIGH" ? "rust"
    : ratingKey === "MODERATE" || ratingKey === "MEDIUM" ? "gold" : "moss";

  /* VaR ring */
  const beta = data?.weighted_beta;
  const betaLabel = beta != null ? `Swings ${Number(beta).toFixed(2)}× the market` : "Risk analysis";

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
              {/* Mini risk ring */}
              <svg viewBox="0 0 80 80" width={84} height={84} style={{ flexShrink: 0 }}>
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
                <text x="40" y="37" textAnchor="middle" fontFamily="var(--v4-display)" fontSize="16" fontWeight="600" fill="var(--v4-ink)">
                  {beta != null ? Number(beta).toFixed(2) : "—"}
                </text>
                <text x="40" y="51" textAnchor="middle" fontFamily="monospace" fontSize="6.5" letterSpacing="1" fill="var(--v4-ink-faint)">
                  BETA
                </text>
              </svg>
              <div style={{ flex: 1 }}>
                <div style={{ fontFamily: "var(--v4-display)", fontSize: 20, fontWeight: 600, letterSpacing: "-.02em", color: "var(--v4-ink)", marginBottom: 5 }}>
                  {betaLabel}
                </div>
                <p style={{ fontSize: 12, color: "var(--v4-ink-dim)", margin: 0, lineHeight: 1.5 }}>
                  {data.risk_rating ? `Risk rating: ${data.risk_rating}` : "Volatility and beta analysis for your portfolio."}
                </p>
              </div>
            </div>
          </div>

          {/* Stat tiles */}
          <div style={statsGridStyle}>
            <StatTile
              label="Portfolio beta"
              value={data.weighted_beta != null ? Number(data.weighted_beta).toFixed(2) : "—"}
              sub="vs market (1.0 = market)"
              tone={data.weighted_beta > 1.2 ? "var(--v4-rust)" : data.weighted_beta > 0.8 ? "var(--v4-gold)" : "var(--v4-moss)"}
            />
            <StatTile
              label="Volatility"
              value={data.weighted_volatility != null ? `${(Number(data.weighted_volatility) * 100).toFixed(1)}%` : "—"}
              sub="annualised"
            />
            <StatTile
              label="Sharpe ratio"
              value={data.weighted_sharpe != null ? Number(data.weighted_sharpe).toFixed(2) : "—"}
              sub="risk-adjusted return"
              tone={data.weighted_sharpe > 1 ? "var(--v4-moss)" : data.weighted_sharpe > 0 ? "var(--v4-gold)" : "var(--v4-rust)"}
            />
            <StatTile label="Max drawdown" value="—" sub="not yet tracked" />
          </div>

          {/* Risk drivers */}
          {data.risk_drivers?.length > 0 && (
            <div style={driversCardStyle}>
              <div style={cardHeaderStyle}>
                <span style={monoLabelStyle}>What's driving the risk</span>
              </div>
              <div style={{ padding: "13px 16px 15px", display: "flex", flexDirection: "column", gap: 8 }}>
                {data.risk_drivers.map((d, i) => (
                  <div key={i} style={driverRowStyle}>
                    <div style={{ width: 3, borderRadius: 2, alignSelf: "stretch", background: IMPACT_TONE[(d.impact || "MEDIUM").toUpperCase()] || "var(--v4-gold)", flexShrink: 0 }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontFamily: "var(--v4-display)", fontSize: 14, color: "var(--v4-ink)", marginBottom: 3 }}>{d.label || d.type}</div>
                      {d.detail && <div style={{ fontSize: 12, color: "var(--v4-ink-dim)", lineHeight: 1.5 }}>{d.detail}</div>}
                    </div>
                    <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1, color: IMPACT_TONE[(d.impact || "MEDIUM").toUpperCase()], textTransform: "uppercase", flexShrink: 0 }}>
                      {(d.impact || "medium").toLowerCase()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Asset allocation bars */}
          {(data.equity_pct > 0 || data.debt_pct > 0) && (
            <div style={{ ...driversCardStyle, marginTop: 0 }}>
              <div style={cardHeaderStyle}><span style={monoLabelStyle}>Asset allocation</span></div>
              <div style={{ padding: "14px 16px" }}>
                <AllocBar label="Equity" pct={data.equity_pct} tone="var(--v4-saffron)" />
                <AllocBar label="Debt"   pct={data.debt_pct}   tone="var(--v4-indigo)" />
                {data.gold_pct  > 0 && <AllocBar label="Gold"  pct={data.gold_pct}  tone="var(--v4-gold)" />}
                {data.other_pct > 0 && <AllocBar label="Other" pct={data.other_pct} tone="var(--v4-ink-faint)" />}
              </div>
            </div>
          )}

          {/* ② Recommendations */}
          {recs.length > 0 && (
            <>
              <div style={hlStyle}>② Recommendations · ranked by priority</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
                {recs.map(action => (
                  <RecommendationCard
                    key={action.action_id || action.id}
                    action={action}
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
            metricLabel={null}
            before={null}
            after={null}
            acceptedCount={accepted.size}
            onSend={() => navigate("/plan")}
          />
        </>
      )}
    </DashboardShell>
  );
}

function AllocBar({ label, pct, tone }) {
  const p = Number(pct || 0);
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span style={{ fontSize: 13, color: "var(--v4-ink)" }}>{label}</span>
        <span style={{ fontFamily: "var(--v4-display)", fontSize: 13, color: tone }}>{p.toFixed(1)}%</span>
      </div>
      <div style={{ height: 5, borderRadius: 3, background: "var(--v4-line-strong)" }}>
        <div style={{ height: "100%", width: `${Math.min(p, 100)}%`, background: tone, borderRadius: 3, transition: "width .5s var(--v4-ease)" }} />
      </div>
    </div>
  );
}

const eyebrowStyle   = { fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 10 };
const insightCardStyle = { background: "linear-gradient(168deg, var(--v4-hero-a), var(--v4-hero-b))", border: "1px solid var(--v4-line-strong)", borderRadius: 16, padding: "16px", marginBottom: 11 };
const statsGridStyle = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px,1fr))", gap: 10, marginBottom: 14 };
const driversCardStyle = { background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))", border: "1px solid var(--v4-line)", borderRadius: "var(--v4-r-lg)", overflow: "hidden", marginBottom: 14 };
const cardHeaderStyle  = { padding: "11px 16px 8px", borderBottom: "1px solid var(--v4-line)" };
const monoLabelStyle   = { fontFamily: "var(--v4-mono)", fontSize: 8.5, letterSpacing: 1.1, color: "var(--v4-ink-mute)", textTransform: "uppercase" };
const driverRowStyle   = { display: "flex", gap: 12, alignItems: "flex-start" };
const hlStyle          = { fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 9, display: "flex", alignItems: "center", gap: 8 };
