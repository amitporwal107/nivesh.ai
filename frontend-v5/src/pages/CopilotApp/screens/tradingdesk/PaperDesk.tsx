/**
 * Smart trading desk — Portfolio & risk: the user's own paper trades and price
 * alerts, added from the Chart tab's risk desk. Simulated: nothing here places
 * an order or reaches a broker.
 *
 *   GET    /api/desk/paper-trades?status=all      open and closed paper trades, marks at the last end-of-day close,
 *                                                 P&L, exit reason, and a summary                (usePaperTrades);
 *                                                 each trade's record (PRD §13.4): signal time, entry rule and
 *                                                 whether it was reached, exit rule, estimated costs, gross and net
 *                                                 P&L, MFE / MAE, observations, strategy and rules version, flags
 *   POST   /api/desk/paper-trades/{id}/close      {} — after a confirmation; closes at the last close (reason "manual"),
 *                                                 or cancels a trade whose entry was not reached
 *   GET    /api/desk/alerts?status=all            price alerts, active and fired, checked through a session (useDeskAlerts)
 *   DELETE /api/desk/alerts/{id}                  after a confirmation
 *
 * Marks and exits use end-of-day daily bars: a session whose low reaches the
 * stop closes the trade at the stop, one whose high reaches the target at the
 * target, and one that reaches both at the stop. An alert fires on the first
 * session after it was set whose high (above) or low (below) reaches its level.
 */
import { useState, type ReactNode } from "react";
import { Btn, DataTable, EmptyBlock, LoadingBlock, Pill, TONE_COLOR, fmtINR, fmtNum, fmtPct, signTone, type Column, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { fmtStamp } from "../desk/broker";
import { SymbolCell } from "../desk/parts";
import { QueryProblem, fmtDay, fmtPrice } from "../trading/parts";
import { useDesk } from "./context";
import {
  costsBreakdownText, useClosePaperTrade, useDeleteAlert, useDeskAlerts, usePaperTrades, writeProblem,
  type DeskAlert, type EntryRule, type EntryStatus, type ExitReason, type PaperTrade, type StrategyExitReason, type StrategyPaperTrade,
} from "./desk-trading";

const plural = (n: number, one: string, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;

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

const REASON: Record<ExitReason, { label: string; investor: string; tone: Tone }> = {
  stop: { label: "Stop", investor: "Exit if wrong", tone: "danger" },
  target: { label: "Target", investor: "Exit if right", tone: "mint" },
  time: { label: "Time exit", investor: "Held long enough", tone: "ink" },
  manual: { label: "Closed by you", investor: "Closed by you", tone: "ink" },
  entry_not_reached: { label: "Entry not reached", investor: "Never bought", tone: "amber" },
  cancelled: { label: "Cancelled", investor: "Cancelled", tone: "ink" },
};

const ENTRY_STATUS: Record<EntryStatus, { trader: string; investor: string; tone: Tone }> = {
  assumed: { trader: "Filled when recorded", investor: "Bought when added", tone: "ink" },
  reached: { trader: "Entry reached", investor: "Bought", tone: "mint" },
  waiting: { trader: "Waiting for entry", investor: "Waiting to buy", tone: "amber" },
  not_reached: { trader: "Entry not reached", investor: "Never bought", tone: "amber" },
};

const RULE_NAME: Record<EntryRule, { trader: string; investor: string }> = {
  at_once: { trader: "At once", investor: "Buy now" },
  break_above: { trader: "Break above", investor: "Buy above" },
  pullback_to: { trader: "Pull back to", investor: "Buy on a dip to" },
};

/** The words the block uses, trader or investor (design-spec §10). */
function wordsFor(investor: boolean) {
  return investor
    ? { entry: "Buy price", stop: "Exit if wrong", target: "Exit if right", gross: "Before costs", net: "After costs", mfe: "Best point", mae: "Worst point",
        rule: "When it buys", obs: "Days checked", unrealised: "Gain now", realised: "Gain taken",
        premium: "Paid or received", mark: "Worth now", legs: "Parts of the trade", signal: "Why it was opened", lifecycle: "What happened" }
    : { entry: "Entry", stop: "Stop", target: "Target", gross: "Gross", net: "Net after costs", mfe: "MFE", mae: "MAE",
        rule: "Entry rule", obs: "Observations", unrealised: "Unrealised P&L", realised: "Realised P&L",
        premium: "Net premium", mark: "Mark", legs: "Legs", signal: "Signal (saved, never edited)", lifecycle: "Lifecycle" };
}

const STRATEGY_REASON: Record<StrategyExitReason, { label: string; investor: string; tone: Tone }> = {
  ...REASON,
  expiry: { label: "Expired", investor: "Expired", tone: "ink" },
};

const DIRECTION_WORD: Record<string, { trader: string; investor: string }> = {
  bullish: { trader: "Bullish", investor: "Expects a rise" },
  bearish: { trader: "Bearish", investor: "Expects a fall" },
  neutral: { trader: "Neutral", investor: "Expects little change" },
};

const BASIS_SHORT: Record<string, string> = {
  settle: "settle", close: "close", expiry_intrinsic: "expiry value", final_settle: "final settle", underlying_close: "share close",
};

function signedPct(p: number | null): string {
  return p == null ? "—" : fmtPct(p, { signed: true, digits: 2 });
}

/** One trade's whole record (PRD §13.4): plan, entry, exit, costs, path and flags. */
function TradeRecord({ t, book, investor }: { t: PaperTrade; book: { entryRules: Partial<Record<EntryRule, string>>; exitRule: string | null }; investor: boolean }) {
  const w = wordsFor(investor);
  const status = t.entryStatus ? ENTRY_STATUS[t.entryStatus] : null;
  const exitRule = [
    `${w.stop} ${fmtPrice(t.stop)}`,
    t.target != null ? `${w.target.toLowerCase()} ${fmtPrice(t.target)}` : "no target",
    t.maxHoldSessions != null ? `or the close of session ${fmtNum(t.maxHoldSessions)} held` : null,
  ].filter(Boolean).join(", ");
  const rows: Array<[string, ReactNode, string]> = [
    ["Signal time", t.signalAt ? (t.signalAt.length === 10 ? fmtDay(t.signalAt) : fmtStamp(t.signalAt)) : t.source?.signalDate ? `${fmtDay(t.source.signalDate)} (scan date)` : "— not recorded", "signal"],
    [w.rule, <>{RULE_NAME[t.entryRule][investor ? "investor" : "trader"]} {fmtPrice(t.entry)}{t.entryWindowSessions != null ? ` · waits ${plural(t.entryWindowSessions, "session")}` : ""}{book.entryRules[t.entryRule] ? <span style={{ display: "block", color: "var(--cp-ink-3)" }}>{book.entryRules[t.entryRule]}</span> : null}</>, "rule"],
    ["Entry", <>{status ? status[investor ? "investor" : "trader"] : "—"}{t.entrySession ? ` · ${fmtDay(t.entrySession)}` : ""}{t.simEntryPrice != null ? ` · simulated at ${fmtPrice(t.simEntryPrice)}` : ""}</>, "entry"],
    ["Exit rule", exitRule, "exit-rule"],
    ["Quantity", fmtNum(t.quantity), "qty"],
    ["Estimated costs", <>{t.estCostsAtTarget != null ? `${fmtINR(t.estCostsAtTarget)} at the target · ` : ""}{t.estCostsAtStop != null ? `${fmtINR(t.estCostsAtStop)} at the stop` : "—"}{t.costModel?.slippagePctPerSide != null && t.costModel.brokerageRsPerSide != null ? <span style={{ display: "block", color: "var(--cp-ink-3)" }}>{fmtNum(t.costModel.slippagePctPerSide, 2)}% of the traded value + {fmtINR(t.costModel.brokerageRsPerSide)} a side{t.costModel.version === "desk-cost-v2" ? " + STT, exchange, SEBI, stamp duty and GST" : ""}{t.costModel.name ? ` (${t.costModel.name}${t.costModel.version ? `, ${t.costModel.version}` : ""})` : ""}</span> : null}</>, "est-costs"],
    ["Strategy version", t.strategyVersion ?? "— not recorded", "strategy"],
    ["Rationale", t.rationale ?? t.note ?? "— not recorded", "rationale"],
    [w.obs, t.observations != null ? `${plural(t.observations, "session")} read${t.heldSessions != null ? ` · ${fmtNum(t.heldSessions)} held` : ""}` : "— not recorded", "obs"],
    ["Exit", t.status === "closed" ? <>{t.exitReason ? REASON[t.exitReason][investor ? "investor" : "label"] : "—"}{t.exitSession ? ` · ${fmtDay(t.exitSession)}` : ""}{t.exitPrice != null ? ` · ${fmtPrice(t.exitPrice)}` : ""}</> : "Open", "exit"],
    [`${w.gross} · costs · ${w.net.toLowerCase()}`, <><Pnl rs={t.grossRs} /> · {t.costsRs != null ? fmtINR(t.costsRs) : "—"} · <Pnl rs={t.netRs} testId="desk-paper-record-net" />{costsBreakdownText(t.costsBreakdown, (n) => fmtPrice(n), t.costModel?.version === "desk-cost-v2") ? <span data-testid="desk-paper-record-costs-breakdown" style={{ display: "block", color: "var(--cp-ink-3)" }}>{costsBreakdownText(t.costsBreakdown, (n) => fmtPrice(n), t.costModel?.version === "desk-cost-v2")}</span> : null}{t.costsBasis ? <span style={{ display: "block", color: "var(--cp-ink-3)" }}>Costs: {t.costsBasis}</span> : null}</>, "pnl"],
    [`${w.mfe} · ${w.mae}`, <>{signedPct(t.mfePct)}{t.mfeRs != null ? ` (${fmtINR(t.mfeRs, { signed: true })})` : ""} · {signedPct(t.maePct)}{t.maeRs != null ? ` (${fmtINR(t.maeRs, { signed: true })})` : ""}</>, "excursion"],
    ["Rules version", t.rulesVersion ?? "— before versions were recorded", "version"],
  ];
  return (
    <div data-testid="desk-paper-record" data-id={t.id} className="flex flex-col" style={{ gap: 8, padding: "12px 14px", borderRadius: 12, border: "1px solid var(--cp-line)", background: "var(--bg-2)" }}>
      <span className="cp-eyebrow">{t.symbol} · paper trade record</span>
      <dl className="m-0 grid" style={{ gridTemplateColumns: "minmax(0,150px) minmax(0,1fr)", gap: "6px 12px", fontSize: 12.5, lineHeight: 1.45 }}>
        {rows.map(([k, v, id]) => (
          <div key={id} className="contents">
            <dt style={{ color: "var(--cp-ink-3)" }}>{k}</dt>
            <dd data-testid={`desk-paper-record-${id}`} className="m-0" style={{ color: "var(--cp-ink)", minWidth: 0, overflowWrap: "anywhere" }}>{v}</dd>
          </div>
        ))}
      </dl>
      <div data-testid="desk-paper-record-flags" className="flex flex-col" style={{ gap: 4 }}>
        <span className="cp-eyebrow">Rule violations or missing data</span>
        {t.flags.length === 0 ? (
          <span style={quiet}>{t.observations == null ? "Not recorded for this trade." : "None found."}</span>
        ) : (
          <ul className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 16 }}>
            {t.flags.map((f, i) => (
              <li key={`${f.code}-${i}`} data-testid="desk-paper-flag" data-code={f.code} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
                {f.session ? `${fmtDay(f.session)}: ` : ""}{f.text}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

const premiumTitle = (rs: number | null) => (rs == null ? undefined : rs < 0 ? "Paid by the option legs (a debit)" : "Received by the option legs (a credit)");

/** One strategy trade's whole record (PRD §17.7): every leg with its entry and mark, the signal it was opened from
 *  (saved with the trade, never edited), the lifecycle log, costs and flags. */
function StrategyRecord({ t, investor }: { t: StrategyPaperTrade; investor: boolean }) {
  const w = wordsFor(investor);
  const reason = t.exitReason ? STRATEGY_REASON[t.exitReason][investor ? "investor" : "label"] : null;
  const dir = t.direction ? DIRECTION_WORD[t.direction][investor ? "investor" : "trader"] : "—";
  const levels = [
    t.stopUnderlying != null ? `${w.stop} on ${t.underlying} ${fmtPrice(t.stopUnderlying)}` : null,
    t.targetUnderlying != null ? `${w.target.toLowerCase()} ${fmtPrice(t.targetUnderlying)}` : null,
    t.maxHoldSessions != null ? `or the close of session ${fmtNum(t.maxHoldSessions)} held` : null,
    "or when every leg has expired",
  ].filter(Boolean).join(", ");
  const rows: Array<[string, ReactNode, string]> = [
    ["Plan", <>{t.summaryText} · {dir}{t.referencePrice != null ? ` · ${t.underlying} was ${fmtPrice(t.referencePrice)}` : ""}{t.strategyPlanId ? ` · plan ${t.strategyPlanId}` : ""}</>, "plan"],
    ["Exit rule", levels, "exit-rule"],
    ["Exit", t.status === "closed" ? <>{reason ?? "—"}{t.exitSession ? ` · ${fmtDay(t.exitSession)}` : ""}{t.exitNote ? <span style={{ display: "block", color: "var(--cp-ink-3)" }}>{t.exitNote}</span> : null}</> : "Open", "exit"],
    [w.premium, <><span title={premiumTitle(t.netPremiumRs)}>{t.netPremiumRs != null ? fmtINR(t.netPremiumRs, { signed: true }) : "—"}</span>{t.markPremiumRs != null ? ` at entry · ${fmtINR(t.markPremiumRs, { signed: true })} at the marks` : ""}</>, "premium"],
    [`${w.gross} · costs · ${w.net.toLowerCase()}`, <><Pnl rs={t.grossRs} /> · {t.costsRs != null ? fmtINR(t.costsRs) : "—"} · <Pnl rs={t.netRs} testId="desk-paper-record-net" />{costsBreakdownText(t.costsBreakdown, (n) => fmtPrice(n), t.costModel?.version === "desk-cost-v2") ? <span data-testid="desk-paper-record-costs-breakdown" style={{ display: "block", color: "var(--cp-ink-3)" }}>{costsBreakdownText(t.costsBreakdown, (n) => fmtPrice(n), t.costModel?.version === "desk-cost-v2")}</span> : null}{t.costsBasis ? <span style={{ display: "block", color: "var(--cp-ink-3)" }}>Costs: {t.costsBasis}</span> : null}</>, "pnl"],
    [`${w.mfe} · ${w.mae}`, <>{t.mfeRs != null ? fmtINR(t.mfeRs, { signed: true }) : "—"} · {t.maeRs != null ? fmtINR(t.maeRs, { signed: true }) : "—"}<span style={{ display: "block", color: "var(--cp-ink-3)" }}>End-of-session P&amp;L of the whole position, not intraday.</span></>, "excursion"],
    [w.obs, t.observations != null ? `${plural(t.observations, "session")} read${t.heldSessions != null ? ` · ${fmtNum(t.heldSessions)} held` : ""}` : "— not read", "obs"],
    ["Rules version", t.rulesVersion ?? "—", "version"],
  ];
  const sg = t.signal;
  return (
    <div data-testid="desk-paper-strategy-record" data-id={t.id} className="flex flex-col" style={{ gap: 10, padding: "12px 14px", borderRadius: 12, border: "1px solid var(--cp-line)", background: "var(--bg-2)" }}>
      <span className="cp-eyebrow">{t.underlying} · strategy paper trade record</span>
      <dl className="m-0 grid" style={{ gridTemplateColumns: "minmax(0,150px) minmax(0,1fr)", gap: "6px 12px", fontSize: 12.5, lineHeight: 1.45 }}>
        {rows.map(([k, v, id]) => (
          <div key={id} className="contents">
            <dt style={{ color: "var(--cp-ink-3)" }}>{k}</dt>
            <dd data-testid={`desk-paper-strategy-record-${id}`} className="m-0" style={{ color: "var(--cp-ink)", minWidth: 0, overflowWrap: "anywhere" }}>{v}</dd>
          </div>
        ))}
      </dl>
      {t.riskNote && <span data-testid="desk-paper-strategy-risk" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>{t.riskNote}</span>}
      <div className="flex flex-col" style={{ gap: 4 }}>
        <span className="cp-eyebrow">{w.legs}</span>
        <div data-testid="desk-paper-strategy-legs" style={{ border: "1px solid var(--cp-line)", borderRadius: 10, overflowX: "auto" }}>
          <table style={{ width: "100%", minWidth: 640, borderCollapse: "collapse", fontSize: 12.5 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--cp-ink-3)" }}>
                <th style={{ padding: "6px 10px", fontWeight: 500 }}>Leg</th>
                <th style={{ padding: "6px 10px", fontWeight: 500, textAlign: "right" }}>{w.entry}</th>
                <th style={{ padding: "6px 10px", fontWeight: 500, textAlign: "right" }}>{t.status === "closed" ? "Closing mark" : w.mark}</th>
                <th style={{ padding: "6px 10px", fontWeight: 500 }}>Mark date</th>
                <th style={{ padding: "6px 10px", fontWeight: 500, textAlign: "right" }}>P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {t.legs.map((leg) => (
                <tr key={leg.index} data-testid="desk-paper-strategy-leg" data-index={leg.index} style={{ borderTop: "1px solid var(--cp-line)" }}>
                  <td style={{ padding: "6px 10px" }}>
                    {leg.label} · {fmtNum(leg.lotSize)} per lot
                    <span style={{ display: "block", color: "var(--cp-ink-3)" }}>Entry from {leg.priceSource ?? "— source not recorded"}</span>
                  </td>
                  <td data-testid="desk-paper-strategy-leg-entry" className="cp-num" style={{ padding: "6px 10px", textAlign: "right" }}>{fmtPrice(leg.entry)}</td>
                  <td data-testid="desk-paper-strategy-leg-mark" className="cp-num" style={{ padding: "6px 10px", textAlign: "right" }} title={leg.markBasisText ?? undefined}>
                    {fmtPrice(leg.mark)}{leg.markBasis ? <span style={{ display: "block", fontSize: 11, color: "var(--cp-ink-3)" }}>{BASIS_SHORT[leg.markBasis]}</span> : null}
                  </td>
                  <td data-testid="desk-paper-strategy-leg-date" style={{ padding: "6px 10px" }}>{leg.markDate ? fmtDay(leg.markDate) : "— no mark"}</td>
                  <td style={{ padding: "6px 10px", textAlign: "right" }}><Pnl rs={leg.pnlRs} testId="desk-paper-strategy-leg-pnl" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <span style={quiet}>Marks are end-of-day contract prices from the NSE F&amp;O bhavcopy (settle, else close); an option on its expiry date is valued at intrinsic value against the share's close. A leg with no price keeps its last mark and is flagged; nothing is filled in.</span>
      </div>
      <div data-testid="desk-paper-strategy-signal" className="flex flex-col" style={{ gap: 4 }}>
        <span className="cp-eyebrow">{w.signal}</span>
        <dl className="m-0 grid" style={{ gridTemplateColumns: "minmax(0,150px) minmax(0,1fr)", gap: "4px 12px", fontSize: 12.5, lineHeight: 1.45 }}>
          <dt style={{ color: "var(--cp-ink-3)" }}>Signal time</dt>
          <dd data-testid="desk-paper-signal-at" className="m-0">{sg.signalAt ? (sg.signalAt.length === 10 ? fmtDay(sg.signalAt) : fmtStamp(sg.signalAt)) : "— not recorded"}</dd>
          <dt style={{ color: "var(--cp-ink-3)" }}>Rule · model version</dt>
          <dd data-testid="desk-paper-signal-versions" className="m-0">{sg.ruleVersion ?? "—"} · {sg.modelVersion ?? "no model"}</dd>
          <dt style={{ color: "var(--cp-ink-3)" }}>Sources</dt>
          <dd data-testid="desk-paper-signal-sources" className="m-0">{sg.sourceRefs.length ? sg.sourceRefs.map((r) => `${r.kind} ${r.ref}${r.asOf ? ` (${r.asOf})` : ""}`).join("; ") : "— none recorded"}</dd>
          <dt style={{ color: "var(--cp-ink-3)" }}>Evidence</dt>
          <dd data-testid="desk-paper-signal-evidence" className="m-0" style={{ overflowWrap: "anywhere" }}>{sg.evidenceSummary ?? "— not recorded"}</dd>
        </dl>
        {t.entryRecordIntact === false && <span data-testid="desk-paper-record-tampered" role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>The stored legs or signal no longer match what was saved at entry. Treat this record as unreliable.</span>}
      </div>
      <div data-testid="desk-paper-strategy-events" className="flex flex-col" style={{ gap: 4 }}>
        <span className="cp-eyebrow">{w.lifecycle}</span>
        <ol className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 18 }}>
          {t.events.map((e, i) => (
            <li key={`${e.type}-${i}`} data-testid="desk-paper-event" data-type={e.type} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
              {e.at ? `${fmtStamp(e.at)} · ` : ""}{e.session ? `session ${fmtDay(e.session)} · ` : ""}{e.text}
            </li>
          ))}
        </ol>
      </div>
      <div data-testid="desk-paper-record-flags" className="flex flex-col" style={{ gap: 4 }}>
        <span className="cp-eyebrow">Rule violations or missing data</span>
        {t.flags.length === 0 ? (
          <span style={quiet}>{t.observations == null ? "Not read." : "None found."}</span>
        ) : (
          <ul className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 16 }}>
            {t.flags.map((f, i) => (
              <li key={`${f.code}-${i}`} data-testid="desk-paper-flag" data-code={f.code} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
                {f.session ? `${fmtDay(f.session)}: ` : ""}{f.text}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function RecordToggle({ t, open, onToggle }: { t: { symbol: string }; open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      className="cp-chip"
      data-testid="desk-paper-record-toggle"
      aria-expanded={open}
      aria-label={`${open ? "Hide" : "Show"} the ${t.symbol} paper trade record`}
      onClick={onToggle}
      style={{ padding: "3px 10px", fontSize: 12 }}
    >
      {open ? "Hide" : "Record"}
    </button>
  );
}

export function PaperTradesBlock() {
  const { mobile } = useCopilotShell();
  const { openTab, persona } = useDesk();
  const investor = persona === "investor";
  const w = wordsFor(investor);
  const q = usePaperTrades();
  const close = useClosePaperTrade();
  const [confirm, setConfirm] = useState<string | null>(null);
  const [record, setRecord] = useState<string | null>(null);

  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading your paper trades" rows={3} />;
  else if (q.isError) body = <div data-testid="desk-paper-trades-error"><QueryProblem what="Your paper trades" error={q.error} onRetry={() => q.refetch()} /></div>;
  else if (q.data.trades.length === 0 && q.data.strategyTrades.length === 0) {
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
    const strategyOpen = d.strategyTrades.filter((t) => t.status === "open");
    const strategyClosed = d.strategyTrades.filter((t) => t.status === "closed");
    const s = d.summary;
    const picked = open.find((t) => t.id === confirm) ?? null;
    const pickedStrategy = strategyOpen.find((t) => t.id === confirm) ?? null;
    const shown = d.trades.find((t) => t.id === record) ?? null;
    const shownStrategy = d.strategyTrades.find((t) => t.id === record) ?? null;
    const toggle = (t: { id: string }) => setRecord(record === t.id ? null : t.id);
    const strategyCols = (isOpen: boolean): Column<StrategyPaperTrade>[] => [
      {
        key: "stock", header: "Underlying", width: "minmax(190px,1.8fr)",
        render: (t) => <SymbolCell symbol={t.underlying} size={20} testId="desk-strategy-symbol" sub={<span data-testid="desk-strategy-summary">{t.summaryText}</span>} />,
      },
      {
        key: "family", header: "Strategy", width: "130px",
        render: (t) => <span data-testid="desk-strategy-family" title={t.direction ?? undefined}>{t.familyName ?? t.family ?? "—"}</span>,
      },
      {
        key: "prem", header: w.premium, align: "right", num: true, width: "104px",
        render: (t) => <span data-testid="desk-strategy-premium" title={premiumTitle(t.netPremiumRs)} className="cp-num">{t.netPremiumRs != null ? fmtINR(t.netPremiumRs, { signed: true }) : "—"}</span>,
      },
      {
        key: "mark", header: w.mark, align: "right", num: true, width: "104px",
        render: (t) => (
          <span data-testid="desk-strategy-mark" className="cp-num" title={t.lastMarkDate ? `End of day ${fmtDay(t.lastMarkDate)}` : t.markError ? `No mark: ${t.markError}` : "No mark yet"}>
            {t.markPremiumRs != null ? fmtINR(t.markPremiumRs, { signed: true }) : "—"}
          </span>
        ),
      },
      { key: "pnl", header: isOpen ? w.gross : (investor ? "Gain before costs" : "Realised"), align: "right", num: true, width: "100px", render: (t) => <Pnl rs={t.grossRs} testId="desk-strategy-gross" /> },
      { key: "net", header: w.net, align: "right", num: true, width: "110px", render: (t) => <Pnl rs={t.netRs} testId="desk-strategy-net" /> },
      {
        key: "status", header: "Status", width: "120px",
        render: (t) => (
          <span data-testid="desk-strategy-status" data-status={t.status} data-reason={t.exitReason ?? ""}>
            {t.status === "open" ? <Pill tone="mint">Open</Pill> : t.exitReason ? <Pill tone={STRATEGY_REASON[t.exitReason].tone}>{STRATEGY_REASON[t.exitReason][investor ? "investor" : "label"]}</Pill> : <Pill tone="ink">Closed</Pill>}
          </span>
        ),
      },
      { key: "rec", header: "", width: "78px", align: "right", render: (t) => <RecordToggle t={{ symbol: t.underlying }} open={record === t.id} onToggle={() => toggle(t)} /> },
      ...(isOpen ? [{
        key: "act", header: "", width: "72px", align: "right" as const,
        render: (t: StrategyPaperTrade) => (
          <button type="button" className="cp-chip" data-testid="desk-strategy-close" aria-label={`Close the ${t.underlying} strategy paper trade`} disabled={close.isPending}
            onClick={() => { close.reset(); setConfirm(t.id); }} style={{ padding: "3px 10px", fontSize: 12 }}>
            Close
          </button>
        ),
      }] : []),
    ];
    const tiles: Array<{ k: string; v: ReactNode; sub: ReactNode; testId: string }> = [
      { k: "Open", v: fmtNum(s?.open ?? open.length), sub: s?.entryPending ? `${fmtNum(s.entryPending)} waiting for the entry` : "Marked at the last close", testId: "desk-paper-open" },
      { k: "Closed", v: fmtNum(s?.closed ?? closed.length), sub: s ? `${fmtNum(s.wins)} won · ${fmtNum(s.losses)} lost${s.notEntered ? ` · ${fmtNum(s.notEntered)} never entered` : ""}` : "", testId: "desk-paper-closed" },
      {
        k: w.realised, v: <Pnl rs={s?.realizedRs ?? null} />, testId: "desk-paper-realised",
        sub: <>Gross · <span data-testid="desk-paper-net-realised">{s?.netRealizedRs != null ? fmtINR(s.netRealizedRs, { signed: true }) : "—"}</span> after costs</>,
      },
      {
        k: w.unrealised, v: <Pnl rs={s?.unrealizedRs ?? null} />, testId: "desk-paper-unrealised",
        sub: s?.unmarkedOpen
          ? `${fmtNum(s.unmarkedOpen)} open without a mark`
          : <>Gross · <span data-testid="desk-paper-net-unrealised">{s?.netUnrealizedRs != null ? fmtINR(s.netUnrealizedRs, { signed: true }) : "—"}</span> after est. costs</>,
      },
    ];
    const statusSub = (t: PaperTrade) => {
      const st = t.entryStatus ? ENTRY_STATUS[t.entryStatus][investor ? "investor" : "trader"] : null;
      return [t.openedAt ? `Opened ${fmtDay(t.openedAt)}` : null, st].filter(Boolean).join(" · ") || undefined;
    };
    const openCols: Column<PaperTrade>[] = [
      { key: "stock", header: "Stock", width: "minmax(130px,1.4fr)", render: (t) => <SymbolCell symbol={t.symbol} size={20} testId="desk-paper-symbol" sub={<span data-testid="desk-paper-entry-status" data-status={t.entryStatus ?? ""}>{statusSub(t)}</span>} /> },
      { key: "qty", header: "Qty", align: "right", num: true, width: "56px", render: (t) => <span data-testid="desk-paper-qty">{fmtNum(t.quantity)}</span> },
      { key: "entry", header: w.entry, align: "right", num: true, width: "88px", render: (t) => fmtPrice(t.entry) },
      { key: "stop", header: w.stop, align: "right", num: true, width: "88px", render: (t) => fmtPrice(t.stop) },
      { key: "target", header: w.target, align: "right", num: true, width: "88px", render: (t) => (t.target != null ? fmtPrice(t.target) : "None") },
      {
        key: "last", header: "Last close", align: "right", num: true, width: "100px",
        render: (t) => (
          <span data-testid="desk-paper-last" title={t.lastCloseDate ? `End of day ${fmtDay(t.lastCloseDate)}` : t.markError ? `No mark: ${t.markError}` : undefined}>
            {fmtPrice(t.lastClose)}
          </span>
        ),
      },
      { key: "pnl", header: w.gross, align: "right", num: true, width: "96px", render: (t) => <Pnl rs={t.unrealizedRs} testId="desk-paper-unrealised-row" /> },
      { key: "net", header: w.net, align: "right", num: true, width: "110px", render: (t) => <Pnl rs={t.netRs} testId="desk-paper-net-row" /> },
      { key: "rec", header: "", width: "78px", align: "right", render: (t) => <RecordToggle t={t} open={record === t.id} onToggle={() => toggle(t)} /> },
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
      { key: "entry", header: w.entry, align: "right", num: true, width: "88px", render: (t) => fmtPrice(t.entry) },
      { key: "exit", header: "Exit", align: "right", num: true, width: "88px", render: (t) => <span data-testid="desk-paper-exit">{fmtPrice(t.exitPrice)}</span> },
      {
        key: "reason", header: "Exit reason", width: "128px",
        render: (t) => (
          <span data-testid="desk-paper-reason" data-reason={t.exitReason ?? ""} title={t.exitNote ?? undefined}>
            {t.exitReason ? <Pill tone={REASON[t.exitReason].tone}>{REASON[t.exitReason][investor ? "investor" : "label"]}{t.exitNote ? " *" : ""}</Pill> : "—"}
          </span>
        ),
      },
      { key: "pnl", header: investor ? "Gain before costs" : "Realised", align: "right", num: true, width: "96px", render: (t) => <Pnl rs={t.realizedRs} testId="desk-paper-realised-row" /> },
      { key: "net", header: w.net, align: "right", num: true, width: "110px", render: (t) => <Pnl rs={t.netRs} testId="desk-paper-net-row" /> },
      {
        key: "mfe", header: `${w.mfe} / ${w.mae}`, align: "right", num: true, width: "120px",
        render: (t) => <span data-testid="desk-paper-excursion">{signedPct(t.mfePct)} / {signedPct(t.maePct)}</span>,
      },
      { key: "rec", header: "", width: "78px", align: "right", render: (t) => <RecordToggle t={t} open={record === t.id} onToggle={() => toggle(t)} /> },
    ];
    const notes = [...new Set(closed.flatMap((t) => (t.exitNote ? [t.exitNote] : [])))];
    const cost = d.costModel;
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
              <DataTable columns={openCols} rows={open} rowKey={(t) => t.id} minWidth={1000} />
            </div>
          ) : (
            <span data-testid="desk-paper-none-open" style={quiet}>No open paper trades.</span>
          )}
          {picked && (
            <Confirm
              testId="desk-paper-confirm"
              yes={picked.entryStatus === "waiting" ? "Cancel paper trade" : "Close paper trade"}
              pending={close.isPending}
              error={close.isError ? close.error : null}
              onNo={() => { setConfirm(null); close.reset(); }}
              onYes={() => close.mutate(picked.id, { onSuccess: () => setConfirm(null) })}
            >
              {picked.entryStatus === "waiting"
                ? <>Cancel the {picked.symbol} paper trade? Its entry has not been reached, so there is no position and no P&amp;L. It is simulated: no order is placed.</>
                : <>Close the {picked.symbol} paper trade ({fmtNum(picked.quantity)} shares) at its last close{picked.lastClose != null ? `, ${fmtPrice(picked.lastClose)}${picked.lastCloseDate ? ` (end of day ${fmtDay(picked.lastCloseDate)})` : ""}` : ""}? It is simulated: no order is placed.</>}
            </Confirm>
          )}
        </div>
        {closed.length > 0 && (
          <div className="flex flex-col" style={{ gap: 8 }}>
            <Head title={<>Closed · <span data-testid="desk-paper-closed-count">{fmtNum(closed.length)}</span></>} />
            <div data-testid="desk-paper-closed-table" style={{ border: "1px solid var(--cp-line)", borderRadius: 12 }}>
              <DataTable columns={closedCols} rows={closed} rowKey={(t) => t.id} minWidth={940} />
            </div>
            {notes.length > 0 && <span data-testid="desk-paper-exit-notes" style={quiet}>* {notes.join(" ")}</span>}
            {s?.partial && <span style={quiet}>Only the most recent closed trades are listed; the counts above cover those listed.</span>}
          </div>
        )}
        {d.strategyTrades.length > 0 && (
          <div data-testid="desk-strategy-trades" className="flex flex-col" style={{ gap: 8 }}>
            <Head title={<>Futures and options · <span data-testid="desk-strategy-count">{fmtNum(d.strategyTrades.length)}</span></>} note="Marked at end-of-day contract prices · simulated" />
            {strategyOpen.length > 0 && (
              <div data-testid="desk-strategy-open-table" style={{ border: "1px solid var(--cp-line)", borderRadius: 12 }}>
                <DataTable columns={strategyCols(true)} rows={strategyOpen} rowKey={(t) => t.id} minWidth={960} />
              </div>
            )}
            {pickedStrategy && (
              <Confirm
                testId="desk-strategy-confirm"
                yes="Close strategy trade"
                pending={close.isPending}
                error={close.isError ? close.error : null}
                onNo={() => { setConfirm(null); close.reset(); }}
                onYes={() => close.mutate(pickedStrategy.id, { onSuccess: () => setConfirm(null) })}
              >
                Close the {pickedStrategy.underlying} strategy ({pickedStrategy.summaryText}) at the last end-of-day marks of its legs? It is simulated: no order is placed.
              </Confirm>
            )}
            {strategyClosed.length > 0 && (
              <div data-testid="desk-strategy-closed-table" style={{ border: "1px solid var(--cp-line)", borderRadius: 12 }}>
                <DataTable columns={strategyCols(false)} rows={strategyClosed} rowKey={(t) => t.id} minWidth={900} />
              </div>
            )}
            <span data-testid="desk-strategy-rules" style={quiet}>
              Each leg is marked on its own contract: a future at its settle price, an option at its settle (else close), on the NSE F&amp;O bhavcopy, end of day. A strategy closes when the share touches its stop or target, when every leg has expired (options at intrinsic value), or after the sessions allowed; the legs close at that session's marks. Futures losses can exceed the margin posted. Rules {d.strategyTrades[0]?.rulesVersion ?? "desk-paper-v3"}.
            </span>
          </div>
        )}
        {shown && <TradeRecord t={shown} book={d} investor={investor} />}
        {shownStrategy && <StrategyRecord t={shownStrategy} investor={investor} />}
        <span data-testid="desk-paper-rules" style={quiet}>
          {d.orders ?? "Simulated: no order is placed."} Marks and exits use end-of-day daily bars{d.checkedThrough ? `, checked through ${fmtDay(d.checkedThrough)}` : d.asOf ? ` through ${fmtDay(d.asOf)}` : ""}{d.source ? ` (${d.source})` : ""}. A session whose low reaches the stop closes the trade at the stop; one whose high reaches the target closes it at the target; one that reaches both closes it at the stop.
          {cost?.slippagePctPerSide != null && cost.brokerageRsPerSide != null
            ? <> Net figures take off estimated costs: <span data-testid="desk-paper-cost-model">{fmtNum(cost.slippagePctPerSide, 2)}% of the traded value + {fmtINR(cost.brokerageRsPerSide)} a side</span>{cost.name ? ` (${cost.name})` : ""}.</>
            : null}
          {d.rulesVersion ? ` Rules ${d.rulesVersion}.` : ""} MFE and MAE are the best and worst points reached from the fill through the exit session.
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
