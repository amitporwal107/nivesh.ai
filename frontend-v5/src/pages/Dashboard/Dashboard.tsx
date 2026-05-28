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

const ACTION_BUCKETS: Array<{
  key: string; label: string;
  textColor: string; bgColor: string;
  matches: string[];
}> = [
  { key: "consolidate", label: "Consolidate",  textColor: "text-[#8E97FF]", bgColor: "bg-[rgba(142,151,255,0.10)]", matches: ["switch", "merge", "consolidat"] },
  { key: "exit",        label: "Exit",         textColor: "text-neg",       bgColor: "bg-[rgb(var(--neg)/0.08)]",   matches: ["sell", "exit", "trim", "reduce"] },
  { key: "review",      label: "Review",       textColor: "text-warm",      bgColor: "bg-[rgb(var(--warm)/0.08)]",  matches: ["hold", "keep", "review"] },
  { key: "add",         label: "Increase SIP", textColor: "text-pos",       bgColor: "bg-[rgb(var(--pos)/0.08)]",   matches: ["sip_increase", "add", "buy"] },
  { key: "cut",         label: "Cut SIP",      textColor: "text-warm",      bgColor: "bg-[rgb(var(--warm)/0.08)]",  matches: ["sip_decrease"] },
];

function classifyAction(at: string): string {
  const t = at.toLowerCase();
  for (const b of ACTION_BUCKETS) {
    if (b.matches.some((m) => t.includes(m))) return b.key;
  }
  return "review";
}

function fmtLakh(rs: number | null | undefined): string | null {
  if (!rs || rs <= 0) return null;
  return rs >= 100_000 ? `₹${(rs / 100_000).toFixed(1)}L` : `₹${Math.round(rs / 1000)}K`;
}

function ActionMatrix({ actions, total, onViewAll }: {
  actions: PlanActionC[];
  total: number;
  onViewAll: () => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);

  // Group into buckets
  const bucketMap: Record<string, { actions: PlanActionC[]; totalRs: number }> = {};
  for (const a of actions) {
    const key = classifyAction(String(a.action_type ?? ""));
    if (!bucketMap[key]) bucketMap[key] = { actions: [], totalRs: 0 };
    bucketMap[key].actions.push(a);
    bucketMap[key].totalRs += a.amount_rs ?? 0;
  }

  const activeBuckets = ACTION_BUCKETS.filter((b) => (bucketMap[b.key]?.actions.length ?? 0) > 0);

  return (
    <div className="mt-7 rounded-lg bg-surface-1 border border-hairline overflow-hidden">
      {/* header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-hairline">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Action matrix</span>
          {total > 0 && <span className="font-mono text-[10px] text-ink-4">· {total} action{total !== 1 ? "s" : ""} pending</span>}
        </div>
        <button onClick={onViewAll} className="flex items-center gap-1 text-accent text-[12px] font-medium hover:underline">
          View all <ArrowRight className="h-3 w-3" />
        </button>
      </div>

      {activeBuckets.length === 0 ? (
        <div className="px-5 py-8 text-center text-[13px] text-ink-3">No pending actions — your portfolio is up to date.</div>
      ) : (
        <>
          {/* bucket pills */}
          <div className="flex flex-wrap gap-2 px-5 py-4 border-b border-hairline">
            {activeBuckets.map((b) => {
              const grp = bucketMap[b.key];
              const amt = fmtLakh(grp.totalRs);
              const active = expanded === b.key;
              return (
                <button
                  key={b.key}
                  onClick={() => setExpanded(active ? null : b.key)}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-full border text-[12px] font-medium transition-all",
                    active
                      ? `${b.bgColor} border-current ${b.textColor}`
                      : "bg-surface-2 border-hairline text-ink-2 hover:border-ink-3",
                  )}
                >
                  <span className={cn("font-display text-[17px] leading-none", b.textColor)}>{grp.actions.length}</span>
                  <span>{b.label}</span>
                  {amt && <span className="font-mono text-[10px] opacity-70">{amt}</span>}
                </button>
              );
            })}
          </div>

          {/* expanded bucket detail */}
          {expanded && bucketMap[expanded] && (() => {
            const b = ACTION_BUCKETS.find((x) => x.key === expanded)!;
            const grp = bucketMap[expanded];
            const amt = fmtLakh(grp.totalRs);
            return (
              <div className="border-b border-hairline">
                <div className="px-5 pt-4 pb-2">
                  <div className="flex items-baseline gap-2 mb-1">
                    {amt && <span className={cn("font-display text-[20px] tracking-tightish", b.textColor)}>{amt}</span>}
                    <span className="text-[12px] text-ink-3">·</span>
                    <span className="text-[12.5px] text-ink-2">{grp.actions.length} fund{grp.actions.length !== 1 ? "s" : ""}</span>
                  </div>
                </div>
                <div className="divide-y divide-[rgb(var(--line)/0.06)]">
                  {grp.actions.slice(0, 8).map((a, i) => {
                    const name = a.holding_name ?? a.asset_name ?? "Unknown fund";
                    const rationale = a.rationale ?? a.reason_text ?? "";
                    const impact = a.estimated_impact?.health_score_delta;
                    const amtRs = fmtLakh(a.amount_rs);
                    return (
                      <div key={a.action_id ?? i} className="px-5 py-3 flex items-start gap-3 hover:bg-surface-2 transition-colors">
                        <span className="font-mono text-[10px] text-ink-4 mt-0.5 shrink-0 w-5">#{i + 1}</span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-baseline gap-2 flex-wrap">
                            <span className="text-[13px] font-medium truncate">{name}</span>
                            {amtRs && <span className="font-mono text-[10px] text-ink-3">{amtRs}</span>}
                          </div>
                          {rationale && <p className="text-[11.5px] text-ink-3 mt-0.5 leading-relaxed line-clamp-2">{rationale}</p>}
                        </div>
                        {impact != null && impact > 0 && (
                          <span className="font-mono text-[10px] text-pos shrink-0">+{impact}pt</span>
                        )}
                      </div>
                    );
                  })}
                  {grp.actions.length > 8 && (
                    <div className="px-5 py-2.5">
                      <button onClick={onViewAll} className="text-[12px] text-accent hover:underline">
                        +{grp.actions.length - 8} more → View all
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })()}
        </>
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
