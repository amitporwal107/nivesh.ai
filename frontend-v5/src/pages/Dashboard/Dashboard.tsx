import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Upload, Info, ArrowRight } from "lucide-react";
import type { PortfolioSummary, NavPoint } from "@/types/portfolio";
import { PortfolioValueCard } from "./PortfolioValueCard";
import { HealthScoreCard } from "./HealthScoreCard";
import { RiskMeterCard } from "./RiskMeterCard";
import { TopInsightsList } from "./TopInsightsList";
import { plansService } from "@/services";
import type { PlanActionC, PlanC } from "@/services/contracts/plan.contract";
import { cn } from "@/lib/utils";

interface DashboardProps {
  summary: PortfolioSummary;
  navHistory: NavPoint[];
}

function healthLabel(score: number): { phrase: string; tone: string } {
  if (score >= 85) return { phrase: "in great shape", tone: "text-pos" };
  if (score >= 70) return { phrase: "mostly healthy", tone: "text-accent" };
  if (score >= 55) return { phrase: "needs some work", tone: "text-warm" };
  return { phrase: "needs attention", tone: "text-neg" };
}

function useCasState() {
  return useQuery({
    queryKey: ["onboarding", "state"],
    queryFn: async () => {
      const res = await fetch("/api/onboarding/state", { credentials: "include" });
      if (!res.ok) return null;
      return res.json() as Promise<{ cas_statement_period?: string | null; gmail_connected?: boolean }>;
    },
    staleTime: 5 * 60_000,
  });
}

function useActivePlan() {
  return useQuery<PlanC | null>({
    queryKey: ["plans", "active-summary"],
    queryFn: () => plansService.getActive(),
    staleTime: 2 * 60_000,
  });
}

// ── CAS banner ────────────────────────────────────────────────────────────────

function CasStatementBanner({ period, gmailConnected, onSync, onUpload }: {
  period: string | null | undefined;
  gmailConnected: boolean;
  onSync: () => void;
  onUpload: () => void;
}) {
  return (
    <div className="flex items-center gap-3 rounded-md bg-surface-1 border border-hairline px-4 py-2.5 text-[12.5px] text-ink-2 mb-6">
      <span className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 shrink-0">Last CAS</span>
      <span className="font-medium text-ink">{period ?? "—"}</span>
      <span className="text-ink-4 mx-1">·</span>
      <span className="text-ink-3 flex-1">Update if you have a newer statement</span>
      <div className="flex items-center gap-2 ml-auto shrink-0">
        {gmailConnected && (
          <button onClick={onSync} className="flex items-center gap-1.5 text-accent font-medium hover:underline text-[12px]">
            <RefreshCw className="h-3 w-3" />Sync Gmail
          </button>
        )}
        <span className="text-ink-4">·</span>
        <button onClick={onUpload} className="flex items-center gap-1.5 text-ink-2 hover:text-accent hover:underline text-[12px]">
          <Upload className="h-3 w-3" />Upload file
        </button>
      </div>
    </div>
  );
}

// ── Tooltip ───────────────────────────────────────────────────────────────────

function InfoTooltip({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="text-ink-4 hover:text-ink-2 transition-colors"
        aria-label="How is this calculated?"
      >
        <Info className="h-3.5 w-3.5" />
      </button>
      {open && (
        <>
          <span className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <span className="absolute z-20 left-1/2 -translate-x-1/2 top-6 w-[280px] rounded-xl bg-surface-1 border border-hairline shadow-xl p-4 text-left">
            {children}
          </span>
        </>
      )}
    </span>
  );
}

// ── Action Matrix ─────────────────────────────────────────────────────────────

const ACTION_BUCKETS: Array<{ key: string; label: string; color: string; matches: string[] }> = [
  { key: "consolidate", label: "Consolidate",  color: "text-indigo",  matches: ["switch", "merge"] },
  { key: "exit",        label: "Exit",         color: "text-neg",     matches: ["sell", "exit", "trim", "reduce"] },
  { key: "review",      label: "Review",       color: "text-warm",    matches: ["hold", "keep", "review"] },
  { key: "increase",    label: "Increase SIP", color: "text-pos",     matches: ["sip_increase", "add", "buy"] },
  { key: "decrease",    label: "Cut SIP",      color: "text-warm",    matches: ["sip_decrease"] },
];

function bucketActions(actions: PlanActionC[]) {
  const counts: Record<string, number> = {};
  for (const a of actions) {
    const at = String(a.action_type ?? "").toLowerCase();
    for (const b of ACTION_BUCKETS) {
      if (b.matches.some((m) => at.includes(m))) {
        counts[b.key] = (counts[b.key] ?? 0) + 1;
        break;
      }
    }
  }
  return counts;
}

function ActionMatrix({ actions, total, onViewAll }: {
  actions: PlanActionC[];
  total: number;
  onViewAll: () => void;
}) {
  const counts = bucketActions(actions);
  const activeBuckets = ACTION_BUCKETS.filter((b) => (counts[b.key] ?? 0) > 0);

  return (
    <div className="mt-7 rounded-lg bg-surface-1 border border-hairline overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-hairline">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Action matrix</span>
          {total > 0 && (
            <span className="font-mono text-[10px] text-ink-4">· {total} action{total !== 1 ? "s" : ""} pending</span>
          )}
        </div>
        <button
          onClick={onViewAll}
          className="flex items-center gap-1 text-accent text-[12px] font-medium hover:underline"
        >
          View all <ArrowRight className="h-3 w-3" />
        </button>
      </div>

      {activeBuckets.length === 0 ? (
        <div className="px-5 py-8 text-center text-[13px] text-ink-3">
          No pending actions — your portfolio is up to date.
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 divide-x divide-y divide-[rgb(var(--line)/0.08)]">
          {ACTION_BUCKETS.map((b) => {
            const count = counts[b.key] ?? 0;
            return (
              <button
                key={b.key}
                onClick={onViewAll}
                disabled={count === 0}
                className={cn(
                  "flex flex-col gap-1 px-4 py-4 text-left transition-colors",
                  count > 0 ? "hover:bg-surface-2 cursor-pointer" : "opacity-30 cursor-default",
                )}
              >
                <span className={cn("font-display text-[28px] leading-none tracking-tightish", count > 0 ? b.color : "text-ink-4")}>
                  {count}
                </span>
                <span className="font-mono text-[9.5px] uppercase tracking-[.1em] text-ink-3">{b.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Main dashboard ────────────────────────────────────────────────────────────

export function Dashboard({ summary, navHistory }: DashboardProps) {
  const navigate = useNavigate();
  const casState   = useCasState();
  const planQuery  = useActivePlan();

  const score = Math.round(summary.healthScore);
  const { phrase, tone } = healthLabel(summary.healthScore);

  const plan: PlanC | null = planQuery.data ?? null;
  const actions: PlanActionC[]  = plan?.actions ?? [];
  const pending   = actions.filter((a) => (a.status ?? "").toString().toLowerCase() === "pending");
  const totalPending: number = plan?.actions_pending ?? pending.length;

  // "The one thing" — only show when we have a meaningful improvement target
  const gain = Math.round(pending.slice(0, 5).reduce(
    (s: number, a: PlanActionC) => s + (a.estimated_impact?.health_score_delta ?? 0), 0
  ));
  const targetScore = Math.min(99, score + gain);
  const showCta = pending.length > 0 && targetScore > score;

  const verdict =
    score >= 85 ? "Excellent — keep it up." :
    score >= 70 ? "Good — a couple of fixes available." :
    score >= 55 ? "Fair — a few changes needed." :
    "Needs work — start with the top action.";

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      {/* CAS statement banner */}
      <CasStatementBanner
        period={casState.data?.cas_statement_period}
        gmailConnected={casState.data?.gmail_connected ?? false}
        onSync={() => navigate("/onboarding?sync=gmail")}
        onUpload={() => navigate("/onboarding?tab=upload")}
      />

      {/* eyebrow + headline */}
      <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Dashboard</div>
      <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
        Your portfolio is <span className={tone}>{phrase}</span>.
      </h1>
      <p className="text-[15.5px] sm:text-base text-ink-2 mt-3 leading-relaxed max-w-[600px]">
        {pending.length > 0
          ? `${totalPending} action${totalPending !== 1 ? "s" : ""} identified — apply them to improve your score.`
          : "Upload your latest CAS statement to see personalised actions."}
      </p>

      {/* hero — value · health · risk */}
      <div className="mt-7 rounded-lg bg-surface-1 border border-hairline shadow-card">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-y-7 md:divide-x md:divide-[rgb(var(--line)/0.10)] p-6 sm:p-7">
          <PortfolioValueCard
            value={summary.totalValue}
            yearChangePct={summary.yearChange.pct}
            navHistory={navHistory}
          />

          {/* Health score with info */}
          <div className="md:px-7 flex items-center gap-5">
            <div className="relative">
              <HealthScoreCard score={summary.healthScore} verdict={verdict} />
            </div>
          </div>
          {/* replace with inline to add tooltip */}
          <div className="md:pl-7 relative">
            <RiskMeterCard level={summary.riskBucketIndex as 1|2|3|4|5} bucket={summary.riskBucket} />
          </div>
        </div>

        {/* Info row under hero cards */}
        <div className="border-t border-hairline grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-[rgb(var(--line)/0.08)]">
          <div className="px-6 py-2.5" />
          <div className="px-7 py-2.5 flex items-center gap-1.5">
            <span className="font-mono text-[10px] text-ink-4 uppercase tracking-[.08em]">How is this calculated?</span>
            <InfoTooltip>
              <p className="font-mono text-[10px] uppercase tracking-[.1em] text-ink-3 mb-2">Health Score · 0–100</p>
              <p className="text-[12.5px] text-ink-2 leading-relaxed">
                Weighted average across 6 composites: <strong>Returns</strong> (vs category peers),{" "}
                <strong>Risk</strong> (volatility + drawdown), <strong>Cost</strong> (TER vs peers),{" "}
                <strong>Consistency</strong> (quartile rank stability), <strong>Portfolio Fit</strong>{" "}
                (overlap + concentration), and <strong>ESG Proxy</strong>. Scores above 70 are Good; above 85 are Excellent.
              </p>
            </InfoTooltip>
          </div>
          <div className="px-7 py-2.5 flex items-center gap-1.5">
            <span className="font-mono text-[10px] text-ink-4 uppercase tracking-[.08em]">How is risk calculated?</span>
            <InfoTooltip>
              <p className="font-mono text-[10px] uppercase tracking-[.1em] text-ink-3 mb-2">Risk Level · 1–5 scale</p>
              <p className="text-[12.5px] text-ink-2 leading-relaxed">
                Weighted portfolio <strong>beta vs Nifty 500</strong> across all holdings, based on 1-year trailing data.
                Beta &lt; 0.8 = Low (1–2), 0.8–1.0 = Moderate (3), 1.0–1.3 = High (4), &gt; 1.3 = Very High (5).
                For mutual funds, fund-level beta is sourced from NIDP DAAS primitives.
              </p>
            </InfoTooltip>
          </div>
        </div>
      </div>

      {/* Action matrix */}
      <ActionMatrix
        actions={pending}
        total={totalPending}
        onViewAll={() => navigate("/recommendations")}
      />

      {/* The one thing — only when we have a real improvement target */}
      {showCta && (
        <div className="mt-7 p-6 sm:p-7 rounded-lg bg-ink text-on-accent flex flex-col sm:flex-row gap-5 sm:items-center">
          <div className="flex-1">
            <div className="text-[13px] tracking-[.04em] opacity-60">The one thing</div>
            <div className="font-display text-2xl sm:text-[28px] tracking-tightish mt-1 leading-tight">
              Apply the top {Math.min(pending.length, 5)} action{pending.length !== 1 ? "s" : ""} to lift your score from{" "}
              <span className="text-warm">{score}</span> → <span className="text-pos">{targetScore}</span>.
            </div>
          </div>
          <button
            onClick={() => navigate("/recommendations")}
            className="flex items-center gap-2 px-6 py-3 rounded-lg bg-accent text-on-accent font-medium text-[14px] hover:opacity-90 transition-opacity self-start sm:self-auto shrink-0"
          >
            View action plan <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  );
}
