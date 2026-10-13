/**
 * Markets → Earnings Tracker. Declared results by sector for an index and
 * quarter from GET /api/markets/earnings. Growth figures are medians of the
 * declared companies, in percent; "grew / shrank" compares net profit with the
 * year-ago quarter (there is no analyst-estimate feed, so no beat / miss).
 */
import { useState } from "react";
import { useEarnings } from "@/hooks/use-markets";
import type { EarningsSector } from "@/services/contracts/markets.contract";
import {
  DataTable, EmptyBlock, LoadingBlock, NotConnected, Section, Tiles, fmtNum, fmtPct,
  type Column,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { LoadError, NameCell, ReadCard, Signed } from "./parts";

const selectStyle = {
  padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)",
  color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13,
} as const;

export function EarningsTab() {
  const [index, setIndex] = useState("Nifty 500");
  const [quarter, setQuarter] = useState<string | undefined>(undefined);
  const q = useEarnings({ index, quarter });
  const { ask } = useCopilotShell();

  if (q.isPending) return <LoadingBlock label="Loading earnings" rows={5} />;
  if (q.isError) return <LoadError title="Earnings didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const data = q.data;
  const summary = data.summary;
  const indices = data.available_indices.length ? data.available_indices : [index];
  const quarterLabel = data.quarter ?? "this quarter";

  const selectors = (
    <div className="flex flex-wrap items-end" style={{ gap: 12 }}>
      <label className="flex flex-col" style={{ gap: 4 }}>
        <span className="cp-mono-note">Index</span>
        <select value={index} onChange={(e) => { setIndex(e.target.value); setQuarter(undefined); }} style={selectStyle} data-testid="markets-earnings-index">
          {indices.map((ix) => <option key={ix} value={ix}>{ix}</option>)}
        </select>
      </label>
      <label className="flex flex-col" style={{ gap: 4 }}>
        <span className="cp-mono-note">Quarter</span>
        <select
          value={quarter ?? data.period_end ?? ""}
          onChange={(e) => setQuarter(e.target.value || undefined)}
          style={selectStyle}
          data-testid="markets-earnings-quarter"
        >
          {data.available_quarters.length === 0 && (
            <option value={data.period_end ?? ""}>{data.quarter ?? "Latest"}</option>
          )}
          {data.available_quarters.map((x) => <option key={x.period_end} value={x.period_end}>{x.label}</option>)}
        </select>
      </label>
    </div>
  );

  if (!summary || data.sectors.length === 0) {
    return (
      <>
        {selectors}
        <EmptyBlock
          title={`No declared results for ${quarterLabel} in ${data.index}`}
          body="Results appear here as companies file them with the exchange."
        />
      </>
    );
  }

  const declaredPct = summary.members > 0 ? (summary.declared / summary.members) * 100 : null;

  const columns: Column<EarningsSector>[] = [
    { key: "sector", header: "Sector", width: "minmax(0,1.7fr)", render: (s) => <NameCell name={s.sector} /> },
    { key: "declared", header: "Declared", align: "right", num: true, render: (s) => `${fmtNum(s.declared)} / ${fmtNum(s.members)}` },
    { key: "grew", header: "Grew", align: "right", num: true, render: (s) => (s.declared > 0 ? fmtNum(s.grew) : "—") },
    { key: "shrank", header: "Shrank", align: "right", num: true, render: (s) => (s.declared > 0 ? fmtNum(s.shrank) : "—") },
    {
      key: "sales", header: "Sales YoY", align: "right", num: true,
      render: (s) => <Signed value={s.sales_yoy}>{fmtPct(s.sales_yoy, { signed: true })}</Signed>,
    },
    {
      key: "profit", header: "Profit YoY", align: "right", num: true,
      render: (s) => <Signed value={s.profit_yoy}>{fmtPct(s.profit_yoy, { signed: true })}</Signed>,
    },
  ];

  return (
    <>
      {selectors}

      <ReadCard eyebrow="Earnings season" testId="markets-earnings-read">
        {fmtNum(summary.declared)} of {fmtNum(summary.members)} {data.index} companies have reported {quarterLabel}.
        {summary.declared > 0 && ` Net profit grew at ${fmtNum(summary.profit_grew)} and shrank at ${fmtNum(summary.profit_shrank)}, against the same quarter a year ago.`}
      </ReadCard>

      <div data-testid="markets-earnings-tiles">
        <Tiles
          items={[
            {
              k: "Declared",
              v: <span data-testid="markets-earnings-declared">{fmtNum(summary.declared)} / {fmtNum(summary.members)}</span>,
              s: declaredPct == null ? undefined : `${fmtPct(declaredPct, { digits: 0 })} of the index`,
            },
            { k: "Profit grew", v: <span data-testid="markets-earnings-grew">{fmtNum(summary.profit_grew)}</span>, s: "vs year-ago quarter", tone: "mint" },
            { k: "Profit shrank", v: <span data-testid="markets-earnings-shrank">{fmtNum(summary.profit_shrank)}</span>, s: "vs year-ago quarter", tone: "danger" },
            { k: "No comparable", v: fmtNum(summary.no_compare), s: "No year-ago quarter filed" },
          ]}
        />
      </div>

      <NotConnected
        testId="markets-earnings-holdings-nc"
        title="Your holdings · upcoming results"
        body="The design lists the result dates for the companies you hold, with how much each stock usually moves on result day. Neither is available from the product yet."
        needs={[
          "A results calendar: the board-meeting date for each company’s upcoming quarterly results",
          "The average result-day price move for each stock",
        ]}
      />

      <Section title={`By sector · ${quarterLabel}`} note="Median of declared companies" flush>
        <div data-testid="markets-earnings-sectors">
          <DataTable
            columns={columns}
            rows={data.sectors}
            rowKey={(s) => s.sector}
            onRowClick={(s) => ask(`How did ${s.sector} companies do in their ${quarterLabel} results?`)}
            minWidth={640}
          />
        </div>
      </Section>
    </>
  );
}
