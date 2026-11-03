/**
 * The Copilot's trade idea for a stock — the `trade_plan` card (backend services/copilot_trade_idea.py; owner, 29 Oct:
 * "User can ask any questions about a stocks and we can put idea how to trade if conditions are favourable and signals
 * are recieved").
 *
 * The server sends it only when the desk's own plan for the stock has a setup (`plan`) or a setup waiting for its
 * confirmation (`wait`), and it carries only ids and labels: every level shown comes from the desk's DecisionCard,
 * which reads the stored TradePlan by id (GET /api/desk/trade-plans/{id}) and the risk service's sizing for this
 * account. So the chat and the desk can never show two versions of one plan, and a thread reopened later reads the
 * same plan again.
 *
 *   header      the stock, "Setup found" / "Waiting for confirmation", the view (with "assumed" when the user did not
 *               say it) and the horizon
 *   wait        the builder's reasons and what would change them
 *   plan        compact, as the desk's AI recommendations show it (owner, 29 Oct): the preferred plan's DecisionCard row
 *               (enter · exit if wrong · targets · size · max loss · charges · hold for, in plain words); "Full card ›"
 *               opens the whole card; the other plans that fit, as links
 *   actions     "Paper trade ›" (the plan's paper-trade ticket in Strategy Lab, ?tab=trade&view=lab&sub=build&tp=<id>)
 *               and "Plan a <other> trade instead" (asks the Copilot again)
 *
 * Ideas, not recommendations; nothing is sent to a broker. No new screen: the ticket is the desk's own.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { viewPath } from "@/pages/CopilotApp/lib/views";
import { fmtDay } from "@/pages/CopilotApp/screens/trading/parts";
import { DecisionCardById } from "@/pages/CopilotApp/screens/tradingdesk/decision/DecisionCard";

type Action = { intent?: string; label?: string; query?: string };

interface PlanRow { plan_id: string; label?: string | null; segment?: string | null; family?: string | null; status?: string | null; preferred?: boolean }
export interface TradeIdeaData {
  symbol?: string;
  status?: "plan" | "wait" | string;
  status_reasons?: Array<{ code?: string | null; message?: string | null }>;
  would_change_if?: string[];
  direction?: string | null;
  direction_stated?: boolean;
  horizon?: string | null;
  horizon_days?: number | null;
  plans?: PlanRow[];
  preferred_plan_id?: string | null;
  data_as_of?: { price?: string | null; fno?: string | null };
}

const VIEW: Record<string, string> = { bullish: "Long view", bearish: "Short view", neutral: "Range-bound view" };
const OTHER: Record<string, string> = { bullish: "bearish", bearish: "bullish", neutral: "bullish" };
const SEGMENT: Record<string, string> = { cash: "shares", futures: "futures", options: "options", combination: "shares + options" };

/** The desk's chart for one TradePlan (Trade Desk › Chart Analysis with the plan's levels and its paper basket; Strategy Lab was removed on 29 Oct). */
export const labTicketPath = (planId: string, symbol?: string | null) =>
  viewPath(`trader/desk?tab=trade&view=chart&sub=live${symbol ? `&sym=${encodeURIComponent(symbol.toUpperCase())}` : ""}&tp=${encodeURIComponent(planId)}`);

const quiet = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;
const link = { fontSize: 12.5, fontWeight: 600, color: "var(--mint)", textDecoration: "none" } as const;

export function TradePlanChatCard({ data, onAction }: { data: TradeIdeaData; onAction?: (a: Action) => void }) {
  const [full, setFull] = useState(false);
  const symbol = data.symbol ?? "—";
  const plans = (data.plans ?? []).filter((p) => p && typeof p.plan_id === "string" && p.plan_id);
  const preferred = data.preferred_plan_id ?? plans[0]?.plan_id ?? null;
  const others = plans.filter((p) => p.plan_id !== preferred);
  const waiting = data.status === "wait";
  const dir = data.direction ?? "";
  const other = OTHER[dir];
  const reasons = (data.status_reasons ?? []).map((r) => r?.message).filter((m): m is string => !!m);
  const asOf = data.data_as_of ?? {};

  return (
    <div data-testid="tpc" data-status={data.status ?? ""} className="flex min-w-0 flex-col" style={{ gap: 10, padding: 12, borderRadius: 14, border: "1px solid var(--line-2)", background: "var(--bg-2)" }}>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 10px" }}>
        <span className="cp-eyebrow" style={{ fontSize: 9.5, color: "var(--mint)" }}>Trade idea</span>
        <strong data-testid="tpc-symbol" style={{ fontSize: 15 }}>{symbol}</strong>
        <span data-testid="tpc-status" className="cp-pill" style={{ color: waiting ? "var(--amber)" : "var(--mint)", flex: "none" }}>
          {waiting ? "Waiting for confirmation" : "Setup found"}
        </span>
      </div>
      <span data-testid="tpc-view" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>
        {VIEW[dir] ?? "View unavailable"}{data.direction_stated === false ? " · assumed (you did not say)" : ""}
        {data.horizon ? ` · ${data.horizon}${data.horizon_days ? `, about ${data.horizon_days} sessions` : ""}` : ""}
      </span>

      {waiting && (reasons.length > 0 || (data.would_change_if ?? []).length > 0) && (
        <ul data-testid="tpc-reasons" className="m-0" style={{ paddingLeft: 16, ...quiet }}>
          {reasons.map((m, i) => <li key={`r${i}`} data-testid="tpc-reason">{m}</li>)}
          {(data.would_change_if ?? []).map((m, i) => <li key={`w${i}`} data-testid="tpc-would-change">Would change if {m.replace(/^[a-z_]+:\s*/, "")}</li>)}
        </ul>
      )}

      {preferred ? <DecisionCardById key={full ? "full" : "row"} planId={preferred} testId="tpc-plan" variant={full ? "full" : "row"} budgets={!full} />
        : <span data-testid="tpc-no-plan" style={quiet}>No trade plan with levels came with this idea.</span>}

      {others.length > 0 && (
        <div data-testid="tpc-others" className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 12px", ...quiet }}>
          <span>Also fits:</span>
          {others.map((p) => (
            <Link key={p.plan_id} data-testid="tpc-other" to={labTicketPath(p.plan_id, data.symbol)} style={{ ...link, fontWeight: 500 }}>
              {p.label ?? p.family ?? p.plan_id}{p.segment ? ` (${SEGMENT[p.segment] ?? p.segment})` : ""} ›
            </Link>
          ))}
        </div>
      )}

      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "6px 14px" }}>
        {preferred && (
          <button type="button" data-testid="tpc-full" className="cp-btn" data-variant="ghost" aria-expanded={full} onClick={() => setFull((x) => !x)}>
            {full ? "Compact card" : "Full card ›"}
          </button>
        )}
        {preferred && <Link data-testid="tpc-open-lab" to={labTicketPath(preferred, data.symbol)} className="cp-btn" data-variant="ghost" style={{ textDecoration: "none" }}>Paper trade ›</Link>}
        {other && onAction && (
          <button type="button" data-testid="tpc-flip" className="cp-btn" data-variant="ghost"
            onClick={() => onAction({ query: `Plan a ${other} trade for ${symbol} instead` })}>
            Plan a {other} trade instead
          </button>
        )}
      </div>

      <span data-testid="tpc-foot" style={{ ...quiet, fontSize: 11 }}>
        Built by the desk&rsquo;s rules from end-of-day prices ({fmtDay(asOf.price)}{asOf.fno ? `; options ${fmtDay(asOf.fno)}` : ""}) and sized by your risk profile.
        Enter only when the entry condition is met. An idea to review, not a recommendation; nothing is sent to a broker.
      </span>
    </div>
  );
}
