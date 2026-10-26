/**
 * F&O lab · 09 Live Trading Desk (?screen=live). Design: the "Live Trading Desk" screen of Nivesh F&O Desk, today state.
 *
 * This build has no order path (the broker adapters are read-only by construction, enforced by
 * tests/test_order_path_guard.py), so the screen is the live readiness gate of PRD §21. The twelve conditions come from
 * GET /api/risk/live-readiness (governance-data.ts useLiveReadiness), each pass / fail with the evidence the server read
 * (gate flag, live feed, live grant, kill switch, stored decisions) and the backlog item that closes it. If that read
 * fails the screen says so; it never falls back to fixed text. The source cards read GET /api/risk/status
 * (tradingdesk/risk-controls.ts). There is no authorise button and no order ticket. The Kite sessions panel
 * (./KiteSessions) offers the two logins that exist: the admin's daily platform login and the user's own read-only
 * Zerodha connection.
 */
import { LoadingBlock, Pill, Section } from "../../components/ui";
import { QueryProblem } from "../trading/parts";
import { useRiskStatus, type RiskStatus } from "../tradingdesk/risk-controls";
import { useLiveReadiness } from "./governance-data";
import { KiteSessions } from "./KiteSessions";
import { GapNote, Mark, SourceCards, type SourceItem } from "./parts";

const SOURCES = (st: RiskStatus | undefined): SourceItem[] => [
  { k: "Order adapter", sub: "Read-only · no order methods", tone: "danger" },
  { k: "OMS", sub: "State machine + paper store · no broker adapter · P3.2", tone: "amber" },
  { k: "F&O risk gate", sub: st?.gateEnabled ? `${st.gatePolicyVersion ?? "fno-risk-v1"} · on for you` : `${st?.gatePolicyVersion ?? "fno-risk-v1"} · off for you`, tone: "amber" },
  { k: "Kill switch", sub: !st || !st.known ? "State unknown" : st.killSwitch ? "On · blocks new paper positions" : "Off · cannot cancel or flatten", tone: st?.known && st.killSwitch ? "danger" : "amber" },
  { k: "Certification", sub: "No records · P3.1", tone: "danger" },
];

export function LiveDesk() {
  const q = useRiskStatus();
  const st = q.data;
  const r = useLiveReadiness();
  const ready = r.data;
  const live = ready ? ready.liveExecutionAvailable : st?.liveExecutionAvailable === true;
  const total = ready?.count ?? 12;
  return (
    <div className="flex flex-col" style={{ gap: 14 }}>
      <SourceCards items={SOURCES(st)} />
      <KiteSessions />
      <Section title="Live readiness gate · PRD §21" note={ready ? <Pill tone={ready.enforceable === ready.count ? "mint" : "amber"}>{ready.enforceable} of {ready.count} enforceable</Pill> : undefined}>
        <div className="flex flex-col" style={{ gap: 12 }}>
          <span data-testid="fnolab-live-headline" data-live={String(live)} style={{ fontFamily: "var(--display)", fontSize: 28, lineHeight: 1.1 }}>
            {live
              ? <>The server reports live execution available, but this build has <span style={{ color: "var(--amber)" }}>no order path</span>.</>
              : <>Live orders are off. <span style={{ color: "var(--amber)" }}>{ready && ready.enforceable > 0 ? `${ready.count - ready.enforceable} of the ${total} conditions` : `None of the ${total} conditions`}</span> {ready && ready.enforceable > 0 ? "still fail." : "can be enforced yet."}</>}
          </span>
          <span style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 760 }}>
            Each row is read from the server now: what exists today, the evidence it was judged on, and the backlog item that closes the gap. Neither the agent nor an operator can waive a condition, and an unreadable value is a fail, never a pass.
          </span>
          {r.isPending && <LoadingBlock label="Reading the live readiness conditions" rows={3} />}
          {r.isError && <QueryProblem what="The live readiness conditions" error={r.error} onRetry={() => void r.refetch()} />}
          {ready && (
            <div data-testid="fnolab-live-gate" data-read-at={ready.readAt ?? ""} className="flex flex-col">
              {ready.conditions.map((c, i) => (
                <div key={c.id} data-testid="fnolab-live-row" data-id={c.id} data-status={c.status} data-tag={c.backlog ?? ""} className="grid" style={{ gridTemplateColumns: "22px minmax(0,1fr) auto", gap: 10, padding: "10px 0", borderTop: "1px solid var(--cp-line)", alignItems: "start" }}>
                  <Mark kind={c.status === "pass" ? "ok" : "fail"} />
                  <span className="flex flex-col" style={{ gap: 2, minWidth: 0 }}>
                    <span style={{ fontSize: 13.5 }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-4)", marginRight: 8 }}>{String(i + 1).padStart(2, "0")}</span>
                      {c.label}
                    </span>
                    <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{c.evidence}</span>
                  </span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--amber)" }}>{c.backlog}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </Section>
      <GapNote tag="P3.2" title="No strategy order ticket and no blotter" testId="fnolab-live-gap">
        The design's strategy order ticket, its OMS states and the live blotter need a broker order adapter (Kite Connect), reconciliation and certification. Until every condition above is enforced, there is no authorise button anywhere in the product.
      </GapNote>
    </div>
  );
}
