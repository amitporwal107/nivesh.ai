/**
 * V4 Concentration Dashboard — ① Insight · ② Recommendations · ③ Apply
 * Endpoints:
 *   GET /api/portfolio/exposure/concentration
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

const CONC_CODES = new Set([
  "AMC_CONCENTRATION_EXIT", "AMC_CONCENTRATION", "SECTOR_CONCENTRATION",
  "COMPANY_CONCENTRATION", "STOCK_CONCENTRATION", "OVERLAP_CONSOLIDATION",
]);

const HHI_META = (hhi) => {
  if (hhi == null) return { label: "—", tone: "var(--v4-ink-faint)" };
  if (hhi < 0.15) return { label: "Well diversified", tone: "var(--v4-moss)" };
  if (hhi < 0.25) return { label: "Moderate",         tone: "var(--v4-gold)" };
  return              { label: "Concentrated",         tone: "var(--v4-rust)" };
};

export default function Concentration() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();

  const [loading, setLoading]   = useState(true);
  const [data, setData]         = useState(null);
  const [plan, setPlan]         = useState(null);
  const [err, setErr]           = useState(null);
  const [accepted, setAccepted] = useState(new Set());
  const [lens, setLens]         = useState("sector"); /* sector | amc | company | group */

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    Promise.allSettled([
      api.get("/api/portfolio/exposure/concentration"),
      api.get("/api/plans/active"),
    ]).then(([c, p]) => {
      if (c.status === "fulfilled") setData(c.value);
      else setErr(c.reason);
      if (p.status === "fulfilled") setPlan(p.value);
      setLoading(false);
    });
  }, [user]);

  if (authLoading) return null;
  if (!user) { navigate("/onboarding", { replace: true }); return null; }

  /* ② filter */
  const allActions  = plan?.plan?.actions || [];
  const domainRecs  = allActions.filter(a =>
    (a.reason_codes || []).some(c => CONC_CODES.has(c))
    && (a.status || "").toUpperCase() !== "COMPLETED"
  );
  const recs = domainRecs.length > 0 ? domainRecs.slice(0, 4) : allActions.filter(a => ["EXIT","TRIM"].includes((a.type||"").toUpperCase()) && (a.status||"").toUpperCase() !== "COMPLETED").slice(0, 3);

  /* ③ improvement metric */
  const improvements = plan?.plan?.improvements || {};
  const before = improvements.top_amc_pct?.before;
  const after  = improvements.top_amc_pct?.after;

  const badge = data?.amc?.hhi != null
    ? HHI_META(data.amc.hhi).label
    : data?.empty ? undefined : "Loading";
  const badgeTone = data?.amc?.hhi >= 0.25 ? "rust" : data?.amc?.hhi >= 0.15 ? "gold" : "moss";

  /* lens data */
  const lensData = {
    sector:  { items: data?.sector?.items,  hhi: data?.sector?.hhi,  hero: data?.sector?.hero_insight,  label: "By sector · look-through" },
    amc:     { items: data?.amc?.items,     hhi: data?.amc?.hhi,     hero: data?.amc?.hero_insight,     label: "By AMC" },
    company: { items: data?.company?.items, hhi: data?.company?.hhi, hero: data?.company?.hero_insight, label: "By stock / company" },
    group:   { items: data?.group?.items,   hhi: data?.group?.hhi,   hero: data?.group?.hero_insight,   label: "By promoter group" },
  };
  const active = lensData[lens];

  return (
    <DashboardShell title="Concentration" badge={badge} badgeTone={badgeTone}>
      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[...Array(4)].map((_, i) => <Skeleton key={i} height={90} />)}
        </div>
      )}
      {!loading && err && <EmptyState icon="⚡" title="Could not load data" sub={err.message || String(err)} />}
      {!loading && data?.empty && <EmptyState title="No portfolio data" sub="Upload a CAS statement from Onboarding." />}

      {!loading && data && !data.empty && (
        <>
          {/* ① Insight */}
          <div style={eyebrowStyle}>① Insight</div>

          {/* Stats row */}
          <div style={statsRowStyle}>
            <StatTile label="Top 5 weight"   value={data.amc?.items?.slice(0,5).reduce((s,i)=>s+(i.pct||0),0).toFixed(1)+"%" ?? "—"} />
            <StatTile label="HHI (sector)"   value={data.sector?.hhi != null ? data.sector.hhi.toFixed(3) : "—"} sub={HHI_META(data.sector?.hhi).label} tone={HHI_META(data.sector?.hhi).tone} />
            <StatTile label="Effective N"     value={data.sector?.effective_n != null ? Number(data.sector.effective_n).toFixed(1) : "—"} />
          </div>

          {/* Lens chips */}
          <div style={chipRowStyle}>
            {(["sector","amc","company","group"]).map(l => (
              <button key={l} type="button" onClick={() => setLens(l)}
                style={l === lens ? {...lensChipStyle, ...lensChipActiveStyle} : lensChipStyle}>
                {l === "sector" ? "Sectors" : l === "amc" ? "AMC" : l === "company" ? "Stocks" : "Groups"}
              </button>
            ))}
          </div>

          {/* Chart card */}
          <div style={chartCardStyle}>
            <div style={chartHeaderStyle}>
              <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8.5, letterSpacing: 1.1, color: "var(--v4-ink-mute)", textTransform: "uppercase" }}>
                {active.label}
              </span>
              {active.hhi != null && (
                <span style={{ marginLeft: "auto", fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 0.9, color: active.hhi > 0.25 ? "var(--v4-rust)" : "var(--v4-gold)", textTransform: "uppercase" }}>
                  Caution {active.hhi > 0.25 ? ">25%" : "25%"}
                </span>
              )}
            </div>
            {active.hero && (
              <div style={heroInsightStyle(active.hero.tone)}>
                <div style={{ fontFamily: "var(--v4-display)", fontSize: 15, color: "var(--v4-ink)", marginBottom: 4 }}>{active.hero.headline}</div>
                {active.hero.detail && <div style={{ fontSize: 12, color: "var(--v4-ink-dim)", lineHeight: 1.5 }}>{active.hero.detail}</div>}
              </div>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "13px 16px 15px" }}>
              {(active.items || []).slice(0, 10).map((item, i) => (
                <BarRow key={item.name || i} item={item} max={(active.items?.[0]?.pct) || 1} />
              ))}
              {(!active.items || active.items.length === 0) && (
                <div style={{ fontSize: 12, color: "var(--v4-ink-faint)", padding: "8px 0" }}>No data for this lens.</div>
              )}
            </div>
          </div>

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
            metricLabel="Top AMC weight"
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

function BarRow({ item, max }) {
  const pct = Number(item.pct || 0);
  const barWidth = max > 0 ? Math.min((pct / max) * 100, 100) : 0;
  const tone = pct > 30 ? "var(--v4-rust)" : pct > 20 ? "var(--v4-gold)" : "var(--v4-saffron)";
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span style={{ fontSize: 13, color: "var(--v4-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "75%" }}>{item.name || "—"}</span>
        <span style={{ fontFamily: "var(--v4-display)", fontSize: 13, color: "var(--v4-ink)", flexShrink: 0 }}>{pct.toFixed(1)}%</span>
      </div>
      <div style={{ height: 4, borderRadius: 2, background: "var(--v4-line-strong)", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${barWidth}%`, background: tone, borderRadius: 2, transition: "width .4s var(--v4-ease)" }} />
      </div>
    </div>
  );
}

const eyebrowStyle = { fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 10 };
const statsRowStyle = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px,1fr))", gap: 10, marginBottom: 12 };
const chipRowStyle  = { display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 11 };
const lensChipStyle = { fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 0.8, color: "var(--v4-ink-faint)", background: "var(--v4-s1)", border: "1px solid var(--v4-line)", padding: "6px 13px", borderRadius: 999, cursor: "pointer", textTransform: "uppercase" };
const lensChipActiveStyle = { color: "var(--v4-saffron)", borderColor: "rgba(255,146,72,.4)", background: "rgba(255,146,72,.08)" };
const chartCardStyle = { background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))", border: "1px solid var(--v4-line)", borderRadius: "var(--v4-r-lg)", overflow: "hidden", marginBottom: 18 };
const chartHeaderStyle = { display: "flex", alignItems: "center", gap: 8, padding: "11px 16px 8px", borderBottom: "1px solid var(--v4-line)" };
const heroInsightStyle = (tone) => ({ borderLeft: `3px solid ${tone === "ok" ? "var(--v4-moss)" : tone === "warn" ? "var(--v4-gold)" : "var(--v4-rust)"}`, padding: "12px 16px 10px", borderBottom: "1px solid var(--v4-line)" });
const hlStyle = { fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 9, display: "flex", alignItems: "center", gap: 8 };
