/**
 * StreamStatus — the copilot's visible reasoning while an answer streams, and
 * the follow-up chips after it. Everything here renders data the stream ALREADY
 * carries (see backend/routes/chat.py):
 *
 *   route    → <AgentRibbon>   which specialist answered ("Risk Advisor")
 *   thinking → <ThinkingSteps> tool steps as they start and finish
 *   done     → <FollowUps>     up to three next questions to tap
 *
 * Shared by the full chat page and the CopilotDock so both stay identical.
 */
import { ArrowUpRight, Check, Loader2, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

export type ThinkingStep = { tool: string; done: boolean };

const AGENT_LABELS: Record<string, string> = {
  auto: "Copilot",
  portfolio_analyst: "Portfolio Analyst",
  risk_advisor: "Risk Advisor",
  tax_advisor: "Tax Advisor",
  fund_researcher: "Fund Researcher",
  goal_planner: "Goal Planner",
  market_analyst: "Market Analyst",
  stock_analyst: "Stock Analyst",
  mf_analyst: "Fund Analyst",
  backtest_analyst: "Backtest Analyst",
  stocks_insights: "Filings Analyst",
};

/** Human label for a backend agent id; unknown ids are title-cased. */
export function agentLabel(id?: string | null): string | null {
  if (!id) return null;
  const key = String(id).toLowerCase();
  if (AGENT_LABELS[key]) return AGENT_LABELS[key];
  return key.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const TOOL_LABELS: Record<string, string> = {
  portfolio: "Reading your holdings",
  get_portfolio: "Reading your holdings",
  get_portfolio_holdings: "Reading your holdings",
  holdings: "Reading your holdings",
  concentration: "Measuring concentration",
  overlap: "Checking fund overlap",
  fund_overlap: "Checking fund overlap",
  risk: "Scoring risk",
  risk_overview: "Scoring risk",
  technical: "Reading the technicals",
  fundamental: "Reading the fundamentals",
  mf: "Looking up the fund",
  sip: "Working out the SIP",
  tax: "Computing tax impact",
  goal: "Checking your goals",
  market: "Reading market context",
  screener: "Running the screen",
  backtest: "Running the backtest",
  stocks_insights: "Reading the filings",
};

/** Human label for a tool name: known tools get a verb phrase, the rest are
 *  de-snaked ("get_quarterly_results" → "Quarterly results"). */
export function toolLabel(tool: string): string {
  const key = String(tool || "").toLowerCase();
  if (TOOL_LABELS[key]) return TOOL_LABELS[key];
  const words = key
    .replace(/^(get|fetch|compute|run|load|build)_/, "")
    .replace(/[_-]+/g, " ")
    .trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Working";
}

export function AgentRibbon({ agent, confidence, className }: { agent?: string | null; confidence?: number | null; className?: string }) {
  const label = agentLabel(agent);
  if (!label) return null;
  const pct = typeof confidence === "number" && confidence > 0 ? Math.round(Math.min(1, confidence) * 100) : null;
  return (
    <span
      data-testid="agent-ribbon"
      className={cn("inline-flex items-center gap-1.5 rounded-full border border-hairline-2 bg-surface-1 px-2.5 py-1 text-[11px] text-ink-2", className)}
      title={pct != null ? `Routed to ${label} · ${pct}% confidence` : `Routed to ${label}`}
    >
      <Sparkles className="h-3 w-3 text-accent" aria-hidden />
      <span className="font-medium">{label}</span>
      {pct != null && <span className="font-mono text-[10px] text-ink-3">{pct}%</span>}
    </span>
  );
}

export function ThinkingSteps({ steps, className }: { steps: ThinkingStep[]; className?: string }) {
  if (!steps.length) return null;
  return (
    <ol data-testid="thinking-steps" className={cn("flex flex-col gap-1", className)} aria-label="Working">
      {steps.map((s, i) => (
        <li key={s.tool + i} className="flex items-center gap-2 text-[12.5px] text-ink-3">
          {s.done
            ? <Check className="h-3.5 w-3.5 text-accent shrink-0" aria-hidden />
            : <Loader2 className="h-3.5 w-3.5 animate-spin text-ink-3 shrink-0" aria-hidden />}
          <span className={s.done ? "text-ink-3" : "text-ink-2"}>{toolLabel(s.tool)}{s.done ? "" : "…"}</span>
        </li>
      ))}
    </ol>
  );
}

export function FollowUps({ items, onPick, disabled, className }: { items: string[]; onPick: (q: string) => void; disabled?: boolean; className?: string }) {
  const list = items.filter((q) => typeof q === "string" && q.trim()).slice(0, 3);
  if (!list.length) return null;
  return (
    <div data-testid="follow-ups" className={className}>
      <div className="font-mono text-[10px] uppercase tracking-[.18em] text-ink-3 mb-2">Ask next</div>
      <div className="flex flex-wrap gap-2">
        {list.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            disabled={disabled}
            className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 border border-hairline px-3 py-1.5 text-[12.5px] text-ink-2 hover:bg-surface-3 hover:text-ink disabled:opacity-50 transition-colors text-left"
          >
            <span>{q}</span>
            <ArrowUpRight className="h-3 w-3 text-accent shrink-0" aria-hidden />
          </button>
        ))}
      </div>
    </div>
  );
}

/** Fold one `thinking` frame into the step list: `start` appends a running
 *  step (once), `end` ticks the matching running step. */
export function stepUpdate(steps: ThinkingStep[], tool?: string, status?: string): ThinkingStep[] {
  const name = tool || "tool";
  if (status === "end") return steps.map((s) => (s.tool === name && !s.done ? { ...s, done: true } : s));
  if (steps.some((s) => s.tool === name && !s.done)) return steps;
  return [...steps, { tool: name, done: false }];
}
