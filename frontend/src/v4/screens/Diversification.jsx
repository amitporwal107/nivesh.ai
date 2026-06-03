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
  DashboardShell, EmptyState, Skeleton,
  RecommendationCard, ApplyCard, HlBar,
} from "../components/DashboardShell";

const DIV_CODES = new Set([
  "OVERLAP_CONSOLIDATION", "REGULAR_DIRECT_DUPLICATE",
  "COST_LEAK_SWITCH_TO_DIRECT", "COST_LEAK_SWITCH",
  "SAME_CATEGORY_CONSOLIDATION", "CROSS_CATEGORY_REPLACEMENT",
  "INTERNATIONAL_DIVERSIFICATION", "GEOGRAPHIC_GAP",
]);

const CAUTION_PCT = 60;

function fundName(isin, fundsMap) {
  const f = fundsMap[isin];
  if (!f) return isin ? isin.slice(-6) : "—";
  const raw = f.name || f.id || isin;
  return raw
    .replace(/\s+(Direct|Regular|Growth|IDCW|Dividend|Plan|Option|Scheme)\b.*/i, "")
    .trim()
    .slice(0, 22);
}

function overlapColor(pct) {
  if (pct >= 65) return "var(--v4-rust)";
  if (pct >= 40) return "var(--v4-gold)";
  return "var(--v4-moss)";
}

// ── Main screen ──────────────────────────────────────────────────────────────

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

  const funds = data?.funds  || [];
  const pairs = data?.pairs  || [];

  /* Build ISIN → fund lookup */
  const fundsMap = {};
  for (const f of funds) fundsMap[f.id] = f;

  /* Sort pairs by overlap descending, take top 8 */
  const sortedPairs = [...pairs]
    .sort((a, b) => Number(b.overlap_pct) - Number(a.overlap_pct))
    .slice(0, 8);

  const maxPct = sortedPairs.length > 0 ? Number(sortedPairs[0].overlap_pct) : 0;
  const scaleMax = Math.max(maxPct, CAUTION_PCT, 1);

  /* High-overlap pairs (≥40%) */
  const highPairs = pairs.filter(p => Number(p.overlap_pct) >= 40).length;
  const uniqueStocks = data?.unique_stocks_count ?? "—";

  /* Headline */
  const overlapFundSet = new Set();
  pairs.filter(p => Number(p.overlap_pct) >= 40).forEach(p => {
    if (p.a) overlapFundSet.add(p.a);
    if (p.b) overlapFundSet.add(p.b);
  });
  const overlapFundCount = overlapFundSet.size;

  /* ② filter recs */
  const allActions = plan?.plan?.actions || [];
  const domainRecs = allActions.filter(a =>
    (a.reason_codes || []).some(c => DIV_CODES.has(c))
    && (a.status || "").toUpperCase() !== "COMPLETED"
  );
  const recs = domainRecs.length > 0
    ? domainRecs.slice(0, 4)
    : allActions
        .filter(a => ["EXIT","TRIM"].includes((a.type||"").toUpperCase())
          && (a.status||"").toUpperCase() !== "COMPLETED")
        .slice(0, 3);

  /* ③ improvement delta */
  const improvements = plan?.plan?.improvements || {};
  const fundCountAfter = improvements.fund_count?.after;

  const badge     = highPairs > 0 ? `${highPairs} ISSUE${highPairs > 1 ? "S" : ""}` : maxPct > 40 ? "MODERATE" : maxPct > 0 ? "HEALTHY" : undefined;
  const badgeTone = highPairs > 0 ? "rust" : maxPct > 40 ? "gold" : "moss";

  return (
    <DashboardShell title="Diversification" badge={badge} badgeTone={badgeTone}>

      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[...Array(4)].map((_, i) => <Skeleton key={i} height={90} />)}
        </div>
      )}
      {!loading && err && (
        <EmptyState icon="⚡" title="Could not load data" sub={err.message || String(err)} />
      )}
      {!loading && data?.empty && (
        <EmptyState title="Need at least 2 mutual funds" sub="Upload a CAS to see overlap analysis." />
      )}

      {!loading && data && !data.empty && (
        <>
          {/* ① Insight */}
          <div style={eyebrowStyle}>① Insight</div>

          <div style={insightCardStyle}>
            <div style={{ fontFamily: "var(--v4-display)", fontSize: 21, fontWeight: 600, letterSpacing: "-.02em", color: "var(--v4-ink)", marginBottom: 6 }}>
              {overlapFundCount > 0
                ? `${overlapFundCount} fund${overlapFundCount > 1 ? "s" : ""} hold near-identical stocks`
                : funds.length > 0 ? `${funds.length} funds mapped` : "Overlap analysis ready"}
            </div>
            <p style={{ fontSize: 12, color: "var(--v4-ink-dim)", margin: "0 0 12px", lineHeight: 1.5 }}>
              Their top holdings overlap heavily — you own less variety than it looks.
            </p>
            <div style={statRowStyle}>
              <StatBox label="Funds" value={funds.length} />
              <StatBox label="Overlap" value={maxPct > 0 ? `${maxPct.toFixed(0)}%` : "—"} />
              <StatBox label="Unique stocks" value={uniqueStocks} />
            </div>
          </div>

          {/* Pairwise overlap bars — matches the design exactly */}
          {sortedPairs.length > 0 && (
            <div style={cardStyle}>
              <div style={cardHeaderStyle}>
                <span style={monoLabel}>Pairwise fund overlap</span>
                <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8, color: "var(--v4-rust)", letterSpacing: 0.9, textTransform: "uppercase" }}>
                  Caution {CAUTION_PCT}%
                </span>
              </div>
              <div style={{ padding: "13px 16px 15px", display: "flex", flexDirection: "column", gap: 8 }}>
                {sortedPairs.map((pair, i) => {
                  const pct   = Number(pair.overlap_pct) || 0;
                  const barW  = Math.round((pct / scaleMax) * 100);
                  const cauW  = Math.round((CAUTION_PCT / scaleMax) * 100);
                  const color = overlapColor(pct);
                  const nA    = fundName(pair.a, fundsMap);
                  const nB    = fundName(pair.b, fundsMap);
                  return (
                    <div key={i} style={{ display: "grid", gridTemplateColumns: "165px 1fr 42px", gap: 10, alignItems: "center" }}>
                      <span style={{ fontSize: 11.5, color: "var(--v4-ink-dim)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {nA} vs {nB}
                      </span>
                      <div style={{ position: "relative", height: 9, background: "var(--v4-s3)", borderRadius: 5, overflow: "hidden" }}>
                        <div style={{ height: "100%", width: `${barW}%`, background: color, borderRadius: 5, transition: "width .5s" }} />
                        {cauW > 0 && cauW < 100 && (
                          <div style={{ position: "absolute", top: -2, bottom: -2, left: `${cauW}%`, width: 1, background: "var(--v4-rust)", opacity: 0.55 }} />
                        )}
                      </div>
                      <span style={{ fontFamily: "var(--v4-mono)", fontSize: 10.5, color: "var(--v4-ink)", textAlign: "right" }}>
                        {pct.toFixed(0)}%
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
            metricLabel="Funds after cleanup"
            before={String(funds.length)}
            after={String(fundCountAfter != null ? fundCountAfter : funds.length)}
            unit=""
            acceptedCount={accepted.size}
            onSend={() => navigate("/plan")}
          />
        </>
      )}
    </DashboardShell>
  );
}

// ── Small components ─────────────────────────────────────────────────────────

function StatBox({ label, value }) {
  return (
    <div style={{ flex: 1, background: "var(--v4-s0)", border: "1px solid var(--v4-line)", borderRadius: 10, padding: "9px 6px", textAlign: "center" }}>
      <div style={{ fontFamily: "var(--v4-mono)", fontSize: 7, letterSpacing: 1, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 3 }}>
        {label}
      </div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 16, fontWeight: 600, color: "var(--v4-ink)" }}>
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
