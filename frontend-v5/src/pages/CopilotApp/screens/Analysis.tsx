/**
 * Portfolio analysis — value, gain and XIRR at the top, then four sections:
 *
 *   Overview                   exposure by sector, company, AMC, group, fund and asset class
 *   Performance                the old Performance screen's data      (portfolio/PerformanceSection)
 *   Concentration and overlap  the old AI Insights headline, ladder and overlap (portfolio/ConcentrationSection)
 *   What to fix                the old AI Insights remediation plan   (portfolio/RemediationSection)
 *
 * Design: NVTools.dc.html, tool === "analysis".
 *
 * Data read in this file:
 *   headline, tiles, Funds tab          GET /api/portfolio/holdings-enriched        (useHoldingsEnriched)
 *   Sectors, Companies, AMCs, Groups    GET /api/portfolio/exposure/concentration   (usePortfolioConcentration)
 *   Asset class tab                     GET /api/portfolio/composition?dimension=asset_class (useComposition)
 *   Asset class tab, mix against target GET /api/user/risk-profile + the risk-category target table
 *                                       the Home drift card uses                    (portfolio/TargetMix)
 *
 * Every row that names a company shows the company icon, every fund row the
 * fund house icon (portfolio/names).
 */
import { useState } from "react";
import { useComposition } from "@/hooks/use-composition";
import { useHoldingsEnriched, usePortfolioConcentration } from "@/hooks/use-portfolio";
import type { EnrichedHoldingsRes } from "@/services/contracts/portfolio.contract";
import {
  AskChips, DataTable, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Screen, ScreenHeader, Section, Tiles,
  TONE_COLOR, fmtINR, fmtNum, fmtPct, signTone, type Column, type TileItem,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { AxisFooter, AxisSummary, AxisTable, CapCell, ConcentrationSection } from "./portfolio/ConcentrationSection";
import { PerformanceSection } from "./portfolio/PerformanceSection";
import { RemediationSection } from "./portfolio/RemediationSection";
import { TargetMix } from "./portfolio/TargetMix";
import { capScale, lensOf, readConcentration, type AxisId, type LensItem } from "./portfolio/concentration-data";
import { BAD_SHAPE, isFund, isStock, loadError, num, readAlerts, readComposition, rec, str, type AssetClassSlice, type EnrichedHolding } from "./portfolio/data";
import { HoldingIcon, Named } from "./portfolio/names";
import { HeaderRow, NiveshRead, NoPortfolio, ShowAll, Tabs, WeightCell, type TabItem } from "./portfolio/parts";

type SectionId = "overview" | "performance" | "concentration" | "fix";

const SECTIONS: Array<TabItem<SectionId>> = [
  { id: "overview", label: "Overview" },
  { id: "performance", label: "Performance" },
  { id: "concentration", label: "Concentration and overlap" },
  { id: "fix", label: "What to fix" },
];

type TabId = "sectors" | "companies" | "amc" | "group" | "funds" | "assets";

const TABS: Array<TabItem<TabId>> = [
  { id: "sectors", label: "Sectors" },
  { id: "companies", label: "Companies" },
  { id: "amc", label: "AMCs" },
  { id: "group", label: "Groups" },
  { id: "funds", label: "Funds" },
  { id: "assets", label: "Asset class" },
];

/** The Overview tab that holds each concentration axis. */
const AXIS_TAB: Record<AxisId, TabId> = { sector: "sectors", company: "companies", amc: "amc", group: "group" };

const FUND_LIMIT = 12;

function Signed({ value, text }: { value: number | null; text: string }) {
  return <span style={{ color: value == null || value === 0 ? undefined : TONE_COLOR[signTone(value)] }}>{text}</span>;
}

function Name({ children, testId }: { children: string; testId?: string }) {
  return <span data-testid={testId} title={children} style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{children}</span>;
}

/** Share of the whole portfolio, from a rupee amount and the portfolio total. */
function share(partRs: number | null, totalRs: number | null): number | null {
  return partRs != null && totalRs != null && totalRs > 0 ? (partRs / totalRs) * 100 : null;
}

/** "+1.2 pts" / "−0.4 pts". */
function points(n: number, unit: string): string {
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(1)} ${unit}`;
}

/** True when the holding's XIRR is the fund's own return standing in for the investor's. */
function xirrEstimated(h: EnrichedHolding): boolean {
  const source = str(h.xirr_source);
  return h.xirr_pct != null && source !== "" && source !== "personal";
}

// ── Sectors ──────────────────────────────────────────────────────────────

interface SectorRow {
  name: string;
  valueRs: number | null;
  weightPct: number | null;
  viaFundsRs: number | null;
  directRs: number | null;
  /** The sector against its cap, as the concentration verdict judges it. */
  cap: LensItem | undefined;
}

function SectorsTable() {
  const { ask } = useCopilotShell();
  const q = usePortfolioConcentration();
  if (q.isPending) return <LoadingBlock label="Loading sector exposure" rows={5} />;
  if (q.isError) return <ErrorBlock title="Sector exposure didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  // The backend always sends the sector axis (with `items: []` for an empty portfolio).
  if (!q.data.sector && q.data.empty !== true) return <ErrorBlock title="Sector exposure didn’t load" error={BAD_SHAPE} onRetry={() => q.refetch()} />;

  const total = num(q.data.total_value);
  const lens = lensOf(readConcentration(q.data), "sector");
  const rows: SectorRow[] = (q.data.sector?.items ?? []).map((it, i) => {
    const via = rec(it.via);
    const valueRs = num(it.value_inr);
    return { name: it.name, valueRs, weightPct: share(valueRs, total), viaFundsRs: num(via?.mf), directRs: num(via?.direct), cap: lens?.items[i] };
  });
  if (!rows.length) {
    return <EmptyBlock title="No sector exposure to show" body="Sector exposure appears once your holdings have been classified." />;
  }
  const max = Math.max(...rows.map((r) => r.weightPct ?? 0));
  const all = num(q.data.sector?.all_items_count);
  const coverage = num(q.data.lookthrough_coverage);
  const note = [
    all != null && all > rows.length ? `Top ${rows.length} of ${all}` : null,
    coverage != null ? `Look-through covers ${fmtPct(coverage, { digits: 0 })} of your funds` : null,
  ].filter(Boolean).join(" · ");
  const columns: Array<Column<SectorRow>> = [
    { key: "name", header: "Sector", width: "minmax(0,1.7fr)", render: (r) => <Name testId="analysis-sector-name">{r.name}</Name> },
    { key: "weight", header: "Weight", num: true, render: (r) => <WeightCell pct={r.weightPct} max={max} /> },
    { key: "value", header: "Value", num: true, render: (r) => fmtINR(r.valueRs, { compact: true }) },
    { key: "funds", header: "Through funds", num: true, render: (r) => fmtINR(r.viaFundsRs, { compact: true }) },
    { key: "direct", header: "Direct", num: true, render: (r) => fmtINR(r.directRs, { compact: true }) },
  ];
  if (lens) {
    const scale = capScale(lens);
    columns.push({ key: "cap", header: "Allocation vs cap", width: "minmax(0,1.5fr)", num: true, render: (r) => <CapCell item={r.cap} scale={scale} /> });
  }
  return (
    <div className="flex flex-col" style={{ gap: 12 }}>
      {lens && <AxisSummary lens={lens} />}
      <Section flush title="Sectors · share of your whole portfolio" note={note}>
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(r) => r.name}
          minWidth={760}
          onRowClick={(r) => ask(`How have my ${r.name} holdings performed, and is ${fmtPct(r.weightPct)} of my portfolio in ${r.name} too much?`)}
        />
        {lens && <AxisFooter lens={lens} />}
      </Section>
    </div>
  );
}

// ── Companies ────────────────────────────────────────────────────────────

interface CompanyRow {
  name: string;
  valueRs: number | null;
  totalPct: number | null;
  directPct: number | null;
  fundsPct: number | null;
  fundCount: number | null;
  /** The company against its cap, as the concentration verdict judges it. */
  cap: LensItem | undefined;
}

function CompaniesTable() {
  const { ask } = useCopilotShell();
  const q = usePortfolioConcentration();
  if (q.isPending) return <LoadingBlock label="Loading company exposure" rows={5} />;
  if (q.isError) return <ErrorBlock title="Company exposure didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  if (!q.data.company && q.data.empty !== true) return <ErrorBlock title="Company exposure didn’t load" error={BAD_SHAPE} onRetry={() => q.refetch()} />;

  const total = num(q.data.total_value);
  const lens = lensOf(readConcentration(q.data), "company");
  const rows: CompanyRow[] = (q.data.company?.items ?? []).map((it, i) => {
    const valueRs = num(it.value_inr);
    const directRs = num(it.via_direct_inr);
    return {
      name: it.name,
      valueRs,
      totalPct: share(valueRs, total),
      directPct: share(directRs, total),
      fundsPct: share(valueRs != null && directRs != null ? valueRs - directRs : null, total),
      fundCount: num(it.via_funds_count),
      cap: lens?.items[i],
    };
  });
  if (!rows.length) {
    return <EmptyBlock title="No company exposure to show" body="Company exposure needs direct stocks, or funds whose portfolios Nivesh can look through." />;
  }
  const max = Math.max(...rows.map((r) => r.totalPct ?? 0));
  const all = num(q.data.company?.all_items_count);
  const columns: Array<Column<CompanyRow>> = [
    { key: "name", header: "Company", width: "minmax(0,1.7fr)", render: (r) => <Named icon={<HoldingIcon name={r.name} assetType="equity" />}><Name testId="analysis-company-name">{r.name}</Name></Named> },
    { key: "total", header: "Total", num: true, render: (r) => <WeightCell pct={r.totalPct} max={max} /> },
    { key: "direct", header: "Direct", num: true, render: (r) => fmtPct(r.directPct) },
    { key: "funds", header: "Via funds", num: true, render: (r) => fmtPct(r.fundsPct) },
    { key: "value", header: "Value", num: true, render: (r) => fmtINR(r.valueRs, { compact: true }) },
    { key: "count", header: "Funds holding it", num: true, render: (r) => fmtNum(r.fundCount) },
  ];
  if (lens) {
    const scale = capScale(lens);
    columns.push({ key: "cap", header: "Allocation vs cap", width: "minmax(0,1.5fr)", num: true, render: (r) => <CapCell item={r.cap} scale={scale} /> });
  }
  return (
    <div className="flex flex-col" style={{ gap: 12 }}>
      {lens && <AxisSummary lens={lens} />}
      <Section flush title="Companies · direct plus through your funds" note={all != null && all > rows.length ? `Look-through · top ${rows.length} of ${all}` : "Look-through"}>
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.name} minWidth={880} onRowClick={(r) => ask(`Research ${r.name} fundamentally and technically`)} />
        {lens && <AxisFooter lens={lens} />}
      </Section>
    </div>
  );
}

// ── Funds ────────────────────────────────────────────────────────────────

function FundsTable({ holdings }: { holdings: EnrichedHolding[] }) {
  const { ask } = useCopilotShell();
  const [expanded, setExpanded] = useState(false);
  const funds = holdings.filter(isFund).sort((a, b) => (b.value_rs ?? 0) - (a.value_rs ?? 0));
  if (!funds.length) {
    return <EmptyBlock title="No mutual funds or ETFs" body="This portfolio holds no funds, so there is nothing to compare here." />;
  }
  const max = Math.max(...funds.map((f) => f.weight_pct ?? 0));
  const columns: Array<Column<EnrichedHolding>> = [
    { key: "name", header: "Fund", width: "minmax(0,2fr)", render: (f) => <Named icon={<HoldingIcon name={f.name} assetType={f.asset_type} />}><Name testId="analysis-fund-name">{f.name}</Name></Named> },
    { key: "weight", header: "Weight", num: true, render: (f) => <WeightCell pct={f.weight_pct ?? null} max={max} /> },
    { key: "value", header: "Value", num: true, render: (f) => fmtINR(f.value_rs, { compact: true }) },
    { key: "ret", header: "Fund 1Y", num: true, render: (f) => <Signed value={f.cagr_1y_pct ?? null} text={fmtPct(f.cagr_1y_pct, { signed: true })} /> },
    {
      key: "bench", header: "vs benchmark", num: true,
      render: (f) => {
        const d = f.benchmark_delta ?? null;
        if (d == null) return "—";
        const horizon = str(f.benchmark_delta_horizon).toUpperCase();
        return <Signed value={d} text={`${points(d, "pts")}${horizon ? ` · ${horizon}` : ""}`} />;
      },
    },
    {
      key: "xirr", header: "Your XIRR", num: true,
      render: (f) => (
        <span title={xirrEstimated(f) ? "Estimated from the fund’s own return — your purchase dates are not on record" : undefined}>
          {fmtPct(f.xirr_pct)}{xirrEstimated(f) ? "*" : ""}
        </span>
      ),
    },
    {
      key: "plan", header: "Plan",
      render: (f) => (f.asset_type.toLowerCase() === "etf" ? "ETF" : f.is_regular_plan === true ? "Regular" : f.is_regular_plan === false ? "Direct" : "—"),
    },
  ];
  return (
    <Section flush title="Funds · weight and return" note={`${funds.length} ${funds.length === 1 ? "fund" : "funds"} · largest first`}>
      <DataTable
        columns={columns}
        rows={expanded ? funds : funds.slice(0, FUND_LIMIT)}
        rowKey={(f) => f.holding_id}
        minWidth={820}
        onRowClick={(f) => ask(`How is ${f.name} doing against its category and benchmark, and should I keep holding it?`)}
      />
      <ShowAll total={funds.length} limit={FUND_LIMIT} expanded={expanded} onToggle={() => setExpanded((v) => !v)} noun="funds" />
      {funds.some(xirrEstimated) && (
        <div style={{ padding: "10px 16px 12px" }}>
          <Footnote>* XIRR estimated from the fund’s own return where your purchase dates are missing</Footnote>
        </div>
      )}
    </Section>
  );
}

// ── Asset class ──────────────────────────────────────────────────────────

interface AssetRow extends AssetClassSlice {
  /** Points this class adds to the portfolio's gain on invested money. */
  contributionPts: number | null;
}

/**
 * `missingBasis` = holdings with no cost basis. The composition endpoint counts
 * their whole value as gain, so the gain columns are left out when any exist.
 */
function AssetClassTable({ missingBasis }: { missingBasis: number }) {
  const { ask } = useCopilotShell();
  const q = useComposition("asset_class");
  if (q.isPending) return <LoadingBlock label="Loading asset classes" rows={4} />;
  if (q.isError) return <ErrorBlock title="Asset classes didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;

  // useComposition does not validate its response, so read it defensively.
  const comp = readComposition(q.data);
  if (!comp) return <ErrorBlock title="Asset classes didn’t load" error={BAD_SHAPE} onRetry={() => q.refetch()} />;
  const totalInvested = comp.totalInvestedRs;
  const rows: AssetRow[] = comp.slices.map((s) => ({
    ...s,
    contributionPts: s.valueRs != null && s.investedRs != null && totalInvested != null && totalInvested > 0 ? ((s.valueRs - s.investedRs) / totalInvested) * 100 : null,
  }));
  if (!rows.length) {
    return <EmptyBlock title="No asset classes to show" body="The asset-class split appears once your holdings are priced." />;
  }
  const showGain = missingBasis === 0;
  const columns: Array<Column<AssetRow>> = [
    { key: "name", header: "Asset", width: "minmax(0,1.4fr)", render: (r) => <Name testId="analysis-asset-name">{r.name}</Name> },
    { key: "weight", header: "Weight", num: true, render: (r) => <WeightCell pct={r.weightPct} max={100} /> },
    { key: "value", header: "Value", num: true, render: (r) => fmtINR(r.valueRs, { compact: true }) },
  ];
  if (showGain) {
    columns.push(
      { key: "invested", header: "Invested", num: true, render: (r) => fmtINR(r.investedRs, { compact: true }) },
      { key: "gain", header: "Gain", num: true, render: (r) => <Signed value={r.gainPct} text={fmtPct(r.gainPct, { signed: true })} /> },
      { key: "contrib", header: "Contribution", num: true, render: (r) => (r.contributionPts == null ? "—" : <Signed value={r.contributionPts} text={points(r.contributionPts, "pt")} />) },
    );
  }
  return (
    <div className="flex flex-col" style={{ gap: 12 }}>
      <Section
        flush
        title={showGain ? "Asset classes · gain since purchase" : "Asset classes · weight and value"}
        note={showGain
          ? "Contribution = points added to your gain on invested money"
          : `Gain hidden: ${missingBasis} ${missingBasis === 1 ? "holding has" : "holdings have"} no cost basis`}
      >
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.name} onRowClick={(r) => ask(`Is ${fmtPct(r.weightPct)} in ${r.name} right for my goals and risk profile?`)} />
      </Section>
      <TargetMix slices={comp.slices} />
    </div>
  );
}

// ── screen ───────────────────────────────────────────────────────────────

function readHeadline(d: EnrichedHoldingsRes, missingBasis: number): { title: string; bullets: string[] } {
  const value = num(d.totals?.value_rs);
  const invested = num(d.totals?.invested_rs);
  const gain = num(d.totals?.pnl_rs);
  const best = d.holdings.reduce<EnrichedHolding | null>((a, h) => ((h.pnl_rs ?? 0) > (a?.pnl_rs ?? 0) ? h : a), null);
  const worst = d.holdings.reduce<EnrichedHolding | null>((a, h) => ((h.pnl_rs ?? 0) < (a?.pnl_rs ?? 0) ? h : a), null);

  let title = `Your portfolio is worth ${fmtINR(value, { compact: true })} across ${d.holdings.length} ${d.holdings.length === 1 ? "holding" : "holdings"}.`;
  if (gain != null && invested != null && invested > 0) {
    title = `Your holdings are ${gain >= 0 ? "up" : "down"} ${fmtINR(Math.abs(gain), { compact: true })} (${fmtPct(num(d.totals?.pnl_pct), { signed: true })}) on ${fmtINR(invested, { compact: true })} invested.`;
    if (best) title += ` ${best.name} has added the most, ${fmtINR(best.pnl_rs, { compact: true, signed: true })}.`;
    if (worst) title += ` ${worst.name} has cost the most, ${fmtINR(worst.pnl_rs, { compact: true })}.`;
  }

  const bullets = readAlerts(d.alerts).slice(0, 3).map((a) => (a.detail ? `${a.title} — ${a.detail}` : a.title));
  if (missingBasis > 0) {
    bullets.push(`${missingBasis} ${missingBasis === 1 ? "holding has" : "holdings have"} no cost basis on record and ${missingBasis === 1 ? "is" : "are"} left out of the gain.`);
  }
  return { title, bullets };
}

function AnalysisBody({ data }: { data: EnrichedHoldingsRes }) {
  const [section, setSection] = useState<SectionId>("overview");
  const [tab, setTab] = useState<TabId>("sectors");
  const holdings = data.holdings;
  const stocks = holdings.filter(isStock).length;
  const funds = holdings.filter(isFund).length;
  const other = holdings.length - stocks - funds;
  const gain = num(data.totals?.pnl_rs);
  const missingBasis = holdings.filter((h) => h.invested_rs == null).length;
  const withXirr = holdings.filter((h) => h.xirr_pct != null).length;
  const estimatedXirr = holdings.filter(xirrEstimated).length;
  const head = readHeadline(data, missingBasis);

  const tiles: TileItem[] = [
    {
      k: "Value",
      v: <span data-testid="analysis-total-value">{fmtINR(num(data.totals?.value_rs), { compact: true })}</span>,
      s: [`${stocks} ${stocks === 1 ? "stock" : "stocks"}`, `${funds} ${funds === 1 ? "fund" : "funds"}`, other > 0 ? `${other} other` : null].filter(Boolean).join(" · "),
    },
    { k: "Invested", v: <span data-testid="analysis-invested">{fmtINR(num(data.totals?.invested_rs), { compact: true })}</span>, s: "Cost basis on record" },
    {
      k: "Unrealised gain",
      v: <span data-testid="analysis-gain">{fmtINR(gain, { compact: true, signed: true })}</span>,
      s: <span data-testid="analysis-gain-pct">{fmtPct(num(data.totals?.pnl_pct), { signed: true })}</span>,
      tone: signTone(gain),
    },
    {
      k: "XIRR",
      v: <span data-testid="analysis-xirr">{fmtPct(num(data.totals?.xirr_pct))}</span>,
      s: `${withXirr} of ${holdings.length} holdings${estimatedXirr > 0 ? ` · ${estimatedXirr} estimated` : ""}`,
    },
  ];

  const largest = holdings.reduce<EnrichedHolding | null>((a, h) => ((h.weight_pct ?? 0) > (a?.weight_pct ?? 0) ? h : a), null);
  const biggestLoss = holdings.reduce<EnrichedHolding | null>((a, h) => ((h.pnl_rs ?? 0) < (a?.pnl_rs ?? 0) ? h : a), null);
  const regular = holdings.filter((h) => isFund(h) && h.is_regular_plan === true).length;
  const chips: Array<{ label: string; query: string }> = [];
  if (largest) chips.push({ label: "Is my largest position too big?", query: `Is ${largest.name} too large at ${fmtPct(largest.weight_pct)} of my portfolio?` });
  if (biggestLoss) chips.push({ label: "Why is my biggest loser down?", query: `Why is ${biggestLoss.name} down ${fmtINR(Math.abs(biggestLoss.pnl_rs ?? 0), { compact: true })} for me, and should I keep it?` });
  if (funds > 1) chips.push({ label: "Which of my funds overlap most?", query: `Which of my ${funds} funds overlap the most, and which could I merge?` });
  if (regular > 0) chips.push({ label: "What do my Regular plans cost me?", query: `How much would I save each year by moving my ${regular} Regular-plan ${regular === 1 ? "fund" : "funds"} to Direct?` });

  return (
    <>
      <NiveshRead testId="analysis-read" title={head.title} bullets={head.bullets} />
      <Tiles items={tiles} min={140} />

      <div className="flex flex-col" style={{ gap: 18 }}>
        <Tabs tabs={SECTIONS} value={section} onChange={setSection} label="Portfolio analysis sections" idPrefix="analysis-section" />
        <div role="tabpanel" id="analysis-section-panel" aria-labelledby={`analysis-section-tab-${section}`} data-testid={`analysis-section-${section}`}>
          {section === "overview" && (
            <div className="flex flex-col" style={{ gap: 14 }}>
              <Tabs tabs={TABS} value={tab} onChange={setTab} label="Portfolio breakdown" idPrefix="analysis" />
              <div role="tabpanel" id="analysis-panel" aria-labelledby={`analysis-tab-${tab}`} data-testid={`analysis-table-${tab}`}>
                {tab === "sectors" && <SectorsTable />}
                {tab === "companies" && <CompaniesTable />}
                {tab === "amc" && <AxisTable axis="amc" />}
                {tab === "group" && <AxisTable axis="group" />}
                {tab === "funds" && <FundsTable holdings={holdings} />}
                {tab === "assets" && <AssetClassTable missingBasis={missingBasis} />}
              </div>
            </div>
          )}
          {section === "performance" && <PerformanceSection />}
          {section === "concentration" && <ConcentrationSection onOpenAxis={(axis) => { setTab(AXIS_TAB[axis]); setSection("overview"); }} />}
          {section === "fix" && <RemediationSection />}
        </div>
      </div>

      <AskChips title="Ask about this" items={chips} />
      <Footnote>From your imported holdings and fund portfolios · Educational, not investment advice</Footnote>
    </>
  );
}

export default function AnalysisScreen() {
  const { ask } = useCopilotShell();
  const q = useHoldingsEnriched();
  const count = q.data?.holdings.length ?? 0;
  return (
    <Screen testId="screen-tool-analysis">
      <HeaderRow askLabel="Ask Copilot about this ›" onAsk={() => ask("Explain where my portfolio’s gains and losses come from, by sector and by fund")}>
        <ScreenHeader
          eyebrow={count > 0 ? `Portfolio analysis · ${count} ${count === 1 ? "holding" : "holdings"}` : "Portfolio analysis"}
          title={<>Where your money sits, and what it has <em>earned</em></>}
          sub="Exposure by sector and company with your funds looked through, each fund’s return, and the gain by asset class."
        />
      </HeaderRow>
      {q.isPending ? (
        <LoadingBlock label="Loading your portfolio" rows={4} />
      ) : q.isError ? (
        <ErrorBlock title="Your portfolio didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />
      ) : q.data.holdings.length === 0 ? (
        <NoPortfolio body="Import a statement or connect a broker and this screen will show where your money sits and what it has earned." />
      ) : (
        <AnalysisBody data={q.data} />
      )}
    </Screen>
  );
}
