/**
 * V4 Diversification Dashboard — ① Insight · ② Recommendations · ③ Apply
 * Endpoints:
 *   GET /api/portfolio/exposure/fund-overlap/matrix
 *   GET /api/plans/active
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Treemap, ResponsiveContainer } from "recharts";
import api from "../api/client";
import {
  DashboardShell, EmptyState, Skeleton,
  RecommendationCard, ApplyCard, HlBar,
} from "../components/DashboardShell";

// ── V4 palette (hex — CSS vars don't resolve inside <svg>) ───────────────────
const C_RUST  = "#c44b3a";   // ≥65% overlap  → danger
const C_GOLD  = "#c49a2a";   // 40–65%        → caution
const C_MOSS  = "#3d7a54";   // <40%          → safe
const C_MUTED = "#2c2926";   // no data

function overlapColor(pct) {
  if (pct >= 65) return C_RUST;
  if (pct >= 40) return C_GOLD;
  if (pct > 0)   return C_MOSS;
  return C_MUTED;
}

function maxOverlapForFund(isin, pairs) {
  let max = 0;
  for (const p of pairs) {
    if (p.a === isin || p.b === isin) max = Math.max(max, Number(p.overlap_pct) || 0);
  }
  return max;
}

function cleanAmc(raw) {
  return (raw || "Other")
    .replace(/\s+(Mutual Fund|Asset Management(?: Co\.?)?|AMC|Ltd\.?|Limited)$/i, "")
    .trim();
}

function shortLabel(name, isin) {
  if (!name || name === isin) return (isin || "").slice(-6);
  return name
    .replace(/\s+(Direct|Regular|Growth|IDCW|Dividend|Plan|Option|Scheme)\b.*/i, "")
    .trim()
    .slice(0, 24);
}

function buildTreemapData(funds, pairs) {
  const byAmc = {};
  for (const f of funds) {
    const amc = cleanAmc(f.amc);
    if (!byAmc[amc]) byAmc[amc] = [];
    byAmc[amc].push({
      name: f.name || f.id,
      isin: f.id,
      value: Math.max(f.value_rs || 0, 500),
      maxOverlap: maxOverlapForFund(f.id, pairs),
    });
  }
  return Object.entries(byAmc)
    .sort(([, a], [, b]) =>
      b.reduce((s, f) => s + f.value, 0) - a.reduce((s, f) => s + f.value, 0)
    )
    .map(([name, children]) => ({ name, children }));
}

function TreemapCell(props) {
  const { x, y, width, height, name, depth, maxOverlap, isin } = props;
  if (!width || !height || width < 2 || height < 2) return null;

  if (depth === 1) {
    return (
      <g>
        <rect
          x={x + 1} y={y + 1}
          width={width - 2} height={height - 2}
          fill="rgba(20,15,10,0)"
          stroke="rgba(255,255,255,0.07)"
          strokeWidth={1}
          rx={6}
        />
        {width > 55 && height > 18 && (
          <text
            x={x + 7} y={y + 13}
            fill="rgba(255,255,255,0.3)"
            fontSize={8}
            fontFamily="ui-monospace, monospace"
            style={{ userSelect: "none", pointerEvents: "none" }}
          >
            {name}
          </text>
        )}
      </g>
    );
  }

  if (depth === 2) {
    const ov = maxOverlap || 0;
    const bg = overlapColor(ov);
    const label = shortLabel(name, isin);
    const showLabel = width > 48 && height > 20;
    const showOv    = width > 52 && height > 40 && ov > 0;
    const fontSize  = Math.max(7.5, Math.min(11, width / 10));

    return (
      <g>
        <rect
          x={x + 2} y={y + 2}
          width={width - 4} height={height - 4}
          fill={bg}
          fillOpacity={0.82}
          rx={4}
        />
        {showLabel && (
          <text
            x={x + width / 2}
            y={y + height / 2 - (showOv ? 8 : 0)}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="#fff"
            fillOpacity={0.9}
            fontSize={fontSize}
            fontFamily="ui-monospace, monospace"
            style={{ userSelect: "none", pointerEvents: "none" }}
          >
            {label}
          </text>
        )}
        {showOv && (
          <text
            x={x + width / 2}
            y={y + height / 2 + 9}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="#fff"
            fillOpacity={0.5}
            fontSize={7.5}
            fontFamily="ui-monospace, monospace"
            style={{ userSelect: "none", pointerEvents: "none" }}
          >
            {ov.toFixed(0)}% overlap
          </text>
        )}
      </g>
    );
  }

  return null;
}

const DIV_CODES = new Set([
  "OVERLAP_CONSOLIDATION", "REGULAR_DIRECT_DUPLICATE",
  "COST_LEAK_SWITCH_TO_DIRECT", "COST_LEAK_SWITCH",
  "SAME_CATEGORY_CONSOLIDATION", "CROSS_CATEGORY_REPLACEMENT",
  "INTERNATIONAL_DIVERSIFICATION", "GEOGRAPHIC_GAP",
]);

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

  const funds      = data?.funds  || [];
  const pairs      = data?.pairs  || [];
  const maxPct     = data?.max_pct   || 0;
  const highPairs  = data?.high_pairs || 0;
  const uniqueStocks = data?.unique_stocks_count ?? "—";

  const treemapData = funds.length >= 2 ? buildTreemapData(funds, pairs) : null;

  // Count distinct funds involved in any overlapping pair (≥40%)
  const overlappingFundSet = new Set();
  pairs.filter(p => Number(p.overlap_pct) >= 40).forEach(p => {
    if (p.a) overlappingFundSet.add(p.a);
    if (p.b) overlappingFundSet.add(p.b);
  });
  const overlappingFundCount = overlappingFundSet.size;

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
          {/* ① Insight header */}
          <div style={eyebrowStyle}>① Insight</div>

          <div style={insightCardStyle}>
            <div style={{ fontFamily: "var(--v4-display)", fontSize: 21, fontWeight: 600, letterSpacing: "-.02em", color: "var(--v4-ink)", marginBottom: 6 }}>
              {overlappingFundCount > 0
                ? `${overlappingFundCount} fund${overlappingFundCount > 1 ? "s" : ""} hold near-identical stocks`
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

          {/* Fund allocation treemap */}
          {treemapData && (
            <div style={cardStyle}>
              <div style={cardHeaderStyle}>
                <span style={monoLabel}>Fund allocation map</span>
                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <LegendDot color={C_RUST} label="≥65% overlap" />
                  <LegendDot color={C_GOLD} label="40–65%" />
                  <LegendDot color={C_MOSS} label="<40%" />
                </div>
              </div>
              <div style={{ padding: "10px 12px 14px" }}>
                <ResponsiveContainer width="100%" height={260}>
                  <Treemap
                    data={treemapData}
                    dataKey="value"
                    content={<TreemapCell />}
                    animationDuration={350}
                  />
                </ResponsiveContainer>
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

function LegendDot({ color, label }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <div style={{ width: 7, height: 7, borderRadius: 2, background: color, flexShrink: 0 }} />
      <span style={{ fontFamily: "var(--v4-mono)", fontSize: 7.5, color: "var(--v4-ink-mute)", letterSpacing: 0.7, textTransform: "uppercase" }}>
        {label}
      </span>
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
