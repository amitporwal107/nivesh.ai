import React, { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { AlertTriangle, RefreshCw } from "lucide-react";
import HeroCard from "../../components/HeroCard";
import CompactCard from "../../components/CompactCard";
import CategoryChip from "../../components/CategoryChip";
import TinyChip from "../../components/TinyChip";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { OverlapDonut } from "../../components/viz";
import { useConcentration } from "../../adapters/concentration";

function HorizBar({ items = [], height = 7 }) {
  const max = Math.max(...items.map((i) => i.pct || 0), 1);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5, width: "100%" }}>
      {items.slice(0, 5).map((item, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ width: 76, fontSize: 10, color: "var(--v3-ink-3)", fontFamily: "var(--v3-font-sans)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {item.name}
          </span>
          <div style={{ flex: 1, height, background: "var(--v3-bg-3)", borderRadius: 2 }}>
            <div style={{ width: `${(item.pct / max) * 100}%`, height: "100%", borderRadius: 2, background: (item.pct || 0) > 25 ? "var(--v3-crimson)" : "var(--v3-saffron)" }} />
          </div>
          <span className="v3-data" style={{ fontSize: 10, color: "var(--v3-ink-2)", minWidth: 30, textAlign: "right" }}>{item.pct?.toFixed(1)}%</span>
        </div>
      ))}
    </div>
  );
}

function DetailPanel({ dimension, data }) {
  if (!data) return null;
  const items = (() => {
    if (dimension === "amc") return (data.amc?.items || []).map((x) => ({ name: x.name || x.amc, pct: x.pct ?? x.weight_pct }));
    if (dimension === "sector") return (data.sector?.items || []).map((x) => ({ name: x.name || x.sector, pct: x.pct ?? x.weight_pct }));
    if (dimension === "company") return (data.company?.items || []).map((x) => ({ name: x.name || x.company, pct: x.pct ?? x.weight_pct }));
    if (dimension === "group") return (data.group?.items || []).map((x) => ({ name: x.name || x.group, pct: x.pct ?? x.weight_pct }));
    if (dimension === "hidden") return (data.hidden_overlap || []).map((x) => ({ name: x.name || x.company, pct: x.pct ?? x.overlap_pct }));
    if (dimension === "category") return (data.category_overlap || []).map((x) => ({ name: x.category, pct: x.fund_count ?? x.count }));
    return [];
  })();
  const hhi = dimension === "amc" ? data.amc?.hhi : dimension === "sector" ? data.sector?.hhi : null;
  if (!items.length) return null;
  return (
    <div style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 14, padding: 16, marginTop: 4 }}>
      {hhi != null && (
        <div style={{ marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
          <span className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", fontSize: 10 }}>HHI</span>
          <span className="v3-data" style={{ color: hhi > 1500 ? "var(--v3-crimson)" : "var(--v3-moss)", fontSize: 13 }}>{hhi}</span>
          <span style={{ fontSize: 11, color: "var(--v3-ink-4)" }}>{hhi > 2500 ? "High concentration" : hhi > 1500 ? "Moderate concentration" : "Well diversified"}</span>
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {items.slice(0, 10).map((item, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="v3-data" style={{ width: 18, fontSize: 10, color: "var(--v3-ink-4)" }}>{i + 1}</span>
            <span style={{ flex: 1, fontSize: 13, color: "var(--v3-ink-1)" }}>{item.name}</span>
            <div style={{ width: 90, height: 5, background: "var(--v3-bg-3)", borderRadius: 2 }}>
              <div style={{ width: `${Math.min((item.pct || 0) * 2.5, 100)}%`, height: "100%", borderRadius: 2, background: "var(--v3-saffron)" }} />
            </div>
            <span className="v3-data" style={{ fontSize: 12, color: "var(--v3-ink-2)", minWidth: 34, textAlign: "right" }}>
              {typeof item.pct === "number" ? `${item.pct.toFixed(1)}%` : item.pct}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ErrorState({ onRetry }) {
  return (
    <div style={{ textAlign: "center", padding: "60px 24px", display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
      <AlertTriangle size={28} color="var(--v3-ink-4)" />
      <p style={{ color: "var(--v3-ink-3)", fontSize: 14, margin: 0 }}>Couldn't load concentration data</p>
      <button onClick={onRetry} style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 16px", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 999, fontSize: 13, color: "var(--v3-ink-2)", cursor: "pointer" }}>
        <RefreshCw size={13} /> Retry
      </button>
    </div>
  );
}

const DIMENSIONS = [
  { id: "all", label: "All" },
  { id: "amc", label: "AMC" },
  { id: "sector", label: "Sector" },
  { id: "company", label: "Company" },
  { id: "group", label: "Group" },
  { id: "hidden", label: "Hidden Overlap" },
  { id: "category", label: "Categories" },
];

export default function Concentration() {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const navigate = useNavigate();
  const [activeDim, setActiveDim] = useState("all");

  const { data, loading, error, refetch } = useConcentration();

  const topSector = data?.sector?.items?.[0] || data?.sector?.top;
  const topSectorName = topSector?.name || topSector?.sector || "—";
  const topSectorPct = topSector?.pct ?? topSector?.weight_pct ?? 0;
  const sectorHHI = data?.sector?.hhi ?? null;

  const sectorItems = (data?.sector?.items || []).slice(0, 5).map((x, i) => ({
    name: x.name || x.sector,
    pct: x.pct ?? x.weight_pct ?? 0,
  }));

  const topAMCPct = data?.amc?.items?.[0]?.pct ?? data?.amc?.top?.pct ?? 0;
  const topCompanyPct = data?.company?.items?.[0]?.pct ?? data?.company?.top?.pct ?? 0;

  const heroTitle = loading
    ? "Loading concentration data…"
    : data?.empty
    ? "Upload your portfolio to see concentration analysis"
    : sectorHHI != null
    ? `Sector HHI ${sectorHHI}${sectorHHI > 1500 ? " — above the 1500 caution threshold" : " — well diversified"}`
    : topSectorPct > 0
    ? `Top sector ${topSectorName} at ${topSectorPct.toFixed(0)}% of portfolio`
    : "Analysing your portfolio concentration…";

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Portfolio · Risk" title="Concentration" />
      {error && !loading ? (
        <ErrorState onRetry={refetch} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 80 }}>
          <HeroCard
            layout={isDesktop ? "desktop" : "mobile"}
            category="risk"
            priorityLabel={loading ? "Loading…" : sectorHHI > 1500 ? "Concentration alert" : "For you"}
            title={heroTitle}
            description={isDesktop && !data?.empty && topSectorName !== "—" ? `Your largest sector is ${topSectorName} at ${topSectorPct.toFixed(0)}%. HHI above 1500 indicates meaningful single-sector risk.` : null}
            viz={
              loading ? (
                <div style={{ width: "100%", height: 100, background: "var(--v3-bg-3)", borderRadius: 10 }} />
              ) : sectorItems.length > 0 ? (
                <HorizBar items={sectorItems} />
              ) : null
            }
            ctaText="Suggest a concentration fix →"
            onClick={() => navigate("/v3/chat?q=How+do+I+reduce+concentration+risk+in+my+portfolio")}
          />

          <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 2 }}>
            {DIMENSIONS.map((d) => (
              <CategoryChip key={d.id} category="risk" label={d.label} active={activeDim === d.id} onClick={() => setActiveDim(activeDim === d.id && d.id !== "all" ? "all" : d.id)} />
            ))}
          </div>

          {activeDim !== "all" && !loading && <DetailPanel dimension={activeDim} data={data} />}

          <section>
            <SectionHead title="Breakdown" count="6 dimensions" />
            <div style={{ display: "grid", gridTemplateColumns: isDesktop ? "repeat(3, 1fr)" : "1fr 1fr", gap: 12 }}>
              <CompactCard category="risk" label={`Top AMC · ${data?.amc?.items?.[0]?.name || "—"}`} meta={`${topAMCPct > 0 ? `${topAMCPct.toFixed(1)}% · ` : ""}HHI ${data?.amc?.hhi ?? "—"}`} viz={<OverlapDonut value={topAMCPct || 0} color="var(--v3-saffron)" size={46} />} onClick={() => setActiveDim("amc")} />
              <CompactCard category="risk" label={`Top sector · ${topSectorName}`} meta={`${topSectorPct > 0 ? `${topSectorPct.toFixed(1)}% · ` : ""}HHI ${sectorHHI ?? "—"}`} viz={<OverlapDonut value={topSectorPct || 0} color={topSectorPct > 25 ? "var(--v3-crimson)" : "var(--v3-indigo)"} size={46} />} onClick={() => setActiveDim("sector")} />
              <CompactCard category="risk" label={`Top stock · ${data?.company?.items?.[0]?.name || "—"}`} meta={`${topCompanyPct > 0 ? `${topCompanyPct.toFixed(1)}%` : "—"} · ${data?.company?.total_stocks ?? "—"} stocks`} viz={<OverlapDonut value={topCompanyPct || 0} color="var(--v3-crimson)" size={46} />} onClick={() => setActiveDim("company")} />
              <CompactCard category="risk" label="Business groups" meta={`${data?.group?.items?.length ?? "—"} groups · top ${data?.group?.items?.[0]?.pct?.toFixed(1) ?? "—"}%`} viz={<OverlapDonut value={data?.group?.items?.[0]?.pct || 0} color="var(--v3-gold)" size={46} />} onClick={() => setActiveDim("group")} />
              <CompactCard category="risk" label="Hidden overlap" meta={`${data?.hidden_overlap?.length ?? 0} stocks via 2+ routes`} viz={<OverlapDonut value={Math.min((data?.hidden_overlap?.length || 0) * 10, 100)} color="var(--v3-moss)" size={46} />} onClick={() => setActiveDim("hidden")} />
              <CompactCard category="risk" label="Category overlap" meta={`${data?.category_overlap?.length ?? 0} categories with 2+ funds`} viz={<OverlapDonut value={Math.min((data?.category_overlap?.length || 0) * 20, 100)} color="var(--v3-indigo)" size={46} />} onClick={() => setActiveDim("category")} />
            </div>
          </section>

          {data?.coverage_pct > 0 && (
            <p className="v3-eyebrow" style={{ color: "var(--v3-ink-4)", fontSize: 10, margin: 0 }}>
              Look-through coverage: {data.coverage_pct.toFixed(0)}% of portfolio
            </p>
          )}

          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <TinyChip onClick={() => navigate("/v3/chat?q=How+can+I+reduce+sector+concentration")}>Reduce sector concentration</TinyChip>
            <TinyChip onClick={() => navigate("/v3/chat?q=Which+duplicate+funds+should+I+exit")}>Exit duplicate funds</TinyChip>
            <TinyChip onClick={() => navigate("/v3/chat?q=Build+me+a+consolidation+plan")}>Build a consolidation plan</TinyChip>
          </div>
        </div>
      )}
    </ScreenContainer>
  );
}
