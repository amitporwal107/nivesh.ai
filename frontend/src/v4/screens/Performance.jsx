/**
 * V4 Performance Dashboard — ① Insight · ② Recommendations · ③ Apply
 * Endpoints:
 *   GET /api/portfolio/fund-performance
 *   GET /api/insights/v3-portfolio
 *   GET /api/plans/active
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api from "../api/client";
import {
  DashboardShell, EmptyState, Skeleton,
  RecommendationCard, ApplyCard, HlBar,
} from "../components/DashboardShell";

const PERF_CODES = new Set([
  "UNDERPERFORMER_REPLACEMENT", "WEAK_MF",
  "COST_LEAK_SWITCH_TO_DIRECT", "COST_LEAK_SWITCH",
]);

function stripFundSuffix(name) {
  if (!name) return "—";
  return name
    .replace(/\s+(Regular Plan Growth|Direct Plan Growth|Fund Growth|Regular Plan|Direct Plan|Growth)\b.*/i, "")
    .trim()
    .slice(0, 22);
}

function alphaColor(alpha) {
  if (alpha > 0) return "var(--v4-moss)";
  return "var(--v4-rust)";
}

export default function Performance() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();

  const [loading, setLoading]   = useState(true);
  const [funds, setFunds]       = useState([]);
  const [perfComp, setPerfComp] = useState(null);
  const [plan, setPlan]         = useState(null);
  const [err, setErr]           = useState(null);
  const [accepted, setAccepted] = useState(new Set());

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    Promise.allSettled([
      api.get("/api/portfolio/fund-performance"),
      api.get("/api/insights/v3-portfolio"),
      api.get("/api/plans/active"),
    ]).then(([f, h, p]) => {
      if (f.status === "fulfilled") {
        const raw = f.value?.fund_ratings || f.value || [];
        setFunds(Array.isArray(raw) ? raw : []);
      } else {
        setErr(f.reason);
      }
      if (h.status === "fulfilled") {
        const comp = h.value?.health?.components?.performance
          || h.value?.components?.performance
          || null;
        setPerfComp(comp);
      }
      if (p.status === "fulfilled") setPlan(p.value);
      setLoading(false);
    });
  }, [user]);

  if (authLoading) return null;
  if (!user) { navigate("/onboarding", { replace: true }); return null; }

  /* Sort by alpha descending, top 8 */
  const sortedFunds = [...funds]
    .sort((a, b) => Number(b.alpha) - Number(a.alpha))
    .slice(0, 8);

  const maxAlpha = sortedFunds.length > 0 ? Number(sortedFunds[0].alpha) : 0;
  const scaleMax = Math.max(maxAlpha, 5);
  const CAUTION_ALPHA = 0; /* caution line at alpha=0 */

  const laggingCount = funds.filter(f => (f.rating || "").toLowerCase() === "underperforming").length;
  const beatingCount = funds.filter(f => (f.rating || "").toLowerCase() === "overperforming").length;

  /* Stats from perf component */
  const sub = perfComp?.sub_scores || {};
  const portfolioReturn = sub.portfolio_return_1y_pct ?? perfComp?.score ?? null;
  const benchmarkReturn = sub.benchmark_return_1y_pct ?? null;
  const alphaPct        = sub.alpha_pct ?? (portfolioReturn != null && benchmarkReturn != null ? portfolioReturn - benchmarkReturn : null);

  /* Headline */
  const beatingBenchmark = alphaPct != null && alphaPct > 0;

  /* Badge */
  const badge     = beatingBenchmark ? "BEATING" : laggingCount > 0 ? `${laggingCount} LAGGING` : undefined;
  const badgeTone = beatingBenchmark ? "moss" : laggingCount > 0 ? "rust" : "gold";

  /* ② filter recs */
  const allActions = plan?.plan?.actions || [];
  const domainRecs = allActions.filter(a => {
    const codes = a.reason_codes || [];
    const type  = (a.type || "").toUpperCase();
    return (codes.some(c => PERF_CODES.has(c)) || type === "TRIM" || type === "EXIT")
      && (a.status || "").toUpperCase() !== "COMPLETED";
  });
  const recs = domainRecs.slice(0, 4);

  /* ③ improvement */
  const improvements    = plan?.plan?.improvements || {};
  const xirrBefore      = portfolioReturn != null ? portfolioReturn.toFixed(1) : null;
  const xirrAfter       = improvements.xirr_after ?? improvements.projected_xirr ?? null;

  /* caution line position as % of scale */
  const cauW = Math.round(((CAUTION_ALPHA - Math.min(0, scaleMax * -1)) / scaleMax) * 100);
  /* For caution at 0 on a scale of [0..scaleMax]: caution is at 0% (left edge) */
  /* We'll skip rendering a visible caution line since it's always at 0 */

  const formatPp = (v) => v != null ? `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(1)} pp` : "—";
  const formatPct = (v) => v != null ? `${Number(v).toFixed(1)}%` : "—";

  return (
    <DashboardShell title="Performance" badge={badge} badgeTone={badgeTone}>

      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[...Array(4)].map((_, i) => <Skeleton key={i} height={90} />)}
        </div>
      )}
      {!loading && err && (
        <EmptyState icon="⚡" title="Could not load data" sub={err.message || String(err)} />
      )}
      {!loading && funds.length === 0 && !err && (
        <EmptyState title="No performance data" sub="Upload a CAS to see how your funds compare to benchmarks." />
      )}

      {!loading && funds.length > 0 && (
        <>
          {/* ① Insight */}
          <div style={eyebrowStyle}>① Insight</div>

          <div style={insightCardStyle}>
            <div style={{ fontFamily: "var(--v4-display)", fontSize: 21, fontWeight: 600, letterSpacing: "-.02em", color: "var(--v4-ink)", marginBottom: 6 }}>
              {alphaPct != null
                ? beatingBenchmark
                  ? `Beating Nifty by ${alphaPct.toFixed(1)} pp`
                  : `Behind Nifty by ${Math.abs(alphaPct).toFixed(1)} pp`
                : laggingCount > 0
                  ? `${laggingCount} fund${laggingCount > 1 ? "s" : ""} lagging benchmark`
                  : beatingCount > 0
                    ? `${beatingCount} fund${beatingCount > 1 ? "s" : ""} beating benchmark`
                    : "Performance analysis ready"}
            </div>
            <p style={{ fontSize: 12, color: "var(--v4-ink-dim)", margin: "0 0 12px", lineHeight: 1.5 }}>
              Funds compared to their respective benchmarks over 1 year.
            </p>
            <div style={statRowStyle}>
              <StatBox label="Your XIRR" value={formatPct(portfolioReturn)} />
              <StatBox label="Nifty"     value={formatPct(benchmarkReturn)} />
              <StatBox label="Alpha"     value={formatPp(alphaPct)}         tone={alphaPct != null ? alphaColor(alphaPct) : undefined} />
            </div>
          </div>

          {/* Fund vs benchmark bar chart */}
          {sortedFunds.length > 0 && (
            <div style={cardStyle}>
              <div style={cardHeaderStyle}>
                <span style={monoLabel}>Fund vs its benchmark · 1-yr</span>
                <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8, color: "var(--v4-ink-faint)", letterSpacing: 0.9, textTransform: "uppercase" }}>
                  pp
                </span>
              </div>
              <div style={{ padding: "13px 16px 15px", display: "flex", flexDirection: "column", gap: 8 }}>
                {sortedFunds.map((fund, i) => {
                  const alpha   = Number(fund.alpha) || 0;
                  const barW    = alpha > 0 ? Math.round((alpha / scaleMax) * 100) : 0;
                  const color   = alphaColor(alpha);
                  const name    = stripFundSuffix(fund.name);
                  return (
                    <div key={fund.name || i} style={{ display: "grid", gridTemplateColumns: "165px 1fr 48px", gap: 10, alignItems: "center" }}>
                      <span style={{ fontSize: 11.5, color: "var(--v4-ink-dim)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {name}
                      </span>
                      <div style={{ position: "relative", height: 9, background: "var(--v4-s3)", borderRadius: 5, overflow: "hidden" }}>
                        {barW > 0 && (
                          <div style={{ height: "100%", width: `${barW}%`, background: color, borderRadius: 5, transition: "width .5s" }} />
                        )}
                      </div>
                      <span style={{ fontFamily: "var(--v4-mono)", fontSize: 10.5, color: alpha < 0 ? "var(--v4-rust)" : "var(--v4-ink)", textAlign: "right" }}>
                        {alpha > 0 ? "+" : ""}{alpha.toFixed(1)}
                      </span>
                    </div>
                  );
                })}
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
            metricLabel="Projected XIRR"
            before={xirrBefore != null ? xirrBefore : undefined}
            after={xirrAfter != null ? String(Number(xirrAfter).toFixed(1)) : xirrBefore != null ? xirrBefore : undefined}
            unit="%"
            acceptedCount={accepted.size}
            onSend={() => navigate("/plan")}
          />
        </>
      )}
    </DashboardShell>
  );
}

// ── Small components ─────────────────────────────────────────────────────────

function StatBox({ label, value, tone }) {
  return (
    <div style={{ flex: 1, background: "var(--v4-s0)", border: "1px solid var(--v4-line)", borderRadius: 10, padding: "9px 6px", textAlign: "center" }}>
      <div style={{ fontFamily: "var(--v4-mono)", fontSize: 7, letterSpacing: 1, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 3 }}>
        {label}
      </div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 16, fontWeight: 600, color: tone || "var(--v4-ink)" }}>
        {value}
      </div>
    </div>
  );
}

// ── Styles ───────────────────────────────────────────────────────────────────

const eyebrowStyle     = { fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 10 };
const insightCardStyle = { background: "linear-gradient(168deg, var(--v4-hero-a), var(--v4-hero-b))", border: "1px solid var(--v4-line-strong)", borderRadius: 16, padding: "14px 16px", marginBottom: 11 };
const statRowStyle     = { display: "flex", gap: 7 };
const cardStyle        = { background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))", border: "1px solid var(--v4-line)", borderRadius: "var(--v4-r-lg)", overflow: "hidden", marginBottom: 11 };
const cardHeaderStyle  = { padding: "11px 16px 8px", borderBottom: "1px solid var(--v4-line)", display: "flex", justifyContent: "space-between", alignItems: "center" };
const monoLabel        = { fontFamily: "var(--v4-mono)", fontSize: 8.5, letterSpacing: 1.1, color: "var(--v4-ink-mute)", textTransform: "uppercase" };
