/**
 * V4 Tax Dashboard — ① Insight · ② Recommendations · ③ Apply
 * Endpoints:
 *   GET /api/portfolio/tax-summary
 *   GET /api/plans/active
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api from "../api/client";
import {
  DashboardShell, EmptyState, Skeleton,
  RecommendationCard, ApplyCard, HlBar, formatInr,
} from "../components/DashboardShell";

/* caution at 100 → the line would be at 100% of the scale bar (right edge = invisible) */
const CAUTION_PCT = 100;

function stripFundSuffix(name) {
  if (!name) return "—";
  return name
    .replace(/\s+(Regular Plan Growth|Direct Plan Growth|Fund Growth|Regular Plan|Direct Plan|Growth)\b.*/i, "")
    .trim()
    .slice(0, 22);
}

export default function Tax() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();

  const [loading, setLoading]   = useState(true);
  const [taxData, setTaxData]   = useState(null);
  const [plan, setPlan]         = useState(null);
  const [err, setErr]           = useState(null);
  const [accepted, setAccepted] = useState(new Set());

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    Promise.allSettled([
      api.get("/api/portfolio/tax-summary"),
      api.get("/api/plans/active"),
    ]).then(([t, p]) => {
      if (t.status === "fulfilled") setTaxData(t.value);
      else setErr(t.reason);
      if (p.status === "fulfilled") setPlan(p.value);
      setLoading(false);
    });
  }, [user]);

  if (authLoading) return null;
  if (!user) { navigate("/onboarding", { replace: true }); return null; }

  const totalHarvestable = taxData?.total_harvestable_rs ?? 0;
  const ltcgUsed         = taxData?.ltcg_used_rs ?? null;
  const ltcgLimit        = taxData?.ltcg_limit_rs ?? 100000;
  const daysLeft         = taxData?.days_to_fy_end ?? null;
  const candidates       = taxData?.candidates || [];
  const isEmpty          = taxData?.empty ?? (totalHarvestable === 0 && candidates.length === 0);

  /* Badge */
  const badge     = totalHarvestable > 0 ? "ACTION DUE" : "ALL CLEAR";
  const badgeTone = totalHarvestable > 0 ? "indigo" : "moss";

  /* Bar chart: sort candidates by harvestable_rs descending, top 8 */
  const sortedCandidates = [...candidates]
    .sort((a, b) => Number(b.harvestable_rs) - Number(a.harvestable_rs))
    .slice(0, 8);
  const maxHarvestable   = sortedCandidates.length > 0 ? Number(sortedCandidates[0].harvestable_rs) : 0;
  const scaleMax         = Math.max(maxHarvestable, 1);

  /* ② filter recs */
  const allActions = plan?.plan?.actions || [];
  const domainRecs = allActions.filter(a => {
    const codes = a.reason_codes || [];
    const domain = (a.source_domain || a.domain || "").toLowerCase();
    return (codes.includes("TAX_HARVEST") || domain === "tax")
      && (a.status || "").toUpperCase() !== "COMPLETED";
  });
  const recs = domainRecs.slice(0, 4);

  /* ③ improvement */
  const improvements    = plan?.plan?.improvements || {};
  const taxSavedBefore  = 0;
  const taxSavedAfter   = improvements.tax_saved ?? improvements.projected_tax_saved ?? null;

  const formatK = (rs) => {
    if (rs == null) return "—";
    const k = Number(rs) / 1000;
    return `${k.toFixed(1)}k`;
  };

  return (
    <DashboardShell title="Tax" badge={badge} badgeTone={badgeTone}>

      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[...Array(4)].map((_, i) => <Skeleton key={i} height={90} />)}
        </div>
      )}
      {!loading && err && (
        <EmptyState icon="⚡" title="Could not load data" sub={err.message || String(err)} />
      )}
      {!loading && taxData?.empty && isEmpty && (
        <EmptyState title="No tax data" sub="Upload a CAS to see your tax harvest opportunities." />
      )}

      {!loading && taxData && !isEmpty && (
        <>
          {/* ① Insight */}
          <div style={eyebrowStyle}>① Insight</div>

          <div style={insightCardStyle}>
            <div style={{ fontFamily: "var(--v4-display)", fontSize: 21, fontWeight: 600, letterSpacing: "-.02em", color: "var(--v4-ink)", marginBottom: 6 }}>
              {totalHarvestable > 0
                ? `${formatInr(totalHarvestable)} of tax is harvestable now`
                : "No harvest opportunity this FY"}
            </div>
            <p style={{ fontSize: 12, color: "var(--v4-ink-dim)", margin: "0 0 12px", lineHeight: 1.5 }}>
              {totalHarvestable > 0
                ? `Book losses now to offset LTCG. You have ₹${((ltcgLimit - (ltcgUsed || 0)) / 1000).toFixed(0)}K of tax-free LTCG headroom remaining.`
                : "Your LTCG is within the ₹1L free limit for this financial year."}
            </p>
            <div style={statRowStyle}>
              <StatBox label="Harvestable" value={formatInr(totalHarvestable)} />
              <StatBox label="LTCG Used"   value={ltcgUsed != null ? formatInr(ltcgUsed) : "—"} />
              <StatBox label="Days Left"   value={daysLeft != null ? String(daysLeft) : "—"} />
            </div>
          </div>

          {/* Harvest opportunity bar chart */}
          {sortedCandidates.length > 0 && (
            <div style={cardStyle}>
              <div style={cardHeaderStyle}>
                <span style={monoLabel}>Harvest opportunity by holding</span>
                <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8, color: "var(--v4-ink-faint)", letterSpacing: 0.9, textTransform: "uppercase" }}>
                  ₹K
                </span>
              </div>
              <div style={{ padding: "13px 16px 15px", display: "flex", flexDirection: "column", gap: 8 }}>
                {sortedCandidates.map((cand, i) => {
                  const rs   = Number(cand.harvestable_rs) || 0;
                  const barW = Math.round((rs / scaleMax) * 100);
                  /* caution at 100% — line never shows visibly */
                  const name = stripFundSuffix(cand.name);
                  return (
                    <div key={cand.name || i} style={{ display: "grid", gridTemplateColumns: "165px 1fr 48px", gap: 10, alignItems: "center" }}>
                      <span style={{ fontSize: 11.5, color: "var(--v4-ink-dim)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {name}
                      </span>
                      <div style={{ position: "relative", height: 9, background: "var(--v4-s3)", borderRadius: 5, overflow: "hidden" }}>
                        <div style={{ height: "100%", width: `${barW}%`, background: "var(--v4-indigo)", borderRadius: 5, transition: "width .5s" }} />
                      </div>
                      <span style={{ fontFamily: "var(--v4-mono)", fontSize: 10.5, color: "var(--v4-ink)", textAlign: "right" }}>
                        {formatK(rs)}
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
            metricLabel="Projected tax saved"
            before={taxSavedAfter != null ? "0" : undefined}
            after={taxSavedAfter != null ? String(Math.round(taxSavedAfter)) : undefined}
            unit=""
            acceptedCount={accepted.size}
            onSend={() => navigate("/plan")}
          />
        </>
      )}

      {/* Show apply card even when no data to send to plan */}
      {!loading && !taxData && !err && (
        <ApplyCard
          metricLabel="Projected tax saved"
          before={undefined}
          after={undefined}
          unit=""
          acceptedCount={accepted.size}
          onSend={() => navigate("/plan")}
        />
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
