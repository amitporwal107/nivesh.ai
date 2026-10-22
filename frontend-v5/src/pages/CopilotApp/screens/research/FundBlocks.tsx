/**
 * Research → Mutual fund: the blocks fed by ./data.
 *
 *   FundFacts     NAV, size, cost, riskometer, benchmark, launch date
 *   FundReturns   returns against the category average, risk measures, rank, peers
 *   FundHoldings  asset split, sector mix and the largest holdings
 *   FundManagers  who runs the scheme and since when
 *
 * Returns and risk come from the data platform (the figures the original app's
 * holding drawer shows). Size, cost, managers and holdings come from the
 * scheme's factsheet. The two are never mixed in one table.
 */
import {
  DataTable, EmptyBlock, LoadingBlock, Section, Tiles, fmtDate, fmtINR, fmtNum, fmtPct,
  type Column, type Tone,
} from "../../components/ui";
import { FundName, StockName } from "../../components/EntityIcon";
import { fmtCrCompact } from "../markets/format";
import { LoadError, NameCell, Signed } from "../markets/parts";
import {
  useFundFactsheet, useFundLookup, useFundNumbers,
  type FactHolding, type FactManager, type FundNumbers,
} from "./data";
import { NotAvailable, inWords, orNA } from "./parts";

export interface FundRef {
  name: string;
  schemeCode: string | null | undefined;
}

const nav = (n: number) => `₹${new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(n)}`;
const pct2 = (n: number) => fmtPct(n, { digits: 2 });
const ratio = (n: number) => fmtNum(n, 2);

/** The original holding drawer's reading of a Sharpe or Sortino ratio: 1 or more is strong, below 0 is weak. */
function ratioTone(v: number | null | undefined): Tone {
  if (v == null || !Number.isFinite(v)) return "ink";
  return v >= 1 ? "mint" : v < 0 ? "danger" : "ink";
}

// ── key facts ────────────────────────────────────────────────────────────

export function FundFacts({ fund }: { fund: FundRef }) {
  const lookup = useFundLookup(fund.name, fund.schemeCode);
  const sheet = useFundFactsheet(fund.name, fund.schemeCode);

  if (lookup.isPending || sheet.isPending) return <LoadingBlock label="Loading the fund’s key facts" rows={4} />;

  const latest = lookup.data?.latest_nav ?? null;
  const facts = sheet.data ?? null;
  const meta = facts?.plan.metadata ?? null;
  const missing = [
    // A failed lookup is reported as an error above, not as a figure the data lacks.
    ...(lookup.isError ? [] : latest?.nav == null ? ["NAV"] : latest.nav_date ? [] : ["the NAV’s date"]),
    ...(facts && meta?.aum_cr == null ? ["fund size"] : []),
    ...(facts && meta?.expense_ratio == null ? ["expense ratio"] : []),
  ];

  return (
    <div className="flex flex-col" style={{ gap: 12 }}>
      {lookup.isError && (
        <div data-testid="research-fund-lookup-error">
          <LoadError title="The latest NAV didn’t load" error={lookup.error} onRetry={() => lookup.refetch()} />
        </div>
      )}
      {sheet.isError && (
        <div data-testid="research-fund-facts-error">
          <LoadError title="The fund’s factsheet didn’t load" error={sheet.error} onRetry={() => sheet.refetch()} />
        </div>
      )}
      {!sheet.isError && !facts && (
        <div data-testid="research-fund-facts-empty">
          <EmptyBlock
            title="No factsheet on file for this scheme yet"
            body="Fund size, expense ratio, riskometer, managers and holdings appear once the scheme’s factsheet has been collected."
          />
        </div>
      )}

      <Section
        title="Key facts"
        note={facts?.fetchedAt ? `Factsheet collected ${fmtDate(facts.fetchedAt)}` : undefined}
      >
        <div className="flex flex-col" style={{ gap: 12 }} data-testid="research-fund-facts">
          <Tiles
            min={140}
            items={[
              {
                k: "NAV",
                v: <span data-testid="research-fund-nav">{orNA(latest?.nav, nav)}</span>,
                s: latest?.nav == null ? undefined : latest.nav_date ? `As of ${fmtDate(latest.nav_date)}` : "Date not reported",
              },
              { k: "Fund size", v: <span data-testid="research-fund-aum">{orNA(meta?.aum_cr, fmtCrCompact)}</span> },
              {
                k: "Expense ratio",
                v: <span data-testid="research-fund-expense">{orNA(meta?.expense_ratio, pct2)}</span>,
                s: meta?.plan_type ? `${meta.plan_type} plan · a year` : undefined,
              },
              { k: "Riskometer", v: <span data-testid="research-fund-risk-label">{meta?.risk_label || <NotAvailable />}</span> },
              { k: "Minimum SIP", v: orNA(meta?.min_sip, (n) => fmtINR(n)) },
              { k: "Portfolio turnover", v: orNA(meta?.portfolio_turnover, (n) => fmtPct(n, { digits: 0 })) },
            ]}
          />
          <span style={{ fontSize: 13, lineHeight: 1.6, color: "var(--cp-ink-2)" }}>
            Benchmark: <span data-testid="research-fund-benchmark" style={{ color: "var(--cp-ink)" }}>{meta?.benchmark || <NotAvailable />}</span>
            {" · "}Launched: <span style={{ color: "var(--cp-ink)" }}>{meta?.launch_date ? fmtDate(meta.launch_date) : <NotAvailable />}</span>
          </span>
          {facts && !facts.exactPlan && (
            <span data-testid="research-fund-plan-note" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>
              The factsheet on file is for {meta?.scheme_name ?? "another plan of this scheme"}
              {meta?.plan_type ? ` (${meta.plan_type} plan)` : ""}. Its expense ratio can differ from the plan you searched for.
            </span>
          )}
          {missing.length > 0 && (
            <span data-testid="research-fund-facts-missing" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>
              Not in the data for this scheme: {inWords(missing)}.
            </span>
          )}
        </div>
      </Section>
    </div>
  );
}

// ── returns, risk, rank ──────────────────────────────────────────────────

interface ReturnLine {
  period: string;
  fund: number | null | undefined;
  /** `undefined` when the data platform does not compute a category average for the period. */
  category: number | null | undefined;
  hasCategory: boolean;
}

function returnLines(d: FundNumbers): ReturnLine[] {
  return [
    { period: "1 month", fund: d.returns["1m"], category: undefined, hasCategory: false },
    { period: "3 months", fund: d.returns["3m"], category: undefined, hasCategory: false },
    { period: "1 year", fund: d.returns["1y"], category: d.category_avg["1y"], hasCategory: true },
    { period: "3 years", fund: d.returns["3y"], category: d.category_avg["3y"], hasCategory: true },
  ];
}

export function FundReturns({ fund }: { fund: FundRef }) {
  const lookup = useFundLookup(fund.name, fund.schemeCode);
  const isin = lookup.data?.resolved.isin ?? null;
  const q = useFundNumbers(isin);

  if (lookup.isPending || (isin && q.isPending)) return <LoadingBlock label="Loading returns and risk" rows={5} />;
  // The lookup's own failure is reported by the key-facts block above this one.
  if (lookup.isError) return null;
  if (q.isError) {
    return (
      <div data-testid="research-fund-returns-error">
        <LoadError title="Returns and risk didn’t load" error={q.error} onRetry={() => q.refetch()} />
      </div>
    );
  }
  if (!isin || !q.data || !q.data.daas_available) {
    return (
      <div data-testid="research-fund-returns-empty">
        <EmptyBlock
          title="No returns or risk figures for this scheme yet"
          body={isin
            ? "The data platform has not computed returns, risk or a category rank for this scheme."
            : "This scheme could not be matched to a fund on the data platform, so there are no returns or risk figures to show."}
        />
      </div>
    );
  }

  const d = q.data;
  const rank = d.ranking.composite_rank;
  const size = d.ranking.category_size;
  const columns: Column<ReturnLine>[] = [
    { key: "period", header: "Period", width: "minmax(0,1.2fr)", render: (r) => <NameCell name={r.period} /> },
    {
      key: "fund", header: "This fund", align: "right", num: true,
      render: (r) => (r.fund == null ? <NotAvailable /> : <Signed value={r.fund}>{fmtPct(r.fund, { signed: true, digits: 2 })}</Signed>),
    },
    {
      key: "cat", header: "Category average", align: "right", num: true,
      render: (r) => (!r.hasCategory ? "Not computed" : r.category == null ? <NotAvailable /> : fmtPct(r.category, { signed: true, digits: 2 })),
    },
    {
      key: "diff", header: "Difference", align: "right", num: true,
      render: (r) => {
        if (!r.hasCategory) return "Not computed";
        if (r.fund == null || r.category == null) return <NotAvailable />;
        const gap = r.fund - r.category;
        return <Signed value={gap}>{fmtPct(gap, { signed: true, digits: 2 })}</Signed>;
      },
    },
  ];

  return (
    <div className="flex flex-col" style={{ gap: 12 }}>
      <Section title={`Returns${d.category ? ` · ${d.category}` : ""}`} note="From the Nivesh data platform" flush>
        <div data-testid="research-fund-returns">
          <DataTable columns={columns} rows={returnLines(d)} rowKey={(r) => r.period} minWidth={460} />
        </div>
      </Section>

      <div data-testid="research-fund-risk">
        <Tiles
          min={140}
          items={[
            { k: "Sharpe ratio", v: <span data-testid="research-fund-sharpe">{orNA(d.risk.sharpe, ratio)}</span>, tone: ratioTone(d.risk.sharpe) },
            { k: "Sortino ratio", v: orNA(d.risk.sortino, ratio), tone: ratioTone(d.risk.sortino) },
            { k: "Volatility", v: orNA(d.risk.volatility_1y, (n) => fmtPct(n)), s: "Over 1 year" },
            { k: "Maximum drawdown", v: <span data-testid="research-fund-drawdown">{orNA(d.risk.max_drawdown, (n) => fmtPct(n))}</span> },
            {
              k: "Rank in category",
              v: <span data-testid="research-fund-rank">{rank == null ? <NotAvailable /> : `${fmtNum(rank)}${size != null ? ` of ${fmtNum(size)}` : ""}`}</span>,
              s: rank == null ? "No rank computed for this scheme" : "1 is best",
            },
          ]}
        />
      </div>

      <Section title="Top funds in its category" note="By the data platform’s category rank" flush>
        <div data-testid="research-fund-peers">
          <DataTable
            columns={[
              { key: "name", header: "Fund", width: "minmax(0,2.4fr)", render: (p) => (p.name ? <FundName name={p.name} size={22} /> : <NotAvailable />) },
              { key: "ret", header: "1-year return", align: "right", num: true, render: (p) => (p.return_1y == null ? <NotAvailable /> : <Signed value={p.return_1y}>{fmtPct(p.return_1y, { signed: true, digits: 2 })}</Signed>) },
              { key: "rank", header: "Rank", align: "right", num: true, render: (p) => orNA(p.composite_rank, (n) => fmtNum(n)) },
            ]}
            rows={d.top_peers}
            rowKey={(p, i) => `${p.name ?? "peer"}-${i}`}
            minWidth={420}
            empty="Not available: the data platform returned no ranked peers for this category."
          />
        </div>
      </Section>
    </div>
  );
}

// ── what it holds ────────────────────────────────────────────────────────

const HOLDINGS_SHOWN = 15;

function isCompany(h: FactHolding): boolean {
  return /equity/i.test(h.instrument_type ?? "");
}

export function FundHoldings({ fund }: { fund: FundRef }) {
  const q = useFundFactsheet(fund.name, fund.schemeCode);

  if (q.isPending) return <LoadingBlock label="Loading the fund’s holdings" rows={6} />;
  if (q.isError) {
    return (
      <div data-testid="research-fund-holdings-error">
        <LoadError title="The fund’s holdings didn’t load" error={q.error} onRetry={() => q.refetch()} />
      </div>
    );
  }
  const plan = q.data?.plan;
  if (!plan || plan.holdings.length === 0) {
    return (
      <div data-testid="research-fund-holdings-empty">
        <EmptyBlock
          title="No holdings on file for this scheme yet"
          body="What the fund owns appears once its factsheet has been collected."
        />
      </div>
    );
  }

  const top = [...plan.holdings].sort((a, b) => (b.pct ?? -1) - (a.pct ?? -1)).slice(0, HOLDINGS_SHOWN);
  const split = plan.split;
  const top10 = plan.v3_primitives?.top10_concentration_pct;

  const columns: Column<FactHolding>[] = [
    {
      key: "name", header: "Holding", width: "minmax(0,2.4fr)",
      // Factsheet rows carry the company's name, not its exchange symbol, so the icon is keyed by the name.
      render: (h) => (isCompany(h) ? <StockName symbol={h.name} size={22} /> : <NameCell name={h.name} />),
    },
    { key: "sector", header: "Sector", width: "minmax(0,1.3fr)", render: (h) => h.sector || <NotAvailable /> },
    { key: "type", header: "Type", width: "minmax(0,1.1fr)", render: (h) => h.instrument_type || <NotAvailable /> },
    { key: "pct", header: "Weight", align: "right", num: true, render: (h) => orNA(h.pct, pct2) },
  ];

  return (
    <div className="flex flex-col" style={{ gap: 12 }}>
      <div data-testid="research-fund-split">
        <Tiles
          min={140}
          items={[
            { k: "Equity", v: orNA(split?.equity, pct2) },
            { k: "Debt", v: orNA(split?.debt, pct2) },
            { k: "Cash", v: orNA(split?.cash, pct2) },
            { k: "Top 10 holdings", v: orNA(top10, pct2), s: "Share of the fund" },
          ]}
        />
      </div>

      <Section
        title={`Largest holdings · ${fmtNum(top.length)} of ${fmtNum(plan.holdings.length)}`}
        note={q.data?.fetchedAt ? `Factsheet collected ${fmtDate(q.data.fetchedAt)}` : undefined}
        flush
      >
        <div data-testid="research-fund-holdings">
          <DataTable columns={columns} rows={top} rowKey={(h, i) => `${h.name}-${i}`} minWidth={620} />
        </div>
      </Section>

      <Section title="Sector mix" flush>
        <div data-testid="research-fund-sectors">
          <DataTable
            columns={[
              { key: "name", header: "Sector", width: "minmax(0,2fr)", render: (s) => <NameCell name={s.name} /> },
              { key: "pct", header: "Weight", align: "right", num: true, render: (s) => orNA(s.pct, pct2) },
            ]}
            rows={plan.sectors}
            rowKey={(s) => s.name}
            minWidth={280}
            empty="Not available: the factsheet has no sector breakdown."
          />
        </div>
      </Section>
    </div>
  );
}

// ── who runs it ──────────────────────────────────────────────────────────

export function FundManagers({ fund }: { fund: FundRef }) {
  const q = useFundFactsheet(fund.name, fund.schemeCode);

  if (q.isPending) return <LoadingBlock label="Loading the fund’s managers" rows={3} />;
  if (q.isError) {
    return (
      <div data-testid="research-fund-managers-error">
        <LoadError title="The fund’s managers didn’t load" error={q.error} onRetry={() => q.refetch()} />
      </div>
    );
  }
  const managers = q.data?.plan.v3_primitives?.fund_managers ?? [];
  if (managers.length === 0) {
    return (
      <div data-testid="research-fund-managers-empty">
        <EmptyBlock
          title="No manager details on file for this scheme yet"
          body="Who runs the fund, and since when, appears once its factsheet has been collected."
        />
      </div>
    );
  }

  const columns: Column<FactManager>[] = [
    { key: "name", header: "Manager", width: "minmax(0,2fr)", render: (m) => <NameCell name={m.name} /> },
    { key: "since", header: "Managing since", render: (m) => (m.since ? fmtDate(m.since) : <NotAvailable />) },
    { key: "tenure", header: "Tenure", align: "right", num: true, render: (m) => orNA(m.tenure_years, (n) => `${fmtNum(n, 1)} years`) },
  ];

  return (
    <Section title="Fund managers" note={q.data?.fetchedAt ? `Factsheet collected ${fmtDate(q.data.fetchedAt)}` : undefined} flush>
      <div data-testid="research-fund-managers">
        <DataTable columns={columns} rows={managers} rowKey={(m, i) => `${m.name}-${i}`} minWidth={420} />
      </div>
    </Section>
  );
}
