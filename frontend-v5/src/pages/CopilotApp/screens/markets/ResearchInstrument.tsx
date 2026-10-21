/**
 * Research → Stock / Mutual fund. Find a real instrument, then either read the
 * blocks the product has an endpoint for or hand the question to the Copilot,
 * which answers with the full research card in the thread.
 *
 *   Search              → GET /api/chat/instrument-search (useInstrumentSearch)
 *   Stock
 *     Key figures, quarterly results, shareholding
 *                       → POST /api/copilot/widgets/company_financials
 *     Price, 52-week range, 200-day average
 *                       → GET /api/research/chart-live/<symbol>/ohlcv
 *     Scores, technicals, risk, peers (the Copilot's card)
 *                       → GET /api/move-odds/stocks/<symbol>/card
 *     Market backdrop   → GET /api/stock/<symbol>/why
 *     Corporate actions → GET /api/markets/corporate-actions?q=<symbol>
 *     Filings           → GET /api/filings/feed?symbol=<symbol>
 *   Mutual fund
 *     NAV               → GET /api/mf/lookup
 *     Returns, risk, rank, peers
 *                       → GET /api/portfolio/holding-detail/<isin>
 *     Size, cost, managers, holdings
 *                       → GET /api/mf/holdings
 *
 * The blocks added for the last two groups live in ../research.
 */
import { useMemo, useState, type ReactNode } from "react";
import { useCorporateActions } from "@/hooks/use-markets";
import { useDebounce } from "@/hooks/use-debounce";
import { useInstrumentSearch, type FundHit, type StockHit } from "@/hooks/use-instrument-search";
import type { CorpAction } from "@/services/contracts/markets.contract";
import {
  Btn, DataTable, EmptyBlock, LoadingBlock, NotConnected, Pill, Section, Tiles, fmtNum, fmtPct,
  type Column,
} from "../../components/ui";
import { FundHouseIcon, StockIcon } from "../../components/EntityIcon";
import { useCopilotShell } from "../../lib/shell-context";
import { FundFacts, FundHoldings, FundManagers, FundReturns, type FundRef } from "../research/FundBlocks";
import { NotAvailable, inWords, orNA } from "../research/parts";
import { StockBackdrop, StockCard, StockPrice } from "../research/StockBlocks";
import { actionLabel } from "./ActionsTab";
import { FilingsFeed } from "./FilingsFeed";
import { dayLabel, fmtCrCompact, fmtCrPlain, fmtMultiple, isoDay, titleCase } from "./format";
import { isHeld, useCompanyNumbers, useHeldKeys, type HoldingRow, type QuarterRow } from "./hooks";
import { LoadError, NameCell, Signed, TabBar, type TabItem } from "./parts";

export type InstrumentKind = "stock" | "fund";
export type PickedInstrument = { kind: "stock"; hit: StockHit } | { kind: "fund"; hit: FundHit };

// ── search ───────────────────────────────────────────────────────────────

function isStockHit(x: unknown): x is StockHit {
  if (!x || typeof x !== "object") return false;
  const h = x as Partial<StockHit>;
  return typeof h.symbol === "string" && h.symbol !== "" && typeof h.name === "string" && h.name !== "";
}

function isFundHit(x: unknown): x is FundHit {
  if (!x || typeof x !== "object") return false;
  const h = x as Partial<FundHit>;
  return typeof h.name === "string" && h.name !== "";
}

/** Typeahead over stocks and mutual funds. `only` narrows the results to one kind. */
export function InstrumentSearch({ only, onPick }: { only?: InstrumentKind; onPick: (p: PickedInstrument) => void }) {
  const [term, setTerm] = useState("");
  const debounced = useDebounce(term, 220);
  const search = useInstrumentSearch(debounced);
  const active = debounced.trim().length >= 2 && term.trim().length >= 2;

  const results = useMemo<PickedInstrument[]>(() => {
    // useInstrumentSearch returns the body as it arrived, so check its shape here.
    const stocks: unknown[] = Array.isArray(search.data?.stocks) ? search.data.stocks : [];
    const funds: unknown[] = Array.isArray(search.data?.funds) ? search.data.funds : [];
    const out: PickedInstrument[] = [];
    if (only !== "fund") {
      for (const hit of stocks) if (isStockHit(hit)) out.push({ kind: "stock", hit });
    }
    if (only !== "stock") {
      for (const hit of funds) if (isFundHit(hit)) out.push({ kind: "fund", hit });
    }
    return out;
  }, [search.data, only]);

  const pick = (p: PickedInstrument) => {
    setTerm("");
    onPick(p);
  };

  return (
    <div className="flex min-w-0 flex-col" style={{ flex: "1 1 280px", gap: 8 }}>
      <label htmlFor="research-search" className="sr-only">Search any NSE/BSE stock or mutual fund</label>
      <div className="cp-card flex items-center" style={{ gap: 10, padding: "11px 14px", borderRadius: 12, borderColor: "var(--line-2)" }}>
        <span style={{ color: "var(--cp-ink-3)" }} aria-hidden>⌕</span>
        <input
          id="research-search"
          data-testid="research-search"
          type="search"
          autoComplete="off"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder={only === "fund" ? "Search any mutual fund" : only === "stock" ? "Search any NSE/BSE stock" : "Search any NSE/BSE stock or mutual fund"}
          style={{ flex: 1, minWidth: 0, border: 0, outline: "none", background: "none", fontSize: 14, color: "var(--cp-ink)", fontFamily: "var(--sans)" }}
        />
      </div>

      {active && (
        search.isError ? (
          <LoadError title="Search didn’t work" error={search.error} onRetry={() => search.refetch()} />
        ) : search.isPending ? (
          <LoadingBlock label="Searching" rows={2} />
        ) : results.length === 0 ? (
          <div className="cp-card" style={{ padding: "12px 14px", fontSize: 13, color: "var(--cp-ink-3)" }} data-testid="research-search-empty">
            No {only === "fund" ? "funds" : only === "stock" ? "stocks" : "stocks or funds"} match “{debounced.trim()}”. Try a different name.
          </div>
        ) : (
          <ul className="cp-card m-0 flex flex-col" style={{ padding: 4, listStyle: "none" }} data-testid="research-search-results">
            {results.map((p) => {
              const name = p.hit.name;
              const sub = p.kind === "stock"
                ? [p.hit.symbol, p.hit.sector].filter(Boolean).join(" · ")
                : [p.hit.amc, p.hit.category].filter(Boolean).join(" · ");
              return (
                <li key={`${p.kind}-${p.kind === "stock" ? p.hit.symbol : p.hit.scheme_code ?? name}`}>
                  <button
                    type="button"
                    data-testid="research-search-result"
                    onClick={() => pick(p)}
                    className="cp-row-link flex w-full items-center"
                    style={{ gap: 10, padding: "9px 10px", border: 0, borderRadius: 10, background: "transparent", textAlign: "left", color: "var(--cp-ink)", fontFamily: "var(--sans)" }}
                  >
                    {p.kind === "stock"
                      ? <StockIcon symbol={p.hit.symbol} name={name} size={26} />
                      : <FundHouseIcon name={p.hit.amc || name} size={26} />}
                    <span className="flex min-w-0 flex-col" style={{ flex: 1, gap: 2 }}>
                      <span style={{ fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</span>
                      {sub && <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sub}</span>}
                    </span>
                    <Pill tone={p.kind === "stock" ? "indigo" : "amber"}>{p.kind === "stock" ? "Stock" : "Fund"}</Pill>
                  </button>
                </li>
              );
            })}
          </ul>
        )
      )}
    </div>
  );
}

// ── shared entity pieces ─────────────────────────────────────────────────

function EntityCard({ icon, crumb, name, meta, held, onAsk, onClear }: {
  /** The company's icon for a stock, the fund house's for a scheme. */
  icon: ReactNode;
  crumb: string;
  name: string;
  meta: string;
  held?: boolean;
  onAsk: () => void;
  onClear: () => void;
}) {
  const { mobile } = useCopilotShell();
  return (
    <div className="cp-card-raised flex flex-wrap justify-between" style={{ gap: 12, padding: 18 }} data-testid="research-entity">
      <div className="flex min-w-0 items-start" style={{ gap: 14, flex: "1 1 320px" }}>
        <span data-testid="research-entity-icon" style={{ flex: "none", paddingTop: 2 }}>{icon}</span>
        <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>{crumb}</span>
          <span data-testid="research-entity-name" style={{ fontFamily: "var(--display)", fontSize: mobile ? 26 : 32, lineHeight: 1.1, letterSpacing: "-0.015em", overflowWrap: "anywhere" }}>{name}</span>
          <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <span className="cp-eyebrow" data-testid="research-entity-meta">{meta}</span>
            {held && <Pill tone="mint">You hold this</Pill>}
          </span>
        </div>
      </div>
      <div className="flex flex-wrap items-start" style={{ gap: 6 }}>
        <Btn variant="ghost" onClick={onClear} data-testid="research-entity-clear">Change</Btn>
        <Btn variant="primary" onClick={onAsk} data-testid="research-entity-ask">Ask Copilot ›</Btn>
      </div>
    </div>
  );
}

/** Question rows that hand off to the Copilot, each built around the picked name. */
function AskList({ title, items }: { title: string; items: Array<{ label: string; query: string }> }) {
  const { ask } = useCopilotShell();
  return (
    <div className="cp-card flex flex-col" style={{ gap: 10, padding: "16px 18px" }} data-testid="research-asks">
      <span className="cp-eyebrow">{title}</span>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,240px),1fr))", gap: 8 }}>
        {items.map((it) => (
          <button
            key={it.label}
            type="button"
            data-testid="research-ask"
            onClick={() => ask(it.query)}
            className="cp-chip flex justify-between"
            style={{ gap: 10, borderRadius: 10, padding: "9px 12px" }}
          >
            <span>{it.label}</span>
            <span style={{ color: "var(--cp-ink-3)" }} aria-hidden>›</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── stock ────────────────────────────────────────────────────────────────

type StockTab = "overview" | "scores" | "shareholding" | "actions" | "filings";

const STOCK_TABS: TabItem<StockTab>[] = [
  { key: "overview", label: "Overview" },
  { key: "scores", label: "Scores and technicals" },
  { key: "shareholding", label: "Shareholding" },
  { key: "actions", label: "Corporate actions" },
  { key: "filings", label: "Filings" },
];

export function StockResearch({ stock, onClear }: { stock: StockHit; onClear: () => void }) {
  const { ask } = useCopilotShell();
  const [tab, setTab] = useState<StockTab>("overview");
  const held = useHeldKeys();
  const name = stock.name;

  return (
    <>
      <EntityCard
        icon={<StockIcon symbol={stock.symbol} name={name} size={44} />}
        crumb={`Stocks${stock.sector ? ` / ${stock.sector}` : ""}`}
        name={name}
        meta={stock.symbol}
        held={isHeld(held.data, stock.symbol, name)}
        onAsk={() => ask(`Tell me about ${name}`)}
        onClear={onClear}
      />

      <TabBar tabs={STOCK_TABS} value={tab} onChange={setTab} label={`${name} sections`} idPrefix="research-stock-tab" />

      {tab === "overview" && (
        <>
          <StockPrice symbol={stock.symbol} name={name} />
          <StockNumbers symbol={stock.symbol} />
          <AskList
            title={`Ask about ${name}`}
            items={[
              { label: "Full overview", query: `Tell me about ${name}` },
              { label: "Worth buying now?", query: `Should I buy ${name}?` },
              { label: "Track record", query: `How has ${name} performed?` },
              { label: "What changed in the latest quarterly results?", query: `What changed in the latest quarterly results of ${name}?` },
              { label: "Compare with its closest peers", query: `Compare ${name} with its closest peers` },
              { label: "How would it fit my portfolio?", query: `How would adding ${name} change my portfolio’s sector mix and risk?` },
            ]}
          />
          <NotConnected
            testId="research-stock-nc"
            title="Some parts of the stock page are not connected yet"
            body={`Annual statements, a fair-value read against ${name}’s own history, bulk and block deals, and what a purchase would do to your portfolio have no source on this page yet, so they are not shown.`}
            needs={[
              "Annual profit and loss, balance sheet, cash flow and efficiency ratios: only quarterly revenue, operating profit, net profit and EPS are stored; no route returns annual statements",
              "ROE, ROCE, debt to equity, P/B and market cap: the feature store carries the fields but does not fill them, so the key-figure tiles read “Not available” until it does",
              "Fair value against the stock’s own P/E history: the feature history is read by daas_client.get_stock_features_history but no route returns it",
              "Health, add and exit scores, the SWOT read and the pre-buy checks for a stock: no endpoint",
              "Pivot levels and the full moving-average and oscillator set for any symbol: /api/research/chart/{symbol}/indicators only covers the frozen snapshot’s symbols",
              "Bulk and block deals for a symbol: the NSE feeds are ingested (bulk_deals, block_deals) but no route returns them",
              "Portfolio fit of a purchase (sector weights, overlap, volatility): POST /api/intelligence/simulate only models removing funds",
              "A live intraday price: the price block is end of day",
              "A 200-day average across the whole chart: it needs daily prices going back 200 sessions before the first one shown",
            ]}
            action={<Btn variant="primary" onClick={() => ask(`Tell me about ${name}`)}>Research {name} in Copilot ›</Btn>}
          />
        </>
      )}
      {tab === "scores" && (
        <>
          <StockCard symbol={stock.symbol} name={name} />
          <StockBackdrop symbol={stock.symbol} />
        </>
      )}
      {tab === "shareholding" && <StockShareholding symbol={stock.symbol} />}
      {tab === "actions" && <StockActions symbol={stock.symbol} />}
      {tab === "filings" && <FilingsFeed symbol={stock.symbol} name={name} />}
    </>
  );
}

function StockNumbers({ symbol }: { symbol: string }) {
  const q = useCompanyNumbers(symbol);

  if (q.isPending) return <LoadingBlock label="Loading reported numbers" rows={5} />;
  if (q.isError) return <LoadError title="Reported numbers didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const { quarters, features: f } = q.data;
  if (quarters.length === 0 && !f) {
    return (
      <EmptyBlock
        title={`No reported numbers for ${symbol} yet`}
        body="Quarterly results and valuation figures appear once the data platform has this company’s exchange filings."
      />
    );
  }

  const columns: Column<QuarterRow>[] = [
    { key: "q", header: "Quarter", width: "minmax(0,1.2fr)", render: (r) => <NameCell name={r.quarter ?? dayLabel(r.period_end, { year: true })} /> },
    { key: "rev", header: "Revenue", align: "right", num: true, render: (r) => orNA(r.revenue_cr, fmtCrPlain) },
    { key: "ebitda", header: "EBITDA", align: "right", num: true, render: (r) => orNA(r.ebitda_cr, fmtCrPlain) },
    { key: "margin", header: "EBITDA margin", align: "right", num: true, render: (r) => orNA(r.ebitda_margin_pct, (n) => fmtPct(n)) },
    { key: "pat", header: "Net profit", align: "right", num: true, render: (r) => orNA(r.pat_cr, fmtCrPlain) },
    { key: "eps", header: "EPS ₹", align: "right", num: true, render: (r) => orNA(r.eps_basic, (n) => fmtNum(n, 2)) },
    {
      key: "yoy", header: "Profit YoY", align: "right", num: true,
      render: (r) => (r.pat_yoy_pct == null ? <NotAvailable /> : <Signed value={r.pat_yoy_pct}>{fmtPct(r.pat_yoy_pct, { signed: true })}</Signed>),
    },
  ];

  // A figure the data does not carry keeps its tile and says so; it is never hidden or shown as 0.
  const figures: Array<{ label: string; value: number | null | undefined }> = [
    { label: "market cap", value: f?.market_cap_cr },
    { label: "P/E", value: f?.pe_ttm },
    { label: "P/B", value: f?.pb },
    { label: "ROE", value: f?.roe_pct },
    { label: "debt to equity", value: f?.debt_to_equity },
  ];
  const missing = figures.filter((x) => x.value == null || !Number.isFinite(x.value)).map((x) => x.label);

  return (
    <>
      <div data-testid="research-stock-metrics" className="flex flex-col" style={{ gap: 8 }}>
        <Tiles
          min={140}
          items={[
            {
              k: "Market cap",
              v: <span data-testid="research-stock-mcap">{orNA(f?.market_cap_cr, fmtCrCompact)}</span>,
              s: f?.market_cap_bucket ? titleCase(f.market_cap_bucket) : undefined,
            },
            { k: "P/E", v: <span data-testid="research-stock-pe">{orNA(f?.pe_ttm, (n) => fmtMultiple(n))}</span>, s: "Trailing 12 months" },
            { k: "P/B", v: <span data-testid="research-stock-pb">{orNA(f?.pb, (n) => fmtMultiple(n))}</span> },
            { k: "ROE", v: <span data-testid="research-stock-roe">{orNA(f?.roe_pct, (n) => fmtPct(n))}</span> },
            { k: "Debt / equity", v: <span data-testid="research-stock-de">{orNA(f?.debt_to_equity, (n) => fmtNum(n, 2))}</span> },
          ]}
        />
        {missing.length > 0 && (
          <span data-testid="research-stock-metrics-missing" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>
            Not in the latest data for {symbol}: {inWords(missing)}.
          </span>
        )}
      </div>
      <Section title="Quarterly results · ₹ Cr" note="Reported · from exchange filings" flush>
        <div data-testid="research-stock-quarters">
          <DataTable
            columns={columns}
            rows={quarters}
            rowKey={(r, i) => r.period_end ?? String(i)}
            minWidth={720}
            empty="No quarterly results are on file for this company yet."
          />
        </div>
      </Section>
    </>
  );
}

interface HolderLine {
  holder: string;
  values: Array<number | null | undefined>;
}

function StockShareholding({ symbol }: { symbol: string }) {
  const q = useCompanyNumbers(symbol);

  if (q.isPending) return <LoadingBlock label="Loading shareholding" rows={4} />;
  if (q.isError) return <LoadError title="Shareholding didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  // The endpoint returns the newest quarter first; read left to right, oldest first.
  const periods = [...q.data.holdings].reverse();
  if (periods.length === 0) {
    return (
      <EmptyBlock
        title={`No shareholding pattern for ${symbol} yet`}
        body="It appears once the company’s quarterly shareholding filing has been processed."
      />
    );
  }

  const line = (holder: string, pick: (h: HoldingRow) => number | null | undefined): HolderLine => ({ holder, values: periods.map(pick) });
  const rows: HolderLine[] = [
    line("Promoter", (h) => h.promoter_pct),
    line("FII", (h) => h.fii_pct),
    line("DII", (h) => h.dii_pct),
    line("Mutual funds", (h) => h.mf_pct),
    line("Public", (h) => h.public_pct),
    line("Promoter shares pledged", (h) => h.promoter_pledged_pct),
  ];

  const columns: Column<HolderLine>[] = [
    { key: "holder", header: "Holder", width: "minmax(0,1.7fr)", render: (r) => <NameCell name={r.holder} /> },
    ...periods.map((p, i): Column<HolderLine> => ({
      key: p.period_end ?? String(i),
      header: p.period ?? dayLabel(p.period_end, { year: true }),
      align: "right",
      num: true,
      render: (r) => orNA(r.values[i], (n) => fmtPct(n, { digits: 2 })),
    })),
  ];

  return (
    <Section title="Shareholding · % of equity" note="Reported quarterly" flush>
      <div data-testid="research-stock-shareholding">
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.holder} minWidth={160 + periods.length * 100} />
      </div>
    </Section>
  );
}

function StockActions({ symbol }: { symbol: string }) {
  const range = useMemo(() => ({ from: isoDay(-3 * 365), to: isoDay(90) }), []);
  const q = useCorporateActions({ ...range, q: symbol });

  if (q.isPending) return <LoadingBlock label="Loading corporate actions" rows={4} />;
  if (q.isError) return <LoadError title="Corporate actions didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  // The calendar's search is a substring match, so keep only this exact symbol; newest first.
  const rows = q.data.actions
    .filter((a) => a.symbol.toUpperCase() === symbol.toUpperCase())
    .sort((a, b) => (b.ex_date ?? "").localeCompare(a.ex_date ?? ""));

  const columns: Column<CorpAction>[] = [
    { key: "ex", header: "Ex-date", width: "minmax(0,1.2fr)", render: (a) => <NameCell name={dayLabel(a.ex_date, { year: true })} /> },
    { key: "action", header: "Action", render: (a) => actionLabel(a.action_type) },
    { key: "details", header: "Details", align: "right", num: true, render: (a) => a.value_label ?? "—" },
  ];

  return (
    <Section title={`Corporate actions · ${symbol}`} note="Last 3 years and the next 90 days · source: NSE" flush>
      <div data-testid="research-stock-actions">
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(a, i) => `${a.action_type}-${a.ex_date ?? ""}-${i}`}
          minWidth={360}
          empty={`No corporate actions for ${symbol} in this window.`}
        />
      </div>
    </Section>
  );
}

// ── mutual fund ──────────────────────────────────────────────────────────

type FundTab = "overview" | "holdings" | "managers";

const FUND_TABS: TabItem<FundTab>[] = [
  { key: "overview", label: "Overview" },
  { key: "holdings", label: "Holdings" },
  { key: "managers", label: "Managers" },
];

export function FundResearch({ fund, onClear }: { fund: FundHit; onClear: () => void }) {
  const { ask } = useCopilotShell();
  const [tab, setTab] = useState<FundTab>("overview");
  const name = fund.name;
  // The AMFI code makes the Copilot resolve the scheme exactly instead of by name.
  const tag = fund.scheme_code ? ` (${fund.scheme_code})` : "";
  const overview = `Show the overview of ${name}${tag}`;
  const ref: FundRef = { name, schemeCode: fund.scheme_code };

  return (
    <>
      <EntityCard
        icon={<FundHouseIcon name={fund.amc || name} size={44} />}
        crumb={`Funds${fund.category ? ` / ${fund.category}` : ""}`}
        name={name}
        meta={[fund.scheme_code ? `AMFI ${fund.scheme_code}` : null, fund.amc].filter(Boolean).join(" · ") || "Mutual fund"}
        onAsk={() => ask(overview)}
        onClear={onClear}
      />

      <TabBar tabs={FUND_TABS} value={tab} onChange={setTab} label={`${name} sections`} idPrefix="research-fund-tab" />

      {tab === "overview" && (
        <>
          <FundFacts fund={ref} />
          <FundReturns fund={ref} />
          <AskList
            title={`Ask about ${name}`}
            items={[
              { label: "Overview", query: overview },
              { label: "Returns", query: `Show the returns of ${name}${tag}` },
              { label: "Holdings", query: `Show the holdings of ${name}${tag}` },
              { label: "Against its peers", query: `Compare ${name}${tag} with its peers` },
            ]}
          />
          <NotConnected
            testId="research-fund-nc"
            title="Some parts of the fund page are not connected yet"
            body={`A NAV chart, returns against the benchmark, the fund’s score, its exit load and its overlap with the funds you hold have no source on this page yet, so they are not shown. The Copilot’s fund card for ${name} covers more in the thread.`}
            needs={[
              "NAV history for a chart: daas_client.get_mf_nav_history reads it but no route returns it",
              "Returns against the benchmark, and 5-year and longer returns from the data platform: /api/portfolio/holding-detail/{isin} stops at 3 years and has no benchmark column",
              "The fund’s score: GET /api/funds/{isin}/v3-score looks the scheme up in the Mongo mf_master collection and does not find the schemes this page searches; the full breakdown at /api/intelligence/v3-score/{id} is admin-only",
              "Rank in category and ranked peers: shown when /api/portfolio/holding-detail/{isin} returns them; the data platform has to compute a category rank for the scheme first",
              "Exit load and beta: in no response used here",
              "Overlap between this fund and the funds you hold: /api/portfolio/exposure/fund-overlap/matrix only compares funds already held; no route takes a candidate scheme",
              "The Copilot’s fund card as a read: stocks have GET /api/move-odds/stocks/{symbol}/card, funds have no equivalent over instrument_research.get_mf_research",
            ]}
            action={<Btn variant="primary" onClick={() => ask(overview)}>Research {name} in Copilot ›</Btn>}
          />
        </>
      )}
      {tab === "holdings" && <FundHoldings fund={ref} />}
      {tab === "managers" && <FundManagers fund={ref} />}
    </>
  );
}
