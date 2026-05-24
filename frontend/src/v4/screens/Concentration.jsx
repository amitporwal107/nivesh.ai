/**
 * V4 Concentration Dashboard — AMC · Sector · Stock concentration.
 * Endpoint: GET /api/portfolio/exposure/concentration
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api from "../api/client";
import {
  DashboardShell,
  SectionHeader,
  StatTile,
  EmptyState,
  Skeleton,
  formatInr,
} from "../components/DashboardShell";

const HHI_LABEL = (hhi) => {
  if (hhi == null) return { label: "—", tone: "var(--v4-ink-faint)" };
  if (hhi < 0.15) return { label: "Well diversified", tone: "var(--v4-moss)" };
  if (hhi < 0.25) return { label: "Moderate", tone: "var(--v4-gold)" };
  return { label: "Concentrated", tone: "var(--v4-rust)" };
};

export default function Concentration() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    api.get("/api/portfolio/exposure/concentration")
      .then(setData)
      .catch(setErr)
      .finally(() => setLoading(false));
  }, [user]);

  if (authLoading) return null;
  if (!user) { navigate("/onboarding", { replace: true }); return null; }

  return (
    <DashboardShell>
      <div style={pageTitleStyle}>
        <div style={{ fontFamily: "var(--v4-display)", fontSize: 30, color: "var(--v4-ink)", marginBottom: 6 }}>
          Concentration
        </div>
        <div style={{ fontSize: 13, color: "var(--v4-ink-dim)" }}>
          How concentrated is your portfolio across AMCs, sectors, and stocks?
        </div>
      </div>

      {loading && (
        <div style={gridStyle}>
          {[...Array(4)].map((_, i) => <Skeleton key={i} height={90} />)}
        </div>
      )}

      {!loading && err && (
        <EmptyState icon="⚡" title="Could not load data" sub={err.message || String(err)} />
      )}

      {!loading && data && data.empty && (
        <EmptyState
          title="No portfolio data"
          sub="Upload a CAS statement from Onboarding to see concentration analysis."
        />
      )}

      {!loading && data && !data.empty && (
        <>
          {/* Hero stats */}
          <div style={gridStyle}>
            <StatTile
              label="Total portfolio value"
              value={formatInr(data.total_value)}
            />
            <StatTile
              label="Holdings"
              value={data.holdings_count ?? "—"}
            />
            <StatTile
              label="AMC concentration"
              value={data.amc?.hhi != null ? data.amc.hhi.toFixed(3) : "—"}
              sub={HHI_LABEL(data.amc?.hhi).label}
              tone={HHI_LABEL(data.amc?.hhi).tone}
            />
            <StatTile
              label="Top AMC weight"
              value={data.amc?.largest_pct != null ? `${data.amc.largest_pct.toFixed(1)}%` : "—"}
            />
          </div>

          {/* AMC breakdown */}
          <ConcentrationSection
            title="AMC breakdown"
            items={data.amc?.items}
            hhi={data.amc?.hhi}
            heroInsight={data.amc?.hero_insight}
          />

          {/* Sector breakdown */}
          <ConcentrationSection
            title="Sector breakdown"
            items={data.sector?.items}
            hhi={data.sector?.hhi}
            heroInsight={data.sector?.hero_insight}
            extra={
              data.sector?.cycle_split && (
                <div style={cycleSplitStyle}>
                  <CyclePill label="Cyclical" pct={data.sector.cycle_split.cyclical_pct} tone="var(--v4-saffron)" />
                  <CyclePill label="Defensive" pct={data.sector.cycle_split.defensive_pct} tone="var(--v4-moss)" />
                  <CyclePill label="Other" pct={data.sector.cycle_split.other_pct} tone="var(--v4-ink-faint)" />
                </div>
              )
            }
          />

          {/* Stock / company breakdown */}
          <ConcentrationSection
            title="Stock / company breakdown"
            items={data.company?.items}
            hhi={data.company?.hhi}
            heroInsight={data.company?.hero_insight}
          />

          {/* Group / promoter */}
          {data.group?.items?.length > 0 && (
            <ConcentrationSection
              title="Promoter group breakdown"
              items={data.group.items}
              hhi={data.group?.hhi}
              heroInsight={data.group?.hero_insight}
            />
          )}
        </>
      )}
    </DashboardShell>
  );
}

function ConcentrationSection({ title, items, hhi, heroInsight, extra }) {
  if (!items || items.length === 0) return null;
  const { label: hhiLabel, tone: hhiTone } = HHI_LABEL(hhi);

  return (
    <section style={{ marginTop: 36 }}>
      <SectionHeader>
        {title}
        {hhi != null && (
          <span style={{ fontFamily: "var(--v4-mono)", fontSize: 9, color: hhiTone }}>
            HHI {hhi.toFixed(3)} · {hhiLabel}
          </span>
        )}
      </SectionHeader>

      {heroInsight && (
        <div style={heroInsightStyle(heroInsight.tone)}>
          <div style={{ fontFamily: "var(--v4-display)", fontSize: 15, color: "var(--v4-ink)", marginBottom: 4 }}>
            {heroInsight.headline}
          </div>
          {heroInsight.detail && (
            <div style={{ fontSize: 12, color: "var(--v4-ink-dim)", lineHeight: 1.5 }}>
              {heroInsight.detail}
            </div>
          )}
        </div>
      )}

      {extra}

      <div style={barListStyle}>
        {items.slice(0, 10).map((item, i) => (
          <BarRow key={`${item.name || i}`} item={item} max={items[0]?.pct || 1} />
        ))}
      </div>
    </section>
  );
}

function BarRow({ item, max }) {
  const pct = Number(item.pct || 0);
  const barWidth = max > 0 ? (pct / max) * 100 : 0;
  const tone =
    pct > 30 ? "var(--v4-rust)" :
    pct > 20 ? "var(--v4-gold)" :
    "var(--v4-saffron)";

  return (
    <div style={barRowStyle}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 5 }}>
          <span style={{ fontSize: 13, color: "var(--v4-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "70%" }}>
            {item.name || "—"}
          </span>
          <span style={{ fontFamily: "var(--v4-display)", fontSize: 13, color: "var(--v4-ink)", flexShrink: 0, marginLeft: 8 }}>
            {pct.toFixed(1)}%
          </span>
        </div>
        <div style={{ height: 4, borderRadius: 2, background: "var(--v4-line-strong)", overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${barWidth}%`, background: tone, borderRadius: 2, transition: "width 0.4s var(--v4-ease)" }} />
        </div>
        {item.value != null && (
          <div style={{ fontFamily: "var(--v4-mono)", fontSize: 10, color: "var(--v4-ink-faint)", marginTop: 3 }}>
            {formatInr(item.value)}
          </div>
        )}
      </div>
    </div>
  );
}

function CyclePill({ label, pct, tone }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: tone }} />
      <span style={{ fontFamily: "var(--v4-mono)", fontSize: 10, color: "var(--v4-ink-faint)" }}>
        {label}: {pct != null ? `${Number(pct).toFixed(1)}%` : "—"}
      </span>
    </div>
  );
}

/* ─── Styles ─── */

const pageTitleStyle = { marginBottom: 32 };

const gridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
  gap: 14,
  marginBottom: 14,
};

const barListStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
  background: "linear-gradient(165deg, var(--v4-s2), var(--v4-s1))",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-lg)",
  padding: "20px 22px",
};

const barRowStyle = {
  display: "flex",
  alignItems: "center",
  gap: 12,
};

const cycleSplitStyle = {
  display: "flex",
  gap: 20,
  marginBottom: 14,
  padding: "10px 14px",
  background: "var(--v4-s1)",
  border: "1px solid var(--v4-line)",
  borderRadius: "var(--v4-r-md)",
};

const heroInsightStyle = (tone) => ({
  background: "linear-gradient(168deg, var(--v4-hero-a), var(--v4-hero-b))",
  border: "1px solid var(--v4-line-strong)",
  borderLeft: `3px solid ${tone === "positive" ? "var(--v4-moss)" : tone === "warning" ? "var(--v4-gold)" : "var(--v4-rust)"}`,
  borderRadius: "var(--v4-r-md)",
  padding: "14px 18px",
  marginBottom: 14,
});
