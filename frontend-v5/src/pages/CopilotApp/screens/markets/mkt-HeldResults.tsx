/**
 * Earnings Tracker → "Your holdings · results". The user's directly held
 * stocks joined with two existing feeds:
 *
 *   result dates       GET /api/market/events (the event calendar, next 14 days)
 *   this quarter       GET /api/markets/earnings/companies (reported / not yet,
 *                      with growth against the year-ago quarter)
 *   the stocks         GET /api/portfolio/holdings-enriched
 *
 * Stocks held only through mutual funds or ETFs are not included, and the block
 * says so: no endpoint returns a fund's underlying stocks with exchange symbols.
 */
import type { ReactNode } from "react";
import { DataTable, LoadingBlock, NotConnected, Pill, fmtNum, fmtPct, type Column, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { dayLabel, fmtCr } from "./format";
import {
  RESULTS_WINDOW_DAYS, findStock, indexStocks, useDirectStocks, useHeldResults, useResultsCalendar,
  type CalendarEvent, type DirectStock, type HeldResult,
} from "./hooks";
import { CompanyCell, LoadError, Signed, SourceLine } from "./parts";

interface HeldDate {
  stock: DirectStock;
  event: CalendarEvent;
}

function resultStatus(r: HeldResult): { label: string; tone: Tone } {
  if (!r.company.declared) return { label: "Not yet reported", tone: "ink" };
  if (r.company.profit_grew === true) return { label: "Reported · profit grew", tone: "mint" };
  if (r.company.profit_grew === false) return { label: "Reported · profit shrank", tone: "danger" };
  return { label: "Reported · no year-ago quarter", tone: "ink" };
}

function plural(n: number, one: string, many: string): string {
  return `${fmtNum(n)} ${n === 1 ? one : many}`;
}

export function HeldResultsBlock({ index, quarter, quarterLabel, sectors }: {
  index: string;
  /** Quarter end (YYYY-MM-DD) the tab is showing; undefined = the latest. */
  quarter?: string;
  quarterLabel: string;
  /** Sector names of the index, from the earnings response. */
  sectors: string[];
}) {
  const direct = useDirectStocks();
  const stocks = direct.data?.stocks ?? [];
  const calendar = useResultsCalendar(stocks.length > 0);
  const results = useHeldResults({ index, quarter, sectors, stocks, enabled: sectors.length > 0 });
  const { ask } = useCopilotShell();

  const frame = (children: ReactNode) => (
    <section className="cp-card flex min-w-0 flex-col" style={{ gap: 16, padding: "16px 18px" }} data-testid="markets-earnings-holdings">
      <span className="cp-eyebrow">Your holdings · results</span>
      {children}
    </section>
  );

  if (direct.isPending) return frame(<LoadingBlock label="Loading your holdings" />);
  if (direct.isError || !direct.data) {
    return frame(<LoadError title="Your holdings didn’t load, so results could not be matched to them" error={direct.error} onRetry={() => direct.refetch()} />);
  }

  const { fundCount } = direct.data;
  const scope = (
    <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }} data-testid="markets-earnings-holdings-scope">
      Only stocks you hold directly are checked.
      {fundCount > 0 && ` Stocks held through your ${plural(fundCount, "mutual fund or ETF", "mutual funds and ETFs")} are not included.`}
    </span>
  );

  if (stocks.length === 0) {
    return frame(
      <>
        <span style={{ fontSize: 14, color: "var(--cp-ink-2)" }} data-testid="markets-earnings-holdings-none">
          You hold no stocks directly, so there are no result dates to show for your portfolio.
        </span>
        {scope}
      </>,
    );
  }

  // ── result dates in the next two weeks ──
  const held = indexStocks(stocks);
  const dates: HeldDate[] = calendar.events.flatMap((event) => {
    const stock = findStock(held, event.symbol, event.company_name);
    return stock ? [{ stock, event }] : [];
  });
  const dateColumns: Column<HeldDate>[] = [
    {
      key: "company", header: "Company", width: "minmax(0,1.9fr)",
      render: (d) => <CompanyCell symbol={d.stock.symbol ?? d.event.symbol} name={d.event.company_name ?? d.stock.name} />,
    },
    { key: "date", header: "Results date", render: (d) => dayLabel(d.event.event_date, { year: true }) },
    { key: "period", header: "Period", render: (d) => d.event.period ?? "—" },
    { key: "purpose", header: "Notice", width: "minmax(0,1.6fr)", render: (d) => <span title={d.event.purpose ?? undefined}>{d.event.purpose ?? "—"}</span> },
  ];
  const windowLabel = `${dayLabel(calendar.from)} – ${dayLabel(calendar.to, { year: true })}`;
  const calendarSources = [...new Set(calendar.events.flatMap((e) => (e.calendar_source ? [e.calendar_source] : [])))];

  let datesBlock: ReactNode;
  if (calendar.status === "loading") {
    datesBlock = <LoadingBlock label="Loading the results calendar" rows={2} />;
  } else if (calendar.status === "error") {
    datesBlock = <LoadError title="The results calendar didn’t load" error={calendar.error} onRetry={calendar.refetch} />;
  } else if (calendar.status === "unavailable") {
    datesBlock = (
      <NotConnected
        testId="markets-earnings-calendar-nc"
        title="Result dates for your stocks"
        body="The results calendar could not be read just now, so upcoming result dates for your stocks are not shown."
        needs={[
          "GET /api/market/events answers with an error note instead of events: it reads the event calendar from the app database, where that table does not exist",
          "Serve the calendar through the data platform’s events calendar endpoint, with a from / to date range, so a window is one request instead of one per day",
        ]}
      />
    );
  } else if (dates.length === 0) {
    datesBlock = (
      <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }} data-testid="markets-earnings-dates-none">
        None of your {plural(stocks.length, "directly held stock", "directly held stocks")} has a results date in the calendar for {windowLabel}.
      </span>
    );
  } else {
    datesBlock = (
      <div className="flex flex-col" style={{ gap: 8 }}>
        <span style={{ fontSize: 14, color: "var(--cp-ink)" }} data-testid="markets-earnings-dates-line">
          {plural(dates.length, "of your stocks reports", "of your stocks report")} results in the next {RESULTS_WINDOW_DAYS} days.
        </span>
        <div className="cp-card" data-testid="markets-earnings-dates">
          <DataTable
            columns={dateColumns}
            rows={dates}
            rowKey={(d, i) => `${d.event.symbol}-${d.event.event_date ?? ""}-${i}`}
            onRowClick={(d) => ask(`${d.event.company_name ?? d.stock.name} reports results on ${dayLabel(d.event.event_date, { year: true })}. What did it report last quarter?`)}
            minWidth={560}
          />
        </div>
        <SourceLine testId="markets-earnings-dates-source" source={calendarSources} note={`Calendar window ${windowLabel}`} />
      </div>
    );
  }

  // ── this quarter so far ──
  const reported = results.rows.filter((r) => r.company.declared).length;
  const quarterColumns: Column<HeldResult>[] = [
    {
      key: "company", header: "Company", width: "minmax(0,1.9fr)",
      render: (r) => <CompanyCell symbol={r.company.symbol} name={r.company.name} />,
    },
    {
      key: "status", header: "Status", width: "minmax(0,1.5fr)",
      render: (r) => {
        const s = resultStatus(r);
        return <Pill tone={s.tone}>{s.label}</Pill>;
      },
    },
    { key: "sales", header: "Sales YoY", align: "right", num: true, render: (r) => <Signed value={r.company.sales_yoy}>{fmtPct(r.company.sales_yoy, { signed: true })}</Signed> },
    { key: "profit", header: "Profit YoY", align: "right", num: true, render: (r) => <Signed value={r.company.profit_yoy}>{fmtPct(r.company.profit_yoy, { signed: true })}</Signed> },
    { key: "pat", header: "Net profit", align: "right", num: true, render: (r) => fmtCr(r.company.pat_cr) },
  ];

  let quarterBlock: ReactNode = null;
  if (sectors.length > 0) {
    if (results.status === "loading") {
      quarterBlock = <LoadingBlock label="Checking your stocks against this quarter’s results" rows={2} />;
    } else if (results.status === "error") {
      quarterBlock = <LoadError title="This quarter’s results could not be matched to your stocks" error={results.error} onRetry={results.refetch} />;
    } else {
      quarterBlock = (
        <div className="flex flex-col" style={{ gap: 8 }}>
          <span style={{ fontSize: 14, color: "var(--cp-ink)" }} data-testid="markets-earnings-holdings-line">
            {results.rows.length === 0
              ? `None of your ${plural(stocks.length, "directly held stock", "directly held stocks")} is in the ${index}.`
              : `${fmtNum(results.rows.length)} of your ${plural(stocks.length, "directly held stock", "directly held stocks")} ${results.rows.length === 1 ? "is" : "are"} in the ${index}: `
                + `${fmtNum(reported)} ${reported === 1 ? "has" : "have"} reported ${quarterLabel} and ${fmtNum(results.rows.length - reported)} ${results.rows.length - reported === 1 ? "has" : "have"} not yet.`}
          </span>
          {results.rows.length > 0 && (
            <div className="cp-card" data-testid="markets-earnings-holdings-quarter">
              <DataTable
                columns={quarterColumns}
                rows={results.rows}
                rowKey={(r) => r.company.symbol}
                onRowClick={(r) => ask(r.company.declared
                  ? `Walk me through ${r.company.name}’s ${quarterLabel} results.`
                  : `${r.company.name} has not reported ${quarterLabel} yet. What did it report last quarter?`)}
                minWidth={640}
              />
            </div>
          )}
          {results.outside.length > 0 && (
            <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }} data-testid="markets-earnings-holdings-outside">
              {plural(results.outside.length, "of your stocks is", "of your stocks are")} not in the {index}. Pick a wider index above to check {results.outside.length === 1 ? "it" : "them"}.
            </span>
          )}
        </div>
      );
    }
  }

  return frame(
    <>
      {datesBlock}
      {quarterBlock}
      {scope}
    </>,
  );
}
