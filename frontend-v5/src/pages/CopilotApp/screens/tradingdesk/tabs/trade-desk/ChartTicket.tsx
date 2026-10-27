/**
 * Trade Desk › Chart Analysis › Live chart: the paper ticket beside the chart, in place of the old capital × risk-%
 * calculator (PLAN.md §2b.1: the size is the risk service's `account_size`, never a browser slider or calculator).
 *
 *   the plan   ?tp=<plan_id> when the chart was opened from an idea; else today's Top 10 stock idea for this symbol
 *              (POST /api/desk/strategy/ideas via useTop10Stocks, the same cached board Market Overview reads)
 *   the size   GET /api/desk/trade-plans/{id} `account_size` (Ticket, NewTrade.tsx); the answer allow / reduce / block
 *
 * A symbol with no idea today has no plan, so no ticket: that is said, with the way to the ideas. Paper only.
 */
import { useSearchParams } from "react-router-dom";
import { LoadingBlock } from "../../../../components/ui";
import { useDesk } from "../../context";
import { useTop10Stocks } from "../../top10-data";
import { Ticket } from "./NewTrade";
import { Panel, linkBtn, quiet } from "./parts";

export function ChartTicket({ symbol, onIdeas }: { symbol: string; onIdeas: () => void }) {
  const desk = useDesk();
  const [params] = useSearchParams();
  const tp = params.get("tp");
  const board = useTop10Stocks(!tp);
  if (tp) return <div data-testid="td-chart-ticket" data-source="url" className="flex min-w-0 flex-col"><Ticket planId={tp} source={null} onOverview={() => desk.openTab("overview")} /></div>;
  if (board.isPending) return <LoadingBlock label="Looking for this stock's idea" rows={2} />;
  const idea = board.data?.ideas.find((i) => i.symbol?.toUpperCase() === symbol.toUpperCase()) ?? null;
  const planId = (idea as { trade_plan?: { plan_id?: string } | null } | null)?.trade_plan?.plan_id ?? null;
  if (!planId) {
    return (
      <div data-testid="td-chart-ticket" data-source="none" className="flex min-w-0 flex-col">
        <Panel title="Paper ticket" note="sized by the risk service" testId="td-chart-ticket-none">
          <span style={{ ...quiet, fontSize: 13, color: "var(--cp-ink-2)" }}>
            {board.isError ? "Today's ideas could not be read, so no plan is known for " : "No idea with a plan for "}{symbol} today, so there is no ticket: a ticket's size is the risk service's account_size for an idea's plan.{" "}
            <button type="button" data-testid="td-chart-ticket-ideas" style={linkBtn} onClick={onIdeas}>Ranked candidates ›</button>
          </span>
        </Panel>
      </div>
    );
  }
  return <div data-testid="td-chart-ticket" data-source="top10" className="flex min-w-0 flex-col"><Ticket planId={planId} source={null} onOverview={() => desk.openTab("overview")} /></div>;
}
