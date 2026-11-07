/**
 * Risk Desk › Trading overview (?tab=risk&view=overview) — the Scanner-to-Paper Trading account at a glance (PRD §12.1,
 * §19.2; Workflow §19; owner, 5 Nov 2026: plain, functional screens on real data, restyled later).
 *
 *   KPI strip            equity (with the API's basis), available cash, deployed, reserved by pending entries, unrealized and
 *                        realized P&L, the day's P&L                       GET /api/v1/risk/account/{id} + /paper/positions
 *   01 Risk vs limits    SPT planned and stressed risk, open risk vs its cap, daily / weekly loss used vs the limit, drawdown
 *   02 Drawdown & switch the ladder band with its thresholds, the kill-switch state and its reasons
 *   03 Activity          qualified opportunities, proposals awaiting approval, open positions, pending orders, new today;
 *                        links to Trade Desk › Paper Trading › Opportunities and the P&L dashboard
 *   04 Risk warnings     every warning the risk engine states (kill-switch reasons, unknown equity, unpriced entries)
 *
 * Refreshed every 30 s. Nothing is invented: a null figure reads "—" with the API's reason. Reads only.
 */
import { LoadingBlock, Pill, signTone } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { QueryProblem } from "../../../trading/parts";
import { stampIst } from "../../overview-data";
import { Card } from "../../RiskControls";
import { Kpi, UseBar, ViewHead, quiet } from "./parts";
import {
  AWAITING, realizedOf, unrealizedOf, useSptAwaiting, useSptLiveOrders, useSptPositions, useSptQualifiedCount, useSptRiskAccount,
  type SptAccount, type SptRiskAccount,
} from "./spt-risk-api";
import {
  BandPill, DASH, FigList, FigRow, KillSwitchPill, LadderBands, MODE_WORDS, ModePill, PaperLink, SourceNote, SptAccountGate, Warnings,
  fig, ksTone, lossTone, pct2, rs, usedOf,
} from "./spt-risk-parts";

function headline(a: SptRiskAccount | undefined): string {
  if (!a) return "Your scanner-to-paper trading account: capital, risk and limits.";
  if (a.error) return "Your paper account could not be read, so its figures are unknown.";
  const eq = a.equityRs == null ? "Paper equity is unknown" : `Paper equity ${rs(a.equityRs)}`;
  const risk = a.sptRisk?.plannedRs == null ? "" : `, open planned risk ${rs(a.sptRisk.plannedRs)}`;
  const band = a.drawdown.ladder.band ? `, drawdown band ${a.drawdown.ladder.band}` : "";
  const ks = a.killSwitch.entriesBlocked ? " — new positions are blocked" : "";
  return `${eq}${risk}${band}${ks}.`;
}

function Figures({ a }: { a: SptRiskAccount }) {
  const { mobile } = useCopilotShell();
  const open = useSptPositions("open");
  const all = useSptPositions("all");
  const unreal = open.data ? unrealizedOf(open.data.items.filter((p) => p.isOpen)) : null;
  const real = all.data ? realizedOf(all.data.items, all.data.count) : null;
  const pending = a.pending.length;
  return (
    <div className="grid" style={{ gap: 10, gridTemplateColumns: `repeat(auto-fit,minmax(min(100%,${mobile ? 140 : 170}px),1fr))` }}>
      <Kpi k="Account equity" testId="spt-kpi-equity" value={rs(a.equityRs)} note={a.equityRs == null ? "unknown — see the warnings" : "paper cash + positions at their marks"} />
      <Kpi k="Available cash" testId="spt-kpi-available" value={rs(a.availableRs)} note={`paper cash ${rs(a.cashRs)}`} />
      <Kpi k="Deployed capital" testId="spt-kpi-deployed" value={rs(a.deployedRs)} note="in filled positions" />
      <Kpi k="Reserved capital" testId="spt-kpi-reserved" value={rs(a.reservedRs)} note={`${pending} pending entry ${pending === 1 ? "order" : "orders"}`} />
      <Kpi k="Unrealized P&L" testId="spt-kpi-unrealized" tone={signTone(unreal?.rs)}
        value={open.isPending ? "…" : open.isError ? DASH : rs(unreal?.rs ?? null)}
        note={open.isError ? "positions could not be read" : !unreal ? "" : unreal.missing ? `${unreal.missing} open ${unreal.missing === 1 ? "position has" : "positions have"} no live mark and ${unreal.missing === 1 ? "is" : "are"} left out` : "open SPT positions at live marks, net of costs"} />
      <Kpi k="Realized P&L" testId="spt-kpi-realized" tone={signTone(real?.rs)}
        value={all.isPending ? "…" : all.isError ? DASH : rs(real?.rs ?? null)}
        note={all.isError ? "positions could not be read" : !real ? "" : `net of costs, ${real.counted} SPT ${real.counted === 1 ? "position" : "positions"}${real.capped ? " (first 500 only)" : ""}`} />
      <Kpi k="Day's P&L" testId="spt-kpi-day" tone={signTone(a.dailyLoss.pnlRs)} value={rs(a.dailyLoss.pnlRs)}
        note={a.dailyLoss.pnlRs == null ? "unknown (fail closed)" : `loss used ${usedOf(a.dailyLoss.lossPct, a.dailyLoss.limitPct)}`} />
    </div>
  );
}

function RiskVsLimits({ a }: { a: SptRiskAccount }) {
  const s = a.sptRisk;
  const loss = (k: "day" | "week") => {
    const l = k === "day" ? a.dailyLoss : a.weeklyLoss;
    return (
      <FigRow testId={`spt-ov-${k}-loss`} k={k === "day" ? "Daily loss used" : "Weekly loss used"} v={usedOf(l.lossPct, l.limitPct)} tone={lossTone(l.lossPct, l.limitPct)}
        note={<>
          <UseBar used={l.lossPct} limit={l.limitPct} label={k === "day" ? "Daily loss" : "Weekly loss"} />
          <span style={{ display: "block", marginTop: 4 }}>
            {l.pnlRs == null ? "The P&L is unknown, so new positions are blocked (fail closed)." : `P&L ${rs(l.pnlRs)} on a starting equity of ${rs(l.startEquityRs)}${l.breached ? " — at or past the limit" : ""}.`}
          </span>
        </>} />
    );
  };
  return (
    <FigList testId="spt-ov-risk">
      <FigRow testId="spt-ov-planned" k="Open planned risk (SPT)" v={rs(s?.plannedRs)}
        note={s ? `${fig(s.entries, 0)} open SPT ${s.entries === 1 ? "entry" : "entries"}; ${s.basis ?? "basis not sent"}` : "Not sent: the account could not be read."} />
      <FigRow testId="spt-ov-stressed" k="Stressed risk (SPT)" v={rs(s?.stressedRs)}
        note={s ? `planned risk plus a ${fig(s.stressedGapPct)}% gap through every stop` : DASH} />
      <FigRow testId="spt-ov-open-risk" k="Open risk vs limit" v={`${rs(a.openRisk.rs)} of ${rs(a.openRisk.capRs)}`}
        tone={lossTone(a.openRisk.rs, a.openRisk.capRs)}
        note={<>
          <UseBar used={a.openRisk.rs} limit={a.openRisk.capRs} label="Open risk" />
          <span style={{ display: "block", marginTop: 4 }}>
            {pct2(a.openRisk.usedPctOfEquity)} of equity; limit {a.openRisk.limitPct == null ? DASH : `${fig(a.openRisk.limitPct)}%`}. {a.openRisk.basis ?? ""}
          </span>
        </>} />
      {loss("day")}
      {loss("week")}
      <FigRow testId="spt-ov-drawdown" k="Drawdown from peak" v={pct2(a.drawdown.pct)} tone={lossTone(a.drawdown.pct, a.drawdown.profileHaltPct)}
        note={`peak ${rs(a.drawdown.peakRs)}; the risk profile halts at ${a.drawdown.profileHaltPct == null ? DASH : `${fig(a.drawdown.profileHaltPct)}%`}`} />
    </FigList>
  );
}

function DrawdownAndSwitch({ a }: { a: SptRiskAccount }) {
  const ks = a.killSwitch;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 14 }}>
      <LadderBands ladder={a.drawdown.ladder} testId="spt-ov-ladder" />
      <div data-testid="spt-ov-ks" data-state={ks.state ?? "unknown"} className="flex min-w-0 flex-col" style={{ gap: 4 }}>
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <KillSwitchPill state={ks.state} testId="spt-ov-ks-state" />
          {ks.entriesBlocked != null && <Pill tone={ks.entriesBlocked ? "danger" : "mint"}>{ks.entriesBlocked ? "New positions blocked" : "New positions allowed"}</Pill>}
        </span>
        <span data-testid="spt-ov-ks-text" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{ks.text ?? "The API sent no state text."}</span>
        {ks.reason && <span data-testid="spt-ov-ks-reason" style={{ fontSize: 13, lineHeight: 1.5, color: `var(--cp-${ksTone(ks.state) === "danger" ? "danger" : "ink"})`, overflowWrap: "anywhere" }}>{ks.reason}</span>}
        <span style={quiet}>Exits and risk-reducing changes are never blocked by any state.</span>
      </div>
    </div>
  );
}

function Activity({ a, acc }: { a: SptRiskAccount; acc: SptAccount }) {
  const qualified = useSptQualifiedCount();
  const awaiting = useSptAwaiting();
  const open = useSptPositions("open");
  const orders = useSptLiveOrders();
  const u = a.utilisation;
  const n = (q: { isPending: boolean; isError: boolean }, v: string) => (q.isPending ? "…" : q.isError ? DASH : v);
  const entries = orders.data?.filter((o) => o.purpose === "ENTRY").length ?? 0;
  const exits = orders.data?.filter((o) => o.purpose === "EXIT").length ?? 0;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <FigList testId="spt-ov-counts">
        <FigRow testId="spt-ov-qualified" k="Qualified opportunities" v={n(qualified, qualified.data ? `${qualified.data.count}${qualified.data.capped ? "+" : ""}` : DASH)}
          note={qualified.isError ? "could not be read" : "market-wide, before your account's sizing"} />
        <FigRow testId="spt-ov-awaiting" k="Proposals awaiting your approval" v={n(awaiting, String(awaiting.data?.count ?? DASH))}
          note={awaiting.isError ? "could not be read" : acc.mode === "approval" ? `state ${AWAITING}` : `your mode is ${acc.mode ?? "unknown"}; only approval mode asks you`} />
        <FigRow testId="spt-ov-positions" k="Open positions" v={`${fig(u.positionsOpen, 0)} of ${fig(u.positionsMax, 0)}`}
          tone={u.positionsOpen != null && u.positionsMax != null && u.positionsOpen >= u.positionsMax ? "danger" : "ink"}
          note={open.isError ? "SPT positions could not be read" : open.data ? `${open.data.items.filter((p) => p.isOpen).length} of them are SPT paper positions` : ""} />
        <FigRow testId="spt-ov-orders" k="Pending orders" v={n(orders, String(orders.data?.length ?? DASH))}
          note={orders.isError ? "could not be read" : `${entries} ${entries === 1 ? "entry" : "entries"}, ${exits} ${exits === 1 ? "exit" : "exits"}`} />
        <FigRow testId="spt-ov-new-today" k="New positions today" v={`${fig(u.newToday, 0)} of ${fig(u.newTodayMax, 0)}`} />
      </FigList>
      <span className="flex flex-wrap" style={{ gap: "6px 16px" }}>
        <PaperLink sub="opportunities" testId="spt-ov-link-opps">Paper Trading › Opportunities</PaperLink>
        <PaperLink sub="pnl" testId="spt-ov-link-pnl">Paper Trading › P&amp;L dashboard</PaperLink>
      </span>
    </div>
  );
}

function Body({ acc }: { acc: SptAccount }) {
  const { mobile } = useCopilotShell();
  const q = useSptRiskAccount(acc.accountId);
  const a = q.data;
  const mode = a?.mode ?? acc.mode;
  return (
    <>
      <ViewHead view="Trading overview" title={headline(a)} />
      <span data-testid="spt-ov-status" className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <ModePill mode={mode} />
        {a && <KillSwitchPill state={a.killSwitch.state} />}
        {a && <BandPill band={a.drawdown.ladder.band} />}
        {a?.asOf && <span className="cp-mono-note" data-testid="spt-ov-asof">as of {stampIst(a.asOf) ?? a.asOf} · refreshed every 30 s</span>}
      </span>
      {mode === "off" && (
        <p data-testid="spt-ov-mode-off" role="note" className="m-0" style={{ fontSize: 13.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {MODE_WORDS.off}. Turn a mode on in <PaperLink sub="settings" testId="spt-ov-link-settings">Paper Trading › Settings</PaperLink>.
        </p>
      )}
      {q.isPending && <LoadingBlock label="Reading your account's risk" rows={4} />}
      {q.isError && <div data-testid="spt-ov-error"><QueryProblem what="Your account's risk" error={q.error} onRetry={() => { void q.refetch(); }} /></div>}
      {a && (
        <>
          <Figures a={a} />
          <SourceNote testId="spt-ov-equity-basis">Equity basis: {a.equityBasis ?? "not sent"}.</SourceNote>
          <div className="grid" style={{ gap: mobile ? 14 : 18, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", alignItems: "start" }}>
            <Card id="spt-ov-risk" num="01" title="Risk vs limits" testId="spt-ov-risk-card"><RiskVsLimits a={a} /></Card>
            <Card id="spt-ov-dd" num="02" title="Drawdown ladder & kill switch" testId="spt-ov-dd-card"><DrawdownAndSwitch a={a} /></Card>
            <Card id="spt-ov-activity" num="03" title="Activity" testId="spt-ov-activity-card"><Activity a={a} acc={acc} /></Card>
            <Card id="spt-ov-warn" num="04" title="Active risk warnings" testId="spt-ov-warn-card"><Warnings a={a} testId="spt-ov-warnings" /></Card>
          </div>
        </>
      )}
    </>
  );
}

export function TradingOverview() {
  const { mobile } = useCopilotShell();
  return (
    <div data-testid="spt-overview-view" className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
      <SptAccountGate head={<ViewHead view="Trading overview" title={headline(undefined)} />}>{(acc) => <Body acc={acc} />}</SptAccountGate>
    </div>
  );
}
