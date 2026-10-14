/**
 * Smart trading desk — Portfolio & risk: the user's own paper trades and price
 * alerts, added from the Chart tab's risk desk. Simulated: nothing here places
 * an order or reaches a broker.
 *
 *   GET    /api/desk/paper-trades?status=all      open and closed paper trades, marks at the last end-of-day close,
 *                                                 P&L, exit reason, and a summary                (usePaperTrades)
 *   POST   /api/desk/paper-trades/{id}/close      {} — after a confirmation; closes at the last close (reason "manual")
 *   GET    /api/desk/alerts?status=all            price alerts, active and fired, checked through a session (useDeskAlerts)
 *   DELETE /api/desk/alerts/{id}                  after a confirmation
 *
 * Marks and exits use end-of-day daily bars: a session whose low reaches the
 * stop closes the trade at the stop, one whose high reaches the target at the
 * target, and one that reaches both at the stop. An alert fires on the first
 * session after it was set whose high (above) or low (below) reaches its level.
 */
import { useState, type ReactNode } from "react";
import { Btn, DataTable, EmptyBlock, LoadingBlock, Pill, TONE_COLOR, fmtINR, fmtNum, signTone, type Column, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { SymbolCell } from "../desk/parts";
import { QueryProblem, fmtDay, fmtPrice } from "../trading/parts";
import { useDesk } from "./context";
import {
  useClosePaperTrade, useDeleteAlert, useDeskAlerts, usePaperTrades, writeProblem,
  type DeskAlert, type ExitReason, type PaperTrade,
} from "./desk-trading";

const quiet = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;

/** The routes' price status for the whole list, in words; null when every price was read. */
function marksProblem(code: string | null, what: string): string | null {
  if (!code) return null;
  if (code === "prices_unavailable") return `End-of-day prices could not be read just now, so ${what} have no mark and none was checked. Nothing is made up; try again later.`;
  if (code === "prices_partially_unavailable") return `Some end-of-day prices could not be read just now; ${what} without a mark were not checked.`;
  return `Prices: ${code}.`;
}

function MarksNote({ text, testId }: { text: string | null; testId: string }) {
  if (!text) return null;
  return <span data-testid={testId} role="status" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>{text}</span>;
}

function Head({ title, note }: { title: ReactNode; note?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 12px" }}>
      <span className="cp-eyebrow" style={{ color: "var(--cp-ink-2)" }}>{title}</span>
      {note && <span className="cp-mono-note">{note}</span>}
    </div>
  );
}

function Pnl({ rs, testId }: { rs: number | null; testId?: string }) {
  const tone = signTone(rs);
  return <span data-testid={testId} className="cp-num" style={{ color: tone === "ink" ? "var(--cp-ink-2)" : TONE_COLOR[tone] }}>{fmtINR(rs, { signed: true })}</span>;
}

function Confirm({ testId, children, yes, onYes, onNo, pending, error }: {
  testId: string;
  children: ReactNode;
  yes: string;
  onYes: () => void;
  onNo: () => void;
  pending: boolean;
  error: unknown;
}) {
  return (
    <div data-testid={testId} role="group" aria-label="Confirm" className="flex flex-col" style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
      <span style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink)" }}>{children}</span>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Btn variant="primary" data-testid={`${testId}-yes`} disabled={pending} onClick={onYes}>{pending ? "Working…" : yes}</Btn>
        <Btn variant="ghost" data-testid={`${testId}-no`} disabled={pending} onClick={onNo}>Cancel</Btn>
      </span>
      {error != null && <span data-testid={`${testId}-error`} role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>{writeProblem(error)}</span>}
    </div>
  );
}

// ── paper trades ─────────────────────────────────────────────────────────

const REASON: Record<ExitReason, { label: string; tone: Tone }> = {
  stop: { label: "Stop", tone: "danger" },
  target: { label: "Target", tone: "mint" },
  manual: { label: "Closed by you", tone: "ink" },
};

export function PaperTradesBlock() {
  const { mobile } = useCopilotShell();
  const { openTab } = useDesk();
  const q = usePaperTrades();
  const close = useClosePaperTrade();
  const [confirm, setConfirm] = useState<string | null>(null);

  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading your paper trades" rows={3} />;
  else if (q.isError) body = <div data-testid="desk-paper-trades-error"><QueryProblem what="Your paper trades" error={q.error} onRetry={() => q.refetch()} /></div>;
  else if (q.data.trades.length === 0) {
    body = (
      <div data-testid="desk-paper-trades-empty" className="flex flex-col items-start" style={{ gap: 8 }}>
        <span style={quiet}>No paper trades yet. Add one from a scanner setup on the Chart tab: its risk desk sizes it and records it here, with no order placed.</span>
        <Btn onClick={() => openTab("chart")}>Open the Chart tab</Btn>
      </div>
    );
  } else {
    const d = q.data;
    const open = d.trades.filter((t) => t.status === "open");
    const closed = d.trades.filter((t) => t.status === "closed");
    const s = d.summary;
    const picked = open.find((t) => t.id === confirm) ?? null;
    const tiles: Array<{ k: string; v: ReactNode; sub: string; testId: string }> = [
      { k: "Open", v: fmtNum(s?.open ?? open.length), sub: "Marked at the last close", testId: "desk-paper-open" },
      { k: "Closed", v: fmtNum(s?.closed ?? closed.length), sub: s ? `${fmtNum(s.wins)} won · ${fmtNum(s.losses)} lost` : "", testId: "desk-paper-closed" },
      { k: "Realised P&L", v: <Pnl rs={s?.realizedRs ?? null} />, sub: "On closed trades", testId: "desk-paper-realised" },
      {
        k: "Unrealised P&L", v: <Pnl rs={s?.unrealizedRs ?? null} />, testId: "desk-paper-unrealised",
        sub: s?.unmarkedOpen ? `${fmtNum(s.unmarkedOpen)} open without a mark` : "Open trades, end of day",
      },
    ];
    const openCols: Column<PaperTrade>[] = [
      { key: "stock", header: "Stock", width: "minmax(110px,1.2fr)", render: (t) => <SymbolCell symbol={t.symbol} size={20} testId="desk-paper-symbol" sub={t.openedAt ? `Opened ${fmtDay(t.openedAt)}` : undefined} /> },
      { key: "qty", header: "Qty", align: "right", num: true, width: "56px", render: (t) => <span data-testid="desk-paper-qty">{fmtNum(t.quantity)}</span> },
      { key: "entry", header: "Entry", align: "right", num: true, width: "88px", render: (t) => fmtPrice(t.entry) },
      { key: "stop", header: "Stop", align: "right", num: true, width: "88px", render: (t) => fmtPrice(t.stop) },
      { key: "target", header: "Target", align: "right", num: true, width: "88px", render: (t) => (t.target != null ? fmtPrice(t.target) : "None") },
      {
        key: "last", header: "Last close", align: "right", num: true, width: "100px",
        render: (t) => (
          <span data-testid="desk-paper-last" title={t.lastCloseDate ? `End of day ${fmtDay(t.lastCloseDate)}` : t.markError ? `No mark: ${t.markError}` : undefined}>
            {fmtPrice(t.lastClose)}
          </span>
        ),
      },
      { key: "pnl", header: "Unrealised", align: "right", num: true, width: "96px", render: (t) => <Pnl rs={t.unrealizedRs} testId="desk-paper-unrealised-row" /> },
      {
        key: "act", header: "", width: "72px", align: "right",
        render: (t) => (
          <button
            type="button"
            className="cp-chip"
            data-testid="desk-paper-close"
            aria-label={`Close the ${t.symbol} paper trade`}
            disabled={close.isPending}
            onClick={() => { close.reset(); setConfirm(t.id); }}
            style={{ padding: "3px 10px", fontSize: 12 }}
          >
            Close
          </button>
        ),
      },
    ];
    const closedCols: Column<PaperTrade>[] = [
      { key: "stock", header: "Stock", width: "minmax(110px,1.2fr)", render: (t) => <SymbolCell symbol={t.symbol} size={20} testId="desk-paper-symbol" sub={t.closedAt ? `Closed ${fmtDay(t.closedAt)}` : undefined} /> },
      { key: "qty", header: "Qty", align: "right", num: true, width: "56px", render: (t) => fmtNum(t.quantity) },
      { key: "entry", header: "Entry", align: "right", num: true, width: "88px", render: (t) => fmtPrice(t.entry) },
      { key: "exit", header: "Exit", align: "right", num: true, width: "88px", render: (t) => <span data-testid="desk-paper-exit">{fmtPrice(t.exitPrice)}</span> },
      {
        key: "reason", header: "Exit reason", width: "110px",
        render: (t) => (
          <span data-testid="desk-paper-reason" data-reason={t.exitReason ?? ""} title={t.exitNote ?? undefined}>
            {t.exitReason ? <Pill tone={REASON[t.exitReason].tone}>{REASON[t.exitReason].label}{t.exitNote ? " *" : ""}</Pill> : "—"}
          </span>
        ),
      },
      { key: "pnl", header: "Realised", align: "right", num: true, width: "96px", render: (t) => <Pnl rs={t.realizedRs} testId="desk-paper-realised-row" /> },
    ];
    body = (
      <div className="flex flex-col" style={{ gap: 12 }}>
        <div className="grid" style={{ gridTemplateColumns: `repeat(${mobile ? 2 : 4},minmax(0,1fr))`, gap: 8 }}>
          {tiles.map((t) => (
            <div key={t.k} className="flex min-w-0 flex-col" style={{ gap: 3, padding: "10px 12px", borderRadius: 10, background: "var(--bg-2)" }}>
              <span className="cp-eyebrow">{t.k}</span>
              <span data-testid={t.testId} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 20 }}>{t.v}</span>
              {t.sub && <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{t.sub}</span>}
            </div>
          ))}
        </div>
        <MarksNote testId="desk-paper-marks-error" text={marksProblem(d.marksError, "open trades")} />
        <div className="flex flex-col" style={{ gap: 8 }}>
          <Head title={<>Open · <span data-testid="desk-paper-open-count">{fmtNum(open.length)}</span></>} note="Marked at the last close · end of day" />
          {open.length ? (
            <div data-testid="desk-paper-open-table" style={{ border: "1px solid var(--cp-line)", borderRadius: 12 }}>
              <DataTable columns={openCols} rows={open} rowKey={(t) => t.id} minWidth={720} />
            </div>
          ) : (
            <span data-testid="desk-paper-none-open" style={quiet}>No open paper trades.</span>
          )}
          {picked && (
            <Confirm
              testId="desk-paper-confirm"
              yes="Close paper trade"
              pending={close.isPending}
              error={close.isError ? close.error : null}
              onNo={() => { setConfirm(null); close.reset(); }}
              onYes={() => close.mutate(picked.id, { onSuccess: () => setConfirm(null) })}
            >
              Close the {picked.symbol} paper trade ({fmtNum(picked.quantity)} shares) at its last close
              {picked.lastClose != null ? `, ${fmtPrice(picked.lastClose)}${picked.lastCloseDate ? ` (end of day ${fmtDay(picked.lastCloseDate)})` : ""}` : ""}? It is simulated: no order is placed.
            </Confirm>
          )}
        </div>
        {closed.length > 0 && (
          <div className="flex flex-col" style={{ gap: 8 }}>
            <Head title={<>Closed · <span data-testid="desk-paper-closed-count">{fmtNum(closed.length)}</span></>} />
            <div data-testid="desk-paper-closed-table" style={{ border: "1px solid var(--cp-line)", borderRadius: 12 }}>
              <DataTable columns={closedCols} rows={closed} rowKey={(t) => t.id} minWidth={620} />
            </div>
            {closed.some((t) => t.exitNote) && (
              <span data-testid="desk-paper-exit-notes" style={quiet}>
                * {[...new Set(closed.flatMap((t) => (t.exitNote ? [t.exitNote] : [])))].join(" ")}
              </span>
            )}
            {s?.partial && <span style={quiet}>Only the most recent closed trades are listed; the counts above cover those listed.</span>}
          </div>
        )}
        <span data-testid="desk-paper-rules" style={quiet}>
          Simulated: no order is placed. Marks and exits use end-of-day daily bars{d.checkedThrough ? `, checked through ${fmtDay(d.checkedThrough)}` : d.asOf ? ` through ${fmtDay(d.asOf)}` : ""}{d.source ? ` (${d.source})` : ""}. A session whose low reaches the stop closes the trade at the stop; one whose high reaches the target closes it at the target; one that reaches both closes it at the stop.
        </span>
      </div>
    );
  }
  return (
    <div data-testid="desk-paper-trades" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <Head title="Your paper trades" note="Simulated · no orders" />
      {body}
    </div>
  );
}

// ── price alerts ─────────────────────────────────────────────────────────

export function AlertsBlock() {
  const q = useDeskAlerts();
  const del = useDeleteAlert();
  const [confirm, setConfirm] = useState<string | null>(null);

  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading your price alerts" rows={2} />;
  else if (q.isError) body = <div data-testid="desk-alerts-error"><QueryProblem what="Your price alerts" error={q.error} onRetry={() => q.refetch()} /></div>;
  else if (q.data.alerts.length === 0) {
    body = <span data-testid="desk-alerts-empty" style={quiet}>No price alerts. “Alert on trigger” on the Chart tab’s risk desk sets one at a setup’s trigger.</span>;
  } else {
    const d = q.data;
    body = (
      <div className="flex flex-col" style={{ gap: 8 }}>
        <MarksNote testId="desk-alerts-marks-error" text={marksProblem(d.marksError, "active alerts")} />
        <ul className="m-0 flex flex-col" style={{ gap: 6, padding: 0, listStyle: "none" }}>
          {d.alerts.map((a) => (
            <AlertRow
              key={a.id}
              a={a}
              confirming={confirm === a.id}
              onAsk={() => { del.reset(); setConfirm(a.id); }}
              onNo={() => { setConfirm(null); del.reset(); }}
              onYes={() => del.mutate(a.id, { onSuccess: () => setConfirm(null) })}
              pending={del.isPending}
              error={confirm === a.id && del.isError ? del.error : null}
            />
          ))}
        </ul>
        <span data-testid="desk-alerts-rules" style={quiet}>
          Checked after each close against the session’s high (above) or low (below), end of day{d.checkedThrough ? `; checked through ${fmtDay(d.checkedThrough)}` : ""}. Alerts show here only: no email or push.
        </span>
      </div>
    );
  }
  return (
    <div data-testid="desk-alerts" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <Head title="Your price alerts" note="End of day" />
      {body}
    </div>
  );
}

function AlertRow({ a, confirming, onAsk, onNo, onYes, pending, error }: {
  a: DeskAlert;
  confirming: boolean;
  onAsk: () => void;
  onNo: () => void;
  onYes: () => void;
  pending: boolean;
  error: unknown;
}) {
  const fired = a.status === "fired";
  const what = `${a.condition === "above" ? "Above" : "Below"} ${fmtPrice(a.level)}`;
  return (
    <li data-testid="desk-alert-row" data-id={a.id} data-status={a.status} className="flex flex-col" style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "6px 12px" }}>
        <span className="flex min-w-0 items-center" style={{ gap: 10 }}>
          <SymbolCell symbol={a.symbol} size={20} testId="desk-alert-symbol" sub={a.createdAt ? `Set ${fmtDay(a.createdAt)}` : undefined} />
        </span>
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <span data-testid="desk-alert-level" className="cp-num" style={{ fontSize: 13, color: "var(--cp-ink)" }}>{what}</span>
          <span data-testid="desk-alert-status"><Pill tone={fired ? "mint" : "ink"}>{fired ? "Fired" : "Active"}</Pill></span>
          {!confirming && (
            <button type="button" className="cp-chip" data-testid="desk-alert-delete" aria-label={`Delete the ${a.symbol} alert`} onClick={onAsk} style={{ padding: "3px 10px", fontSize: 12 }}>
              Delete
            </button>
          )}
        </span>
      </div>
      {!fired && a.lastClose != null && (
        <span data-testid="desk-alert-last" className="cp-mono-note">Last close {fmtPrice(a.lastClose)}{a.lastCloseDate ? ` · end of day ${fmtDay(a.lastCloseDate)}` : ""}</span>
      )}
      {fired && (
        <span data-testid="desk-alert-fired" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>
          Reached on {fmtDay(a.firedSession ?? a.firedAt)}{a.firedPrice != null ? ` at ${fmtPrice(a.firedPrice)}` : ""} (end of day).
        </span>
      )}
      {a.note && <span style={quiet}>{a.note}</span>}
      {confirming && (
        <Confirm testId="desk-alert-confirm" yes="Delete alert" pending={pending} error={error} onNo={onNo} onYes={onYes}>
          Delete the {a.symbol} alert ({what.toLowerCase()})?
        </Confirm>
      )}
    </li>
  );
}
