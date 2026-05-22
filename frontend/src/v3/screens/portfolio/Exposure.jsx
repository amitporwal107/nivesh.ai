import React, { useMemo, useState } from "react";
import { useNavigate, useOutletContext, useSearchParams } from "react-router-dom";
import { AlertTriangle, RefreshCw, Layers } from "lucide-react";
import HeroCard from "../../components/HeroCard";
import CompactCard from "../../components/CompactCard";
import CardStrip from "../../components/CardStrip";
import CategoryChip from "../../components/CategoryChip";
import TinyChip from "../../components/TinyChip";
import SectionHead from "../../components/SectionHead";
import ScreenContainer from "../../components/layout/ScreenContainer";
import TopBar from "../../components/layout/TopBar";
import { OverlapDonut, FundCountHistogram } from "../../components/viz";
import { useConcentration } from "../../adapters/concentration";
import { usePortfolioSummary, useFundOverlap } from "../../adapters";

const TABS = [
  { id: "concentration", label: "Concentration" },
  { id: "diversification", label: "Diversification" },
];

const DIMENSION_KEYS = ["amc", "sector", "company", "group", "hidden", "category", "cap"];

export default function Exposure({ defaultTab = "concentration" }) {
  const { viewport } = useOutletContext() || { viewport: "mobile" };
  const isDesktop = viewport === "desktop";
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.id === params.get("tab")) ? params.get("tab") : defaultTab;

  function setTab(id) {
    setParams((p) => { p.set("tab", id); return p; }, { replace: true });
  }

  return (
    <ScreenContainer variant={isDesktop ? "desktop" : "mobile"}>
      <TopBar variant={isDesktop ? "desktop" : "mobile"} eyebrow="Portfolio · Exposure" title="Concentration & Diversification" />

      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 26 : 18, paddingBottom: 80 }}>
        <div style={{ display: "flex", gap: 8 }} role="tablist" aria-label="Exposure view">
          {TABS.map((t) => (
            <CategoryChip
              key={t.id}
              category="risk"
              label={t.label}
              active={tab === t.id}
              onClick={() => setTab(t.id)}
            />
          ))}
        </div>

        {tab === "concentration"
          ? <ConcentrationTab isDesktop={isDesktop} />
          : <DiversificationTab isDesktop={isDesktop} />}
      </div>
    </ScreenContainer>
  );
}

// ── Concentration tab ──────────────────────────────────────────────────────

function ConcentrationTab({ isDesktop }) {
  const navigate = useNavigate();
  const [activeDim, setActiveDim] = useState(null);
  const { data, loading, error, refetch } = useConcentration();

  const topSector = data?.sector?.items?.[0] || data?.sector?.top;
  const topSectorName = topSector?.name || topSector?.sector || "—";
  const topSectorPct = topSector?.pct ?? topSector?.weight_pct ?? 0;
  const sectorHHI = data?.sector?.hhi ?? null;

  const dimensionCards = useMemo(() => buildDimensionCards(data), [data]);

  if (error && !loading) return <ErrorState onRetry={refetch} message="Couldn't load concentration data" />;

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
    <>
      <HeroCard
        layout={isDesktop ? "desktop" : "mobile"}
        category="risk"
        priorityLabel={loading ? "Loading…" : sectorHHI > 1500 ? "Concentration alert" : "For you"}
        title={heroTitle}
        description={isDesktop && !data?.empty && topSectorName !== "—"
          ? `Your largest sector is ${topSectorName} at ${topSectorPct.toFixed(0)}%. HHI above 1500 indicates meaningful single-sector risk.`
          : null}
        viz={loading
          ? <div style={{ width: "100%", height: 100, background: "var(--v3-bg-3)", borderRadius: 10 }} />
          : null}
        ctaText="Suggest a concentration fix →"
        onClick={() => navigate("/chat?q=How+do+I+reduce+concentration+risk+in+my+portfolio")}
      />

      {!loading && !data?.empty && (
        <section>
          <SectionHead title="Dimensions" count={`${dimensionCards.length} dimensions`} />
          <CardStrip ariaLabel="Concentration dimensions" desktopColumns={4}>
            {dimensionCards.map((card) => (
              <CompactCard
                key={card.key}
                category="risk"
                label={card.label}
                meta={card.meta}
                viz={card.viz}
                onClick={() => setActiveDim(activeDim === card.key ? null : card.key)}
              />
            ))}
          </CardStrip>
        </section>
      )}

      {activeDim && !loading && <DetailPanel dimension={activeDim} data={data} />}

      {data?.coverage_pct > 0 && (
        <p className="v3-eyebrow" style={{ color: "var(--v3-ink-4)", fontSize: 10, margin: 0 }}>
          Look-through coverage: {data.coverage_pct.toFixed(0)}% of portfolio
        </p>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <TinyChip onClick={() => navigate("/chat?q=How+can+I+reduce+sector+concentration")}>Reduce sector concentration</TinyChip>
        <TinyChip onClick={() => navigate("/chat?q=Which+duplicate+funds+should+I+exit")}>Exit duplicate funds</TinyChip>
        <TinyChip onClick={() => navigate("/chat?q=Build+me+a+consolidation+plan")}>Build a consolidation plan</TinyChip>
      </div>
    </>
  );
}

function buildDimensionCards(data) {
  if (!data) return [];
  const cards = [];
  const amcTop = data.amc?.items?.[0];
  if (amcTop) cards.push({
    key: "amc",
    label: `Top AMC · ${amcTop.name || amcTop.amc || "—"}`,
    meta: `${(amcTop.pct ?? amcTop.weight_pct ?? 0).toFixed(1)}% · HHI ${data.amc?.hhi ?? "—"}`,
    viz: <OverlapDonut value={amcTop.pct ?? amcTop.weight_pct ?? 0} color="var(--v3-saffron)" size={46} />,
  });
  const secTop = data.sector?.items?.[0];
  if (secTop) cards.push({
    key: "sector",
    label: `Top sector · ${secTop.name || secTop.sector || "—"}`,
    meta: `${(secTop.pct ?? secTop.weight_pct ?? 0).toFixed(1)}% · HHI ${data.sector?.hhi ?? "—"}`,
    viz: <OverlapDonut value={secTop.pct ?? secTop.weight_pct ?? 0} color={(secTop.pct ?? 0) > 25 ? "var(--v3-crimson)" : "var(--v3-indigo)"} size={46} />,
  });
  const coTop = data.company?.items?.[0];
  if (coTop) cards.push({
    key: "company",
    label: `Top stock · ${coTop.name || coTop.company || "—"}`,
    meta: `${(coTop.pct ?? coTop.weight_pct ?? 0).toFixed(1)}% · ${data.company?.total_stocks ?? "—"} stocks`,
    viz: <OverlapDonut value={coTop.pct ?? coTop.weight_pct ?? 0} color="var(--v3-crimson)" size={46} />,
  });
  const grpTop = data.group?.items?.[0];
  if (grpTop) cards.push({
    key: "group",
    label: "Business groups",
    meta: `${data.group?.items?.length ?? "—"} groups · top ${(grpTop.pct ?? 0).toFixed(1)}%`,
    viz: <OverlapDonut value={grpTop.pct ?? 0} color="var(--v3-gold)" size={46} />,
  });
  if (data.hidden_overlap?.length != null) cards.push({
    key: "hidden",
    label: "Hidden overlap",
    meta: `${data.hidden_overlap.length} stocks via 2+ routes`,
    viz: <OverlapDonut value={Math.min((data.hidden_overlap.length || 0) * 10, 100)} color="var(--v3-moss)" size={46} />,
  });
  if (data.category_overlap?.length != null) cards.push({
    key: "category",
    label: "Category overlap",
    meta: `${data.category_overlap.length} categories with 2+ funds`,
    viz: <OverlapDonut value={Math.min((data.category_overlap.length || 0) * 20, 100)} color="var(--v3-indigo)" size={46} />,
  });
  const capTop = data.cap?.items?.[0];
  if (capTop) cards.push({
    key: "cap",
    label: `Top cap · ${capTop.name || "—"}`,
    meta: `${(capTop.pct ?? capTop.weight_pct ?? 0).toFixed(1)}% of equity`,
    viz: <OverlapDonut value={capTop.pct ?? 0} color="var(--v3-indigo)" size={46} />,
  });
  return cards;
}

function DetailPanel({ dimension, data }) {
  const items = (() => {
    if (dimension === "amc")     return (data.amc?.items     || []).map((x) => ({ name: x.name || x.amc,     pct: x.pct ?? x.weight_pct }));
    if (dimension === "sector")  return (data.sector?.items  || []).map((x) => ({ name: x.name || x.sector,  pct: x.pct ?? x.weight_pct }));
    if (dimension === "company") return (data.company?.items || []).map((x) => ({ name: x.name || x.company, pct: x.pct ?? x.weight_pct }));
    if (dimension === "group")   return (data.group?.items   || []).map((x) => ({ name: x.name || x.group,   pct: x.pct ?? x.weight_pct }));
    if (dimension === "hidden")  return (data.hidden_overlap   || []).map((x) => ({ name: x.name || x.company, pct: x.pct ?? x.overlap_pct }));
    if (dimension === "category")return (data.category_overlap || []).map((x) => ({ name: x.category,         pct: x.fund_count ?? x.count }));
    if (dimension === "cap")     return (data.cap?.items     || []).map((x) => ({ name: x.name,              pct: x.pct ?? x.weight_pct }));
    return [];
  })();
  const hhi = dimension === "amc" ? data.amc?.hhi : dimension === "sector" ? data.sector?.hhi : null;
  if (!items.length) return null;
  return (
    <div style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 14, padding: 16 }}>
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

// ── Diversification tab ────────────────────────────────────────────────────

function heatColor(v) {
  if (v >= 80) return "var(--v3-crimson)";
  if (v >= 65) return "rgba(217, 79, 79, 0.55)";
  if (v >= 45) return "rgba(212, 175, 55, 0.45)";
  if (v >= 25) return "rgba(123, 160, 91, 0.35)";
  return "var(--v3-bg-3)";
}

function DiversificationTab({ isDesktop }) {
  const navigate = useNavigate();
  const portfolioState = usePortfolioSummary();
  const p = portfolioState.data;
  const overlapState = useFundOverlap();
  const overlap = overlapState.data || {};
  const { funds = [], matrix = [], pairs = 0, maxPct = 0, coverage_pct = 0, topPairs = [], empty } = overlap;

  return (
    <>
      <HeroCard
        layout={isDesktop ? "desktop" : "mobile"}
        category="risk"
        priorityLabel={overlapState.loading ? "Loading…" : empty ? "No overlap data" : "Concentration"}
        title={
          overlapState.loading ? "Computing fund overlap…"
          : empty ? "Add 2+ mutual funds to see overlap"
          : `${pairs} fund pair${pairs === 1 ? "" : "s"} overlap above 65%`
        }
        description={isDesktop && !empty
          ? `The highest overlap pair shares roughly ${maxPct}% of underlying stocks. ${pairs > 0 ? "Consolidating may reduce concentration without losing diversification." : "Healthy spread across SEBI categories."}`
          : null}
        viz={
          <div>
            <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", marginBottom: 8 }}>Fund count vs ideal</div>
            <FundCountHistogram count={p?.funds?.count ?? funds.length} height={isDesktop ? 96 : 72} showIdealLabel={isDesktop} />
          </div>
        }
        ctaText={empty ? null : "Show me the consolidation plan →"}
        onClick={empty ? null : () => navigate("/chat?q=Build%20me%20a%20consolidation%20plan")}
      />

      <section>
        <SectionHead title="Breakdown" count="4 lenses" />
        <CardStrip ariaLabel="Diversification breakdowns" desktopColumns={4}>
          <CompactCard category="risk" label="Fund count"        meta={`${p?.funds?.count ?? 0} funds`}                viz={<OverlapDonut value={Math.min(100, (p?.funds?.count ?? 0) * 10)} color="var(--v3-saffron)" />} />
          <CompactCard category="risk" label="AMC concentration" meta={`${p?.funds?.amcCount ?? 0} AMCs`}              viz={<OverlapDonut value={(p?.funds?.amcCount ?? 0) * 12} color="var(--v3-indigo)" />} />
          <CompactCard category="risk" label="Max pair overlap"  meta={`${maxPct}%`}                                   viz={<OverlapDonut value={maxPct} color={maxPct >= 65 ? "var(--v3-crimson)" : "var(--v3-moss)"} />} />
          <CompactCard category="risk" label="High-overlap pairs" meta={`${pairs} pair${pairs === 1 ? "" : "s"} ≥65%`} viz={<OverlapDonut value={Math.min(100, pairs * 25)} color={pairs > 0 ? "var(--v3-crimson)" : "var(--v3-moss)"} />} />
        </CardStrip>
      </section>

      <section>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <SectionHead title="Overlap heatmap" count={funds.length ? `${funds.length} × ${funds.length}` : "—"} />
          {coverage_pct > 0 && coverage_pct < 100 && (
            <span className="v3-data" style={{ fontSize: 10, color: "var(--v3-ink-4)" }}>
              Coverage {coverage_pct}% of AUM
            </span>
          )}
        </div>
        {overlapState.error && !overlapState.loading ? (
          <ErrorState onRetry={overlapState.refetch} message="Couldn't load fund overlap matrix" />
        ) : empty && !overlapState.loading ? (
          <EmptyOverlap funds={funds} />
        ) : (
          <div style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 14, padding: 16, overflowX: "auto" }}>
            <table style={{ borderCollapse: "separate", borderSpacing: 4, fontFamily: "var(--v3-font-mono)", fontSize: 11 }}>
              <thead>
                <tr>
                  <th style={{ width: 88 }} />
                  {funds.map((f, i) => (
                    <th key={i} style={{ padding: "4px 6px", color: "var(--v3-ink-3)", textAlign: "left", fontWeight: 500, whiteSpace: "nowrap" }}>{f}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.map((row, i) => (
                  <tr key={i}>
                    <td style={{ color: "var(--v3-ink-3)", padding: "4px 6px", whiteSpace: "nowrap" }}>{funds[i]}</td>
                    {row.map((v, j) => (
                      <td key={j} style={{ width: 44, height: 36, padding: 0 }}>
                        <div
                          title={i === j ? "Same fund" : `${funds[i]} ↔ ${funds[j]}: ${v}% overlap`}
                          style={{
                            background: heatColor(v),
                            color: v > 60 ? "var(--v3-ink-1)" : "var(--v3-ink-3)",
                            height: "100%",
                            borderRadius: 4,
                            display: "grid",
                            placeItems: "center",
                            fontFamily: "var(--v3-font-mono)",
                            fontWeight: 600,
                            fontSize: 11,
                          }}
                        >
                          {i === j ? "·" : v}
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {!empty && topPairs.length > 0 && (
        <section>
          <SectionHead title="Highest-overlap pairs" count={`Top ${Math.min(topPairs.length, 5)}`} />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {topPairs.slice(0, 5).map((pair, i) => (
              <div key={i} style={{ background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 10, padding: "10px 14px", display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ width: 44, height: 32, background: heatColor(pair.overlap_pct), borderRadius: 6, display: "grid", placeItems: "center", fontFamily: "var(--v3-font-mono)", fontSize: 12, fontWeight: 600, color: pair.overlap_pct > 60 ? "var(--v3-ink-1)" : "var(--v3-ink-3)" }}>
                  {pair.overlap_pct}%
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: "var(--v3-ink-1)", lineHeight: 1.3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {pair.a_name} <span style={{ color: "var(--v3-ink-4)" }}>↔</span> {pair.b_name}
                  </div>
                  <div className="v3-data" style={{ fontSize: 10, color: "var(--v3-ink-4)", marginTop: 2 }}>
                    {pair.shared_count} shared stocks
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <TinyChip onClick={() => navigate("/chat?q=Which+funds+have+the+highest+overlap")}>Highest overlap funds</TinyChip>
        <TinyChip onClick={() => navigate("/chat?q=Build+me+a+consolidation+plan")}>Consolidation plan</TinyChip>
        <TinyChip onClick={() => navigate("/chat?q=Am+I+overdiversified")}>Am I over-diversified?</TinyChip>
      </div>
    </>
  );
}

// ── Shared states ──────────────────────────────────────────────────────────

function ErrorState({ onRetry, message }) {
  return (
    <div style={{ textAlign: "center", padding: "48px 24px", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 14, display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
      <AlertTriangle size={28} color="var(--v3-ink-4)" />
      <p style={{ color: "var(--v3-ink-3)", fontSize: 14, margin: 0 }}>{message}</p>
      <button onClick={onRetry} style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 16px", background: "var(--v3-bg-3)", border: "1px solid var(--v3-line)", borderRadius: 999, fontSize: 13, color: "var(--v3-ink-2)", cursor: "pointer" }}>
        <RefreshCw size={13} /> Retry
      </button>
    </div>
  );
}

function EmptyOverlap({ funds }) {
  const reason = funds.length === 0 ? "No mutual fund holdings to compare."
    : funds.length === 1 ? "Need at least 2 mutual funds to compute overlap."
    : "Fund stock-composition data isn't available for any of your funds yet.";
  return (
    <div style={{ textAlign: "center", padding: "48px 24px", background: "var(--v3-bg-2)", border: "1px solid var(--v3-line)", borderRadius: 14, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
      <Layers size={28} color="var(--v3-ink-4)" />
      <p style={{ color: "var(--v3-ink-2)", fontSize: 14, margin: 0 }}>{reason}</p>
    </div>
  );
}
