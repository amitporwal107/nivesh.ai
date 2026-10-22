/**
 * Markets → FII / DII. Cash-segment flows from GET /api/markets/fii-dii (₹ crore,
 * newest period first; one row per session or per month) and holdings by sector
 * from GET /api/markets/institutional-positioning (₹ crore; positioning, not flows).
 */
import { useState } from "react";
import type { FiiDiiFlowRow, SectorPositioning } from "@/services/contracts/markets.contract";
import { Btn, DataTable, EmptyBlock, LoadingBlock, Section, fmtNum, type Column } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { dayLabel, fmtCr, fmtCrCompact, fmtCrPlain, monthLabel } from "./format";
import { useInstitutionalFlows, useSectorPositioning } from "./hooks";
import { FilterChips, LoadError, NameCell, ReadCard, Signed, SourceLine } from "./parts";

type Gran = "daily" | "monthly";

const GRANS: { key: Gran; label: string }[] = [
  { key: "daily", label: "Daily" },
  { key: "monthly", label: "Monthly" },
];

/** Periods drawn in the chart: the original app's window, fewer on a phone. */
const CHART_PERIODS: Record<Gran, number> = { daily: 30, monthly: 18 };
const CHART_PERIODS_PHONE = 10;
/** Rows listed before "Show all". */
const TABLE_ROWS = 10;

const FII_COLOR = "var(--cp-indigo)";
const DII_COLOR = "var(--amber)";

function periodLabel(r: FiiDiiFlowRow, opts: { year?: boolean } = {}): string {
  return r.date ? dayLabel(r.date, opts) : monthLabel(r.month);
}

function combined(r: FiiDiiFlowRow): number | null {
  return r.fii_net == null && r.dii_net == null ? null : (r.fii_net ?? 0) + (r.dii_net ?? 0);
}

/** What the two investor groups did in the latest period, and how often FIIs sold lately. */
function flowsLine(latest: FiiDiiFlowRow, periods: FiiDiiFlowRow[], gran: Gran): string {
  const when = latest.date ? ` on ${dayLabel(latest.date)}` : latest.month ? ` in ${monthLabel(latest.month)}` : "";
  const unit = gran === "daily" ? "sessions" : "months";
  const parts: string[] = [];
  if (latest.fii_net != null) {
    const sells = periods.filter((r) => (r.fii_net ?? 0) < 0).length;
    parts.push(
      `FIIs ${latest.fii_net < 0 ? "sold" : "bought"} a net ${fmtCr(Math.abs(latest.fii_net))} in cash${when}`
      + (periods.length > 1 ? `, and were net sellers in ${sells} of the last ${periods.length} ${unit}` : ""),
    );
  }
  if (latest.dii_net != null) {
    parts.push(`DIIs ${latest.dii_net < 0 ? "sold" : "bought"} a net ${fmtCr(Math.abs(latest.dii_net))}${parts.length ? "" : when}`);
  }
  return parts.length ? `${parts.join("; ")}.` : "Net figures for the latest period are not available yet.";
}

export function FlowsTab() {
  const q = useInstitutionalFlows(90);
  const { mobile } = useCopilotShell();
  const [gran, setGran] = useState<Gran>("daily");
  const [all, setAll] = useState(false);

  if (q.isPending) return <LoadingBlock label="Loading institutional flows" rows={5} />;
  if (q.isError) return <LoadError title="FII / DII flows didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const series = gran === "daily" ? q.data.daily : q.data.monthly;
  const toggle = (
    <FilterChips
      items={GRANS}
      value={gran}
      onChange={(g) => { setGran(g); setAll(false); }}
      label="Flow period"
      idPrefix="markets-flows-gran"
    />
  );

  if (series.length === 0) {
    return (
      <>
        {toggle}
        <EmptyBlock
          title={gran === "daily" ? "No institutional-flow figures yet" : "No monthly totals yet"}
          body="FII and DII cash figures appear here once the exchange has published them for a session."
        />
        <Positioning />
      </>
    );
  }

  const chartRows = series.slice(0, mobile ? CHART_PERIODS_PHONE : CHART_PERIODS[gran]);
  const recent = series.slice(0, TABLE_ROWS);
  const listed = all ? series : recent;

  const columns: Column<FiiDiiFlowRow>[] = [
    { key: "date", header: gran === "daily" ? "Date" : "Month", width: "minmax(0,1.3fr)", render: (r) => <NameCell name={periodLabel(r, { year: true })} /> },
    { key: "fb", header: "FII buy", align: "right", num: true, render: (r) => fmtCrPlain(r.fii_buy) },
    { key: "fs", header: "FII sell", align: "right", num: true, render: (r) => fmtCrPlain(r.fii_sell) },
    { key: "fn", header: "FII net", align: "right", num: true, render: (r) => <Signed value={r.fii_net} testId="markets-fii-net">{fmtCrPlain(r.fii_net, { signed: true })}</Signed> },
    { key: "db", header: "DII buy", align: "right", num: true, render: (r) => fmtCrPlain(r.dii_buy) },
    { key: "ds", header: "DII sell", align: "right", num: true, render: (r) => fmtCrPlain(r.dii_sell) },
    { key: "dn", header: "DII net", align: "right", num: true, render: (r) => <Signed value={r.dii_net} testId="markets-dii-net">{fmtCrPlain(r.dii_net, { signed: true })}</Signed> },
    { key: "cn", header: "Both, net", align: "right", num: true, render: (r) => <Signed value={combined(r)} testId="markets-combined-net">{fmtCrPlain(combined(r), { signed: true })}</Signed> },
  ];

  return (
    <>
      {toggle}

      <ReadCard eyebrow="Flows read" testId="markets-flows-read">{flowsLine(series[0], recent, gran)}</ReadCard>

      <FlowBars rows={chartRows} gran={gran} />

      <Section
        title={`Cash market · ₹ Cr · ${fmtNum(series.length)} ${gran === "daily" ? "sessions" : "months"}`}
        note="Net = buy − sell"
        flush
      >
        <div data-testid="markets-flows-table">
          <DataTable columns={columns} rows={listed} rowKey={(r, i) => r.date ?? r.month ?? String(i)} minWidth={820} />
          <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px", padding: "10px 16px" }}>
            <SourceLine testId="markets-flows-source" asOf={q.data.as_of} />
            {series.length > TABLE_ROWS && (
              <Btn variant="ghost" onClick={() => setAll((v) => !v)} data-testid="markets-flows-all" style={{ padding: "6px 10px", fontSize: 12 }}>
                {all ? `Show the latest ${TABLE_ROWS}` : `Show all ${fmtNum(series.length)}`}
              </Btn>
            )}
          </div>
        </div>
      </Section>

      <Positioning />
    </>
  );
}

/**
 * Net flows for the latest periods, oldest on the left. FII is always the left
 * bar of a pair and DII the right, on one shared scale; the table below it is
 * the same data as figures.
 */
function FlowBars({ rows, gran }: { rows: FiiDiiFlowRow[]; gran: Gran }) {
  const { mobile } = useCopilotShell();
  const ordered = [...rows].reverse();
  const max = Math.max(1, ...ordered.flatMap((r) => [Math.abs(r.fii_net ?? 0), Math.abs(r.dii_net ?? 0)]));
  const unit = gran === "daily" ? "sessions" : "months";
  // Pairs get narrower as more periods share the row.
  const barWidth = ordered.length > 20 ? 5 : ordered.length > 12 ? 7 : 10;
  // A label under every bar only while they fit.
  const labelEvery = Math.max(1, Math.ceil(ordered.length / (mobile ? 5 : 15)));

  const bar = (value: number | null, color: string, left: string) => {
    if (value == null || value === 0) return null;
    const h = (Math.abs(value) / max) * 50;
    const up = value > 0;
    return (
      <span
        style={{
          position: "absolute", left, width: barWidth, height: `${h}%`, minHeight: 2, background: color,
          ...(up ? { bottom: "50%", borderRadius: "4px 4px 0 0" } : { top: "50%", borderRadius: "0 0 4px 4px" }),
        }}
      />
    );
  };

  return (
    <section className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: "16px 18px" }} data-testid="markets-flows-chart">
      <div className="flex flex-wrap justify-between" style={{ gap: 10 }}>
        <span className="cp-eyebrow">Net cash flows · last {ordered.length} {unit} · ₹ Cr</span>
        <span className="flex cp-mono-note" style={{ gap: 14, color: "var(--cp-ink-3)" }}>
          <span className="inline-flex items-center" style={{ gap: 6 }}>
            <span className="nv-dot" style={{ background: FII_COLOR }} aria-hidden />FII · left bar
          </span>
          <span className="inline-flex items-center" style={{ gap: 6 }}>
            <span className="nv-dot" style={{ background: DII_COLOR }} aria-hidden />DII · right bar
          </span>
        </span>
      </div>
      <div
        role="img"
        aria-label={`Net FII and DII cash flows for the last ${ordered.length} ${unit}; the figures are in the table below.`}
        className="flex"
        style={{ gap: ordered.length > 12 ? 2 : mobile ? 2 : 6, height: 160 }}
      >
        {ordered.map((r, i) => {
          const label = periodLabel(r);
          const [first, second] = label.split(" ");
          const showLabel = (ordered.length - 1 - i) % labelEvery === 0;
          return (
            <div
              key={r.date ?? r.month ?? i}
              data-testid="markets-flows-bar"
              className="flex min-w-0 flex-col"
              style={{ flex: 1, gap: 6 }}
              title={`${label} · FII ${fmtCr(r.fii_net, { signed: true })} · DII ${fmtCr(r.dii_net, { signed: true })}`}
            >
              <div className="relative" style={{ flex: 1 }}>
                <span style={{ position: "absolute", left: 0, right: 0, top: "50%", height: 1, background: "var(--line-2)" }} />
                {bar(r.fii_net, FII_COLOR, `calc(50% - ${barWidth + 1}px)`)}
                {bar(r.dii_net, DII_COLOR, "calc(50% + 1px)")}
              </div>
              <span className="cp-num" style={{ height: 22, fontSize: 9, lineHeight: 1.2, color: "var(--cp-ink-3)", textAlign: "center", overflow: "hidden", textTransform: "uppercase" }}>
                {showLabel && <>{first}<br />{second}</>}
              </span>
            </div>
          );
        })}
      </div>
      <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>
        Bars above the line are net buying, below it net selling. Tallest bar: {fmtCr(max)}.
      </span>
    </section>
  );
}

type Lens = "fii" | "dii" | "both";

const LENSES: { key: Lens; label: string }[] = [
  { key: "fii", label: "Rank by FII" },
  { key: "dii", label: "Rank by DII" },
  { key: "both", label: "Rank by both" },
];

function lensValue(s: SectorPositioning, lens: Lens): number {
  if (lens === "fii") return s.fii_cr ?? 0;
  if (lens === "dii") return s.dii_cr ?? 0;
  return (s.fii_cr ?? 0) + (s.dii_cr ?? 0);
}

function Positioning() {
  const q = useSectorPositioning();
  const [lens, setLens] = useState<Lens>("fii");
  const [all, setAll] = useState(false);

  if (q.isPending) return <LoadingBlock label="Loading institutional holdings" />;
  if (q.isError) return <LoadError title="Institutional holdings didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const ranked = [...q.data.sectors]
    .filter((s) => (s.fii_cr ?? 0) > 0 || (s.dii_cr ?? 0) > 0)
    .sort((a, b) => lensValue(b, lens) - lensValue(a, lens));
  const listed = all ? ranked : ranked.slice(0, 10);

  const columns: Column<SectorPositioning>[] = [
    { key: "sector", header: "Sector", width: "minmax(0,1.7fr)", render: (s) => <NameCell name={s.sector} /> },
    { key: "fii", header: "FII holding", align: "right", num: true, render: (s) => fmtCrCompact(s.fii_cr) },
    { key: "dii", header: "DII holding", align: "right", num: true, render: (s) => fmtCrCompact(s.dii_cr) },
    { key: "both", header: "Both", align: "right", num: true, render: (s) => fmtCrCompact(lensValue(s, "both")) },
    { key: "n", header: "Stocks", align: "right", num: true, render: (s) => fmtNum(s.n) },
  ];

  return (
    <Section title={`FII and DII holdings by sector · ${q.data.universe}`} note="Positioning, not flows" flush>
      <div style={{ padding: "12px 16px" }}>
        <FilterChips items={LENSES} value={lens} onChange={setLens} label="Rank sectors by" idPrefix="markets-positioning-lens" />
      </div>
      <div data-testid="markets-positioning">
        <DataTable
          columns={columns}
          rows={listed}
          rowKey={(s) => s.sector}
          minWidth={560}
          empty="No shareholding data is available for this view."
        />
        <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px", padding: "10px 16px" }}>
          <SourceLine
            testId="markets-positioning-source"
            asOf={q.data.period_end}
            asOfLabel="shareholding of"
            note="Holding value = holding % × market cap"
          />
          {ranked.length > 10 && (
            <Btn variant="ghost" onClick={() => setAll((v) => !v)} data-testid="markets-positioning-all" style={{ padding: "6px 10px", fontSize: 12 }}>
              {all ? "Show the top 10" : `Show all ${fmtNum(ranked.length)}`}
            </Btn>
          )}
        </div>
      </div>
    </Section>
  );
}
