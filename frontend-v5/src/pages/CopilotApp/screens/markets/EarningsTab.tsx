/**
 * Markets → Earnings Tracker. Declared results by sector for an index and
 * quarter from GET /api/markets/earnings; opening a sector lists its companies
 * from GET /api/markets/earnings/companies. Growth figures are in percent:
 * medians of the declared companies for a sector, the company's own for a
 * company row. "Grew / shrank" compares net profit with the year-ago quarter
 * (there is no analyst-estimate feed, so no beat / miss).
 *
 * "Your holdings · results" (mkt-HeldResults) joins the same feeds with the
 * user's directly held stocks.
 */
import { useState } from "react";
import type { EarningsCompany, EarningsSector } from "@/services/contracts/markets.contract";
import {
  Btn, DataTable, EmptyBlock, LoadingBlock, NotConnected, Pill, Section, Tiles, fmtNum, fmtPct, signTone,
  type Column, type Tone,
} from "../../components/ui";
import { fmtCr } from "./format";
import { isHeld, useEarningsSeason, useEarningsSectorCompanies, useHeldKeys } from "./hooks";
import { HeldResultsBlock } from "./mkt-HeldResults";
import { AskLink, CompanyCell, Field, LoadError, NameCell, ReadCard, SelectField, Signed, SourceLine, useReveal } from "./parts";

function growth(n: number | null | undefined) {
  return <Signed value={n}>{fmtPct(n, { signed: true })}</Signed>;
}

export function EarningsTab() {
  const [index, setIndex] = useState("Nifty 500");
  const [quarter, setQuarter] = useState<string | undefined>(undefined);
  const [sector, setSector] = useState<string | null>(null);
  const q = useEarningsSeason({ index, quarter });

  if (q.isPending) return <LoadingBlock label="Loading earnings" rows={5} />;
  if (q.isError) return <LoadError title="Earnings didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const data = q.data;
  const summary = data.summary;
  const indices = data.available_indices.length ? data.available_indices : [index];
  const quarterLabel = data.quarter ?? "this quarter";

  const selectors = (
    <div className="flex flex-wrap items-end" style={{ gap: 12 }}>
      <SelectField label="Index" value={index} onChange={(v) => { setIndex(v); setQuarter(undefined); setSector(null); }} testId="markets-earnings-index">
        {indices.map((ix) => <option key={ix} value={ix}>{ix}</option>)}
      </SelectField>
      <SelectField label="Quarter" value={quarter ?? data.period_end ?? ""} onChange={(v) => { setQuarter(v || undefined); setSector(null); }} testId="markets-earnings-quarter">
        {data.available_quarters.length === 0 && (
          <option value={data.period_end ?? ""}>{data.quarter ?? "Latest"}</option>
        )}
        {data.available_quarters.map((x) => <option key={x.period_end} value={x.period_end}>{x.label}</option>)}
      </SelectField>
    </div>
  );

  const holdings = (
    <HeldResultsBlock index={data.index} quarter={quarter} quarterLabel={quarterLabel} sectors={data.sectors.map((s) => s.sector)} />
  );
  const moveGap = (
    <NotConnected
      testId="markets-earnings-move-nc"
      title="Typical result-day move"
      body="The design also shows how much each of your stocks usually moves on its results day. That figure is not available from the product yet."
      needs={["The average result-day price move for each stock"]}
    />
  );

  if (!summary || data.sectors.length === 0) {
    return (
      <>
        {selectors}
        <EmptyBlock
          title={`No declared results for ${quarterLabel} in ${data.index}`}
          body="Results appear here as companies file them with the exchange."
        />
        {holdings}
        {moveGap}
      </>
    );
  }

  const declaredPct = summary.members > 0 ? (summary.declared / summary.members) * 100 : null;

  const columns: Column<EarningsSector>[] = [
    { key: "sector", header: "Sector", width: "minmax(0,1.7fr)", render: (s) => <NameCell name={s.sector} /> },
    { key: "declared", header: "Declared", align: "right", num: true, render: (s) => `${fmtNum(s.declared)} / ${fmtNum(s.members)}` },
    { key: "grew", header: "Grew", align: "right", num: true, render: (s) => (s.declared > 0 ? fmtNum(s.grew) : "—") },
    { key: "shrank", header: "Shrank", align: "right", num: true, render: (s) => (s.declared > 0 ? fmtNum(s.shrank) : "—") },
    { key: "nocomp", header: "No comp.", align: "right", num: true, render: (s) => (s.declared > 0 ? fmtNum(s.no_compare) : "—") },
    { key: "sales", header: "Sales YoY", align: "right", num: true, render: (s) => growth(s.sales_yoy) },
    { key: "profit", header: "Profit YoY", align: "right", num: true, render: (s) => growth(s.profit_yoy) },
    { key: "salesq", header: "Sales QoQ", align: "right", num: true, render: (s) => growth(s.sales_qoq) },
    { key: "profitq", header: "Profit QoQ", align: "right", num: true, render: (s) => growth(s.profit_qoq) },
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
            {
              k: "Sales growth · YoY",
              v: <span data-testid="markets-earnings-sales-yoy">{fmtPct(summary.sales_yoy, { signed: true })}</span>,
              s: <span data-testid="markets-earnings-profit-yoy">Profit {fmtPct(summary.profit_yoy, { signed: true })} YoY</span>,
              tone: signTone(summary.sales_yoy),
            },
            {
              k: "Sales growth · QoQ",
              v: <span data-testid="markets-earnings-sales-qoq">{fmtPct(summary.sales_qoq, { signed: true })}</span>,
              s: `Profit ${fmtPct(summary.profit_qoq, { signed: true })} QoQ`,
              tone: signTone(summary.sales_qoq),
            },
          ]}
        />
      </div>

      {holdings}
      {moveGap}

      {sector && (
        <SectorCompanies index={data.index} quarter={quarter} quarterLabel={quarterLabel} sector={sector} onClose={() => setSector(null)} />
      )}

      <Section title={`By sector · ${quarterLabel}`} note="Open a row for the sector’s companies" flush>
        <div data-testid="markets-earnings-sectors">
          <DataTable
            columns={columns}
            rows={data.sectors}
            rowKey={(s) => s.sector}
            onRowClick={(s) => setSector(s.sector === sector ? null : s.sector)}
            minWidth={900}
          />
          <SourceLine
            testId="markets-earnings-source"
            asOf={data.period_end}
            asOfLabel="quarter ended"
            note="Growth is the median of the companies that have declared; banks report profit but not sales"
            style={{ padding: "10px 16px" }}
          />
        </div>
      </Section>
    </>
  );
}

function companyStatus(c: EarningsCompany): { label: string; tone: Tone } {
  if (!c.declared) return { label: "Not yet reported", tone: "ink" };
  if (c.profit_grew === true) return { label: "Profit grew", tone: "mint" };
  if (c.profit_grew === false) return { label: "Profit shrank", tone: "danger" };
  return { label: "No year-ago quarter", tone: "ink" };
}

/** The companies behind one sector row, with a name / symbol filter. */
function SectorCompanies({ index, quarter, quarterLabel, sector, onClose }: {
  index: string;
  quarter?: string;
  quarterLabel: string;
  sector: string;
  onClose: () => void;
}) {
  const q = useEarningsSectorCompanies({ index, sector, quarter }, true);
  const held = useHeldKeys();
  const [filter, setFilter] = useState("");
  const ref = useReveal<HTMLElement>(sector);

  const needle = filter.trim().toLowerCase();
  const companies = (q.data?.companies ?? []).filter(
    (c) => !needle || c.name.toLowerCase().includes(needle) || c.symbol.toLowerCase().includes(needle),
  );

  const columns: Column<EarningsCompany>[] = [
    {
      key: "company", header: "Company", width: "minmax(0,1.9fr)",
      render: (c) => <CompanyCell symbol={c.symbol} name={c.name} held={isHeld(held.data, c.symbol, c.name)} />,
    },
    {
      key: "status", header: "Status", width: "minmax(0,1.2fr)",
      render: (c) => {
        const s = companyStatus(c);
        return <Pill tone={s.tone}>{s.label}</Pill>;
      },
    },
    { key: "sales", header: "Sales YoY", align: "right", num: true, render: (c) => growth(c.sales_yoy) },
    { key: "profit", header: "Profit YoY", align: "right", num: true, render: (c) => growth(c.profit_yoy) },
    { key: "salesq", header: "Sales QoQ", align: "right", num: true, render: (c) => growth(c.sales_qoq) },
    { key: "profitq", header: "Profit QoQ", align: "right", num: true, render: (c) => growth(c.profit_qoq) },
    { key: "rev", header: "Revenue", align: "right", num: true, render: (c) => fmtCr(c.revenue_cr) },
    { key: "pat", header: "Net profit", align: "right", num: true, render: (c) => fmtCr(c.pat_cr) },
  ];

  return (
    <section ref={ref} className="cp-card flex min-w-0 flex-col" style={{ gap: 14, padding: "16px 18px" }} data-testid="markets-earnings-companies">
      <div className="flex flex-wrap items-start justify-between" style={{ gap: 12 }}>
        <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <span className="cp-eyebrow">{index} · {quarterLabel}</span>
          <span style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.15 }} data-testid="markets-earnings-companies-sector">{sector}</span>
          {q.data && (
            <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }} data-testid="markets-earnings-companies-count">
              {fmtNum(q.data.declared)} of {fmtNum(q.data.members)} companies have declared
            </span>
          )}
        </div>
        <Btn variant="ghost" onClick={onClose} data-testid="markets-earnings-companies-close" style={{ padding: "6px 10px", fontSize: 12 }}>Close ✕</Btn>
      </div>

      {q.isPending ? (
        <LoadingBlock label="Loading the sector’s companies" />
      ) : q.isError ? (
        <LoadError title="This sector’s companies didn’t load" error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <>
          <div className="flex">
            <Field label="Filter by company or symbol" type="search" value={filter} onChange={setFilter} testId="markets-earnings-companies-filter" grow />
          </div>
          <div className="cp-card">
            <DataTable
              columns={columns}
              rows={companies}
              rowKey={(c) => c.symbol}
              minWidth={900}
              empty={needle ? `No company in this sector matches “${filter.trim()}”.` : "No companies are listed for this sector."}
            />
          </div>
        </>
      )}

      <AskLink query={`How did ${sector} companies do in their ${quarterLabel} results?`} testId="markets-earnings-companies-ask">
        Ask Copilot about this sector’s results ›
      </AskLink>
    </section>
  );
}
