/**
 * Portfolio analysis — performance: the data blocks of the old Performance
 * screen (src/pages/Performance/index.tsx), in this shell's building blocks.
 *
 * Data:
 *   headline, status, period tiles, monthly returns, coverage
 *                                    GET /api/dashboards/performance?period=  (useDashboard)
 *   portfolio value history          GET /api/portfolio/value-history         (useValueHistory)
 *   composition, holdings, vs category benchmark, best & worst
 *                                    GET /api/portfolio/fund-performance      (useFundPerformance)
 *   Stocks and SGB values, stock split, gain / loss plot
 *                                    GET /api/portfolio/analytics             (useHeatmapTiles)
 *   recommendations, scores          GET /api/portfolio/recommendations/v5    (useHoldingRecs)
 *   category leaders (open holding)  GET /api/mf/category-top                 (useCategoryTop)
 *   Resync                           POST /api/portfolio/resync               (useResync — the old screen's own button, no confirmation there either)
 *
 * Every label is the old screen's. The figures are what its backend sends:
 * the value history and the monthly strip are changes in statement value, and
 * the benchmark is a category or Nifty 500 comparison, not a Nifty 50 TRI one.
 *
 * Icons: a row that names a stock shows the company icon, a fund row the fund
 * house icon (portfolio/names) — holdings, best and worst performers, the
 * company split, category leaders, recommendations and the open holding.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { useDashboard } from "@/hooks/use-dashboards";
import { useResync } from "@/hooks/use-resync";
import {
  Btn, DataTable, EmptyBlock, ErrorBlock, Eyebrow, Footnote, LoadingBlock, Pill, Section, Tiles,
  TONE_COLOR, fmtINR, fmtNum, fmtPct, relTime, signTone, type Column, type TileItem, type Tone,
} from "../../components/ui";
import { FundHouseIcon } from "../../components/EntityIcon";
import { useCopilotShell } from "../../lib/shell-context";
import { ScatterPlot, ShareBar, ValueChart } from "./charts";
import { humanise, loadError } from "./data";
import { HoldingIcon, Named } from "./names";
import { ShowAll, Tabs } from "./parts";
import {
  ASSET_TABS, BENCHMARK_EXPLANATION, DRILL_SORTS, PERF_KEY_LABEL, PERIODS, PERIOD_BADGE, QUALITY_SCORE_EXPLANATION,
  actionMeta, assetTabLabel, companyAllocation, compositionSlices, distributionFor, drillRows, findHolding, monthVerdict,
  performersFor, readPerformance, recsForTab, scatterPoints, scoreTone, sectorAllocation, sortRows, valueSeries,
  useCategoryTop, useFundPerformance, useHeatmapTiles, useHoldingRecs, useValueHistory,
  type AssetTab, type CategoryPeer, type DrillSort, type FundPerformance, type FundRating, type HeatmapTile, type HoldingRec,
  type HoldingRecs, type MonthReturn, type NamedReturn, type PerfTile, type PeriodId, type ValueShare,
} from "./performance-data";

const quiet = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;
const body = { fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" } as const;
const pressed = { borderColor: "var(--mint-line)", color: "var(--mint)" } as const;
const twoUp = { gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,320px),1fr))", gap: 16 } as const;

/** A query's loading and error states, then its data. */
function Loaded<T>({ q, label, title, rows = 3, children }: { q: UseQueryResult<T>; label: string; title: string; rows?: number; children: (data: T) => ReactNode }) {
  if (q.isPending) return <LoadingBlock label={label} rows={rows} />;
  if (q.isError) return <ErrorBlock title={title} error={loadError(q.error)} onRetry={() => q.refetch()} />;
  return <>{children(q.data)}</>;
}

function SignedPct({ value, testId }: { value: number | null; testId?: string }) {
  return <span data-testid={testId} style={{ color: value == null || value === 0 ? undefined : TONE_COLOR[signTone(value)] }}>{fmtPct(value, { signed: true })}</span>;
}

function plural(n: number, one: string, many: string): string {
  return `${fmtNum(n)} ${n === 1 ? one : many}`;
}

/** "Hit Rate" → "hit-rate", for a tile's test id. */
function slug(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

// ── period figures ───────────────────────────────────────────────────────

function PeriodPicker({ value, onChange }: { value: PeriodId; onChange: (p: PeriodId) => void }) {
  return (
    <div role="group" aria-label="Performance period" className="flex flex-wrap" style={{ gap: 6 }}>
      {PERIODS.map((p) => (
        <button
          key={p.id}
          type="button"
          className="cp-chip"
          data-testid={`analysis-perf-period-${p.id}`}
          aria-pressed={p.id === value}
          onClick={() => onChange(p.id)}
          style={{ padding: "6px 12px", ...(p.id === value ? pressed : null) }}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}

function statusTone(pill: string): Tone {
  if (pill === "HEALTHY") return "mint";
  return pill === "POOR" ? "danger" : "amber";
}

function perfTiles(tiles: PerfTile[]): TileItem[] {
  return tiles.map((t) => ({
    k: t.label,
    v: <span data-testid={`analysis-perf-tile-${slug(t.label)}`}>{t.value}</span>,
    s: t.sub || t.note ? [t.sub, t.note].filter(Boolean).join(" · ") : undefined,
    tone: t.tone,
  }));
}

function MonthlyBlock({ months, period }: { months: MonthReturn[]; period: PeriodId }) {
  const maxAbs = Math.max(0, ...months.map((m) => Math.abs(m.portfolio ?? 0)));
  return (
    <Section title={`Monthly returns vs benchmark · ${PERIOD_BADGE[period]}`}>
      {months.length === 0 ? (
        <span data-testid="analysis-months-empty" style={body}>Your month-by-month story starts after your first full month invested.</span>
      ) : (
        <div className="flex flex-col" style={{ gap: 10 }}>
          <div data-testid="analysis-months" className="cp-scroll flex overflow-x-auto" style={{ gap: 8, paddingBottom: 6 }}>
            {months.map((m) => {
              const verdict = monthVerdict(m);
              const up = (m.portfolio ?? 0) >= 0;
              const height = m.portfolio != null && maxAbs > 0 ? (Math.abs(m.portfolio) / maxAbs) * 18 : 0;
              return (
                <div key={m.month} data-testid="analysis-month" className="flex flex-col items-center" style={{ gap: 4, flex: "none", minWidth: 68, padding: "8px 6px", borderRadius: 8, background: "var(--bg-2)" }}>
                  <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>{m.month}</span>
                  <span aria-hidden="true" style={{ position: "relative", display: "block", width: "100%", height: 40 }}>
                    <span style={{ position: "absolute", left: 10, right: 10, top: "50%", height: 1, background: "var(--line-2)" }} />
                    {height > 0 && (
                      <span style={{ position: "absolute", left: "calc(50% - 4px)", width: 8, height, ...(up ? { bottom: "50%" } : { top: "50%" }), borderRadius: up ? "3px 3px 0 0" : "0 0 3px 3px", background: TONE_COLOR[up ? "mint" : "danger"] }} />
                    )}
                  </span>
                  <span className="cp-num" style={{ fontSize: 12 }}><SignedPct value={m.portfolio} testId="analysis-month-return" /></span>
                  <span
                    role="img"
                    aria-label={verdict === "beat" ? "Beat benchmark" : verdict === "miss" ? "Missed benchmark" : "No benchmark data"}
                    style={{ fontSize: 10, color: verdict === "beat" ? "var(--mint)" : verdict === "miss" ? "var(--cp-danger)" : "var(--cp-ink-4)" }}
                  >
                    {verdict === "beat" ? "▲" : verdict === "miss" ? "▼" : "·"}
                    {m.benchmark != null && <span className="cp-num" style={{ marginLeft: 4, color: "var(--cp-ink-3)" }}>{fmtPct(m.benchmark, { signed: true })}</span>}
                  </span>
                </div>
              );
            })}
          </div>
          <span style={quiet}>
            ▲ at or above the benchmark · ▼ below it · a dot where the month has no benchmark figure. Each month is the change in your statement value from the month before, so it includes money you added or took out. The benchmark, where there is one, is your funds’ one-year category average spread evenly over twelve months.
          </span>
        </div>
      )}
    </Section>
  );
}

// ── portfolio value history ──────────────────────────────────────────────

function ValueBlock() {
  const [table, setTable] = useState(false);
  const q = useValueHistory();
  if (q.isPending) return <LoadingBlock label="Loading portfolio value history" rows={4} />;
  if (q.isError) return <ErrorBlock title="Portfolio value history didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  const series = valueSeries(q.data);
  if (!series) {
    return (
      <div data-testid="analysis-value-empty">
        <EmptyBlock title="No portfolio history yet" body="Upload a CAS statement to see your portfolio history." />
      </div>
    );
  }
  const change = series.changePct;
  const source = q.data.source === "" || q.data.source === "cas_statement" ? "CAS statement" : humanise(q.data.source);
  return (
    <Section
      title="Portfolio value"
      note={<span data-testid="analysis-value-source">Source: {source} · {plural(series.monthCount, "month", "months")} of history</span>}
    >
      <div className="flex flex-col" style={{ gap: 12 }}>
        <div className="flex flex-wrap items-baseline" style={{ gap: "4px 14px" }}>
          <span data-testid="analysis-value-now" className="cp-num" style={{ fontSize: 26 }}>{fmtINR(series.lastRs, { compact: true })}</span>
          {change != null && (
            <span data-testid="analysis-value-change" className="cp-num" style={{ fontSize: 12, color: TONE_COLOR[change >= 0 ? "mint" : "danger"] }}>
              {change >= 0 ? "↑" : "↓"} {Math.abs(change).toFixed(1)}% over the period
            </span>
          )}
        </div>
        <ValueChart series={series} />
        <span style={quiet}>The change is in your statement value from the first month shown to now. It includes money you added or took out, so it is not a return.</span>
        <div>
          <button type="button" aria-expanded={table} onClick={() => setTable((v) => !v)} style={{ fontSize: 13, color: "var(--cp-ink-2)", background: "none", border: 0, padding: 0, cursor: "pointer" }}>
            {table ? "Hide the monthly values" : "Show the monthly values"} ›
          </button>
        </div>
        {table && (
          <div className="cp-card" data-testid="analysis-value-table">
            <DataTable
              columns={[
                { key: "month", header: "Month", render: (p) => p.label },
                { key: "value", header: "Value", num: true, render: (p) => fmtINR(p.valueRs) },
              ]}
              rows={series.points}
              rowKey={(p) => p.label}
              minWidth={260}
            />
          </div>
        )}
      </div>
    </Section>
  );
}

// ── holdings composition and its drill-down ──────────────────────────────

function rankText(r: FundRating): string {
  if (r.categoryRank != null) return `Rank ${r.categoryRank}${r.categoryTotal ? `/${r.categoryTotal}` : ""} in category`;
  if (r.sectorRank != null) return `Rank ${r.sectorRank}${r.sectorTotal ? `/${r.sectorTotal}` : ""} in ${r.sector || "sector"}`;
  return "";
}

const clip = { display: "block", overflow: "hidden", textOverflow: "ellipsis" } as const;

const HOLDING_COLUMNS: Array<Column<FundRating>> = [
  {
    key: "name", header: "Name", width: "minmax(0,2.4fr)",
    render: (r) => {
      const sub = [r.schemeCategory || r.sector, rankText(r)].filter(Boolean).join(" · ");
      return (
        <Named icon={<HoldingIcon name={r.name} assetType={r.assetType} />}>
          <span data-testid="analysis-holding-name" title={r.name} style={{ ...clip, color: "var(--cp-ink)", fontWeight: 500 }}>{r.name}</span>
          {sub && <span title={sub} style={{ ...clip, fontSize: 11, color: "var(--cp-ink-3)" }}>{sub}</span>}
        </Named>
      );
    },
  },
  { key: "invested", header: "Invested", num: true, render: (r) => <span data-testid="analysis-holding-invested">{r.invested != null && r.invested > 0 ? fmtINR(r.invested, { compact: true }) : "—"}</span> },
  { key: "value", header: "Value", num: true, render: (r) => <span data-testid="analysis-holding-value">{r.currentValue != null && r.currentValue > 0 ? fmtINR(r.currentValue, { compact: true }) : "—"}</span> },
  { key: "pnl", header: "P&L %", num: true, render: (r) => <SignedPct value={r.simpleReturnPct} testId="analysis-holding-pnl" /> },
  { key: "ret1y", header: "1Y Ret", num: true, render: (r) => <SignedPct value={r.return1y} testId="analysis-holding-1y" /> },
];

const DRILL_LIMIT = 5;

function emptyDrill(tab: AssetTab): string {
  if (tab === "sgb") return "No SGB holdings found. SGBs appear only in NSDL/CDSL eCAS — if you hold Sovereign Gold Bonds, please import a Consolidated Account Statement from NSDL or CDSL.";
  if (tab === "stocks") return "No direct equity holdings found. Stocks appear from the NSDL/CDSL eCAS demat section.";
  return "No holdings in this asset class.";
}

/** The holdings behind the selected class: five at first, sortable. Mounted afresh for each tab. */
function Drill({ fp, tiles, tab, onPick }: { fp: FundPerformance; tiles: HeatmapTile[]; tab: AssetTab; onPick: (name: string) => void }) {
  const [sort, setSort] = useState<DrillSort>("return");
  const [expanded, setExpanded] = useState(false);
  const drill = drillRows(fp.ratings, tiles, tab);
  const rows = sortRows(drill.rows, sort);
  return (
    <div data-testid="analysis-holdings" style={{ borderTop: "1px solid var(--cp-line)" }}>
      <div className="flex flex-wrap items-center" style={{ gap: "8px 12px", padding: "12px 16px" }}>
        <span data-testid="analysis-holdings-count" className="cp-eyebrow">
          {tab === "all" ? "Top holdings" : assetTabLabel(tab)} · {plural(rows.length, "holding", "holdings")}
        </span>
        <div role="group" aria-label="Sort holdings" className="flex flex-wrap" style={{ gap: 6 }}>
          {DRILL_SORTS.map((s) => (
            <button
              key={s.id}
              type="button"
              className="cp-chip"
              data-testid={`analysis-holdings-sort-${s.id}`}
              aria-pressed={sort === s.id}
              onClick={() => { setSort(s.id); setExpanded(false); }}
              style={{ padding: "4px 10px", fontSize: 12, ...(sort === s.id ? pressed : null) }}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
      {drill.mergedFolios > 0 && (
        <div style={{ ...quiet, padding: "0 16px 10px" }}>
          Showing {plural(drill.rows.length, "consolidated fund", "consolidated funds")} from {plural(drill.folios, "folio", "folios")}. The same fund bought in different folios is merged, and its values and returns are the combined total.
        </div>
      )}
      <DataTable
        columns={HOLDING_COLUMNS}
        rows={expanded ? rows : rows.slice(0, DRILL_LIMIT)}
        rowKey={(r, i) => `${r.name}-${i}`}
        minWidth={620}
        onRowClick={(r) => onPick(r.name)}
        empty={emptyDrill(tab)}
      />
      <ShowAll total={rows.length} limit={DRILL_LIMIT} expanded={expanded} onToggle={() => setExpanded((v) => !v)} noun="holdings" />
    </div>
  );
}

function CompositionBlock({ fp, tiles, tab, onTab, onPick }: { fp: FundPerformance; tiles: HeatmapTile[]; tab: AssetTab; onTab: (t: AssetTab) => void; onPick: (name: string) => void }) {
  const slices = compositionSlices(fp.ratings, tiles);
  if (!slices.length) {
    return (
      <div data-testid="analysis-composition-empty">
        <EmptyBlock title="No holdings data available" body="The composition appears once your holdings are priced." />
      </div>
    );
  }
  return (
    <Section flush title="Holdings composition" note="Current value by asset class">
      <div data-testid="analysis-composition" className="flex flex-col" style={{ gap: 4, padding: "12px 10px" }}>
        {slices.map((s) => {
          const on = tab === s.tab;
          return (
            <button
              key={s.tab}
              type="button"
              data-testid={`analysis-composition-${s.tab}`}
              aria-pressed={on}
              onClick={() => onTab(on ? "all" : s.tab)}
              className="grid items-center text-left"
              style={{ gridTemplateColumns: "84px minmax(0,1fr) auto 40px", gap: 12, padding: "8px 6px", borderRadius: 8, border: `1px solid ${on ? "var(--line-2)" : "transparent"}`, background: on ? "var(--bg-2)" : "transparent", color: "inherit", cursor: "pointer", fontFamily: "var(--sans)" }}
            >
              <span style={{ fontSize: 13, color: "var(--cp-ink)" }}>{s.label}</span>
              <ShareBar pct={s.pct} dim={tab !== "all" && !on} />
              <span data-testid={`analysis-composition-${s.tab}-value`} className="cp-num" style={{ fontSize: 13 }}>{fmtINR(s.valueRs, { compact: true })}</span>
              <span data-testid={`analysis-composition-${s.tab}-pct`} className="cp-num" style={{ fontSize: 12, textAlign: "right", color: "var(--cp-ink-3)" }}>{s.pct}%</span>
            </button>
          );
        })}
        <span style={{ ...quiet, padding: "4px 6px 0" }}>
          Select a class to see its holdings. MF and ETF values come from your fund figures; Stocks and SGB / Bonds come from your largest holdings by value, so the four can add up to less than your portfolio.
        </span>
      </div>
      <Drill key={tab} fp={fp} tiles={tiles} tab={tab} onPick={onPick} />
    </Section>
  );
}

// ── one holding, opened from a table, a list or the plot ─────────────────

interface Fact {
  k: string;
  v: ReactNode;
  tone?: Tone;
  testId?: string;
}

function Facts({ title, items, note }: { title: string; items: Fact[]; note?: string }) {
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <Eyebrow>{title}</Eyebrow>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(96px,1fr))", gap: 8 }}>
        {items.map((f) => (
          <div key={f.k} className="flex flex-col" style={{ gap: 4, padding: "10px 12px", borderRadius: 10, background: "var(--bg-2)" }}>
            <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>{f.k}</span>
            <span data-testid={f.testId} className="cp-num" style={{ fontSize: 15, color: TONE_COLOR[f.tone ?? "ink"] }}>{f.v}</span>
          </div>
        ))}
      </div>
      {note && <span style={quiet}>{note}</span>}
    </div>
  );
}

const TYPE_LABEL: Record<string, string> = { mutual_fund: "Mutual fund", etf: "ETF", equity: "Stock", gold: "Gold", sgb: "SGB" };

function CategoryLeaders({ holding }: { holding: FundRating }) {
  // Asked for only when the fund is ranked in its category, as on the old screen.
  const q = useCategoryTop(holding.schemeCategory, holding.categoryRank != null);
  if (holding.categoryRank == null || !holding.schemeCategory) return null;
  if (q.isPending) return <LoadingBlock label="Loading category leaders" rows={2} />;
  if (q.isError) return <ErrorBlock title="Category leaders didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  if (!q.data.funds.length) return null;
  const columns: Array<Column<CategoryPeer>> = [
    { key: "rank", header: "#", width: "44px", num: true, render: (p) => (p.rank != null ? `#${p.rank}` : "—") },
    {
      key: "fund", header: "Fund", width: "minmax(0,2.2fr)",
      render: (p) => {
        const yours = holding.schemeCode !== "" && p.schemeCode === holding.schemeCode;
        return (
          <Named icon={<FundHouseIcon name={p.schemeName} size={22} />}>
            <span title={p.schemeName} style={{ color: yours ? "var(--mint)" : "var(--cp-ink)" }}>{p.schemeName}{yours ? " ← you" : ""}</span>
          </Named>
        );
      },
    },
    { key: "r1", header: "1Y%", num: true, render: (p) => fmtPct(p.ret1y, { signed: true }) },
    { key: "r3", header: "3Y%", num: true, render: (p) => fmtPct(p.ret3y, { signed: true }) },
    { key: "score", header: "Score", num: true, render: (p) => <span style={{ color: p.composite == null ? undefined : TONE_COLOR[scoreTone(p.composite)] }}>{fmtNum(p.composite)}</span> },
  ];
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <Eyebrow>Top 5 in category{q.data.rankDate ? ` · ${q.data.rankDate}` : ""}</Eyebrow>
      <div className="cp-card" data-testid="analysis-holding-leaders">
        <DataTable columns={columns} rows={q.data.funds} rowKey={(p, i) => `${p.schemeCode}-${i}`} minWidth={460} />
      </div>
    </div>
  );
}

function RecFact({ recs, name }: { recs: UseQueryResult<HoldingRecs>; name: string }) {
  if (recs.isPending) return <span style={quiet}>Loading the recommendation…</span>;
  const rec = recs.data?.holdings.find((h) => h.name === name);
  if (!rec) return <span style={quiet}>No recommendation data available.</span>;
  const meta = actionMeta(rec.action);
  return (
    <div data-testid="analysis-holding-rec" className="flex flex-col items-start" style={{ gap: 6 }}>
      <Pill tone={meta.tone}>{meta.label}</Pill>
      {rec.reason && <span style={body}>{rec.reason}</span>}
      {rec.categoryRank != null && (
        <span style={quiet}>Rank {rec.categoryRank}{rec.categoryTotal != null ? `/${rec.categoryTotal}` : ""} in {rec.category || "category"}</span>
      )}
    </div>
  );
}

function HoldingDetail({ name, fp, tiles, recs, onClose }: { name: string; fp: FundPerformance; tiles: HeatmapTile[]; recs: UseQueryResult<HoldingRecs>; onClose: () => void }) {
  const { ask } = useCopilotShell();
  const ref = useRef<HTMLElement>(null);
  // It opens under the holdings table, which may be far from what was selected.
  useEffect(() => {
    ref.current?.scrollIntoView({ block: "nearest" });
    ref.current?.focus({ preventScroll: true });
  }, [name]);

  const holding = findHolding(name, fp.ratings, tiles);
  const rec = recs.data?.holdings.find((h) => h.name === name);
  const close = (
    <button type="button" aria-label="Close holding detail" onClick={onClose} style={{ fontSize: 13, color: "var(--cp-ink-2)", background: "none", border: 0, cursor: "pointer", whiteSpace: "nowrap" }}>
      Close ×
    </button>
  );
  if (!holding) {
    return (
      <section ref={ref} tabIndex={-1} data-testid="analysis-holding-detail" aria-label={`${name} detail`} className="cp-card-raised flex flex-wrap items-center justify-between" style={{ gap: 12, padding: "16px 18px", outline: "none" }}>
        <span style={body}>There are no figures on record for {name}.</span>
        {close}
      </section>
    );
  }

  const kind = TYPE_LABEL[holding.assetType] ?? (humanise(holding.assetType) || "Holding");
  const group = holding.schemeCategory || holding.sector;
  return (
    <section ref={ref} tabIndex={-1} data-testid="analysis-holding-detail" aria-label={`${name} detail`} className="cp-card-raised flex flex-col" style={{ gap: 16, padding: "16px 18px", outline: "none" }}>
      <div className="flex flex-wrap items-start justify-between" style={{ gap: 12 }}>
        <div className="flex min-w-0 flex-col" style={{ gap: 6, flex: "1 1 260px" }}>
          <Eyebrow>{group ? `${kind} · ${group}` : kind}</Eyebrow>
          <span className="flex items-center" style={{ gap: 10, minWidth: 0 }}>
            <HoldingIcon name={holding.name} assetType={holding.assetType} size={30} />
            <span data-testid="analysis-holding-detail-name" className="cp-pretty" style={{ minWidth: 0, fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.2, overflowWrap: "anywhere" }}>{holding.name}</span>
          </span>
          <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
            {holding.categoryRank != null ? (
              <>
                <Pill tone="indigo">Rank {holding.categoryRank}{holding.categoryTotal ? `/${holding.categoryTotal}` : ""} in {holding.schemeCategory || "category"}</Pill>
                {holding.categoryRankPct != null && <span style={quiet}>Top {(100 - holding.categoryRankPct).toFixed(0)}%</span>}
              </>
            ) : holding.sectorRank != null ? (
              <Pill tone="indigo">Rank {holding.sectorRank}{holding.sectorTotal ? `/${holding.sectorTotal}` : ""} in {holding.sector || "sector"}</Pill>
            ) : (
              <span style={quiet}>Rank unavailable</span>
            )}
          </span>
        </div>
        {close}
      </div>

      <Facts
        title="Value"
        items={[
          { k: "Invested", v: fmtINR(holding.invested, { compact: true }), testId: "analysis-holding-detail-invested" },
          { k: "Cur. Value", v: fmtINR(holding.currentValue, { compact: true }), testId: "analysis-holding-detail-value" },
          { k: "P&L", v: fmtPct(holding.simpleReturnPct, { signed: true }), tone: signTone(holding.simpleReturnPct), testId: "analysis-holding-detail-pnl" },
        ]}
      />
      {rec && (rec.qualityScore != null || rec.healthScore != null) && (
        <Facts
          title="Scores"
          note={QUALITY_SCORE_EXPLANATION}
          items={[
            ...(rec.qualityScore != null ? [{ k: "Quality", v: `${Math.round(rec.qualityScore)}/100`, tone: scoreTone(rec.qualityScore) }] : []),
            ...(rec.healthScore != null ? [{ k: "Health", v: `${Math.round(rec.healthScore)}/100`, tone: scoreTone(rec.healthScore) }] : []),
          ]}
        />
      )}
      <Facts
        title="Returns"
        items={[
          { k: "1M", v: fmtPct(holding.return1m, { signed: true }), tone: signTone(holding.return1m) },
          { k: "3M", v: fmtPct(holding.return3m, { signed: true }), tone: signTone(holding.return3m) },
          { k: "1Y", v: fmtPct(holding.return1y, { signed: true }), tone: signTone(holding.return1y) },
          { k: "3Y", v: fmtPct(holding.return3y, { signed: true }), tone: signTone(holding.return3y) },
        ]}
      />
      {(holding.benchmarkReturn != null || holding.alpha != null) && (
        <Facts
          title="vs Benchmark"
          items={[
            ...(holding.benchmarkReturn != null ? [{ k: holding.benchmarkName || "Benchmark", v: fmtPct(holding.benchmarkReturn, { signed: true }), tone: signTone(holding.benchmarkReturn) }] : []),
            ...(holding.alpha != null ? [{ k: "Alpha", v: `${holding.alpha > 0 ? "+" : holding.alpha < 0 ? "−" : ""}${Math.abs(holding.alpha).toFixed(2)} pp`, tone: signTone(holding.alpha) }] : []),
          ]}
        />
      )}
      <CategoryLeaders holding={holding} />
      <div className="flex flex-col" style={{ gap: 8 }}>
        <Eyebrow>Recommendation</Eyebrow>
        <RecFact recs={recs} name={name} />
      </div>
      <div>
        <Btn
          variant="primary"
          onClick={() => ask(`How is ${holding.name} doing for me (invested ${fmtINR(holding.invested, { compact: true })}, now ${fmtINR(holding.currentValue, { compact: true })}, ${fmtPct(holding.simpleReturnPct, { signed: true })}), and should I keep holding it?`)}
        >
          Ask Copilot about this holding
        </Btn>
      </div>
    </section>
  );
}

// ── vs category benchmark, best and worst ────────────────────────────────

type Rating = "overperforming" | "meeting" | "underperforming";

const RATINGS: Array<{ id: Rating; label: string; tone: Tone }> = [
  { id: "overperforming", label: "Outperforming", tone: "mint" },
  { id: "meeting", label: "Meeting", tone: "amber" },
  { id: "underperforming", label: "Underperforming", tone: "danger" },
];

function PerformerList({ title, tone, rows, onPick }: { title: string; tone: Tone; rows: NamedReturn[]; onPick: (name: string) => void }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
      <Eyebrow tone={tone}>{title}</Eyebrow>
      {rows.map((f, i) => (
        <button
          key={`${f.name}-${i}`}
          type="button"
          data-testid="analysis-performer"
          onClick={() => onPick(f.name)}
          className="cp-row-link grid items-center text-left"
          style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: 12, padding: "8px 4px", border: 0, borderBottom: "1px solid var(--cp-line)", color: "inherit", fontFamily: "var(--sans)" }}
        >
          <Named icon={<HoldingIcon name={f.name} size={22} />}>
            <span title={f.name} style={{ ...clip, whiteSpace: "nowrap", fontSize: 13, color: "var(--cp-ink-2)" }}>{f.name}</span>
          </Named>
          <span className="cp-num" style={{ fontSize: 13 }}><SignedPct value={f.returnPct} /></span>
        </button>
      ))}
    </div>
  );
}

/** The benchmark split and the performers it filters. Mounted afresh for each tab, which clears the filter. */
function BenchmarkBlocks({ fp, tab, period, onPick }: { fp: FundPerformance; tab: AssetTab; period: PeriodId; onPick: (name: string) => void }) {
  const [filter, setFilter] = useState<Rating | null>(null);
  const [showAll, setShowAll] = useState(false);
  const dist = distributionFor(fp, tab);
  const total = dist.overperforming + dist.meeting + dist.underperforming;
  const view = performersFor(fp, tab, period);

  const top = !filter || filter === "overperforming" ? view.top.slice(0, showAll ? 10 : 4) : [];
  const bottom = !filter || filter === "underperforming" ? view.bottom.slice(0, showAll ? 10 : 4) : [];
  const meeting = filter === "meeting" ? (showAll ? view.meeting : view.meeting.slice(0, 6)) : [];
  const hasMore = view.top.length > 4 || view.bottom.length > 4 || view.meeting.length > 6;
  const periodLabel = PERF_KEY_LABEL[view.key];

  return (
    <div className="grid" style={twoUp}>
      <Section title={`vs category benchmark · ${PERIOD_BADGE[period]}`} note={total > 0 ? <span data-testid="analysis-benchmark-total">{plural(total, "fund", "funds")}</span> : undefined}>
        <div className="flex flex-col" style={{ gap: 10 }}>
          <span data-testid="analysis-benchmark-basis" style={quiet}>{BENCHMARK_EXPLANATION[tab]}</span>
          {total === 0 ? (
            <span data-testid="analysis-benchmark-empty" style={body}>No benchmark data yet.</span>
          ) : (
            <>
              <div className="flex flex-col" style={{ gap: 4 }}>
                {RATINGS.map((r) => {
                  const on = filter === r.id;
                  return (
                    <button
                      key={r.id}
                      type="button"
                      aria-pressed={on}
                      onClick={() => { setFilter(on ? null : r.id); setShowAll(false); }}
                      className="grid items-center text-left"
                      style={{ gridTemplateColumns: "116px minmax(0,1fr) 36px 40px", gap: 10, padding: "8px 6px", borderRadius: 8, border: `1px solid ${on ? "var(--line-2)" : "transparent"}`, background: on ? "var(--bg-2)" : "transparent", color: "inherit", cursor: "pointer", fontFamily: "var(--sans)" }}
                    >
                      <span style={{ fontSize: 13, color: "var(--cp-ink)" }}>{r.label}</span>
                      <ShareBar pct={dist[r.id]} max={total} tone={r.tone} dim={filter != null && !on} />
                      <span data-testid={`analysis-benchmark-${r.id}`} className="cp-num" style={{ fontSize: 13, textAlign: "right" }}>{fmtNum(dist[r.id])}</span>
                      <span className="cp-num" style={{ fontSize: 12, textAlign: "right", color: "var(--cp-ink-3)" }}>{Math.round((dist[r.id] / total) * 100)}%</span>
                    </button>
                  );
                })}
              </div>
              <span style={quiet}>
                {plural(total, "fund", "funds")} matched · select a group to filter the performers
                {filter && <> · <button type="button" onClick={() => setFilter(null)} style={{ fontSize: 12, color: "var(--cp-ink-2)", background: "none", border: 0, padding: 0, cursor: "pointer", textDecoration: "underline" }}>Clear filter</button></>}
              </span>
            </>
          )}
        </div>
      </Section>

      <Section title={`Best & worst performers · ${PERIOD_BADGE[period]}`} note={filter ? `Filtered by ${RATINGS.find((r) => r.id === filter)?.label.toLowerCase()}` : undefined}>
        <div data-testid="analysis-performers" className="flex flex-col" style={{ gap: 12 }}>
          {top.length + bottom.length + meeting.length === 0 ? (
            <span style={body}>{filter === "meeting" ? "No meeting-benchmark data available." : "No performers to show for this period."}</span>
          ) : (
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,220px),1fr))", gap: 16 }}>
              {top.length > 0 && <PerformerList title={`Top performers · ${periodLabel}`} tone="mint" rows={top} onPick={onPick} />}
              {bottom.length > 0 && <PerformerList title={`Needs review · ${periodLabel}`} tone="danger" rows={bottom} onPick={onPick} />}
              {meeting.length > 0 && <PerformerList title={`Meeting benchmark — ${plural(view.meeting.length, "fund", "funds")} (within ±2%)`} tone="amber" rows={meeting} onPick={onPick} />}
            </div>
          )}
          {hasMore && (
            <div>
              <button type="button" aria-expanded={showAll} onClick={() => setShowAll((v) => !v)} style={{ fontSize: 13, color: "var(--cp-ink-2)", background: "none", border: 0, padding: 0, cursor: "pointer" }}>
                {showAll ? "Show less" : filter === "meeting" ? `View all ${view.meeting.length} meeting funds` : `View all ${view.top.length + view.bottom.length} funds`} ›
              </button>
            </div>
          )}
        </div>
      </Section>
    </div>
  );
}

// ── direct stocks: sector and company split ──────────────────────────────

function ShareRows({ rows, onPick, stocks }: { rows: ValueShare[]; onPick?: (name: string) => void; /** The rows are companies: show the company icon. */ stocks?: boolean }) {
  const line = { gridTemplateColumns: "minmax(0,1.4fr) minmax(0,1fr) auto 36px", gap: 10, padding: "8px 4px", borderBottom: "1px solid var(--cp-line)" } as const;
  const cells = (r: ValueShare) => (
    <>
      <Named icon={stocks ? <HoldingIcon name={r.name} assetType="equity" size={22} /> : null}>
        <span title={r.name} style={{ ...clip, whiteSpace: "nowrap", fontSize: 13, color: "var(--cp-ink)" }}>{r.name}</span>
      </Named>
      <ShareBar pct={r.pct} />
      <span className="cp-num" style={{ fontSize: 13 }}>
        {fmtINR(r.valueRs, { compact: true })}
        {r.returnPct != null && <span style={{ marginLeft: 8 }}><SignedPct value={r.returnPct} /></span>}
      </span>
      <span className="cp-num" style={{ fontSize: 12, textAlign: "right", color: "var(--cp-ink-3)" }}>{r.pct}%</span>
    </>
  );
  return (
    <div className="flex flex-col">
      {rows.map((r) => (onPick ? (
        <button key={r.name} type="button" onClick={() => onPick(r.name)} className="cp-row-link grid items-center text-left" style={{ ...line, border: 0, borderBottom: line.borderBottom, color: "inherit", fontFamily: "var(--sans)" }}>
          {cells(r)}
        </button>
      ) : (
        <div key={r.name} className="grid items-center" style={line}>{cells(r)}</div>
      )))}
    </div>
  );
}

function StockSplit({ tiles, onPick }: { tiles: HeatmapTile[]; onPick: (name: string) => void }) {
  const sectors = sectorAllocation(tiles);
  const companies = companyAllocation(tiles);
  if (companies.count === 0) {
    return <EmptyBlock title="No equity holdings found" body="Direct stocks appear here once they are among the holdings the analytics figures cover." />;
  }
  return (
    <div className="grid" style={twoUp}>
      <Section title="Sector allocation" note={plural(sectors.length, "sector", "sectors")}>
        <div data-testid="analysis-stock-sectors" className="flex flex-col" style={{ gap: 8 }}>
          <span style={quiet}>Current value by sector · direct stocks among your largest holdings</span>
          <ShareRows rows={sectors} />
        </div>
      </Section>
      <Section title="Company allocation · top 8" note={plural(companies.count, "stock", "stocks")}>
        <div data-testid="analysis-stock-companies" className="flex flex-col" style={{ gap: 8 }}>
          <span style={quiet}>Top holdings by current value · select one to open it</span>
          <ShareRows rows={companies.top} onPick={onPick} stocks />
          {companies.restValueRs > 0 && <span style={quiet}>+{companies.restCount} more · {fmtINR(companies.restValueRs, { compact: true })}</span>}
        </div>
      </Section>
    </div>
  );
}

// ── recommendations ──────────────────────────────────────────────────────

function RecRow({ rec }: { rec: HoldingRec }) {
  const { ask } = useCopilotShell();
  const meta = actionMeta(rec.action);
  const rank = rec.categoryRank != null
    ? rec.categoryTotal != null ? `Rank ${rec.categoryRank}/${rec.categoryTotal} in category` : `Rank #${rec.categoryRank}`
    : "";
  const where = [rec.category, rank, rec.categoryRankPct != null ? `Top ${(100 - rec.categoryRankPct).toFixed(0)}%` : ""].filter(Boolean).join(" · ");
  return (
    <div data-testid="analysis-rec" className="flex flex-col" style={{ gap: 6, padding: "12px 16px", borderBottom: "1px solid var(--cp-line)" }}>
      <div className="flex flex-wrap items-center" style={{ gap: "6px 10px" }}>
        <span data-testid="analysis-rec-action"><Pill tone={meta.tone}>{meta.label}</Pill></span>
        <span className="flex items-center" style={{ flex: "1 1 220px", minWidth: 0, gap: 8 }}>
          <HoldingIcon name={rec.name} size={22} />
          <span data-testid="analysis-rec-name" style={{ minWidth: 0, fontSize: 13, fontWeight: 500, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{rec.name}</span>
        </span>
        <button
          type="button"
          onClick={() => ask(`Nivesh says “${meta.label}” for ${rec.name}. ${rec.reason} Explain the reasoning and what I should check before acting.`.replace(/\s+/g, " "))}
          style={{ fontSize: 12, color: "var(--mint)", background: "none", border: 0, padding: 0, cursor: "pointer", whiteSpace: "nowrap" }}
        >
          Ask why ›
        </button>
      </div>
      {where && <span style={quiet}>{where}</span>}
      {rec.reason && <span style={body}>{rec.reason}</span>}
      {(rec.qualityScore != null || rec.healthScore != null) && (
        <span className="flex flex-wrap cp-num" style={{ gap: 12, fontSize: 12 }}>
          {rec.qualityScore != null && <span style={{ color: TONE_COLOR[scoreTone(rec.qualityScore)] }}>Quality {Math.round(rec.qualityScore)}/100</span>}
          {rec.healthScore != null && <span style={{ color: TONE_COLOR[scoreTone(rec.healthScore)] }}>Health {Math.round(rec.healthScore)}/100</span>}
        </span>
      )}
    </div>
  );
}

function RecsBlock({ recs, tab }: { recs: HoldingRecs; tab: AssetTab }) {
  const { go } = useCopilotShell();
  const rows = recsForTab(recs, tab);
  return (
    <Section flush title="Recommendations" note={tab === "all" ? "Most actionable across classes" : assetTabLabel(tab)}>
      {rows.length === 0
        ? <div data-testid="analysis-recs-empty" style={{ ...body, padding: 16 }}>No scoring data yet for this asset class.</div>
        : rows.map((r, i) => <RecRow key={`${r.name}-${i}`} rec={r} />)}
      <div className="flex flex-col items-start" style={{ gap: 10, padding: "12px 16px" }}>
        <span style={quiet}>{QUALITY_SCORE_EXPLANATION}</span>
        <Btn onClick={() => go("tool/recommend")}>Open recommendations ›</Btn>
      </div>
    </Section>
  );
}

// ── section ──────────────────────────────────────────────────────────────

export function PerformanceSection() {
  const { mobile } = useCopilotShell();
  const [period, setPeriod] = useState<PeriodId>("inception");
  const [tab, setTab] = useState<AssetTab>("all");
  const [picked, setPicked] = useState<string | null>(null);
  const dash = useDashboard("performance", { period });
  const sync = useResync();
  const fundPerf = useFundPerformance();
  const tiles = useHeatmapTiles();
  const recs = useHoldingRecs();

  const read = dash.data ? readPerformance(dash.data, period) : null;
  const computedAt = sync.lastSyncedAt ?? read?.computedAt ?? "";
  const holdingsError = fundPerf.isError ? fundPerf.error : tiles.isError ? tiles.error : null;
  const changeTab = (t: AssetTab) => { setTab(t); setPicked(null); };

  return (
    <div data-testid="analysis-performance" className="flex flex-col" style={{ gap: 16 }}>
      <div className="flex flex-wrap items-start justify-between" style={{ gap: 14 }}>
        <div className="flex min-w-0 flex-col" style={{ gap: 8, flex: "1 1 320px" }}>
          <span className="flex flex-wrap items-center" style={{ gap: 10 }}>
            <Eyebrow>Performance · {PERIOD_BADGE[period]}</Eyebrow>
            {read?.statusPill && <span data-testid="analysis-perf-status"><Pill tone={statusTone(read.statusPill)}>{read.statusPill}</Pill></span>}
          </span>
          {read?.headline && (
            <span data-testid="analysis-perf-headline" className="cp-pretty" style={{ fontFamily: "var(--display)", fontSize: mobile ? 22 : 28, lineHeight: 1.2 }}>{read.headline}</span>
          )}
        </div>
        <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <PeriodPicker value={period} onChange={setPeriod} />
          <Btn data-testid="analysis-perf-resync" disabled={sync.isPending} onClick={() => { void sync.resync(); }} title="Recompute the performance figures from your holdings">
            {sync.isPending ? "Resyncing…" : "Resync"}
          </Btn>
        </div>
      </div>
      {sync.error && <ErrorBlock title="Resync didn’t finish" error={sync.error} />}

      {dash.isPending ? (
        <LoadingBlock label="Loading performance figures" rows={2} />
      ) : dash.isError ? (
        <ErrorBlock title="Performance figures didn’t load" error={loadError(dash.error)} onRetry={() => dash.refetch()} />
      ) : read && read.tiles.length > 0 ? (
        <div data-testid="analysis-perf-tiles"><Tiles items={perfTiles(read.tiles)} min={140} /></div>
      ) : (
        <EmptyBlock title="No performance figures for this period" body="The figures appear once your statements cover it." />
      )}

      <ValueBlock />
      {read && <MonthlyBlock months={read.months} period={period} />}

      <div className="flex flex-col" style={{ gap: 14 }}>
        <Tabs tabs={ASSET_TABS} value={tab} onChange={changeTab} label="Asset class" idPrefix="analysis-perf-asset" />
        <div role="tabpanel" id="analysis-perf-asset-panel" aria-labelledby={`analysis-perf-asset-tab-${tab}`} className="flex flex-col" style={{ gap: 16 }}>
          {fundPerf.data && tiles.data ? (
            <CompositionBlock fp={fundPerf.data} tiles={tiles.data} tab={tab} onTab={changeTab} onPick={setPicked} />
          ) : holdingsError ? (
            <ErrorBlock
              title="Holdings composition didn’t load"
              error={loadError(holdingsError)}
              onRetry={() => { if (fundPerf.isError) void fundPerf.refetch(); if (tiles.isError) void tiles.refetch(); }}
            />
          ) : (
            <LoadingBlock label="Loading holdings composition" rows={4} />
          )}

          {picked && fundPerf.data && tiles.data && (
            <HoldingDetail name={picked} fp={fundPerf.data} tiles={tiles.data} recs={recs} onClose={() => setPicked(null)} />
          )}

          {tab === "stocks" ? (
            <Loaded q={tiles} label="Loading your direct stocks" title="Your direct stocks didn’t load">
              {(data) => <StockSplit tiles={data} onPick={setPicked} />}
            </Loaded>
          ) : (
            <Loaded q={fundPerf} label="Loading the benchmark comparison" title="The benchmark comparison didn’t load">
              {(data) => <BenchmarkBlocks key={tab} fp={data} tab={tab} period={period} onPick={setPicked} />}
            </Loaded>
          )}

          <Loaded q={recs} label="Loading recommendations" title="Recommendations didn’t load">
            {(data) => <RecsBlock recs={data} tab={tab} />}
          </Loaded>

          <Loaded q={tiles} label="Loading the gain and loss plot" title="The gain and loss plot didn’t load" rows={4}>
            {(data) => {
              const points = scatterPoints(data, tab);
              return (
                <Section title="Gain / loss distribution" note={points.length > 0 ? plural(points.length, "holding", "holdings") : undefined}>
                  {points.length === 0 ? (
                    <span data-testid="analysis-scatter-empty" style={body}>No holdings data yet.</span>
                  ) : (
                    <div data-testid="analysis-scatter" className="flex flex-col" style={{ gap: 6 }}>
                      <span style={quiet}>Each dot = holding · X = invested · Y = return % · size = current value. Holdings with no cost basis on record are left out.</span>
                      <ScatterPlot points={points} onPick={setPicked} />
                    </div>
                  )}
                </Section>
              );
            }}
          </Loaded>
        </div>
      </div>

      {(read?.coverage || computedAt) && (
        <Footnote>
          {read?.coverage && <span data-testid="analysis-perf-coverage">{read.coverage.matched} of {read.coverage.total} funds matched via AMFI</span>}
          {read?.coverage && computedAt ? " · " : ""}
          {computedAt && `Figures computed ${relTime(computedAt)}`}
        </Footnote>
      )}
    </div>
  );
}
