/**
 * V4 Diversification Dashboard — ① Insight · ② Recommendations · ③ Apply
 * Endpoints:
 *   GET /api/portfolio/exposure/fund-overlap/matrix
 *   GET /api/plans/active
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api from "../api/client";
import {
  DashboardShell, SectionHeader, StatTile, EmptyState, Skeleton,
  RecommendationCard, ApplyCard, formatInr,
} from "../components/DashboardShell";

const DIV_CODES = new Set([
  "OVERLAP_CONSOLIDATION", "REGULAR_DIRECT_DUPLICATE",
  "COST_LEAK_SWITCH_TO_DIRECT", "COST_LEAK_SWITCH",
]);

export default function Diversification() {
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
      api.get("/api/portfolio/exposure/fund-overlap/matrix"),
      api.get("/api/plans/active"),
    ]).then(([d, p]) => {
      if (d.status === "fulfilled") setData(d.value);
      else setErr(d.reason);
      if (p.status === "fulfilled") setPlan(p.value);
      setLoading(false);
    });
  }, [user]);

  if (authLoading) return null;
  if (!user) { navigate("/onboarding", { replace: true }); return null; }

  const pairs    = data?.pairs || [];
  const maxPct   = data?.max_pct || 0;
  const highPairs = data?.high_pairs || 0;

  /* ② filter */
  const allActions = plan?.plan?.actions || [];
  const domainRecs = allActions.filter(a =>
    (a.reason_codes || []).some(c => DIV_CODES.has(c))
    && (a.status || "").toUpperCase() !== "COMPLETED"
  );
  const recs = domainRecs.length > 0
    ? domainRecs.slice(0, 4)
    : allActions.filter(a => ["EXIT","TRIM"].includes((a.type||"").toUpperCase()) && (a.status||"").toUpperCase() !== "COMPLETED").slice(0, 3);

  /* ③ improvement */
  const improvements = plan?.plan?.improvements || {};
  const before = improvements.overlap_pct?.before;
  const after  = improvements.overlap_pct?.after;

  const badge = maxPct > 65 ? "High overlap" : maxPct > 40 ? "Moderate" : maxPct > 0 ? "Low overlap" : undefined;
  const badgeTone = maxPct > 65 ? "rust" : maxPct > 40 ? "gold" : "moss";

  return (
    <DashboardShell title="Diversification" badge={badge} badgeTone={badgeTone}>
      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[...Array(4)].map((_, i) => <Skeleton key={i} height={90} />)}
        </div>
      )}
      {!loading && err && <EmptyState icon="⚡" title="Could not load data" sub={err.message || String(err)} />}
      {!loading && data?.empty && <EmptyState title="Need at least 2 mutual funds" sub="Upload a CAS to see overlap analysis." />}

      {!loading && data && !data.empty && (
        <>
          {/* ① Insight */}
          <div style={eyebrowStyle}>① Insight</div>

          <div style={insightCardStyle}>
            <div style={{ fontFamily: "var(--v4-display)", fontSize: 21, fontWeight: 600, letterSpacing: "-.02em", color: "var(--v4-ink)", marginBottom: 6 }}>
              {highPairs > 0
                ? `${highPairs} fund pair${highPairs > 1 ? "s" : ""} hold near-identical stocks`
                : pairs.length > 0 ? `${pairs.length} fund pairs analysed` : "Overlap analysis ready"}
            </div>
            <p style={{ fontSize: 12, color: "var(--v4-ink-dim)", margin: "0 0 12px", lineHeight: 1.5 }}>
              Their top holdings overlap heavily — you own less variety than it looks.
            </p>
            <div style={statRowStyle}>
              <StatBox label="Funds" value={data.funds?.length ?? "—"} />
              <StatBox label="Max overlap" value={maxPct > 0 ? `${maxPct.toFixed(0)}%` : "—"} />
              <StatBox label="High-overlap pairs" value={highPairs} />
            </div>
          </div>

          {/* Overlap list */}
          {pairs.length > 0 && (
            <div style={overlapCardStyle}>
              <div style={overlapHeaderStyle}>
                <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8.5, letterSpacing: 1.1, color: "var(--v4-ink-mute)", textTransform: "uppercase" }}>
                  Pairwise fund overlap
                </span>
              </div>
              <div style={{ padding: "13px 16px 15px", display: "flex", flexDirection: "column", gap: 8 }}>
                {pairs.slice(0, 10).map((pair, i) => <OverlapRow key={i} pair={pair} />)}
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
            metricLabel="Fund overlap"
            before={before != null ? before.toFixed(1) : null}
            after={after != null ? after.toFixed(1) : null}
            unit="%"
            acceptedCount={accepted.size}
            onSend={() => navigate("/plan")}
          />
        </>
      )}
    </DashboardShell>
  );
}

function StatBox({ label, value }) {
  return (
    <div style={{ flex: 1, background: "var(--v4-s0)", border: "1px solid var(--v4-line)", borderRadius: 10, padding: "9px 6px", textAlign: "center" }}>
      <div style={{ fontFamily: "var(--v4-mono)", fontSize: 7, letterSpacing: 1, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 3 }}>{label}</div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 16, fontWeight: 600, color: "var(--v4-ink)" }}>{value}</div>
    </div>
  );
}

function OverlapRow({ pair }) {
  const pct  = Number(pair.overlap_pct || 0);
  const tone = pct >= 65 ? "var(--v4-rust)" : pct >= 40 ? "var(--v4-gold)" : "var(--v4-moss)";
  const label = pct >= 65 ? "HIGH" : pct >= 40 ? "MED" : "LOW";
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <div style={{ fontSize: 12, color: "var(--v4-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "65%" }}>
          {pair.fund_a || pair.a || "Fund A"} <span style={{ color: "var(--v4-ink-faint)" }}>vs</span> {pair.fund_b || pair.b || "Fund B"}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          <span style={{ fontFamily: "var(--v4-display)", fontSize: 14, color: tone }}>{pct.toFixed(1)}%</span>
          <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8, color: tone, letterSpacing: 1 }}>{label}</span>
        </div>
      </div>
      <div style={{ height: 3, borderRadius: 2, background: "var(--v4-line-strong)", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: tone, borderRadius: 2 }} />
      </div>
    </div>
  );
}

const eyebrowStyle   = { fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 10 };
const insightCardStyle = { background: "linear-gradient(168deg, var(--v4-hero-a), var(--v4-hero-b))", border: "1px solid var(--v4-line-strong)", borderRadius: 16, padding: "14px 16px", marginBottom: 11 };
const statRowStyle   = { display: "flex", gap: 7 };
const overlapCardStyle = { background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))", border: "1px solid var(--v4-line)", borderRadius: "var(--v4-r-lg)", overflow: "hidden", marginBottom: 18 };
const overlapHeaderStyle = { padding: "11px 16px 8px", borderBottom: "1px solid var(--v4-line)" };
const hlStyle        = { fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 9, display: "flex", alignItems: "center", gap: 8 };
