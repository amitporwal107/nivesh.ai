/**
 * Trader desk — the broker block. Read-only: nothing here can place an order.
 *
 * Data:
 *   GET /api/broker/accounts      which broker accounts the user has connected (useBrokerAccounts)
 *   GET /api/portfolio/holdings   the delivery holdings a broker read stored (useBrokerHoldings)
 *   GET /api/broker/positions     open positions, read live from each account signed in on the
 *                                 broker's own page (useBrokerPositions)
 *
 * What it shows:
 *   no account            says so, with a link to Broker connections
 *   account, rows stored  the holdings as the broker reported them: quantity, average, last price, P&L, as-of time
 *   account, no rows      says nothing has been read yet
 *   open positions        per account: instrument, product, signed quantity, average, last price and
 *                         the broker's own P&L, with the time of the read; an account that could not
 *                         be read says why and the others are still shown
 *
 * Not connected, in every state: the broker's funds and its day P&L, and a
 * stop or target per position. No route returns them, so the block says so.
 */
import { useState, type ReactNode } from "react";
import {
  Btn, DataTable, EmptyBlock, Footnote, LoadingBlock, NotConnected, Section,
  TONE_COLOR, fmtDate, fmtINR, fmtNum, fmtPct, humaniseTag, signTone,
  type Column,
} from "../../components/ui";
import { BrokerName, StockName } from "../../components/EntityIcon";
import { useCopilotShell } from "../../lib/shell-context";
import { Labeled, QueryProblem, fmtPrice } from "../trading/parts";
import { isForbidden, useBrokerAccounts, type BrokerAccount } from "../trading/queries";
import { fmtStamp, positionRefOf, totalsOf, useBrokerHoldings, useBrokerPositions, type BrokerHolding, type BrokerPosition, type PositionsAccount } from "./broker";

const TITLE = "Broker account · read-only";

const plural = (n: number, one: string, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;

const STATUS_WORDS: Record<string, string> = {
  active: "Connected",
  pending: "Sign-in not finished",
  error: "The last read failed",
};

function accountLine(a: BrokerAccount): string {
  const status = STATUS_WORDS[a.status ?? ""] ?? (a.status ? humaniseTag(a.status) : "Status unknown");
  const read = a.lastSyncAt
    ? `${a.lastSyncCount != null ? `${plural(a.lastSyncCount, "holding")} read` : "Read"} ${fmtStamp(a.lastSyncAt)}`
    : "Nothing read yet";
  return `${status} · ${read}`;
}

/** The latest of a set of ISO timestamps; null when none parses. */
function latest(stamps: Array<string | null>): string | null {
  let best: string | null = null;
  let bestT = -Infinity;
  for (const s of stamps) {
    if (!s) continue;
    const t = new Date(s).getTime();
    if (Number.isFinite(t) && t > bestT) {
      best = s;
      bestT = t;
    }
  }
  return best;
}

function Accounts({ accounts }: { accounts: BrokerAccount[] }) {
  const { go } = useCopilotShell();
  return (
    <div className="flex flex-wrap items-center justify-between" style={{ gap: "10px 16px" }}>
      <div className="flex flex-wrap" style={{ gap: "10px 22px", minWidth: 0 }}>
        {accounts.map((a) => (
          <BrokerName key={a.id} testId="trader-broker-account" name={a.name} sub={accountLine(a)} />
        ))}
      </div>
      <Btn onClick={() => go("page/brokers")}>Broker connections</Btn>
    </div>
  );
}

function HoldingsTable({ rows, accounts }: { rows: BrokerHolding[]; accounts: BrokerAccount[] }) {
  const { ask } = useCopilotShell();
  const nameOf = new Map(accounts.map((a) => [a.id, a.name]));
  const totals = totalsOf(rows);
  const readAt = latest(rows.map((r) => r.readAt));

  const columns: Column<BrokerHolding>[] = [
    { key: "stock", header: "Stock", width: "minmax(0,1.8fr)", render: (r) => <StockName testId="broker-holding-row" symbol={r.symbol} name={r.name} size={24} /> },
    { key: "qty", header: "Qty", num: true, render: (r) => fmtNum(r.qty, Number.isInteger(r.qty) ? 0 : 2) },
    { key: "avg", header: "Average", num: true, render: (r) => fmtPrice(r.avg) },
    { key: "last", header: "Last price", num: true, render: (r) => fmtPrice(r.last) },
    {
      key: "pnl", header: "P&L", num: true, width: "minmax(0,1.3fr)",
      render: (r): ReactNode => (
        <span data-testid="broker-holding-pnl" style={{ color: TONE_COLOR[signTone(r.pnlRs)] }}>
          {fmtINR(r.pnlRs, { signed: true })}{r.pnlPct != null ? ` · ${fmtPct(r.pnlPct, { signed: true })}` : ""}
        </span>
      ),
    },
    { key: "asof", header: "Price as of", num: true, width: "minmax(0,1.2fr)", render: (r) => <span data-testid="broker-holding-asof">{fmtStamp(r.priceAt)}</span> },
  ];
  if (accounts.length > 1) {
    columns.splice(1, 0, { key: "broker", header: "Broker", render: (r) => nameOf.get(r.accountId) ?? (r.broker ? humaniseTag(r.broker) : "—") });
  }

  return (
    <Section
      title="Holdings read from your broker"
      note={<span data-testid="trader-broker-asof">{plural(rows.length, "holding")}{readAt ? ` · read ${fmtStamp(readAt)}` : ""}</span>}
      flush
    >
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        minWidth={accounts.length > 1 ? 860 : 760}
        onRowClick={(r) => ask(`Show the ${r.symbol} chart with support and resistance. My broker account holds ${fmtNum(r.qty, Number.isInteger(r.qty) ? 0 : 2)}${r.avg != null ? ` at an average of ${fmtPrice(r.avg)}` : ""}.`)}
      />
      <div className="flex flex-col" style={{ gap: 6, padding: "10px 16px" }}>
        {totals.priced > 0 && (
          <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>
            Value <span data-testid="broker-holdings-value">{fmtINR(totals.valueRs)}</span>
            {" · "}P&amp;L <span data-testid="broker-holdings-pnl" style={{ color: TONE_COLOR[signTone(totals.pnlRs)] }}>{fmtINR(totals.pnlRs, { signed: true })}</span>
            {totals.priced < rows.length ? ` · ${fmtNum(totals.priced)} of ${fmtNum(rows.length)} priced` : ""}
          </span>
        )}
        <Footnote>
          Delivery holdings. Quantity and average are as your broker reported them when the account was last read, and stay so until it is read again.
          The last price is the latest one stored for the stock; the final column says when it was taken.
          P&amp;L = (last price − average) × quantity. When a broker sends no average, the import estimates one from the broker’s own P&amp;L, so a figure here can differ from the broker’s app.
        </Footnote>
      </div>
    </Section>
  );
}

const PRODUCT_WORDS: Record<string, string> = {
  intraday: "Intraday",
  delivery: "Delivery",
  carryforward: "Carry forward",
  margin: "Margin",
};

/** "27 Oct 2026 future" · "27 Oct 2026 · 25,000 call"; null for a share. */
function contractOf(p: BrokerPosition): string | null {
  if (!p.instrument) return null;
  const expiry = p.expiry ? fmtDate(p.expiry) : null;
  if (p.instrument === "FUT") return [expiry, "future"].filter(Boolean).join(" ");
  const side = p.instrument === "CE" ? "call" : p.instrument === "PE" ? "put" : p.instrument;
  return [expiry, [p.strike != null ? fmtNum(p.strike, Number.isInteger(p.strike) ? 0 : 2) : null, side].filter(Boolean).join(" ")].filter(Boolean).join(" · ");
}

/** What a position row asks the Copilot. A future or an option says which
 *  contract it is and calls an option's average a premium, so that figure is
 *  not read as the share's own price. */
function positionQuestion(p: BrokerPosition): string {
  const qty = fmtNum(Math.abs(p.qty), Number.isInteger(p.qty) ? 0 : 2);
  const held = `${p.qty < 0 ? "a short position of" : "an open position of"} ${qty}`;
  const option = p.instrument === "CE" || p.instrument === "PE";
  const expiry = p.expiry ? ` expiring ${fmtDate(p.expiry)}` : "";
  const strike = option && p.strike != null ? `${fmtNum(p.strike, Number.isInteger(p.strike) ? 0 : 2)} ` : "";
  const contract = option
    ? ` in a ${strike}${p.instrument === "CE" ? "call" : "put"} option${expiry}`
    : p.instrument ? ` in a ${p.instrument === "FUT" ? "future" : p.instrument}${expiry}` : "";
  const avg = p.avg != null
    ? `${contract ? "," : ""} at an average ${option ? "premium " : ""}of ${fmtPrice(p.avg)}`
    : "";
  return `Show the ${p.symbol} chart with support and resistance. My broker account has ${held}${contract}${avg}.`;
}

/** Why one account could not be read, in plain words. The server's own sentence goes to admins only. */
function readFailure(a: PositionsAccount, broker: string): string {
  if (a.errorCode === "BROKER_SESSION_EXPIRED") return `Your ${broker} session has ended. Sign in again from Broker connections to read its positions.`;
  if (a.errorCode === "BROKER_READ_NOT_SUPPORTED") return `Open positions cannot be read from this kind of ${broker} account.`;
  if (a.errorCode === "BROKER_READ_FAILED") return `${broker} did not return its positions. Try again in a little while.`;
  return `The positions of this ${broker} account could not be read.`;
}

type PositionFilter = "all" | "fno" | "intraday";

function AccountPositions({ account, filter }: { account: PositionsAccount; filter: PositionFilter }) {
  const { ask, isAdmin } = useCopilotShell();
  const broker = account.label ?? (account.broker ? humaniseTag(account.broker) : "Broker");
  const rows = account.positions.filter((p) => (filter === "fno" ? p.fno : filter === "intraday" ? p.intraday : true));
  const withPnl = rows.filter((p) => p.pnlRs != null);
  const pnl = withPnl.reduce((sum, p) => sum + (p.pnlRs as number), 0);

  const columns: Column<BrokerPosition>[] = [
    {
      key: "instrument", header: "Instrument", width: "minmax(0,2fr)",
      render: (p) => <StockName testId="broker-position-row" symbol={p.symbol} name={p.name} sub={contractOf(p) ?? p.exchange ?? undefined} size={24} />,
    },
    { key: "product", header: "Held as", render: (p) => (p.product ? PRODUCT_WORDS[p.product] ?? humaniseTag(p.product) : "—") },
    {
      key: "qty", header: "Qty", num: true,
      render: (p) => <span data-testid="broker-position-qty">{p.qty < 0 ? `Short ${fmtNum(-p.qty, Number.isInteger(p.qty) ? 0 : 2)}` : fmtNum(p.qty, Number.isInteger(p.qty) ? 0 : 2)}</span>,
    },
    { key: "avg", header: "Average", num: true, render: (p) => fmtPrice(p.avg) },
    { key: "last", header: "Last price", num: true, render: (p) => (p.last != null ? fmtPrice(p.last) : "Not sent") },
    {
      key: "pnl", header: "P&L", num: true,
      render: (p) => <span data-testid="broker-position-pnl" style={{ color: TONE_COLOR[signTone(p.pnlRs)] }}>{p.pnlRs != null ? fmtINR(p.pnlRs, { signed: true }) : "Not sent"}</span>,
    },
  ];

  return (
    <div data-testid="trader-positions-account" className="flex flex-col" style={{ gap: 8 }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "6px 16px", padding: "0 16px" }}>
        <BrokerName name={broker} sub={account.ok ? `Read ${fmtStamp(account.asOf)}` : "Not read"} size={24} />
        {account.ok && withPnl.length > 0 && (
          <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>
            P&amp;L <span data-testid="broker-positions-pnl" style={{ color: TONE_COLOR[signTone(pnl)] }}>{fmtINR(pnl, { signed: true })}</span>
            {withPnl.length < rows.length ? ` · ${fmtNum(withPnl.length)} of ${fmtNum(rows.length)} positions carry one` : ""}
          </span>
        )}
      </div>
      {!account.ok ? (
        <div data-testid="trader-positions-account-error" role="alert" style={{ padding: "0 16px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {readFailure(account, broker)}
          {isAdmin && account.errorMessage && <span className="cp-mono-note" style={{ display: "block", marginTop: 4, overflowWrap: "anywhere" }}>Server said: {account.errorMessage}</span>}
        </div>
      ) : rows.length === 0 ? (
        <div data-testid="trader-positions-none" style={{ padding: "0 16px", fontSize: 13, color: "var(--cp-ink-3)" }}>
          {account.positions.length === 0 ? "No open positions in this account." : "No open position of this kind in this account."}
        </div>
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(p) => p.key}
          minWidth={760}
          onRowClick={(p) => {
            // A future or an option also says which contract it is, so the answer charts
            // the contract itself. A share row sends the question alone.
            const position = positionRefOf(p);
            ask(positionQuestion(p), position ? { position } : undefined);
          }}
        />
      )}
    </div>
  );
}

/** Open positions, read live from each account signed in on the broker's own page. */
function OpenPositions() {
  const { go } = useCopilotShell();
  const q = useBrokerPositions(true);
  const [filter, setFilter] = useState<PositionFilter>("all");

  let body: ReactNode;
  if (q.isPending) {
    body = <div style={{ padding: "0 16px 12px" }}><LoadingBlock label="Reading open positions from your broker" rows={2} /></div>;
  } else if (q.isError) {
    body = isForbidden(q.error) ? (
      <div data-testid="trader-positions-off" style={{ padding: "0 16px 14px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
        Reading positions from a broker is not switched on for this account.
      </div>
    ) : (
      <div style={{ padding: "0 16px 12px" }}><QueryProblem what="Open positions" error={q.error} onRetry={() => q.refetch()} /></div>
    );
  } else if (q.data.accounts.length === 0) {
    body = (
      <div data-testid="trader-positions-no-live" className="flex flex-wrap items-center justify-between" style={{ gap: "8px 16px", padding: "0 16px 14px" }}>
        <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)", maxWidth: 620 }}>
          Open positions are read only from an account signed in on the broker’s own page. None of your connected accounts is, so there is nothing to read.
        </span>
        <Btn onClick={() => go("page/brokers")}>Broker connections</Btn>
      </div>
    );
  } else {
    const all = q.data.accounts.flatMap((a) => (a.ok ? a.positions : []));
    const counts: Record<PositionFilter, number> = { all: all.length, fno: all.filter((p) => p.fno).length, intraday: all.filter((p) => p.intraday).length };
    const chips: Array<[PositionFilter, string]> = [["all", "All"], ["fno", "F&O"], ["intraday", "Intraday"]];
    body = (
      <div className="flex flex-col" style={{ gap: 14, paddingBottom: 12 }}>
        <div className="flex flex-wrap" role="group" aria-label="Which positions to show" style={{ gap: 8, padding: "0 16px" }}>
          {chips.map(([key, label]) => (
            <button key={key} type="button" className="cp-chip" data-testid={`trader-positions-filter-${key}`} aria-pressed={filter === key} onClick={() => setFilter(key)}
              style={{ padding: "5px 12px", fontSize: 12, ...(filter === key ? { borderColor: "var(--mint-line)", color: "var(--cp-ink)" } : {}) }}>
              {label} · {fmtNum(counts[key])}
            </button>
          ))}
        </div>
        {q.data.accounts.map((a) => <AccountPositions key={a.id} account={a} filter={filter} />)}
        <div style={{ padding: "0 16px" }}>
          <Footnote>
            Read from your broker when this desk opened, not streamed: use “Read again” for the current book. Quantity, average, last price and P&amp;L are the broker’s own figures; a field the broker did not send says so. Nivesh only reads; it cannot place, change or close a position.
          </Footnote>
        </div>
      </div>
    );
  }

  return (
    <Section
      title="Open positions · read live from your broker"
      note={
        <span className="flex items-center" style={{ gap: 10 }}>
          {q.data?.asOf && <span data-testid="trader-positions-asof">Read {fmtStamp(q.data.asOf)}</span>}
          <button type="button" data-testid="trader-positions-refresh" onClick={() => q.refetch()} disabled={q.isFetching} style={{ background: "none", border: 0, padding: 0, cursor: "pointer", color: "var(--cp-ink)", fontSize: 12 }}>
            {q.isFetching ? "Reading…" : "Read again ›"}
          </button>
        </span>
      }
      flush
    >
      <div data-testid="trader-open-positions">{body}</div>
    </Section>
  );
}

function Connected({ accounts }: { accounts: BrokerAccount[] }) {
  const q = useBrokerHoldings(true);
  const names = accounts.map((a) => a.name).join(", ");

  let body: ReactNode;
  if (q.isPending) {
    body = <LoadingBlock label="Loading holdings read from your broker" />;
  } else if (q.isError) {
    body = <QueryProblem what="Holdings read from your broker" error={q.error} onRetry={() => q.refetch()} />;
  } else if (!q.data.length) {
    body = (
      <div data-testid="trader-broker-holdings-empty">
        <EmptyBlock
          title={`Nothing has been read from ${names} yet`}
          body="The account is connected, but no holdings from it are stored. Holdings appear here after the account has been read; this desk cannot start a read itself."
        />
      </div>
    );
  } else {
    body = <HoldingsTable rows={q.data} accounts={accounts} />;
  }

  return (
    <Labeled title={TITLE} note={<span data-testid="trader-broker-status">{plural(accounts.length, "account")} connected</span>}>
      <Accounts accounts={accounts} />
      {body}
      <OpenPositions />
    </Labeled>
  );
}

/** What is still not read from a broker. Shown in every state, because it is true in every state. */
function PositionBookMissing() {
  return (
    <NotConnected
      testId="trader-positions-not-connected"
      title="Broker funds and day P&L are not read yet"
      body="Holdings and open positions are read from a connected broker. Its funds (available and used margin) and its day P&L are not, and a broker’s book has no stop or target, so none of those are shown and nothing else is used to fill them in. Trades you log yourself are in the journal below. Nivesh only reads from a broker; it cannot place orders."
      needs={[
        "A read-only GET route for broker funds, for trading capital and day P&L. services/brokers/*.fetch_funds() exists; no route returns it.",
        "Day positions (kind=day) work only where the broker has a day book; this desk reads the net book.",
        "A stop and a target for each position; a broker’s book has neither.",
      ]}
    />
  );
}

export function BrokerPositions() {
  const { go } = useCopilotShell();
  const q = useBrokerAccounts();

  let block: ReactNode;
  if (q.isPending) {
    block = <Labeled title={TITLE} note={<span data-testid="trader-broker-status">Checking broker connections</span>}><LoadingBlock label="Checking broker connections" rows={2} /></Labeled>;
  } else if (q.isError) {
    block = <Labeled title={TITLE}><QueryProblem what="Broker connections" error={q.error} onRetry={() => q.refetch()} /></Labeled>;
  } else if (!q.data.length) {
    block = (
      <Labeled title={TITLE} note={<span data-testid="trader-broker-status">No broker connected</span>}>
        <div data-testid="trader-broker-none">
          <EmptyBlock
            title="No broker account is connected"
            body="When a broker account is connected, the holdings it reports are listed here with quantity, average, last price and P&L. Nivesh only reads from a broker; it cannot place orders."
            action={<Btn onClick={() => go("page/brokers")}>Broker connections</Btn>}
          />
        </div>
      </Labeled>
    );
  } else {
    block = <Connected accounts={q.data} />;
  }

  return (
    <div data-testid="trader-broker-positions" className="flex flex-col min-w-0" style={{ gap: 12 }}>
      {block}
      <PositionBookMissing />
    </div>
  );
}
