/**
 * Screens of the design that do not show their data yet. Paper execution records orders, fills, positions, capital and P&L,
 * but these screens do not read them; the rest are not built. They keep their place in the navigation and say what they
 * will show; they never show sample figures.
 */
import { Link } from "react-router-dom";
import { useIsMobile } from "../hooks";
import { screenById, screenNo, type ScreenId } from "../nav";
import { Card, PhaseNote, ScreenHeader } from "../ui";

const COPY: Partial<Record<ScreenId, { title: string; what: string; today: string; note: string; label?: string; links: [ScreenId, string][] }>> = {
  workbench: {
    title: "From signal to plan, step by step.",
    what: "The workbench will let you take a signal, compare strategies priced from the option chain, and edit a plan version by version before it goes to risk.",
    today: "Today the Trading Assistant builds the plans itself; each plan, its versions and its risk report are shown in the Approval queue.",
    note: "This screen is not built yet.",
    label: "Not built yet",
    links: [["scanner", "Opportunity scanner"], ["approvals", "Approval queue"]],
  },
  trades: {
    title: "Paper trades are recorded, not shown here yet.",
    what: "This screen will list each open trade with its orders, fills, stops, targets and lifecycle events.",
    today: "The desk records paper orders, fills and positions for approved plans, but this screen does not read them yet. The desk also closes each position by its plan's rules and records the closed trade. Approved plans are in the Approval queue.",
    note: "The desk records this data; this screen does not show it yet.",
    links: [["approvals", "Approval queue"]],
  },
  pnl: {
    title: "Paper P&L is recorded, not shown here yet.",
    what: "This screen will show paper P&L after estimated charges, by trade, strategy and agent, through the session.",
    today: "The desk records paper P&L after estimated charges for approved plans, but this screen does not read it yet. It is realized P&L of closed positions plus open positions against their cost.",
    note: "The desk records this data; this screen does not show it yet.",
    links: [["overview", "Desk overview"]],
  },
  risk: {
    title: "Capital and risk, itemised.",
    what: "This screen will show capital reserved and deployed, margin, open risk and how close each limit is, across positions.",
    today: "The desk records reserved and deployed capital, margin and open risk for paper positions, but this screen does not read them yet. Daily-loss, weekly-loss and drawdown limits act on paper P&L: a breach refuses new plans, and a drawdown breach suspends the account. Every plan is checked against the policy by the risk engine before approval; the checks are in each approval request.",
    note: "The desk records the capital figures; this screen does not show them yet.",
    links: [["approvals", "Approval queue"], ["policies", "Policies & permissions"]],
  },
  middle: {
    title: "An independent controller.",
    what: "The middle office will show breaches, reconciliation items and a replay of any workflow from its stored events.",
    today: "Today the Middle Office agent's approval decisions, with their reasons, are in the Approval queue and the Agent command centre. The desk also records a capital reconciliation and a journal of each paper trade, which this screen does not show yet. Orders of unknown state are reconciled by the desk.",
    note: "This screen is not built yet; the desk records some of its data.",
    links: [["agents", "Agent command centre"], ["approvals", "Approval queue"]],
  },
  fleet: {
    title: "Fleet health and incidents.",
    what: "This screen will show incidents, feed lag, recovery drills and each agent's reliability over time.",
    today: "Each agent's status, version and recent tasks are in the Agent command centre.",
    note: "This screen is not built yet.",
    label: "Not built yet",
    links: [["agents", "Agent command centre"]],
  },
};

export default function Phase2Screen({ id }: { id: ScreenId }) {
  const mobile = useIsMobile();
  const def = screenById(id);
  const c = COPY[id];
  return (
    <div data-testid={`screen-${id}`} style={{ display: "flex", flexDirection: "column", gap: 24, fontFamily: "var(--sans)", color: "var(--ink)" }}>
      <ScreenHeader mobile={mobile} eyebrow={`${screenNo(id)} · ${def.label}`} title={c?.title ?? def.label} />
      <Card>
        <PhaseNote label={c?.label ?? (c ? "Not shown yet" : "Not built yet")} testId="phase2-note">{c ? `${c.what} ${c.note}` : "This screen is not built yet."}</PhaseNote>
        {c && <span style={{ fontSize: 14, lineHeight: 1.55, color: "var(--ink-2)" }}>{c.today}</span>}
        {c && (
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            {c.links.map(([to, label]) => <Link key={to} to={screenById(to).path} className="ad-link">{label} ›</Link>)}
          </div>
        )}
      </Card>
    </div>
  );
}
