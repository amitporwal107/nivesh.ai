/**
 * Trader desk — the broker block. Read-only: nothing here can place an order.
 *
 * Data:
 *   GET /api/broker/accounts      which broker accounts the user has connected (useBrokerAccounts)
 *   GET /api/portfolio/holdings   the delivery holdings a broker read stored (useBrokerHoldings)
 *
 * What it shows:
 *   no account            says so, with a link to Broker connections
 *   account, rows stored  the holdings as the broker reported them: quantity, average, last price, P&L, as-of time
 *   account, no rows      says nothing has been read yet
 *
 * Not connected, in every state: the broker's open-position book (intraday and
 * F&O), its funds and its day P&L. The server has no route that returns them,
 * so the block says exactly that instead of showing holdings as "positions".
 */
import type { ReactNode } from "react";
import {
  Btn, DataTable, EmptyBlock, Footnote, LoadingBlock, NotConnected, Section,
  TONE_COLOR, fmtINR, fmtNum, fmtPct, humaniseTag, signTone,
  type Column,
} from "../../components/ui";
import { BrokerName, StockName } from "../../components/EntityIcon";
import { useCopilotShell } from "../../lib/shell-context";
import { Labeled, QueryProblem, fmtPrice } from "../trading/parts";
import { useBrokerAccounts, type BrokerAccount } from "../trading/queries";
import { totalsOf, useBrokerHoldings, type BrokerHolding } from "./broker";

const TITLE = "Broker account · read-only";

const plural = (n: number, one: string, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;

/** "13 Oct, 3:42 pm" in India time — a broker read is an India-market timestamp wherever it is viewed. */
export function fmtStamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return "—";
  return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true });
}

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
    </Labeled>
  );
}

/** What the server cannot read from a broker today. Shown in every state, because it is true in every state. */
function PositionBookMissing() {
  return (
    <NotConnected
      testId="trader-positions-not-connected"
      title="Open positions cannot be read from a broker yet"
      body="The server can store the delivery holdings a connected broker reports. It has no way to hand this desk a broker’s open intraday and F&O positions, its funds or its day P&L, so none of those are shown and nothing else is used to fill them in. Trades you log yourself are in the journal below. Nivesh only reads from a broker; it cannot place orders."
      needs={[
        "A GET route that returns a connected account’s position book. The readers exist and nothing calls them for the app: OpenAlgoClient.fetch_positions_raw() (/api/v1/positionbook) is used only inside POST /api/broker/accounts/{id}/sync to fill average prices, and services/brokers/*.fetch_positions() has no caller.",
        "A GET route for broker funds, for trading capital and day P&L. fetch_funds_raw() and services/brokers/*.fetch_funds() exist; /api/v1/funds is called only as the connection check.",
        "A read this app can start. Holdings are imported only by POST /api/broker/accounts/{id}/sync, which builds an OpenAlgo client; an account connected through /api/broker/native stores no OpenAlgo URL, so that route cannot read it.",
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
