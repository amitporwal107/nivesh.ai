/**
 * Trader desk — the broker block (also mounted in the Smart trading desk's
 * Portfolio tab). Read-only: nothing here can place an order.
 *
 * Data:
 *   GET /api/broker/accounts      which broker accounts the user has connected (useBrokerAccounts)
 *   GET /api/broker/holdings      each account's holdings, read live from the broker (useLiveHoldings)
 *   GET /api/broker/positions     each account's open positions, read live (useBrokerPositions)
 *   GET /api/portfolio/holdings   the holdings the last sync stored (useBrokerHoldings). Fetched only
 *                                 when an account's live read failed, and shown for that account
 *                                 labelled "as of last sync" — never as live.
 *
 * What it shows, per connected account (broker icon and name):
 *   live holdings   each stock with its icon: quantity, average, last price, value, P&L, P&L %,
 *                   "Live · read <time>" and the account's totals (a total needs every row)
 *   read failed     why — session ended: Reconnect; not readable live: a sentence; anything
 *                   else: the reason and Try again — then the rows stored at the last sync, if any
 *   none held       "No holdings at <broker>"
 *   open positions  All / F&O / Intraday with counts; a futures or options row says which
 *                   contract (FUT / CE / PE, expiry, strike) and asks about that contract's chart
 * One "Refresh" reads holdings and positions again. Nothing polls: brokers rate-limit.
 *
 * Not connected, in every state: the broker's funds and its day P&L, and a
 * stop or target per position. No route returns them, so the block says so.
 */
import { useState, type ReactNode } from "react";
import {
  Btn, DataTable, EmptyBlock, Footnote, LoadingBlock, NotConnected,
  TONE_COLOR, fmtDate, fmtINR, fmtNum, fmtPct, humaniseTag, signTone,
  type Column,
} from "../../components/ui";
import { BrokerName, StockName } from "../../components/EntityIcon";
import { useCopilotShell } from "../../lib/shell-context";
import { Labeled, QueryProblem, fmtPrice } from "../trading/parts";
import { isForbidden, useBrokerAccounts, type BrokerAccount } from "../trading/queries";
import {
  fmtStamp, positionRefOf, totalsOf, useBrokerHoldings, useBrokerPositions, useLiveHoldings,
  type BrokerHolding, type BrokerPosition, type LiveHolding, type LiveHoldingsAccount, type PositionsAccount,
} from "./broker";

const TITLE = "Broker account · read-only";

const plural = (n: number, one: string, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;
const qtyText = (q: number) => fmtNum(q, Number.isInteger(q) ? 0 : 2);
const quietLine = { padding: "0 16px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" } as const;

const SESSION_ENDED = "BROKER_SESSION_EXPIRED";
const NOT_SUPPORTED = "BROKER_READ_NOT_SUPPORTED";
const READ_FAILED = "BROKER_READ_FAILED";

/** "3:45 pm" for a read made today (India time), else "12 Oct, 3:45 pm". */
function fmtReadTime(at: string | null | undefined): string {
  if (!at) return "—";
  const d = new Date(at);
  if (!Number.isFinite(d.getTime())) return "—";
  const day = (x: Date) => x.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata" });
  if (day(d) !== day(new Date())) return fmtStamp(at);
  return d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true });
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

/** What a holding row asks the Copilot. */
function holdingQuestion(symbol: string, qty: number, avg: number | null): string {
  return `Show the ${symbol} chart with support and resistance. My broker account holds ${qtyText(qty)}${avg != null ? ` at an average of ${fmtPrice(avg)}` : ""}.`;
}

// ── holdings, read live ──────────────────────────────────────────────────

function LiveHoldingsTable({ rows }: { rows: LiveHolding[] }) {
  const { ask } = useCopilotShell();
  const columns: Column<LiveHolding>[] = [
    { key: "stock", header: "Stock", width: "minmax(0,1.9fr)", render: (r) => <StockName testId="broker-live-row" symbol={r.symbol} name={r.name} size={24} /> },
    { key: "qty", header: "Qty", num: true, render: (r) => <span data-testid="broker-live-qty">{qtyText(r.qty)}</span> },
    { key: "avg", header: "Average", num: true, render: (r) => fmtPrice(r.avg) },
    {
      key: "last", header: "Last price", num: true, width: "minmax(0,1.3fr)",
      render: (r) => (
        <span data-testid="broker-live-last">
          {fmtPrice(r.last)}
          {r.priceSource === "masterdata" && (
            <span className="cp-mono-note" title="The broker sent no price for this holding; this is the latest stored exchange close or NAV."> · not live</span>
          )}
        </span>
      ),
    },
    { key: "value", header: "Value", num: true, render: (r) => <span data-testid="broker-live-value">{fmtINR(r.valueRs)}</span> },
    {
      key: "pnl", header: "P&L", num: true,
      render: (r) => <span data-testid="broker-live-pnl" style={{ color: TONE_COLOR[signTone(r.pnlRs)] }}>{fmtINR(r.pnlRs, { signed: true })}</span>,
    },
    {
      key: "pct", header: "P&L %", num: true,
      render: (r) => <span data-testid="broker-live-pnl-pct" style={{ color: TONE_COLOR[signTone(r.pnlPct)] }}>{fmtPct(r.pnlPct, { signed: true })}</span>,
    },
  ];
  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(r) => r.key}
      minWidth={860}
      onRowClick={(r) => ask(holdingQuestion(r.symbol, r.qty, r.avg))}
    />
  );
}

/** The account's totals as the server added them up. A total is missing when any row lacks what it needs; the rows that have it are then summed apart and labelled so. */
function LiveTotals({ account, name }: { account: LiveHoldingsAccount; name: string }) {
  const t = account.totals;
  const rows = account.holdings;
  const complete = t.investedRs != null && t.valueRs != null && t.pnlRs != null;
  const whole = rows.filter((r) => r.investedRs != null && r.valueRs != null && r.pnlRs != null);
  const lacking = rows.length - whole.length;
  const partValue = whole.reduce((s, r) => s + (r.valueRs as number), 0);
  const partPnl = whole.reduce((s, r) => s + (r.pnlRs as number), 0);
  return (
    <div className="flex flex-col" style={{ gap: 4, padding: "0 16px" }}>
      <span data-testid="broker-live-totals" className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>
        Value <span data-testid="broker-live-total-value">{fmtINR(t.valueRs)}</span>
        {" · "}Invested <span data-testid="broker-live-total-invested">{fmtINR(t.investedRs)}</span>
        {" · "}P&amp;L{" "}
        <span data-testid="broker-live-total-pnl" style={{ color: TONE_COLOR[signTone(t.pnlRs)] }}>
          {fmtINR(t.pnlRs, { signed: true })}{t.pnlPct != null ? ` · ${fmtPct(t.pnlPct, { signed: true })}` : ""}
        </span>
      </span>
      {!complete && lacking > 0 && (
        <span data-testid="broker-live-totals-note" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          {fmtNum(lacking)} of {plural(rows.length, "holding")} {lacking === 1 ? "has" : "have"} no price or no average from {name}, so the account totals are not added up.
          {whole.length > 0 && ` The ${plural(whole.length, "holding")} with both: value ${fmtINR(partValue)} · P&L ${fmtINR(partPnl, { signed: true })}.`}
        </span>
      )}
    </div>
  );
}

/** Why one account's holdings were not read live, and what the user can do. The server's own sentence goes to admins only. */
function LiveFailure({ account, name, onRetry, retrying }: { account: LiveHoldingsAccount; name: string; onRetry: () => void; retrying: boolean }) {
  const { go, isAdmin } = useCopilotShell();
  let sentence: string;
  let action: ReactNode = null;
  if (account.errorCode === SESSION_ENDED) {
    sentence = `Your ${name} session has ended, so this account’s holdings and positions cannot be read live. Reconnect by signing in at ${name} again.`;
    action = <Btn data-testid="broker-reconnect" onClick={() => go("page/brokers")}>Reconnect</Btn>;
  } else if (account.errorCode === NOT_SUPPORTED) {
    sentence = `Holdings cannot be read live from this ${name} connection. A live read needs an account signed in on the broker’s own page, at a broker Nivesh can read.`;
  } else {
    sentence = account.errorCode === READ_FAILED
      ? `${name} did not return its holdings just now. Try again in a little while.`
      : `The holdings of this ${name} account could not be read.`;
    action = <Btn data-testid="broker-live-retry" onClick={onRetry} disabled={retrying}>{retrying ? "Reading…" : "Try again"}</Btn>;
  }
  return (
    <div data-testid="broker-live-holdings-error" data-code={account.errorCode ?? ""} role="alert" className="flex flex-wrap items-center justify-between" style={{ gap: "8px 16px", padding: "0 16px" }}>
      <span style={{ flex: "1 1 260px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
        {sentence}
        {isAdmin && account.errorMessage && <span className="cp-mono-note" style={{ display: "block", marginTop: 4, overflowWrap: "anywhere" }}>Server said: {account.errorMessage}</span>}
      </span>
      {action}
    </div>
  );
}

// ── holdings stored at the last sync (only for an account not read live) ──

function StoredHoldings({ rows }: { rows: BrokerHolding[] }) {
  const { ask } = useCopilotShell();
  const totals = totalsOf(rows);
  const readAt = latest(rows.map((r) => r.readAt));
  const columns: Column<BrokerHolding>[] = [
    { key: "stock", header: "Stock", width: "minmax(0,1.8fr)", render: (r) => <StockName testId="broker-stored-row" symbol={r.symbol} name={r.name} size={24} /> },
    { key: "qty", header: "Qty", num: true, render: (r) => qtyText(r.qty) },
    { key: "avg", header: "Average", num: true, render: (r) => fmtPrice(r.avg) },
    { key: "last", header: "Last price", num: true, render: (r) => fmtPrice(r.last) },
    {
      key: "pnl", header: "P&L", num: true, width: "minmax(0,1.3fr)",
      render: (r): ReactNode => (
        <span data-testid="broker-stored-pnl" style={{ color: TONE_COLOR[signTone(r.pnlRs)] }}>
          {fmtINR(r.pnlRs, { signed: true })}{r.pnlPct != null ? ` · ${fmtPct(r.pnlPct, { signed: true })}` : ""}
        </span>
      ),
    },
    { key: "asof", header: "Price as of", num: true, width: "minmax(0,1.2fr)", render: (r) => <span data-testid="broker-stored-price-asof">{fmtStamp(r.priceAt)}</span> },
  ];
  return (
    <div data-testid="broker-stored-holdings" className="flex flex-col" style={{ gap: 6 }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 12px", padding: "0 16px" }}>
        <span className="cp-eyebrow">Stored at the last sync · not live</span>
        <span className="cp-mono-note" data-testid="broker-stored-asof">
          {plural(rows.length, "holding")} · as of last sync{readAt ? ` ${fmtStamp(readAt)}` : ""}
        </span>
      </div>
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        minWidth={760}
        onRowClick={(r) => ask(holdingQuestion(r.symbol, r.qty, r.avg))}
      />
      {totals.priced > 0 && (
        <span className="cp-num" style={{ padding: "0 16px", fontSize: 12, color: "var(--cp-ink-2)" }}>
          Value <span data-testid="broker-stored-value">{fmtINR(totals.valueRs)}</span>
          {" · "}P&amp;L <span data-testid="broker-stored-total-pnl" style={{ color: TONE_COLOR[signTone(totals.pnlRs)] }}>{fmtINR(totals.pnlRs, { signed: true })}</span>
          {totals.priced < rows.length ? ` · ${fmtNum(totals.priced)} of ${fmtNum(rows.length)} priced` : ""}
        </span>
      )}
    </div>
  );
}

function StoredFallback({ accountId, stored }: { accountId: string; stored: ReturnType<typeof useBrokerHoldings> }) {
  if (stored.isPending) return <div style={{ padding: "0 16px" }}><LoadingBlock label="Loading the holdings stored at the last sync" rows={2} /></div>;
  if (stored.isError) {
    return <div style={{ padding: "0 16px" }}><QueryProblem what="Holdings stored at the last sync" error={stored.error} onRetry={() => stored.refetch()} /></div>;
  }
  const rows = stored.data.filter((r) => r.accountId === accountId);
  if (!rows.length) return <div data-testid="broker-stored-none" style={{ ...quietLine, color: "var(--cp-ink-3)" }}>No holdings from this account are stored from an earlier sync either.</div>;
  return <StoredHoldings rows={rows} />;
}

// ── open positions, read live ────────────────────────────────────────────

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

/** Why one account's positions could not be read, in plain words. The server's own sentence goes to admins only. */
function readFailure(a: PositionsAccount, broker: string): string {
  if (a.errorCode === SESSION_ENDED) return `Your ${broker} session has ended. Sign in again from Broker connections to read its positions.`;
  if (a.errorCode === NOT_SUPPORTED) return `Open positions cannot be read live from this ${broker} connection.`;
  if (a.errorCode === READ_FAILED) return `${broker} did not return its positions. Try again in a little while.`;
  return `The positions of this ${broker} account could not be read.`;
}

type PositionFilter = "all" | "fno" | "intraday";

function AccountPositions({ account, name }: { account: PositionsAccount; name: string }) {
  const { ask, isAdmin } = useCopilotShell();
  const [filter, setFilter] = useState<PositionFilter>("all");

  if (!account.ok) {
    return (
      <div data-testid="trader-positions-account" className="flex flex-col" style={{ gap: 6 }}>
        <span className="cp-eyebrow" style={{ padding: "0 16px" }}>Open positions</span>
        <div data-testid="trader-positions-account-error" data-code={account.errorCode ?? ""} role="status" style={quietLine}>
          {readFailure(account, name)}
          {isAdmin && account.errorMessage && <span className="cp-mono-note" style={{ display: "block", marginTop: 4, overflowWrap: "anywhere" }}>Server said: {account.errorMessage}</span>}
        </div>
      </div>
    );
  }

  const all = account.positions;
  const counts: Record<PositionFilter, number> = { all: all.length, fno: all.filter((p) => p.fno).length, intraday: all.filter((p) => p.intraday).length };
  const rows = all.filter((p) => (filter === "fno" ? p.fno : filter === "intraday" ? p.intraday : true));
  const withPnl = rows.filter((p) => p.pnlRs != null);
  const pnl = withPnl.reduce((sum, p) => sum + (p.pnlRs as number), 0);
  const chips: Array<[PositionFilter, string]> = [["all", "All"], ["fno", "F&O"], ["intraday", "Intraday"]];

  const columns: Column<BrokerPosition>[] = [
    {
      key: "instrument", header: "Instrument", width: "minmax(0,2fr)",
      render: (p) => <StockName testId="broker-position-row" symbol={p.symbol} name={p.name} sub={contractOf(p) ?? p.exchange ?? undefined} size={24} />,
    },
    { key: "product", header: "Held as", render: (p) => (p.product ? PRODUCT_WORDS[p.product] ?? humaniseTag(p.product) : "—") },
    {
      key: "qty", header: "Qty", num: true,
      render: (p) => <span data-testid="broker-position-qty">{p.qty < 0 ? `Short ${fmtNum(-p.qty, Number.isInteger(p.qty) ? 0 : 2)}` : qtyText(p.qty)}</span>,
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
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 16px", padding: "0 16px" }}>
        <span className="cp-eyebrow">Open positions · live</span>
        <div className="flex flex-wrap" role="group" aria-label={`Which ${name} positions to show`} style={{ gap: 8 }}>
          {chips.map(([key, label]) => (
            <button key={key} type="button" className="cp-chip" data-testid={`trader-positions-filter-${key}`} aria-pressed={filter === key} onClick={() => setFilter(key)}
              style={{ padding: "5px 12px", fontSize: 12, ...(filter === key ? { borderColor: "var(--mint-line)", color: "var(--cp-ink)" } : {}) }}>
              {label} · {fmtNum(counts[key])}
            </button>
          ))}
        </div>
      </div>
      {rows.length === 0 ? (
        <div data-testid="trader-positions-none" style={{ ...quietLine, color: "var(--cp-ink-3)" }}>
          {all.length === 0 ? "No open positions in this account." : "No open position of this kind in this account."}
        </div>
      ) : (
        <>
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
          {withPnl.length > 0 && (
            <span className="cp-num" style={{ padding: "0 16px", fontSize: 12, color: "var(--cp-ink-2)" }}>
              P&amp;L <span data-testid="broker-positions-pnl" style={{ color: TONE_COLOR[signTone(pnl)] }}>{fmtINR(pnl, { signed: true })}</span>
              {withPnl.length < rows.length ? ` · ${fmtNum(withPnl.length)} of ${fmtNum(rows.length)} positions carry one` : ""}
            </span>
          )}
        </>
      )}
    </div>
  );
}

// ── one account ──────────────────────────────────────────────────────────

type ReadState = "pending" | "error" | "done";

function AccountCard({ id, name, live, liveState, positions, positionsState, stored, onRefresh, refreshing }: {
  id: string;
  name: string;
  /** This account's entry in the live holdings read; undefined while reading, or when the whole read failed. */
  live: LiveHoldingsAccount | undefined;
  liveState: ReadState;
  positions: PositionsAccount | undefined;
  positionsState: ReadState;
  stored: ReturnType<typeof useBrokerHoldings>;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  let status: string;
  if (liveState === "pending") status = "Reading holdings…";
  else if (live?.ok) status = `Live · read ${fmtReadTime(live.asOf)}`;
  else if (live?.errorCode === SESSION_ENDED) status = "Session ended · reconnect to read live";
  else if (live?.errorCode === NOT_SUPPORTED) status = "Not read live";
  else status = "Live read failed";

  let holdings: ReactNode;
  if (liveState === "pending") {
    holdings = <div style={{ padding: "0 16px" }}><LoadingBlock label={`Reading holdings from ${name}`} rows={2} /></div>;
  } else if (live?.ok) {
    holdings = live.holdings.length ? (
      <div className="flex flex-col" style={{ gap: 8 }}>
        <LiveHoldingsTable rows={live.holdings} />
        <LiveTotals account={live} name={name} />
      </div>
    ) : (
      <div data-testid="broker-live-holdings-empty" style={quietLine}>No holdings at {name}.</div>
    );
  } else {
    holdings = (
      <div className="flex flex-col" style={{ gap: 10 }}>
        {live ? (
          <LiveFailure account={live} name={name} onRetry={onRefresh} retrying={refreshing} />
        ) : liveState === "done" ? (
          <div data-testid="broker-live-holdings-error" role="alert" style={quietLine}>This account was not in the live read. Refresh to read it again.</div>
        ) : null}
        <StoredFallback accountId={id} stored={stored} />
      </div>
    );
  }

  let positionsSlot: ReactNode = null;
  if (positionsState === "pending") {
    positionsSlot = <div data-testid="trader-positions-reading" role="status" style={{ ...quietLine, color: "var(--cp-ink-3)" }}>Reading open positions…</div>;
  } else if (positionsState === "done") {
    positionsSlot = positions
      ? <AccountPositions account={positions} name={name} />
      : <div style={{ ...quietLine, color: "var(--cp-ink-3)" }}>Open positions were not read for this account.</div>;
  }

  return (
    <section data-testid="broker-account-card" data-account-id={id} className="cp-card flex flex-col min-w-0" style={{ gap: 14, padding: "14px 0" }}>
      <div style={{ padding: "0 16px", minWidth: 0 }}>
        <BrokerName testId="trader-broker-account" name={name} sub={<span data-testid="broker-live-status">{status}</span>} size={28} />
      </div>
      {holdings}
      {positionsSlot}
    </section>
  );
}

// ── the block ────────────────────────────────────────────────────────────

function Connected({ accounts }: { accounts: BrokerAccount[] }) {
  const { go } = useCopilotShell();
  const live = useLiveHoldings(true);
  const pos = useBrokerPositions(true);
  const liveById = new Map((live.data?.accounts ?? []).map((a) => [a.id, a]));
  const posById = new Map((pos.data?.accounts ?? []).map((a) => [a.id, a]));

  // An account the connections list does not have yet (connected since it loaded) still gets its card.
  const cards = accounts.map((a) => ({ id: a.id, name: a.name }));
  for (const e of [...(live.data?.accounts ?? []), ...(pos.data?.accounts ?? [])]) {
    if (!cards.some((c) => c.id === e.id)) cards.push({ id: e.id, name: e.brokerName ?? e.label ?? (e.broker ? humaniseTag(e.broker) : "Broker") });
  }

  // The stored rows are wanted only for an account that was not read live.
  const needStored = live.isError || (live.isSuccess && cards.some((c) => !liveById.get(c.id)?.ok));
  const stored = useBrokerHoldings(needStored);

  const refreshing = live.isFetching || pos.isFetching;
  const refresh = () => {
    void live.refetch();
    void pos.refetch();
  };
  const stateOf = (q: { isPending: boolean; isError: boolean }): ReadState => (q.isPending ? "pending" : q.isError ? "error" : "done");
  const readAt = latest([live.data?.asOf ?? null, pos.data?.asOf ?? null]);

  return (
    <Labeled title={TITLE} note={<span data-testid="trader-broker-status">{plural(accounts.length, "account")} connected</span>}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 16px" }}>
        <span className="cp-mono-note" data-testid="trader-broker-live-asof">
          {live.isPending || pos.isPending ? "Reading from your broker…" : readAt ? `Holdings and positions read live ${fmtReadTime(readAt)}` : "Not read live"}
        </span>
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <Btn data-testid="trader-broker-refresh" onClick={refresh} disabled={refreshing}>{refreshing ? "Reading…" : "Refresh"}</Btn>
          <Btn onClick={() => go("page/brokers")}>Broker connections</Btn>
        </span>
      </div>

      {live.isError && (
        <div data-testid="trader-holdings-problem">
          {isForbidden(live.error) ? (
            <div data-testid="trader-holdings-off" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
              Reading holdings live from a broker is not switched on for this account. The holdings stored at the last sync are shown instead.
            </div>
          ) : (
            <QueryProblem what="Live holdings" error={live.error} onRetry={() => live.refetch()} />
          )}
        </div>
      )}
      {pos.isError && (
        <div data-testid="trader-positions-problem">
          {isForbidden(pos.error) ? (
            <div data-testid="trader-positions-off" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
              Reading positions from a broker is not switched on for this account.
            </div>
          ) : (
            <QueryProblem what="Open positions" error={pos.error} onRetry={() => pos.refetch()} />
          )}
        </div>
      )}

      {cards.map((c) => (
        <AccountCard
          key={c.id}
          id={c.id}
          name={c.name}
          live={liveById.get(c.id)}
          liveState={stateOf(live)}
          positions={posById.get(c.id)}
          positionsState={stateOf(pos)}
          stored={stored}
          onRefresh={refresh}
          refreshing={refreshing}
        />
      ))}

      <Footnote>
        Read live from each broker when this block opened, not streamed: “Refresh” reads again. Quantity, average and last price are the broker’s own;
        a price marked “not live” is the latest stored exchange close or NAV, used only where the broker sent none. Value = last price × quantity;
        P&amp;L = (last price − average) × quantity. Positions show the broker’s own P&amp;L. Rows marked “as of last sync” were stored by the last sync and are not live.
        Nivesh only reads; it cannot place, change or close a position.
      </Footnote>
    </Labeled>
  );
}

/** What is still not read from a broker. Shown in every state, because it is true in every state. */
function PositionBookMissing() {
  return (
    <NotConnected
      testId="trader-positions-not-connected"
      title="Broker funds and day P&L are not read yet"
      body="Holdings and open positions are read live from a connected broker. Its funds (available and used margin) and its day P&L are not, and a broker’s book has no stop or target, so none of those are shown and nothing else is used to fill them in. Trades you log yourself are in the journal below. Nivesh only reads from a broker; it cannot place orders."
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
            body="When a broker account is connected, its holdings and open positions are read live here, with quantity, average, last price and P&L. Nivesh only reads from a broker; it cannot place orders."
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
