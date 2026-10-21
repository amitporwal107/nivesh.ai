/**
 * Corporate Actions → "Your holdings · corporate actions". The calendar for
 * the chosen dates (GET /api/markets/corporate-actions, every action type)
 * narrowed to the stocks the user holds directly (GET
 * /api/portfolio/holdings-enriched).
 *
 * Stocks held only through mutual funds or ETFs are not included, and the block
 * says so. A dividend's rupee amount is per-share dividend × the shares in the
 * user's latest holdings; the note under the table says what that assumes.
 */
import type { ReactNode } from "react";
import { DataTable, LoadingBlock, fmtINR, fmtNum, type Column } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { actionLabel, dayLabel } from "./format";
import { heldActions, useActionCalendar, useDirectStocks, type HeldAction } from "./hooks";
import { CompanyCell, LoadError } from "./parts";

/** Rupees a dividend row comes to on the shares held now; null when either figure is missing. */
function dividendOnShares(h: HeldAction): number | null {
  const perShare = h.action.dividend_amount;
  const shares = h.stock.quantity;
  if (h.action.action_type !== "DIVIDEND" || perShare == null || shares == null || shares <= 0) return null;
  return perShare * shares;
}

export function HeldActionsBlock({ from, to }: { from: string; to: string }) {
  const direct = useDirectStocks();
  // Every action type for the dates, whatever filter the table below has on.
  const calendar = useActionCalendar({ from, to });
  const { ask } = useCopilotShell();

  const frame = (children: ReactNode) => (
    <section className="cp-card flex min-w-0 flex-col" style={{ gap: 12, padding: "16px 18px" }} data-testid="markets-actions-holdings">
      <span className="cp-eyebrow">Your holdings · corporate actions</span>
      {children}
    </section>
  );

  if (direct.isPending || calendar.isPending) return frame(<LoadingBlock label="Checking your holdings against the calendar" rows={2} />);
  if (direct.isError || !direct.data) {
    return frame(<LoadError title="Your holdings didn’t load, so the calendar could not be matched to them" error={direct.error} onRetry={() => direct.refetch()} />);
  }
  if (calendar.isError) {
    return frame(<LoadError title="The calendar didn’t load, so your holdings could not be checked" error={calendar.error} onRetry={() => calendar.refetch()} />);
  }

  const { stocks, fundCount } = direct.data;
  const scope = (
    <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }} data-testid="markets-actions-holdings-scope">
      Only stocks you hold directly are checked.
      {fundCount > 0 && ` Stocks held through your ${fmtNum(fundCount)} ${fundCount === 1 ? "mutual fund or ETF" : "mutual funds and ETFs"} are not included.`}
    </span>
  );
  if (stocks.length === 0) {
    return frame(
      <>
        <span style={{ fontSize: 14, color: "var(--cp-ink-2)" }} data-testid="markets-actions-holdings-none">
          You hold no stocks directly, so no corporate action applies to your portfolio here.
        </span>
        {scope}
      </>,
    );
  }

  const rows = heldActions(calendar.data.actions, stocks);
  const total = Object.values(calendar.data.type_counts).reduce((a, b) => a + b, 0);
  const listed = calendar.data.actions.length;
  const windowWords = `from ${dayLabel(calendar.data.from ?? from)} to ${dayLabel(calendar.data.to ?? to, { year: true })}`;
  const stockWords = `${fmtNum(stocks.length)} directly held ${stocks.length === 1 ? "stock" : "stocks"}`;

  const columns: Column<HeldAction>[] = [
    {
      key: "company", header: "Company", width: "minmax(0,1.9fr)",
      render: (h) => <CompanyCell symbol={h.action.symbol} name={h.action.name} />,
    },
    { key: "ex", header: "Ex-date", render: (h) => dayLabel(h.action.ex_date, { year: true }) },
    { key: "event", header: "Event", render: (h) => actionLabel(h.action.action_type) },
    { key: "details", header: "Details", align: "right", num: true, render: (h) => h.action.value_label ?? "—" },
    { key: "shares", header: "Your shares", align: "right", num: true, render: (h) => fmtNum(h.stock.quantity) },
    {
      key: "amount", header: "Dividend on them", align: "right", num: true,
      render: (h) => <span data-testid="markets-actions-holdings-amount">{fmtINR(dividendOnShares(h))}</span>,
    },
  ];

  return frame(
    <>
      <span style={{ fontSize: 14, color: "var(--cp-ink)" }} data-testid="markets-actions-holdings-line">
        {rows.length === 0
          ? `None of your ${stockWords} has a corporate action ${windowWords}.`
          : `${fmtNum(rows.length)} corporate ${rows.length === 1 ? "action" : "actions"} on your ${stockWords}, ${windowWords}.`}
      </span>
      {rows.length > 0 && (
        <>
          <div className="cp-card" data-testid="markets-actions-holdings-table">
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(h, i) => `${h.action.symbol}-${h.action.action_type}-${h.action.ex_date ?? ""}-${i}`}
              onRowClick={(h) => ask(
                `What does the ${actionLabel(h.action.action_type).toLowerCase()} from ${h.action.name}`
                + `${h.action.ex_date ? ` with ex-date ${dayLabel(h.action.ex_date, { year: true })}` : ""} mean for me as a shareholder?`,
              )}
              minWidth={700}
            />
          </div>
          {rows.some((h) => dividendOnShares(h) != null) && (
            <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
              Dividend amounts are the per-share dividend times the shares in your latest holdings, before tax. What you receive depends on the shares you hold on the record date.
            </span>
          )}
        </>
      )}
      {total > listed && (
        <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }} data-testid="markets-actions-holdings-partial">
          The calendar returned the first {fmtNum(listed)} of {fmtNum(total)} actions for these dates, so the rest are not checked. Narrow the dates to check them all.
        </span>
      )}
      {scope}
    </>,
  );
}
