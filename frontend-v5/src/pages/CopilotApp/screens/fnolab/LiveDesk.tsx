/**
 * F&O lab · 09 Live Trading Desk (?screen=live). Design: the "Live Trading Desk" screen of Nivesh F&O Desk, today state.
 *
 * This build has no order path (the broker adapters are read-only by construction, enforced by
 * tests/test_order_path_guard.py), so the screen is the live readiness gate of PRD §21: twelve conditions, where each
 * stands today and the backlog item that closes it. None is enforceable, so the count is 0 of 12. Three rows read live
 * state from GET /api/risk/status (tradingdesk/risk-controls.ts): the kill switch, the policy gate for this account and
 * the admin-granted live authorization. `live_execution_available: false` reads "Live orders are off".
 * There is no authorise button and no order ticket. The Kite sessions panel (./KiteSessions) offers the two logins that
 * exist: the admin's daily platform login and the user's own read-only Zerodha connection.
 */
import { LoadingBlock, Pill, Section } from "../../components/ui";
import { QueryProblem } from "../trading/parts";
import { useRiskStatus, type RiskStatus } from "../tradingdesk/risk-controls";
import { KiteSessions } from "./KiteSessions";
import { GapNote, Mark, SourceCards, type SourceItem } from "./parts";

interface GateRow { k: string; today: string; tag: string }

function rows(st: RiskStatus | undefined): GateRow[] {
  const gate = !st ? "state unknown" : st.gateEnabled == null ? "state not reported" : st.gateEnabled ? "on for your account" : "off for your account";
  const kill = !st || !st.known ? "state unknown" : st.killSwitch ? "ON" : "off";
  const la = !st ? "state unknown" : st.liveAuthorization?.granted ? "granted" : "not granted";
  return [
    { k: "Agent version certified", today: "No certification service", tag: "P3.1" },
    { k: "Strategy template certified", today: "No strategy certification", tag: "P3.1" },
    { k: "Contract in certified universe", today: "No universe scope record", tag: "P3.1" },
    { k: "Broker, account and adapter certified", today: "Broker adapters are read-only; no order methods exist", tag: "P3.2" },
    { k: "Risk policy matches certification", today: `${st?.gatePolicyVersion ?? "fno-risk-v1"} gate exists (${gate}); no certification to match it against`, tag: "P3.1" },
    { k: "Market data fresh and complete", today: "Index options are subscribed on the live feed (NIFTY and BANKNIFTY, 2 expiries, ATM ±15) with quotes cached per contract; stock options are not on the feed, and there is no freshness check before a decision", tag: "P0.1" },
    { k: "Pricing, payoff, Greeks, margin pass", today: "Margin needs the platform's daily Kite login; no margin buffer view", tag: "P1.1" },
    { k: "Portfolio risk checks pass", today: "The gate caps lots, legs, open structures and capital at risk; no portfolio Greeks or stress tests", tag: "P1.2" },
    { k: "User authorisation present", today: `Admin-granted live authorization exists (${la}); no order confirmation flow`, tag: "P3.2" },
    { k: "OMS and reconciliation healthy", today: "OMS state machine and idempotent paper store exist; no broker adapter and no reconciliation", tag: "P3.2" },
    { k: "Kill switch inactive and available", today: `Kill switch ${kill}; it blocks new paper positions and cannot cancel or flatten`, tag: "P0.4" },
    { k: "Evidence persisted", today: "Every gate decision is persisted with a correlation id; no snapshot store", tag: "P0.3" },
  ];
}

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
  const live = st?.liveExecutionAvailable === true;
  const list = rows(st);
  return (
    <div className="flex flex-col" style={{ gap: 14 }}>
      <SourceCards items={SOURCES(st)} />
      <KiteSessions />
      <Section title="Live readiness gate · PRD §21" note={<Pill tone="amber">0 of 12 enforceable</Pill>}>
        <div className="flex flex-col" style={{ gap: 12 }}>
          <span data-testid="fnolab-live-headline" data-live={String(live)} style={{ fontFamily: "var(--display)", fontSize: 28, lineHeight: 1.1 }}>
            {live
              ? <>The server reports live execution available, but this build has <span style={{ color: "var(--amber)" }}>no order path</span>.</>
              : <>Live orders are off. <span style={{ color: "var(--amber)" }}>None of the 12 conditions</span> can be enforced yet.</>}
          </span>
          <span style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 760 }}>
            Each row shows what exists today and the backlog item that closes the gap. Neither the agent nor an operator can waive a condition, and no row is marked passed while the order path is missing.
          </span>
          {q.isPending && <LoadingBlock label="Reading your risk status" rows={1} />}
          {q.isError && <QueryProblem what="Your risk status" error={q.error} onRetry={() => void q.refetch()} />}
          <div data-testid="fnolab-live-gate" className="flex flex-col">
            {list.map((g, i) => (
              <div key={g.k} data-testid="fnolab-live-row" data-tag={g.tag} className="grid" style={{ gridTemplateColumns: "22px minmax(0,1fr) auto", gap: 10, padding: "10px 0", borderTop: "1px solid var(--cp-line)", alignItems: "start" }}>
                <Mark kind="fail" />
                <span className="flex flex-col" style={{ gap: 2, minWidth: 0 }}>
                  <span style={{ fontSize: 13.5 }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-4)", marginRight: 8 }}>{String(i + 1).padStart(2, "0")}</span>
                    {g.k}
                  </span>
                  <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{g.today}</span>
                </span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--amber)" }}>{g.tag}</span>
              </div>
            ))}
          </div>
        </div>
      </Section>
      <GapNote tag="P3.2" title="No strategy order ticket and no blotter" testId="fnolab-live-gap">
        The design's strategy order ticket, its OMS states and the live blotter need a broker order adapter (Kite Connect), reconciliation and certification. Until every condition above is enforced, there is no authorise button anywhere in the product.
      </GapNote>
    </div>
  );
}
