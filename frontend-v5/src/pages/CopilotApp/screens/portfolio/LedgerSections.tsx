/**
 * Portfolio ledger — the blocks beside the holdings list:
 *
 *   Allocation by type        from the holdings (the original Portfolio page's bar;
 *                             lib/use-portfolio-context keeps its rules)
 *   Top gainers and losers    from the holdings, by gain on invested money
 *   Statements and snapshots  GET /api/portfolio/cas-snapshots   (useStatements)
 *   Transactions              GET /api/portfolio/transactions    (useTransactions)
 *   SIPs                      GET /api/portfolio/sips            (useDetectedSips)
 *
 * A fund row shows the fund house icon, a stock row the company icon.
 */
import { useState } from "react";
import { FundName } from "../../components/EntityIcon";
import {
  DataTable, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Pill, Section,
  TONE_COLOR, fmtDate, fmtINR, fmtNum, fmtPct, signTone, type Column, type Tone,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import type { AllocationPart } from "../../lib/use-portfolio-context";
import { humanise, loadError, type EnrichedHolding } from "./data";
import {
  triggerLabel, txnLabel, useDetectedSips, useStatements, useTransactions,
  type DetectedSip, type LedgerTxn, type StatementRecord,
} from "./ledger-data";
import { HoldingIcon } from "./names";
import { ShowAll } from "./parts";

const quiet = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;

function Signed({ value, text }: { value: number | null; text: string }) {
  return <span style={{ color: value == null || value === 0 ? undefined : TONE_COLOR[signTone(value)] }}>{text}</span>;
}

// ── allocation by type ───────────────────────────────────────────────────

// One fill per instrument type, in the shell's own colours.
const TYPE_FILL: Record<string, string> = {
  equity: "var(--mint)",
  mutual_fund: "var(--cp-indigo)",
  etf: "var(--amber)",
  gold: "var(--cp-ink-2)",
  bond: "var(--cp-ink-3)",
  fd: "var(--line-3)",
  other: "var(--bg-4)",
};

/** The split across stocks, mutual funds, ETFs, gold and the rest, by value. */
export function TypeSplit({ parts }: { parts: AllocationPart[] }) {
  if (!parts.length) return null;
  return (
    <Section title="Allocation by type" note="Share of market value">
      <div data-testid="ledger-type-split" className="flex flex-col" style={{ gap: 10 }}>
        <div role="img" aria-label={parts.map((p) => `${p.label} ${fmtPct(p.pct, { digits: 0 })}`).join(", ")} className="flex overflow-hidden" style={{ height: 10, borderRadius: 5, background: "var(--bg-3)" }}>
          {parts.map((p) => <span key={p.key} style={{ width: `${p.pct}%`, background: TYPE_FILL[p.key] ?? TYPE_FILL.other }} />)}
        </div>
        <div className="flex flex-wrap" style={{ gap: "6px 18px" }}>
          {parts.map((p) => (
            <span key={p.key} data-testid={`ledger-type-${p.key}`} className="inline-flex items-center" style={{ gap: 6, fontSize: 12, color: "var(--cp-ink-2)" }}>
              <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: 2, background: TYPE_FILL[p.key] ?? TYPE_FILL.other }} />
              {p.label}
              <span className="cp-num" style={{ color: "var(--cp-ink-3)" }}>{fmtPct(p.pct, { digits: 0 })}</span>
            </span>
          ))}
        </div>
      </div>
    </Section>
  );
}

// ── top gainers and losers ───────────────────────────────────────────────

const MOVER_LIMIT = 5;

function MoverList({ title, tone, rows, testId }: { title: string; tone: Tone; rows: EnrichedHolding[]; testId: string }) {
  const { ask } = useCopilotShell();
  return (
    <Section title={<span style={{ color: TONE_COLOR[tone] }}>{title}</span>} note="Gain on invested money">
      <div data-testid={testId} className="flex flex-col">
        {rows.length === 0 && <span style={quiet}>None.</span>}
        {rows.map((h) => (
          <button
            key={h.holding_id}
            type="button"
            data-testid="ledger-mover"
            onClick={() => ask(`Why is ${h.name} ${(h.pnl_pct ?? 0) >= 0 ? "up" : "down"} ${fmtPct(Math.abs(h.pnl_pct ?? 0))} for me, and what does that mean for holding it?`)}
            className="cp-row-link grid items-center text-left"
            style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: 12, padding: "8px 4px", border: 0, borderBottom: "1px solid var(--cp-line)", color: "inherit", fontFamily: "var(--sans)" }}
          >
            <span className="flex items-center" style={{ gap: 8, minWidth: 0 }}>
              <HoldingIcon name={h.name} assetType={h.asset_type} symbol={h.nse_symbol} size={22} reserve />
              <span data-testid="ledger-mover-name" title={h.name} style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 13, color: "var(--cp-ink-2)" }}>{h.name}</span>
            </span>
            <span data-testid="ledger-mover-pct" className="cp-num" style={{ fontSize: 13 }}><Signed value={h.pnl_pct ?? null} text={fmtPct(h.pnl_pct, { signed: true })} /></span>
          </button>
        ))}
      </div>
    </Section>
  );
}

/** The five holdings with the largest gain and the five with the largest loss, as the original Portfolio page lists them. */
export function Movers({ holdings }: { holdings: EnrichedHolding[] }) {
  const withGain = holdings.filter((h) => h.pnl_pct != null);
  if (!withGain.length) return null;
  const gainers = withGain.filter((h) => (h.pnl_pct ?? 0) >= 0).sort((a, b) => (b.pnl_pct ?? 0) - (a.pnl_pct ?? 0)).slice(0, MOVER_LIMIT);
  const losers = withGain.filter((h) => (h.pnl_pct ?? 0) < 0).sort((a, b) => (a.pnl_pct ?? 0) - (b.pnl_pct ?? 0)).slice(0, MOVER_LIMIT);
  return (
    <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: 12 }}>
      <MoverList title="Top gainers" tone="mint" rows={gainers} testId="ledger-gainers" />
      <MoverList title="Top losers" tone="danger" rows={losers} testId="ledger-losers" />
    </div>
  );
}

// ── statements and snapshots on record ───────────────────────────────────

const STATEMENT_COLUMNS: Array<Column<StatementRecord>> = [
  { key: "date", header: "Date", num: true, render: (s) => <span data-testid="ledger-statement-date" style={{ color: "var(--cp-ink)" }}>{fmtDate(s.date)}</span> },
  { key: "by", header: "Recorded by", width: "minmax(0,1.2fr)", render: (s) => triggerLabel(s.trigger) || "—" },
  { key: "value", header: "Value", num: true, align: "right", render: (s) => <span data-testid="ledger-statement-value">{fmtINR(s.valueRs, { compact: true })}</span> },
  { key: "invested", header: "Invested", num: true, align: "right", render: (s) => fmtINR(s.investedRs, { compact: true }) },
  { key: "gain", header: "Gain", num: true, align: "right", render: (s) => <Signed value={s.returnPct} text={fmtPct(s.returnPct, { signed: true })} /> },
  { key: "health", header: "Health", num: true, align: "right", render: (s) => (s.health == null ? "—" : `${fmtNum(s.health)}${s.grade ? ` · ${s.grade}` : ""}`) },
  { key: "holdings", header: "Holdings", num: true, align: "right", render: (s) => fmtNum(s.holdings) },
];

/** One row per statement import or daily record: what the portfolio was worth and held that day. */
export function Statements() {
  const q = useStatements();
  if (q.isPending) return <LoadingBlock label="Loading statements on record" rows={2} />;
  if (q.isError) return <ErrorBlock title="Statements on record didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  if (!q.data.length) {
    return (
      <div data-testid="ledger-statements-empty">
        <EmptyBlock title="No statement on record" body="Each statement you import is kept here with what your portfolio was worth and held that day." />
      </div>
    );
  }
  return (
    <Section flush title="Statements and snapshots on record" note={<span data-testid="ledger-statements-count">{q.data.length} on record · newest first</span>}>
      <div data-testid="ledger-statements">
        <DataTable columns={STATEMENT_COLUMNS} rows={q.data} rowKey={(s) => `${s.date}-${s.trigger}`} minWidth={720} />
      </div>
    </Section>
  );
}

// ── transactions ─────────────────────────────────────────────────────────

const TXN_LIMIT = 10;
const OUTFLOWS = new Set(["REDEMPTION", "SWITCH_OUT"]);

const TXN_COLUMNS: Array<Column<LedgerTxn>> = [
  { key: "date", header: "Date", num: true, render: (t) => fmtDate(t.date) },
  {
    key: "scheme", header: "Fund", width: "minmax(0,2.2fr)",
    render: (t) => (t.scheme
      ? <FundName testId="ledger-txn-scheme" name={t.scheme} sub={t.folio ? `Folio ${t.folio}` : undefined} size={24} />
      : <span style={{ color: "var(--cp-ink-3)" }}>Not named on the statement</span>),
  },
  { key: "type", header: "Type", render: (t) => <span data-testid="ledger-txn-type"><Pill tone={OUTFLOWS.has(t.type) ? "amber" : "ink"}>{txnLabel(t.type) || "—"}</Pill></span> },
  { key: "amount", header: "Amount", num: true, align: "right", render: (t) => <span data-testid="ledger-txn-amount">{fmtINR(t.amountRs)}</span> },
  { key: "units", header: "Units", num: true, align: "right", render: (t) => fmtNum(t.units, 3) },
  { key: "nav", header: "Price per unit", num: true, align: "right", render: (t) => (t.nav != null && t.nav > 0 ? fmtINR(t.nav) : "—") },
];

/** Purchases, redemptions and switches read from the user's statements, newest first. */
export function Transactions() {
  const [expanded, setExpanded] = useState(false);
  const q = useTransactions();
  if (q.isPending) return <LoadingBlock label="Loading transactions" rows={3} />;
  if (q.isError) return <ErrorBlock title="Transactions didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  const { rows, investedRs, redeemedRs } = q.data;
  if (!rows.length) {
    return (
      <div data-testid="ledger-transactions-empty">
        <EmptyBlock
          title="No transactions on record"
          body="No purchases or redemptions have been read from your statements. They are listed here when a statement that carries transactions is imported; a statement that lists only holdings has none."
        />
      </div>
    );
  }
  return (
    <Section
      flush
      title={<>Transactions · <span data-testid="ledger-transactions-count">{rows.length}</span> on record</>}
      note={<>Invested <span data-testid="ledger-transactions-invested">{fmtINR(investedRs, { compact: true })}</span> · Redeemed <span data-testid="ledger-transactions-redeemed">{fmtINR(redeemedRs, { compact: true })}</span></>}
    >
      <div data-testid="ledger-transactions">
        <DataTable columns={TXN_COLUMNS} rows={expanded ? rows : rows.slice(0, TXN_LIMIT)} rowKey={(t) => t.key} minWidth={780} />
      </div>
      <ShowAll total={rows.length} limit={TXN_LIMIT} expanded={expanded} onToggle={() => setExpanded((v) => !v)} noun="transactions" />
      <div style={{ padding: "10px 16px 12px" }}>
        <Footnote>As read from your statements · newest first</Footnote>
      </div>
    </Section>
  );
}

// ── SIPs ─────────────────────────────────────────────────────────────────

const SIP_COLUMNS: Array<Column<DetectedSip>> = [
  {
    key: "scheme", header: "Fund", width: "minmax(0,2.2fr)",
    render: (s) => <FundName testId="ledger-sip-scheme" name={s.scheme} sub={s.folio ? `Folio ${s.folio}` : undefined} size={24} />,
  },
  { key: "status", header: "Status", render: (s) => <span data-testid="ledger-sip-status"><Pill tone={s.status === "ACTIVE" ? "mint" : "amber"}>{humanise(s.status) || "—"}</Pill></span> },
  { key: "amount", header: "Instalment", num: true, align: "right", render: (s) => <span data-testid="ledger-sip-amount">{fmtINR(s.amountRs)}{s.cadence === "QUARTERLY" ? " / quarter" : s.cadence === "MONTHLY" ? " / month" : ""}</span> },
  { key: "count", header: "Instalments", num: true, align: "right", render: (s) => fmtNum(s.instalments) },
  { key: "last", header: "Last one", num: true, align: "right", render: (s) => fmtDate(s.lastDate) },
  { key: "total", header: "Invested", num: true, align: "right", render: (s) => fmtINR(s.totalInvestedRs, { compact: true }) },
];

/** SIPs the backend detects in the statement's transactions: same fund, same amount, regular gap. */
export function Sips() {
  const q = useDetectedSips();
  if (q.isPending) return <LoadingBlock label="Loading SIPs" rows={2} />;
  if (q.isError) return <ErrorBlock title="SIPs didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;
  if (!q.data.rows.length) {
    return (
      <div data-testid="ledger-sips-empty">
        <EmptyBlock title="No recurring SIPs detected" body="A SIP is detected from at least three regular purchases of the same fund in your statement’s transactions. None was found." />
      </div>
    );
  }
  return (
    <Section
      flush
      title={<>SIPs · <span data-testid="ledger-sips-active">{q.data.active}</span> active</>}
      note={<>Going out each month · <span data-testid="ledger-sips-monthly">{fmtINR(q.data.monthlyRs)}</span></>}
    >
      <div data-testid="ledger-sips">
        <DataTable columns={SIP_COLUMNS} rows={q.data.rows} rowKey={(s) => s.key} minWidth={760} />
      </div>
      <div style={{ padding: "10px 16px 12px" }}>
        <Footnote>Detected from your statement’s transactions · a quarterly SIP counts a third towards the monthly figure</Footnote>
      </div>
    </Section>
  );
}
