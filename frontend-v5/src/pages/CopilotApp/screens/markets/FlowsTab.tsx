/**
 * Markets → FII / DII. Cash-segment flows from GET /api/markets/fii-dii (₹ crore,
 * newest session first) and holdings by sector from
 * GET /api/markets/institutional-positioning (₹ crore; positioning, not flows).
 */
import { useMarketsFiiDii, useInstitutionalPositioning } from "@/hooks/use-markets";
import type { FiiDiiFlowRow, SectorPositioning } from "@/services/contracts/markets.contract";
import { DataTable, EmptyBlock, LoadingBlock, Section, fmtNum, type Column } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { dayLabel, fmtCr, fmtCrCompact, fmtCrPlain } from "./format";
import { LoadError, NameCell, ReadCard, Signed } from "./parts";

const SESSIONS = 10;
const FII_COLOR = "var(--cp-indigo)";
const DII_COLOR = "var(--amber)";

/** What the two investor groups did on the latest session, and how often FIIs sold lately. */
function flowsLine(latest: FiiDiiFlowRow, sessions: FiiDiiFlowRow[]): string {
  const day = latest.date ? ` on ${dayLabel(latest.date)}` : "";
  const parts: string[] = [];
  if (latest.fii_net != null) {
    const sells = sessions.filter((r) => (r.fii_net ?? 0) < 0).length;
    parts.push(
      `FIIs ${latest.fii_net < 0 ? "sold" : "bought"} a net ${fmtCr(Math.abs(latest.fii_net))} in cash${day}`
      + (sessions.length > 1 ? `, and were net sellers in ${sells} of the last ${sessions.length} sessions` : ""),
    );
  }
  if (latest.dii_net != null) {
    parts.push(`DIIs ${latest.dii_net < 0 ? "sold" : "bought"} a net ${fmtCr(Math.abs(latest.dii_net))}${parts.length ? "" : day}`);
  }
  return parts.length ? `${parts.join("; ")}.` : "Net figures for the latest session are not available yet.";
}

export function FlowsTab() {
  const q = useMarketsFiiDii(90);

  if (q.isPending) return <LoadingBlock label="Loading institutional flows" rows={5} />;
  if (q.isError) return <LoadError title="FII / DII flows didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const recent = q.data.daily.slice(0, SESSIONS);
  if (recent.length === 0) {
    return (
      <>
        <EmptyBlock
          title="No institutional-flow figures yet"
          body="Daily FII and DII cash figures appear after the exchange publishes its provisional numbers."
        />
        <Positioning />
      </>
    );
  }

  const columns: Column<FiiDiiFlowRow>[] = [
    { key: "date", header: "Date", width: "minmax(0,1.3fr)", render: (r) => <NameCell name={dayLabel(r.date, { year: true })} /> },
    { key: "fb", header: "FII buy", align: "right", num: true, render: (r) => fmtCrPlain(r.fii_buy) },
    { key: "fs", header: "FII sell", align: "right", num: true, render: (r) => fmtCrPlain(r.fii_sell) },
    { key: "fn", header: "FII net", align: "right", num: true, render: (r) => <Signed value={r.fii_net} testId="markets-fii-net">{fmtCrPlain(r.fii_net, { signed: true })}</Signed> },
    { key: "db", header: "DII buy", align: "right", num: true, render: (r) => fmtCrPlain(r.dii_buy) },
    { key: "ds", header: "DII sell", align: "right", num: true, render: (r) => fmtCrPlain(r.dii_sell) },
    { key: "dn", header: "DII net", align: "right", num: true, render: (r) => <Signed value={r.dii_net} testId="markets-dii-net">{fmtCrPlain(r.dii_net, { signed: true })}</Signed> },
  ];

  return (
    <>
      <ReadCard eyebrow="Flows read" testId="markets-flows-read">{flowsLine(recent[0], recent)}</ReadCard>

      <FlowBars rows={recent} />

      <Section
        title="Cash market · ₹ Cr"
        note={`NSE provisional${q.data.as_of ? ` · as of ${dayLabel(q.data.as_of, { year: true })}` : ""}`}
        flush
      >
        <div data-testid="markets-flows-table">
          <DataTable columns={columns} rows={recent} rowKey={(r, i) => r.date ?? String(i)} minWidth={720} />
        </div>
      </Section>

      <Positioning />
    </>
  );
}

/**
 * Net flows for the last sessions, oldest on the left. FII is always the left
 * bar of a pair and DII the right, on one shared scale; the table below it is
 * the same data as figures.
 */
function FlowBars({ rows }: { rows: FiiDiiFlowRow[] }) {
  const { mobile } = useCopilotShell();
  const ordered = [...rows].reverse();
  const max = Math.max(1, ...ordered.flatMap((r) => [Math.abs(r.fii_net ?? 0), Math.abs(r.dii_net ?? 0)]));

  const bar = (value: number | null, color: string, left: string) => {
    if (value == null || value === 0) return null;
    const h = (Math.abs(value) / max) * 50;
    const up = value > 0;
    return (
      <span
        style={{
          position: "absolute", left, width: 10, height: `${h}%`, minHeight: 2, background: color,
          ...(up ? { bottom: "50%", borderRadius: "4px 4px 0 0" } : { top: "50%", borderRadius: "0 0 4px 4px" }),
        }}
      />
    );
  };

  return (
    <section className="cp-card flex flex-col" style={{ gap: 10, padding: "16px 18px" }} data-testid="markets-flows-chart">
      <div className="flex flex-wrap justify-between" style={{ gap: 10 }}>
        <span className="cp-eyebrow">Net cash flows · last {ordered.length} sessions · ₹ Cr</span>
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
        aria-label={`Net FII and DII cash flows for the last ${ordered.length} sessions; the figures are in the table below.`}
        className="flex"
        style={{ gap: mobile ? 2 : 6, height: 160 }}
      >
        {ordered.map((r, i) => {
          const label = dayLabel(r.date);
          const [day, month] = label.split(" ");
          return (
            <div
              key={r.date ?? i}
              className="flex min-w-0 flex-col"
              style={{ flex: 1, gap: 6 }}
              title={`${label} · FII ${fmtCr(r.fii_net, { signed: true })} · DII ${fmtCr(r.dii_net, { signed: true })}`}
            >
              <div className="relative" style={{ flex: 1 }}>
                <span style={{ position: "absolute", left: 0, right: 0, top: "50%", height: 1, background: "var(--line-2)" }} />
                {bar(r.fii_net, FII_COLOR, "calc(50% - 11px)")}
                {bar(r.dii_net, DII_COLOR, "calc(50% + 1px)")}
              </div>
              <span className="cp-num" style={{ fontSize: 9, lineHeight: 1.2, color: "var(--cp-ink-3)", textAlign: "center", whiteSpace: mobile ? "normal" : "nowrap", overflow: "hidden", textTransform: "uppercase" }}>
                {mobile ? <>{day}<br />{month}</> : label}
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

function Positioning() {
  const q = useInstitutionalPositioning();

  if (q.isPending) return <LoadingBlock label="Loading institutional holdings" />;
  if (q.isError) return <LoadError title="Institutional holdings didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const ranked = [...q.data.sectors]
    .filter((s) => (s.fii_cr ?? 0) > 0 || (s.dii_cr ?? 0) > 0)
    .sort((a, b) => (b.fii_cr ?? 0) - (a.fii_cr ?? 0))
    .slice(0, 10);

  const columns: Column<SectorPositioning>[] = [
    { key: "sector", header: "Sector", width: "minmax(0,1.7fr)", render: (s) => <NameCell name={s.sector} /> },
    { key: "fii", header: "FII holding", align: "right", num: true, render: (s) => fmtCrCompact(s.fii_cr) },
    { key: "dii", header: "DII holding", align: "right", num: true, render: (s) => fmtCrCompact(s.dii_cr) },
    { key: "n", header: "Stocks", align: "right", num: true, render: (s) => fmtNum(s.n) },
  ];

  return (
    <Section
      title={`FII and DII holdings by sector · ${q.data.universe}`}
      note={`Positioning, not flows${q.data.period_end ? ` · shareholding of ${dayLabel(q.data.period_end, { year: true })}` : ""}`}
      flush
    >
      <div data-testid="markets-positioning">
        <DataTable
          columns={columns}
          rows={ranked}
          rowKey={(s) => s.sector}
          minWidth={460}
          empty="No shareholding data is available for this view."
        />
      </div>
    </Section>
  );
}
