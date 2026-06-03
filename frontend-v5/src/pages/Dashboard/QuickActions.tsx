import { useNavigate } from "react-router-dom";
import { ChevronRight, BarChart2, GitMerge, Zap, ArrowUpRight, Shield, TrendingUp, Scissors } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RiskCategory } from "@/hooks/use-risk-profile";

interface QuickAction {
  icon: React.ElementType;
  label: string;
  sub: string;
  color: string;
  path: string;
}

const ALL_ACTIONS: Record<string, QuickAction> = {
  compare_funds:    { icon: BarChart2,    label: "Compare My Funds",     sub: "Rolling returns · expense · alpha", color: "text-[#3B82F6]", path: "/concentration" },
  detect_overlap:   { icon: GitMerge,     label: "Detect Fund Overlap",  sub: "Are you paying twice for the same stocks?", color: "text-[#8B5CF6]", path: "/diversification" },
  sip_topup:        { icon: Zap,          label: "SIP Top-up Plan",      sub: "Project growth with higher SIP",    color: "text-accent",    path: "/goals" },
  switch_direct:    { icon: Scissors,     label: "Switch to Direct",     sub: "Save 0.6%+ p.a. on expense ratio", color: "text-[#F59E0B]", path: "/recommendations" },
  review_risk:      { icon: Shield,       label: "Review Risk Holdings", sub: "Flag high-risk stocks vs your profile", color: "text-neg",  path: "/risk" },
  tax_harvest:      { icon: Scissors,     label: "Tax Harvest",          sub: "Realise losses before year-end",    color: "text-[#14B8A6]", path: "/tax" },
  equity_screen:    { icon: TrendingUp,   label: "Screen Quality Stocks",sub: "V3 quality score ≥ 70",            color: "text-pos",       path: "/recommendations" },
  rebalance:        { icon: ArrowUpRight, label: "Rebalance Portfolio",  sub: "Align to your target allocation",  color: "text-warm",      path: "/recommendations" },
};

const PERSONA_ACTIONS: Record<string, string[]> = {
  mutual_fund_investor:  ["compare_funds", "detect_overlap", "switch_direct", "sip_topup"],
  equity_investor:       ["equity_screen", "review_risk", "tax_harvest", "rebalance"],
  balanced_investor:     ["rebalance", "detect_overlap", "compare_funds", "sip_topup"],
  conservative_investor: ["review_risk", "rebalance", "tax_harvest", "switch_direct"],
  aggressive_investor:   ["equity_screen", "sip_topup", "detect_overlap", "rebalance"],
  default:               ["compare_funds", "detect_overlap", "switch_direct", "sip_topup"],
};

// Adjust actions when risk profile is known
function adjustForRisk(actions: string[], riskCategory?: RiskCategory | null): string[] {
  if (!riskCategory) return actions;
  if (riskCategory === "Conservative" || riskCategory === "Moderately Conservative") {
    // Replace aggressive suggestions with safety-oriented ones
    return actions.map(a => a === "equity_screen" ? "review_risk" : a === "sip_topup" ? "tax_harvest" : a);
  }
  return actions;
}

interface Props {
  persona?: string | null;
  riskCategory?: RiskCategory | null;
}

export function QuickActions({ persona, riskCategory }: Props) {
  const navigate = useNavigate();
  const keys = adjustForRisk(PERSONA_ACTIONS[persona ?? "default"] ?? PERSONA_ACTIONS.default, riskCategory);
  const actions = keys.map(k => ALL_ACTIONS[k]).filter(Boolean);

  return (
    <div className="rounded-lg bg-surface-1 border border-hairline overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-hairline">
        <Zap className="h-3.5 w-3.5 text-accent" />
        <span className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Quick actions</span>
        {persona && (
          <span className="font-mono text-[9px] text-ink-4 uppercase tracking-[.08em] ml-auto">
            for {persona.replace(/_/g, " ")}
          </span>
        )}
      </div>
      <div className="divide-y divide-[rgb(var(--line)/0.06)]">
        {actions.map((act, i) => {
          const Icon = act.icon;
          return (
            <button
              key={i}
              onClick={() => navigate(act.path)}
              className="w-full flex items-center gap-3 px-4 py-3.5 hover:bg-surface-2 transition-colors text-left"
            >
              <div className={cn("shrink-0 h-8 w-8 rounded-lg bg-surface-2 flex items-center justify-center")}>
                <Icon className={cn("h-4 w-4", act.color)} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[13px] font-medium text-ink">{act.label}</div>
                <div className="text-[11px] text-ink-3">{act.sub}</div>
              </div>
              <ChevronRight className="h-3.5 w-3.5 text-ink-4 shrink-0" />
            </button>
          );
        })}
      </div>
    </div>
  );
}
