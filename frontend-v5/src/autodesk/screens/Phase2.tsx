/**
 * Screens of the design whose data needs paper execution (orders, fills, positions, P&L) or later services. They keep
 * their place in the navigation and say what they will show; they never show sample figures.
 */
import { Link } from "react-router-dom";
import { useIsMobile } from "../hooks";
import { screenById, screenNo, type ScreenId } from "../nav";
import { Card, PhaseNote, ScreenHeader } from "../ui";

const COPY: Partial<Record<ScreenId, { title: string; what: string; today: string; links: [ScreenId, string][] }>> = {
  workbench: {
    title: "From signal to plan, step by step.",
    what: "The workbench will let you take a signal, compare strategies priced from the option chain, and edit a plan version by version before it goes to risk.",
    today: "Today the Trading Assistant builds the plans itself; each plan, its versions and its risk report are shown in the Approval queue.",
    links: [["scanner", "Opportunity scanner"], ["approvals", "Approval queue"]],
  },
  trades: {
    title: "Active trades start with paper execution.",
    what: "This screen will list each open trade with its orders, fills, stops, targets and lifecycle events.",
    today: "Phase 1 has no orders, fills or positions: plans end at approval. Approved plans are in the Approval queue.",
    links: [["approvals", "Approval queue"]],
  },
  pnl: {
    title: "Real-time P&L needs fills.",
    what: "This screen will show paper P&L after estimated charges, by trade, strategy and agent, through the session.",
    today: "Nothing is executed in Phase 1, so there is no P&L to show yet.",
    links: [["overview", "Desk overview"]],
  },
  risk: {
    title: "Capital and risk, itemised.",
    what: "This screen will show capital reserved and deployed, margin, open risk and how close each limit is, across positions.",
    today: "Today every plan is checked against the policy by the risk engine before approval; the checks are in each approval request.",
    links: [["approvals", "Approval queue"], ["policies", "Policies & permissions"]],
  },
  middle: {
    title: "An independent controller.",
    what: "The middle office will show breaches, reconciliation items and a replay of any workflow from its stored events.",
    today: "Today the Middle Office agent's approval decisions, with their reasons, are in the Approval queue and the Agent command centre.",
    links: [["agents", "Agent command centre"], ["approvals", "Approval queue"]],
  },
  fleet: {
    title: "Fleet health and incidents.",
    what: "This screen will show incidents, feed lag, recovery drills and each agent's reliability over time.",
    today: "Each agent's status, version and recent tasks are in the Agent command centre.",
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
        <PhaseNote testId="phase2-note">{c?.what ?? "This screen arrives with paper execution."} It needs paper execution, which comes in Phase 2.</PhaseNote>
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
