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
  RecommendationCard, ApplyCard, HlBar, formatInr,
} from "../components/DashboardShell";

const CONC_CODES = new Set([
  "AMC_CONCENTRATION_EXIT", "AMC_CONCENTRATION", "SECTOR_CONCENTRATION",
  "COMPANY_CONCENTRATION", "STOCK_CONCENTRATION", "OVERLAP_CONSOLIDATION",
]);

const CAUTION_PCT = 25; // threshold line shown on bars

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
  const healthBefore = improvements.health_score?.before ?? improvements.concentration_score?.before ?? null;
  const healthAfter  = improvements.health_score?.after  ?? improvements.concentration_score?.after  ?? null;

  /* Badge: HIGH / MEDIUM / LOW based on sector HHI */
  const sectorHhi = data?.sector?.hhi;
  const badge = sectorHhi != null
    ? (sectorHhi >= 0.25 ? "HIGH" : sectorHhi >= 0.15 ? "MEDIUM" : "LOW")
    : data?.empty ? undefined : undefined;
  const badgeTone = sectorHhi >= 0.25 ? "rust" : sectorHhi >= 0.15 ? "gold" : "moss";

  /* Lens tabs — order: Stocks | Sectors | AMC | Groups */
  const LENS_ORDER = ["company", "sector", "amc", "group"];
  const LENS_LABELS = { company: "Stocks", sector: "Sectors", amc: "AMC", group: "Groups" };

  const lensData = {
    sector:  { items: data?.sector?.items,  hhi: data?.sector?.hhi,  hero: data?.sector?.hero_insight,  label: "By sector · look-through" },
    amc:     { items: data?.amc?.items,     hhi: data?.amc?.hhi,     hero: data?.amc?.hero_insight,     label: "By AMC" },
    company: { items: data?.company?.items, hhi: data?.company?.hhi, hero: data?.company?.hero_insight, label: "By stock / company" },
    group:   { items: data?.group?.items,   hhi: data?.group?.hhi,   hero: data?.group?.hero_insight,   label: "By promoter group" },
  };
  const active = lensData[lens];
  const activeMax = (active.items?.[0]?.pct) || 1;

  /* TOP 5 uses sector items (matches headline context) */
  const top5Pct = (data?.sector?.items || []).slice(0, 5).reduce((s, i) => s + (i.pct || 0), 0).toFixed(0);

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

          {/* Insight card */}
          <div style={insightCardStyle}>
            {active.hero?.headline ? (
              <>
                <div style={{ fontFamily: "var(--v4-display)", fontSize: 21, fontWeight: 600, letterSpacing: "-.02em", color: "var(--v4-ink)" }}>
                  {active.hero.headline}
                </div>
                {active.hero.detail && (
                  <p style={{ fontSize: 12, color: "var(--v4-ink-dim)", margin: "4px 0 11px", lineHeight: 1.5 }}>{active.hero.detail}</p>
                )}
              </>
            ) : (
              <>
                <div style={{ fontFamily: "var(--v4-display)", fontSize: 21, fontWeight: 600, letterSpacing: "-.02em", color: "var(--v4-ink)" }}>
                  Concentration analysis ready
                </div>
                <p style={{ fontSize: 12, color: "var(--v4-ink-dim)", margin: "4px 0 11px", lineHeight: 1.5 }}>
                  Look at your top exposures across sectors, AMCs, stocks and groups.
                </p>
              </>
            )}
            <div style={inlineStatRowStyle}>
              <InlineStat label="Top 5" value={`${top5Pct}%`} />
              <InlineStat label="HHI" value={data.sector?.hhi != null ? Math.round(data.sector.hhi * 10000).toString() : "—"} />
              <InlineStat label="Eff. N" value={data.sector?.effective_n != null ? Number(data.sector.effective_n).toFixed(1) : "—"} />
            </div>
          </div>

          {/* Lens chips — Stocks | Sectors | AMC | Groups */}
          <div style={chipRowStyle}>
            {LENS_ORDER.map(l => (
              <button key={l} type="button" onClick={() => setLens(l)}
                style={l === lens ? {...lensChipStyle, ...lensChipActiveStyle} : lensChipStyle}>
                {LENS_LABELS[l]}
              </button>
            ))}
          </div>

          {/* Chart card */}
          <div style={chartCardStyle}>
            <div style={chartHeaderStyle}>
              <span style={{ fontFamily: "var(--v4-mono)", fontSize: 8.5, letterSpacing: 1.1, color: "var(--v4-ink-mute)", textTransform: "uppercase" }}>
                {active.label}
              </span>
              <span style={{ marginLeft: "auto", fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 0.9, color: "var(--v4-saffron)", textTransform: "uppercase" }}>
                Caution {CAUTION_PCT}%
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "13px 16px 15px" }}>
              {(active.items || []).slice(0, 10).map((item, i) => (
                <BarRow key={item.name || i} item={item} max={activeMax} caution={CAUTION_PCT} />
              ))}
              {(!active.items || active.items.length === 0) && (
                <div style={{ fontSize: 12, color: "var(--v4-ink-faint)", padding: "8px 0" }}>No data for this lens.</div>
              )}
            </div>
          </div>

          {/* ② Recommendations */}
          {recs.length > 0 && (
            <>
              <HlBar>② Recommendations · ranked by priority</HlBar>
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
            metricLabel="Projected health"
            before={healthBefore != null ? String(Math.round(healthBefore)) : null}
            after={healthAfter != null ? String(Math.round(healthAfter)) : null}
            unit=""
            acceptedCount={accepted.size}
            onSend={() => navigate("/plan")}
          />
        </>
      )}
    </DashboardShell>
  );
}

function InlineStat({ label, value }) {
  return (
    <div style={inlineStatBoxStyle}>
      <div style={{ fontFamily: "var(--v4-mono)", fontSize: 7, letterSpacing: 1, color: "var(--v4-ink-faint)", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontFamily: "var(--v4-display)", fontSize: 16, fontWeight: 600, marginTop: 3, color: "var(--v4-ink)" }}>{value}</div>
    </div>
  );
}

function BarRow({ item, max, caution }) {
  const pct = Number(item.pct || 0);
  const barWidth = max > 0 ? Math.min((pct / max) * 100, 100) : 0;
  // Caution tick position as % of the track — only render if max > caution
  const cautionPos = (caution && max > caution) ? Math.min((caution / max) * 100, 100) : null;
  const tone = pct > caution ? "var(--v4-rust)" : "var(--v4-moss)";
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span style={{ fontSize: 13, color: "var(--v4-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "75%" }}>{item.name || "—"}</span>
        <span style={{ fontFamily: "var(--v4-display)", fontSize: 13, color: "var(--v4-ink)", flexShrink: 0 }}>{pct.toFixed(1)}%</span>
      </div>
      <div style={{ height: 4, borderRadius: 2, background: "var(--v4-line-strong)", position: "relative" }}>
        <div style={{ height: "100%", width: `${barWidth}%`, background: tone, borderRadius: 2, transition: "width .4s var(--v4-ease)" }} />
        {cautionPos != null && (
          <div style={{ position: "absolute", top: 0, left: `${cautionPos}%`, width: 1, height: "100%", background: "rgba(255,255,255,0.25)" }} />
        )}
      </div>
    </div>
  );
}

const eyebrowStyle = { fontFamily: "var(--v4-mono)", fontSize: 8, letterSpacing: 1.6, color: "var(--v4-ink-faint)", textTransform: "uppercase", marginBottom: 10 };
const insightCardStyle = { background: "linear-gradient(168deg, var(--v4-hero-a), var(--v4-hero-b))", border: "1px solid var(--v4-line-strong)", borderRadius: 16, padding: "14px 16px", marginBottom: 11 };
const inlineStatRowStyle = { display: "flex", gap: 8 };
const inlineStatBoxStyle = { flex: 1, background: "var(--v4-s0)", border: "1px solid var(--v4-line)", borderRadius: 10, padding: "9px 6px", textAlign: "center" };
const chipRowStyle  = { display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 11 };
const lensChipStyle = { fontFamily: "var(--v4-mono)", fontSize: 9, letterSpacing: 0.8, color: "var(--v4-ink-faint)", background: "var(--v4-s1)", border: "1px solid var(--v4-line)", padding: "6px 13px", borderRadius: 999, cursor: "pointer", textTransform: "uppercase" };
const lensChipActiveStyle = { color: "var(--v4-saffron)", borderColor: "rgba(255,146,72,.4)", background: "rgba(255,146,72,.08)" };
const chartCardStyle = { background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))", border: "1px solid var(--v4-line)", borderRadius: "var(--v4-r-lg)", overflow: "hidden", marginBottom: 18 };
const chartHeaderStyle = { display: "flex", alignItems: "center", gap: 8, padding: "11px 16px 8px", borderBottom: "1px solid var(--v4-line)" };
