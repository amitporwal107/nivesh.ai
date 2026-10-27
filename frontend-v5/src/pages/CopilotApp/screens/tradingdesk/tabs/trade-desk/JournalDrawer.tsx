/**
 * The trade journal, as a drawer from any Trade Desk row (the plan: "the chart and the trade journal open as drawers, not as
 * places to navigate to"). Everything comes from the paper-trade list the tab already read (GET /api/desk/paper-trades):
 *
 *   lifecycle timeline   `transitions` (trade-lifecycle-v1, append-only: from → to, time, session, source, rule version);
 *                        a strategy without transitions shows its `events`
 *   fills                entry (requested vs simulated, session, slippage on the fill event) and exit
 *   P/L bridge           gross, the desk-cost-v2 card's lines (brokerage, STT, exchange, SEBI, stamp, GST, slippage), total,
 *                        net — "net, before income tax"
 *   stop history         `stop_history`, the stop in force
 *   exit flags           `flags`: both_in_range ("stop and target both touched: stop assumed", the owner's rule of 27 Oct;
 *                        there is no AMBIGUOUS state), gap_through_stop ("filled at the open")
 *   links                the chart (Market Desk › Stock Research, ?sym=) and the plan (its decision card,
 *                        GET /api/desk/trade-plans/{id})
 *
 * Close (POST /api/desk/paper-trades/{id}/close) after a confirmation; Roll for an open F&O structure. Simulated only.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Btn, fmtINR, fmtNum, fmtPct } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { fmtStamp } from "../../../desk/broker";
import { fmtDay, fmtPrice } from "../../../trading/parts";
import { DecisionCardById } from "../../decision/DecisionCard";
import {
  useClosePaperTrade, writeProblem, type CostsBreakdown, type PaperFlag, type PaperTrade, type StrategyPaperTrade, type Transition,
} from "../../desk-trading";
import { RollAction } from "../../RollAction";
import { LegTable, StructureFigures } from "./StructureCard";
import { EXIT_WORDS, FLAG_LEAD, Kv, PAPER_ONLY, Pnl, STATE_WORDS, StatePill, entryRuleLine, quiet, rsSigned } from "./parts";

export type JournalTrade = { kind: "cash"; t: PaperTrade } | { kind: "strategy"; t: StrategyPaperTrade };

const ENTRY_STATUS_WORD: Record<string, string> = { assumed: "Filled when recorded", reached: "Entry reached", waiting: "Waiting for entry", not_reached: "Entry not reached" };

const dayShort = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T12:00:00+05:30` : iso);
  return Number.isFinite(d.getTime()) ? d.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" }) : iso;
};
const stamp = (iso: string | null) => (iso ? (iso.length === 10 ? fmtDay(iso) : fmtStamp(iso)) : "—");

function Block({ title, testId, children, note }: { title: string; testId: string; children: ReactNode; note?: ReactNode }) {
  return (
    <section data-testid={testId} aria-label={title} className="flex min-w-0 flex-col" style={{ gap: 8, padding: 14, borderRadius: 14, border: "1px solid var(--cp-line)", background: "var(--bg-2)" }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 10px" }}>
        <h4 className="cp-eyebrow m-0">{title}</h4>
        {note && <span className="cp-mono-note">{note}</span>}
      </div>
      {children}
    </section>
  );
}

// ── lifecycle ────────────────────────────────────────────────────────────

function Timeline({ transitions, events }: { transitions: Transition[]; events?: StrategyPaperTrade["events"] }) {
  if (!transitions.length && events?.length) {
    return (
      <ol className="m-0 flex flex-col" style={{ gap: 6, paddingLeft: 18 }}>
        {events.map((e, i) => (
          <li key={`${e.type}-${i}`} data-testid="td-journal-event" data-type={e.type} style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
            <span className="cp-num" style={{ color: "var(--cp-ink-3)" }}>{stamp(e.at)}{e.session ? ` · session ${dayShort(e.session)}` : ""}</span> · {e.text}
          </li>
        ))}
      </ol>
    );
  }
  if (!transitions.length) return <span data-testid="td-journal-timeline-empty" style={quiet}>No lifecycle events on record (a trade recorded before trade-lifecycle-v1).</span>;
  return (
    <ol className="m-0 flex flex-col" style={{ gap: 0, padding: 0, listStyle: "none" }}>
      {transitions.map((e, i) => {
        const w = STATE_WORDS[e.to];
        const dot = w ? (w.tone === "mint" ? "var(--mint)" : w.tone === "amber" ? "var(--amber)" : w.tone === "danger" ? "var(--cp-danger)" : w.tone === "indigo" ? "var(--cp-indigo)" : "var(--cp-ink-3)") : "var(--cp-ink-3)";
        return (
          <li key={`${e.seq ?? i}-${e.to}`} data-testid="td-journal-transition" data-to={e.to} data-from={e.from ?? ""} className="flex" style={{ gap: 12 }}>
            <span aria-hidden className="flex flex-col items-center" style={{ flex: "none", width: 10 }}>
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: dot, marginTop: 5 }} />
              {i < transitions.length - 1 && <span style={{ flex: 1, width: 1, background: "var(--line-2)" }} />}
            </span>
            <span className="flex min-w-0 flex-col" style={{ gap: 2, paddingBottom: 12 }}>
              <span className="cp-num" style={{ fontSize: 10.5, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>
                {stamp(e.at)}{e.session ? ` · session ${dayShort(e.session)}` : ""} · <span style={{ color: dot }}>{e.from ? `${e.from} → ` : ""}{e.to}</span>
              </span>
              <span style={{ fontSize: 12.5, lineHeight: 1.45, color: "var(--cp-ink)" }}>{e.reason ?? (w ? w.label : e.to)}
                {e.fillPrice != null ? ` Filled at ${fmtPrice(e.fillPrice)}${e.slippage != null ? ` (slippage ${fmtPrice(e.slippage)})` : ""}.` : ""}</span>
              <span data-testid="td-journal-transition-meta" className="cp-num" style={{ fontSize: 10.5, color: "var(--cp-ink-4)" }}>
                source {e.source ?? "not recorded"} · rules {e.ruleVersion ?? "not recorded"}{e.derived ? " · rebuilt from stored fields" : ""}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

// ── fills ────────────────────────────────────────────────────────────────

function Fills({ t }: { t: PaperTrade }) {
  const entryEvent = t.transitions.find((e) => e.to === "POSITION_OPEN");
  const exitEvent = [...t.transitions].reverse().find((e) => e.to === "CLOSED" && e.fillPrice != null);
  const entered = t.entryStatus === "assumed" || t.entryStatus === "reached";
  const fill = entryEvent?.fillPrice ?? t.simEntryPrice ?? (t.entryStatus === "assumed" ? t.entry : null);
  const rows: Array<{ id: string; side: string; qty: string; requested: string; simulated: string; when: string; note: string }> = [];
  rows.push({
    id: "entry", side: "Buy", qty: fmtNum(t.quantity), requested: fmtPrice(t.entry),
    simulated: entered ? fmtPrice(fill) : "not filled",
    when: entered ? dayShort(t.entrySession ?? entryEvent?.session ?? t.openedAt) : "—",
    note: entered ? (entryEvent?.slippage != null ? `slippage ${fmtPrice(entryEvent.slippage)}` : t.entryRule === "at_once" ? "at once, inside the last session's range" : "level traded") : t.entryStatus === "not_reached" ? "entry not reached" : "waiting for the entry",
  });
  if (t.status === "closed" && entered) {
    rows.push({
      id: "exit", side: "Sell", qty: fmtNum(t.quantity), requested: t.exitReason === "target" ? fmtPrice(t.target) : t.exitReason === "stop" || t.exitReason === "trailing_stop" ? fmtPrice(t.currentStop ?? t.stop) : "—",
      simulated: fmtPrice(exitEvent?.fillPrice ?? t.exitPrice), when: dayShort(t.exitSession ?? t.closedAt),
      note: EXIT_WORDS[t.exitReasonCode ?? ""]?.label ?? t.exitReasonCode ?? "—",
    });
  }
  const th = { padding: "5px 8px", fontWeight: 500, whiteSpace: "nowrap" as const };
  const td = { padding: "6px 8px", whiteSpace: "nowrap" as const };
  return (
    <div className="cp-scroll" style={{ maxWidth: "100%", overflowX: "auto" }}>
      <table style={{ width: "100%", minWidth: 480, borderCollapse: "collapse", fontSize: 12.5 }}>
        <thead><tr className="cp-mono-note" style={{ textAlign: "left" }}><th style={th}>Fill</th><th style={th}>Side</th><th style={{ ...th, textAlign: "right" }}>Qty</th><th style={{ ...th, textAlign: "right" }}>Requested</th><th style={{ ...th, textAlign: "right" }}>Simulated</th><th style={th}>Session</th><th style={th}>Note</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} data-testid={`td-journal-fill-${r.id}`} style={{ borderTop: "1px solid var(--cp-line)" }}>
              <td style={td}>{r.id === "entry" ? "Entry" : "Exit"}</td><td style={td}>{r.side}</td>
              <td className="cp-num" style={{ ...td, textAlign: "right" }}>{r.qty}</td>
              <td className="cp-num" style={{ ...td, textAlign: "right" }}>{r.requested}</td>
              <td data-testid={`td-journal-fill-${r.id}-price`} className="cp-num" style={{ ...td, textAlign: "right" }}>{r.simulated}</td>
              <td style={td}>{r.when || "—"}</td><td style={{ ...td, color: "var(--cp-ink-3)" }}>{r.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── the P/L bridge ───────────────────────────────────────────────────────

const COST_LINES: Array<[keyof CostsBreakdown, string]> = [
  ["brokerage", "Brokerage"], ["stt", "STT"], ["exchange", "Exchange charges"], ["sebi", "SEBI fee"], ["stamp", "Stamp duty"], ["gst", "GST"], ["slippage", "Slippage"],
];

export function PnlBridge({ gross, costs, net, breakdown, model, basis, open }: {
  gross: number | null; costs: number | null; net: number | null; breakdown: CostsBreakdown | null;
  model: { version: string | null; slippagePctPerSide: number | null; brokerageRsPerSide: number | null; name: string | null } | null;
  basis: string | null; open: boolean;
}) {
  const statutory = model?.version === "desk-cost-v2";
  const lines = COST_LINES.filter(([k]) => statutory || k === "brokerage" || k === "slippage");
  const row = (label: string, v: ReactNode, id: string, strong?: boolean) => (
    <div key={id} data-testid={`td-bridge-${id}`} className="flex items-baseline justify-between" style={{ gap: 12, padding: "6px 0", borderTop: "1px solid var(--cp-line)", fontSize: strong ? 14 : 12.5, color: strong ? "var(--cp-ink)" : "var(--cp-ink-2)" }}>
      <span>{label}</span><span className="cp-num">{v}</span>
    </div>
  );
  return (
    <div className="flex min-w-0 flex-col">
      {row(open ? "Gross P/L (unrealised)" : "Gross P/L", <Pnl rs={gross} />, "gross")}
      {breakdown
        ? lines.map(([k, label]) => row(label, breakdown[k] != null ? rsSigned(-(breakdown[k] as number)) : "—", k))
        : row("Costs by line", "not recorded for this trade", "lines")}
      {row("Total costs", costs != null ? rsSigned(-costs) : "—", "total")}
      {row("Net P/L", <Pnl rs={net} testId="td-bridge-net-value" />, "net", true)}
      <span data-testid="td-bridge-note" style={{ ...quiet, fontSize: 11.5, paddingTop: 6 }}>
        Net, before income tax. Cost card {model?.version ?? "not recorded"}
        {statutory ? ": STT, exchange, SEBI, stamp duty and GST by segment" : ""}
        {model?.brokerageRsPerSide != null ? `; brokerage ${fmtINR(model.brokerageRsPerSide)} a side (a desk assumption)` : ""}
        {model?.slippagePctPerSide != null ? `; slippage ${fmtNum(model.slippagePctPerSide, 2)}% a side, charged as a cost line` : ""}.
        {open ? " Open: the exit side is estimated at the last mark." : ""}{basis ? ` ${basis}.` : ""}
      </span>
    </div>
  );
}

// ── flags and stops ──────────────────────────────────────────────────────

export function ExitFlags({ flags, testId = "td-journal-flags" }: { flags: PaperFlag[]; testId?: string }) {
  const lead = flags.filter((f) => FLAG_LEAD[f.code]);
  const rest = flags.filter((f) => !FLAG_LEAD[f.code]);
  if (!flags.length) return <span data-testid={`${testId}-none`} style={quiet}>None: no gap through a level and no session that touched both the stop and the target.</span>;
  return (
    <ul className="m-0 flex flex-col" style={{ gap: 6, paddingLeft: 16 }}>
      {lead.map((f, i) => (
        <li key={`l-${f.code}-${i}`} data-testid="td-journal-flag" data-code={f.code} style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--amber)" }}>
          <strong style={{ fontWeight: 600 }}>{FLAG_LEAD[f.code](dayShort(f.session))}.</strong>{" "}
          <span style={{ color: "var(--cp-ink-2)" }}>{f.text}</span>
        </li>
      ))}
      {rest.map((f, i) => (
        <li key={`r-${f.code}-${i}`} data-testid="td-journal-flag" data-code={f.code} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {f.session ? `${dayShort(f.session)}: ` : ""}{f.text}
        </li>
      ))}
    </ul>
  );
}

function StopHistory({ t }: { t: PaperTrade }) {
  if (!t.stopHistory.length) return <span data-testid="td-journal-stops-none" style={quiet}>The initial stop {fmtPrice(t.stop)}; no stop history recorded for this trade.</span>;
  return (
    <ol className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 18, fontSize: 12.5 }}>
      {t.stopHistory.map((v, i) => (
        <li key={`${v.version ?? i}-${v.session ?? "entry"}`} data-testid="td-journal-stop" data-reason={v.reason}>
          <span className="cp-num">{fmtPrice(v.stop)}</span> · {v.session ? `set at the ${dayShort(v.session)} close, in force from the next session` : "at entry"} · {v.reason === "initial" ? "initial stop" : v.reason === "trailing_atr" ? "raised by the ATR trail" : v.reason}
        </li>
      ))}
    </ol>
  );
}

// ── the drawer ───────────────────────────────────────────────────────────

function CloseAction({ id, label, what }: { id: string; label: string; what: string }) {
  const close = useClosePaperTrade();
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return <button type="button" className="cp-chip" data-testid="td-journal-close" onClick={() => { close.reset(); setAsking(true); }} style={{ padding: "4px 12px", fontSize: 12 }}>{label}</button>;
  }
  return (
    <div data-testid="td-journal-close-confirm" role="group" aria-label="Confirm" className="flex w-full flex-col" style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
      <span style={{ fontSize: 12.5, lineHeight: 1.5 }}>{what} It is simulated: no order is placed.</span>
      <span className="flex flex-wrap" style={{ gap: 8 }}>
        <Btn variant="primary" data-testid="td-journal-close-yes" disabled={close.isPending || close.isSuccess} onClick={() => close.mutate(id)}>{close.isSuccess ? "Done" : close.isPending ? "Working…" : label}</Btn>
        <Btn variant="ghost" data-testid="td-journal-close-no" disabled={close.isPending} onClick={() => setAsking(false)}>Cancel</Btn>
      </span>
      {close.isError && <span role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>{writeProblem(close.error)}</span>}
    </div>
  );
}

export function JournalDrawer({ item, onClose, onChart }: { item: JournalTrade; onClose: () => void; onChart: (symbol: string) => void }) {
  const { mobile } = useCopilotShell();
  const closeRef = useRef<HTMLButtonElement>(null);
  const [plan, setPlan] = useState(false);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); opener?.focus?.(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per opened trade; the parent keys the drawer by id
  }, []);

  const t = item.t;
  const symbol = item.kind === "cash" ? item.t.symbol : item.t.underlying;
  const open = t.status === "open";
  const planId = t.tradePlanId;
  const title = item.kind === "cash" ? `${symbol} · ${item.t.quantity != null ? `${fmtNum(item.t.quantity)} shares` : "shares"}` : `${item.t.familyName ?? item.t.family ?? "Structure"} · ${symbol}`;

  let body: ReactNode;
  if (item.kind === "cash") {
    const c = item.t;
    const exitW = EXIT_WORDS[c.exitReasonCode ?? ""];
    body = (
      <>
        <Block title="Lifecycle" testId="td-journal-timeline" note="append-only · trade-lifecycle-v1"><Timeline transitions={c.transitions} /></Block>
        <Block title="Fills · requested vs simulated" testId="td-journal-fills" note="end-of-day bars"><Fills t={c} /></Block>
        <Block title="P/L bridge" testId="td-journal-bridge">
          <PnlBridge gross={c.grossRs} costs={c.costsRs} net={c.netRs} breakdown={c.costsBreakdown} model={c.costModel} basis={c.costsBasis} open={open} />
        </Block>
        <Block title="Exit flags" testId="td-journal-flags"><ExitFlags flags={c.flags} /></Block>
        <Block title="Stop history" testId="td-journal-stops" note={c.currentStop != null ? `in force ${fmtPrice(c.currentStop)}` : undefined}><StopHistory t={c} /></Block>
        <Block title="The record" testId="td-journal-record">
          <Kv testPrefix="td-journal-rec" rows={[
            ["Entry rule", entryRuleLine(c), "rule"],
            ["Entry", `${c.entryStatus ? ENTRY_STATUS_WORD[c.entryStatus] : "not recorded"}${c.entrySession ? ` · ${fmtDay(c.entrySession)}` : ""}${c.simEntryPrice != null ? ` · simulated at ${fmtPrice(c.simEntryPrice)}` : ""}`, "entry"],
            ["Exit rule", `stop ${fmtPrice(c.currentStop ?? c.stop)}, target ${c.target != null ? fmtPrice(c.target) : "none"}${c.maxHoldSessions != null ? `, or the close of session ${c.maxHoldSessions} held` : ""}; a session touching both takes the stop`, "exit-rule"],
            ["Exit", c.status === "closed" ? `${exitW?.label ?? c.exitReasonCode ?? "—"}${c.exitSession ? ` · ${fmtDay(c.exitSession)}` : ""}${c.exitPrice != null ? ` · ${fmtPrice(c.exitPrice)}` : ""}` : "Open", "exit"],
            ["Research exit rules", c.exitRules.length ? c.exitRules.map((r) => `${r.label}${r.version ? ` (${r.version})` : ""} · opt-in research rule`).join("; ") : "None: stop, target and time only", "exit-rules"],
            ["MFE · MAE", `${c.mfePct != null ? fmtPct(c.mfePct, { signed: true, digits: 2 }) : "—"} · ${c.maePct != null ? fmtPct(c.maePct, { signed: true, digits: 2 }) : "—"}`, "excursion"],
            ["Signal", `${c.signalAt ? stamp(c.signalAt) : c.source?.signalDate ? `${fmtDay(c.source.signalDate)} (scan date)` : "not recorded"}${c.source?.kind ? ` · ${c.source.kind}${c.source.bucket ? ` ${c.source.bucket.replace(/_/g, " ")}` : ""}` : ""}`, "signal"],
            ["Versions", `rules ${c.rulesVersion ?? "not recorded"}${c.exitRulesVersion ? ` · exits ${c.exitRulesVersion}` : ""}`, "versions"],
          ]} />
        </Block>
      </>
    );
  } else {
    const s = item.t;
    body = (
      <>
        <Block title="Structure" testId="td-journal-structure" note={s.summaryText}>
          <StructureFigures t={s} />
          <LegTable t={s} testId="td-journal-legs" />
        </Block>
        <Block title="Lifecycle" testId="td-journal-timeline" note="append-only"><Timeline transitions={s.transitions} events={s.events} /></Block>
        <Block title="P/L bridge" testId="td-journal-bridge">
          <PnlBridge gross={s.grossRs} costs={s.costsRs} net={s.netRs} breakdown={s.costsBreakdown} model={s.costModel} basis={s.costsBasis} open={open} />
        </Block>
        <Block title="Exit flags" testId="td-journal-flags"><ExitFlags flags={s.flags} /></Block>
        <Block title="The record" testId="td-journal-record">
          <Kv testPrefix="td-journal-rec" rows={[
            ["Exit rule", [s.stopUnderlying != null ? `stop ${s.underlying} ${fmtPrice(s.stopUnderlying)}` : null, s.targetUnderlying != null ? `target ${fmtPrice(s.targetUnderlying)}` : null, s.maxHoldSessions != null ? `or session ${s.maxHoldSessions} held` : null, "or when every leg has expired"].filter(Boolean).join(", "), "exit-rule"],
            ["Exit", s.status === "closed" ? `${EXIT_WORDS[s.exitReasonCode ?? ""]?.label ?? s.exitReasonCode ?? "—"}${s.exitSession ? ` · ${fmtDay(s.exitSession)}` : ""}${s.exitNote ? ` · ${s.exitNote}` : ""}` : "Open", "exit"],
            ["Roll", s.rolledFrom ? `rolled from ${s.rolledFrom}` : s.rolledTo ? `rolled to ${s.rolledTo}` : "not rolled", "roll"],
            ["Signal", `${stamp(s.signal.signalAt)} · rules ${s.signal.ruleVersion ?? "—"}${s.signal.evidenceSummary ? ` · ${s.signal.evidenceSummary}` : ""}`, "signal"],
            ["Versions", `rules ${s.rulesVersion ?? "not recorded"}`, "versions"],
          ]} />
        </Block>
      </>
    );
  }

  return (
    <div data-testid="td-journal-root" style={{ position: "fixed", inset: 0, zIndex: 60 }}>
      <div data-testid="td-journal-backdrop" onClick={onClose} style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.55)" }} />
      <aside role="dialog" aria-modal="true" aria-label={`Trade journal · ${symbol}`} data-testid="td-journal" data-id={t.id} data-kind={item.kind}
        style={{ position: "absolute", top: 0, bottom: 0, right: 0, width: mobile ? "100%" : "min(720px, 94vw)", background: "var(--bg-1)", borderLeft: mobile ? undefined : "1px solid var(--line-2)", display: "flex", flexDirection: "column", minWidth: 0 }}>
        <div className="flex items-center justify-between" style={{ padding: "12px 16px", borderBottom: "1px solid var(--cp-line)", gap: 12 }}>
          <span className="cp-eyebrow">Trade journal · paper trade {t.id}</span>
          <button ref={closeRef} type="button" data-variant="ghost" className="cp-btn" onClick={onClose} data-testid="td-journal-dismiss" aria-label="Close the trade journal">Close ✕</button>
        </div>
        <div className="flex min-w-0 flex-col" style={{ gap: 14, padding: 16, overflowY: "auto", overflowX: "hidden", flex: 1 }}>
          <div className="flex flex-wrap items-start justify-between" style={{ gap: 12 }}>
            <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
              <StatePill state={t.state} fallback={open ? "open" : "closed"} testId="td-journal-state" />
              <span data-testid="td-journal-title" style={{ fontFamily: "var(--display)", fontSize: mobile ? 21 : 25, lineHeight: 1.15, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{title}</span>
              <span style={quiet}>{t.openedAt ? `Recorded ${fmtStamp(t.openedAt)}` : ""}{planId ? ` · plan ${planId}` : " · no trade plan cited"}</span>
            </div>
            <span className="flex flex-col items-end" style={{ gap: 2 }}>
              <Pnl rs={t.netRs} testId="td-journal-net" big />
              <span style={{ ...quiet, fontSize: 10.5 }}>net, before income tax</span>
            </span>
          </div>
          <div className="flex flex-wrap items-start" style={{ gap: 8 }}>
            <button type="button" className="cp-chip" data-testid="td-journal-chart" onClick={() => onChart(symbol)} style={{ padding: "4px 12px", fontSize: 12 }}>Chart · {symbol} ›</button>
            {planId && (
              <button type="button" className="cp-chip" data-testid="td-journal-plan" aria-expanded={plan} onClick={() => setPlan((v) => !v)} style={{ padding: "4px 12px", fontSize: 12 }}>
                {plan ? "Hide the plan" : `Plan ${planId}`}
              </button>
            )}
            {item.kind === "strategy" && open && <RollAction t={item.t} testPrefix="td-journal-roll" />}
            {open && (
              <CloseAction id={t.id}
                label={item.kind === "cash" && item.t.entryStatus === "waiting" ? "Cancel paper trade" : "Close at the last close"}
                what={item.kind === "cash"
                  ? item.t.entryStatus === "waiting" ? `Cancel the ${symbol} paper trade? Its entry has not been reached, so there is no position and no P/L.` : `Close the ${symbol} paper trade at its last end-of-day close${item.t.lastClose != null ? ` (${fmtPrice(item.t.lastClose)})` : ""}?`
                  : `Close the ${symbol} structure at the last end-of-day marks of its legs?`} />
            )}
          </div>
          {plan && planId && (
            <div data-testid="td-journal-plan-card" className="flex flex-col" style={{ gap: 4 }}>
              <span className="cp-eyebrow">The trade plan it records</span>
              <DecisionCardById planId={planId} testId="td-journal-dc" />
            </div>
          )}
          {body}
          <span style={{ ...quiet, fontSize: 11 }}>{PAPER_ONLY}</span>
        </div>
      </aside>
    </div>
  );
}
