import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Upload, Info, ArrowRight, Lock, AlertTriangle, Check } from "lucide-react";
import type { PortfolioSummary, NavPoint, PortfolioInsight } from "@/types/portfolio";
import { PortfolioValueCard } from "./PortfolioValueCard";
import { HealthScoreCard, type HealthBreakdown } from "./HealthScoreCard";
import { RiskMeterCard } from "./RiskMeterCard";
import { PersonaCard } from "./PersonaCard";
import { IntelligenceFeed, type AllocationDrift } from "./IntelligenceFeed";
import { QuickActions } from "./QuickActions";
import { plansService } from "@/services";
import type { PlanActionC, PlanC } from "@/services/contracts/plan.contract";
import type { RiskProfile } from "@/hooks/use-risk-profile";
import { TARGET_ALLOCATION } from "@/hooks/use-risk-profile";
import { cn } from "@/lib/utils";
import { SafeWidget } from "@/components/shared/SafeWidget";
import { ProfileWizardModal, type WizardCompleteness } from "./ProfileWizardModal";

// ── Types ─────────────────────────────────────────────────────────────────────

interface OboardingState {
  cas_statement_period?: string | null;
  gmail_connected?: boolean;
  persona?: string | null;
  persona_confidence?: number | null;
  has_risk_profile?: boolean;
}

interface DashboardProps {
  summary: PortfolioSummary;
  navHistory: NavPoint[];
  healthBreakdown?: HealthBreakdown;
  insights?: PortfolioInsight[];
  riskProfile?: RiskProfile | null;
  holdingsCount?: number;
  hasGoal?: boolean;
  onRiskProfileSaved?: () => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function healthLabel(score: number): { phrase: string; tone: string } {
  if (score >= 85) return { phrase: "in great shape",  tone: "text-pos"  };
  if (score >= 70) return { phrase: "mostly healthy",  tone: "text-accent" };
  if (score >= 55) return { phrase: "needs some work", tone: "text-warm"  };
  return { phrase: "needs attention", tone: "text-neg" };
}

function fmtLakh(rs: number | null | undefined): string | null {
  if (!rs || rs <= 0) return null;
  return rs >= 100_000 ? `₹${(rs / 100_000).toFixed(1)}L` : `₹${Math.round(rs / 1000)}K`;
}

// ── Data hooks ────────────────────────────────────────────────────────────────

function useCasState() {
  return useQuery({
    queryKey: ["onboarding", "state"],
    queryFn: async () => {
      const res = await fetch("/api/onboarding/state", { credentials: "include" });
      if (!res.ok) return null;
      return res.json() as Promise<OboardingState>;
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

// ── Info tooltip ──────────────────────────────────────────────────────────────

function InfoTooltip({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex">
      <button type="button" onClick={() => setOpen(o => !o)} className="text-ink-4 hover:text-ink-2 transition-colors" aria-label="How is this calculated?">
        <Info className="h-3.5 w-3.5" />
      </button>
      {open && (
        <>
          <span className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <span className="absolute z-20 left-1/2 -translate-x-1/2 top-6 w-[280px] rounded-xl bg-surface-1 border border-hairline shadow-xl p-4 text-left">{children}</span>
        </>
      )}
    </span>
  );
}

// ── V2-style Action Matrix ────────────────────────────────────────────────────

const ACTION_BUCKETS: Array<{
  key: string; label: string;
  icon: string;
  textColor: string; bgColor: string; borderColor: string;
  matchType: string[]; matchDomain: string[];
}> = [
  {
    key: "consolidate", label: "Consolidate",
    icon: "⇄",
    textColor: "text-[#8B5CF6]", bgColor: "bg-[rgba(139,92,246,0.10)]", borderColor: "border-[rgba(139,92,246,0.30)]",
    matchType: ["switch","merge","SWITCH","MERGE"], matchDomain: ["concentration","diversification"],
  },
  {
    key: "tax_watch", label: "Tax Watch",
    icon: "§",
    textColor: "text-[#F59E0B]", bgColor: "bg-[rgba(245,158,11,0.10)]", borderColor: "border-[rgba(245,158,11,0.30)]",
    matchType: ["harvest","HARVEST"], matchDomain: ["tax"],
  },
  {
    key: "review", label: "Review",
    icon: "⚠",
    textColor: "text-warm", bgColor: "bg-[rgb(var(--warm)/0.08)]", borderColor: "border-[rgb(var(--warm)/0.25)]",
    matchType: ["hold","keep","HOLD","KEEP","review","REVIEW","trim","TRIM"], matchDomain: ["risk","performance"],
  },
  {
    key: "exit", label: "Exit",
    icon: "↓",
    textColor: "text-neg", bgColor: "bg-[rgb(var(--neg)/0.08)]", borderColor: "border-[rgb(var(--neg)/0.25)]",
    matchType: ["sell","exit","EXIT","SELL","reduce","REDUCE"], matchDomain: [],
  },
  {
    key: "increase", label: "Increase SIP",
    icon: "↑",
    textColor: "text-pos", bgColor: "bg-[rgb(var(--pos)/0.08)]", borderColor: "border-[rgb(var(--pos)/0.25)]",
    matchType: ["sip_increase","SIP_INCREASE","add","ADD","buy","BUY"], matchDomain: ["goals"],
  },
  {
    key: "core_add", label: "Core / Add",
    icon: "✓",
    textColor: "text-[#3B82F6]", bgColor: "bg-[rgba(59,130,246,0.10)]", borderColor: "border-[rgba(59,130,246,0.30)]",
    matchType: ["hold_core","HOLD_CORE"], matchDomain: ["diversification"],
  },
];

function classifyAction(action: PlanActionC): string {
  const t = String(action.action_type ?? "").toLowerCase();
  const d = String((action as Record<string, unknown>).source_domain ?? "").toLowerCase();

  for (const b of ACTION_BUCKETS) {
    if (b.matchType.some(m => t === m.toLowerCase())) return b.key;
    if (d && b.matchDomain.includes(d)) return b.key;
  }
  // fallback by verb
  if (t.includes("switch") || t.includes("merge")) return "consolidate";
  if (t.includes("exit") || t.includes("sell")) return "exit";
  if (t.includes("sip_increase") || t.includes("add") || t.includes("buy")) return "increase";
  if (t.includes("hold") || t.includes("keep") || t.includes("review") || t.includes("trim")) return "review";
  return "review";
}

// Severity → visual treatment (maps PRD §8 → UI colors)
const SEVERITY_STYLE: Record<string, { dot: string; border: string; label: string }> = {
  severe:   { dot: "bg-neg",         border: "border-l-2 border-neg",  label: "URGENT"  },
  mismatch: { dot: "bg-warm",        border: "border-l-2 border-warm", label: "ACTION"  },
  minor:    { dot: "bg-[#3B82F6]",   border: "",                       label: "NOTE"    },
  aligned:  { dot: "bg-pos",         border: "",                       label: "OK"      },
};

// Execution path → short label
const PATH_LABEL: Record<string, string> = {
  redirect:  "new money",
  harvest:   "tax harvest",
  stagger:   "spread exit",
  "sell-now": "sell now",
};

// Sort actions severe-first within a bucket (PRD §8)
const SEV_ORDER = ["severe", "mismatch", "minor", "aligned"];
function sortBySeverity(arr: PlanActionC[]): PlanActionC[] {
  return [...arr].sort((a, b) => {
    const ai = SEV_ORDER.indexOf(String(a.severity ?? "minor"));
    const bi = SEV_ORDER.indexOf(String(b.severity ?? "minor"));
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });
}

function ActionMatrix({ actions, total, onViewAll }: { actions: PlanActionC[]; total: number; onViewAll: () => void }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  type BucketMap = Record<string, { actions: PlanActionC[]; totalRs: number; hasSevere: boolean }>;
  const bucketMap: BucketMap = {};
  for (const a of actions) {
    const key = classifyAction(a);
    if (!bucketMap[key]) bucketMap[key] = { actions: [], totalRs: 0, hasSevere: false };
    bucketMap[key].actions.push(a);
    bucketMap[key].totalRs += a.amount_rs ?? 0;
    if (a.severity === "severe") bucketMap[key].hasSevere = true;
  }
  const activeBuckets = ACTION_BUCKETS.filter(b => (bucketMap[b.key]?.actions.length ?? 0) > 0);

  return (
    <div className="mt-7 rounded-lg bg-surface-1 border border-hairline overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-hairline">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Action matrix</span>
          {total > 0 && <span className="font-mono text-[10px] text-ink-4">· {total} pending</span>}
        </div>
        <button onClick={onViewAll} className="flex items-center gap-1 text-accent text-[12px] font-medium hover:underline">
          View all <ArrowRight className="h-3 w-3" />
        </button>
      </div>

      {activeBuckets.length === 0 ? (
        <div className="px-5 py-8 text-center text-[13px] text-ink-3">No pending actions — your portfolio is up to date.</div>
      ) : (
        <>
          {/* bucket strip */}
          <div className="flex flex-wrap gap-2 px-5 py-4 border-b border-hairline">
            {activeBuckets.map(b => {
              const grp = bucketMap[b.key];
              const amt = fmtLakh(grp.totalRs);
              const active = expanded === b.key;
              return (
                <button
                  key={b.key}
                  onClick={() => setExpanded(active ? null : b.key)}
                  className={cn(
                    "relative flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-[12px] font-medium transition-all",
                    active ? `${b.bgColor} ${b.borderColor} ${b.textColor}` : "bg-surface-2 border-hairline text-ink-2 hover:border-ink-3 hover:text-ink"
                  )}
                >
                  {grp.hasSevere && (
                    <span className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full bg-neg border-2 border-surface-1" />
                  )}
                  <span className={cn("text-[14px] leading-none opacity-80", active && b.textColor)}>{b.icon}</span>
                  <span className="font-display text-[15px] leading-none">{grp.actions.length}</span>
                  <span>{b.label}</span>
                  {amt && <span className={cn("font-mono text-[10px] opacity-70")}>{amt}</span>}
                </button>
              );
            })}
          </div>

          {/* expanded bucket */}
          {expanded && bucketMap[expanded] && (() => {
            const b = ACTION_BUCKETS.find(x => x.key === expanded)!;
            const grp = bucketMap[expanded];
            const amt = fmtLakh(grp.totalRs);
            return (
              <div className="border-b border-hairline">
                <div className="px-5 pt-4 pb-2 flex items-baseline gap-2">
                  {amt && <span className={cn("font-display text-[18px] tracking-tightish", b.textColor)}>{amt}</span>}
                  <span className="text-[12px] text-ink-3">· {grp.actions.length} fund{grp.actions.length !== 1 ? "s" : ""}</span>
                </div>
                <div className="divide-y divide-[rgb(var(--line)/0.06)]">
                  {sortBySeverity(grp.actions).slice(0, 8).map((a, i) => {
                    const name = a.holding_name ?? a.asset_name ?? "Unknown";
                    const rationale = a.rationale ?? a.reason_text ?? "";
                    const impact = a.estimated_impact?.health_score_delta;
                    const amtRs = fmtLakh(a.amount_rs);
                    const sev = String(a.severity ?? "minor");
                    const sevStyle = SEVERITY_STYLE[sev] ?? SEVERITY_STYLE.minor;
                    const pathLabel = a.execution_path ? PATH_LABEL[a.execution_path] ?? a.execution_path : null;
                    const needsConfirm = a.requires_confirmation === true;
                    return (
                      <div
                        key={a.action_id ?? i}
                        className={cn(
                          "px-5 py-2.5 flex items-start gap-3 hover:bg-surface-2 transition-colors",
                          sevStyle.border,
                        )}
                      >
                        <span className="font-mono text-[10px] text-ink-4 mt-0.5 shrink-0 w-5">#{i + 1}</span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[13px] font-medium truncate">{name}</span>
                            {amtRs && <span className="font-mono text-[10px] text-ink-3">{amtRs}</span>}
                            {needsConfirm && (
                              <span className="flex items-center gap-0.5 font-mono text-[9px] text-ink-3 bg-surface-2 px-1.5 py-0.5 rounded-full border border-hairline">
                                <Lock className="h-2.5 w-2.5" />confirm
                              </span>
                            )}
                            {sev === "severe" && (
                              <span className="flex items-center gap-0.5 font-mono text-[9px] text-neg bg-[rgb(var(--neg)/0.08)] px-1.5 py-0.5 rounded-full">
                                <AlertTriangle className="h-2.5 w-2.5" />URGENT
                              </span>
                            )}
                          </div>
                          {rationale && <p className="text-[11px] text-ink-3 mt-0.5 line-clamp-2">{rationale}</p>}
                          {pathLabel && (
                            <span className="inline-block mt-1 font-mono text-[9px] text-ink-4 bg-surface-2 px-1.5 py-0.5 rounded-full">
                              via {pathLabel}
                            </span>
                          )}
                        </div>
                        {impact != null && impact > 0 && (
                          <span className="font-mono text-[10px] text-pos shrink-0">+{impact}pt</span>
                        )}
                      </div>
                    );
                  })}
                  {grp.actions.length > 8 && (
                    <div className="px-5 py-2.5">
                      <button onClick={onViewAll} className="text-[12px] text-accent hover:underline">+{grp.actions.length - 8} more → View all</button>
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

export function Dashboard({ summary, navHistory, healthBreakdown, insights, riskProfile, holdingsCount = 0, hasGoal = false, onRiskProfileSaved }: DashboardProps) {
  const navigate = useNavigate();
  const casState  = useCasState();
  const planQuery = useActivePlan();
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardStart, setWizardStart] = useState<0 | 1 | 2>(0);

  const score = Math.round(summary.healthScore);
  const { phrase, tone } = healthLabel(summary.healthScore);

  const plan: PlanC | null = planQuery.data ?? null;
  const actions: PlanActionC[] = plan?.actions ?? [];
  const pending = actions.filter(a => (a.status ?? "").toString().toLowerCase() === "pending");
  const totalPending = plan?.actions_pending ?? pending.length;

  const gain = Math.round(pending.slice(0, 5).reduce((s, a) => s + (a.estimated_impact?.health_score_delta ?? 0), 0));
  const targetScore = Math.min(99, score + gain);
  const showCta = pending.length > 0 && targetScore > score;

  const verdict =
    score >= 85 ? "Excellent — keep it up." :
    score >= 70 ? "Good — a couple of fixes available." :
    score >= 55 ? "Fair — a few changes needed." :
    "Needs work — start with the top action.";

  // Allocation drift: compare actual equity % vs risk-profile target
  const allocationDrift: AllocationDrift | null = riskProfile
    ? (() => {
        const target = TARGET_ALLOCATION[riskProfile.category];
        const equitySlice = summary.allocation?.find(a => a.assetClass === "equity");
        if (!equitySlice) return null;
        return {
          actual_pct: equitySlice.pct,  // already 0-100
          target_pct: target.equity,
          label: "equity",
        };
      })()
    : null;

  const persona = casState.data?.persona;

  const completeness: WizardCompleteness = {
    hasRiskProfile: Boolean(riskProfile),
    hasGoal,
    hasSnapshot: false, // snapshot is optional — don't block
  };
  const stepsComplete = [completeness.hasRiskProfile, completeness.hasGoal].filter(Boolean).length;
  const profileIncomplete = !completeness.hasRiskProfile || !completeness.hasGoal;

  function openWizard(step: 0 | 1 | 2) {
    setWizardStart(step);
    setWizardOpen(true);
  }

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">

      {/* Profile wizard */}
      <ProfileWizardModal
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        completeness={completeness}
        existingProfile={riskProfile}
        startStep={wizardStart}
        onComplete={() => {
          setWizardOpen(false);
          onRiskProfileSaved?.();
        }}
      />

      {/* Profile completion banner — shown until both risk + goal are done */}
      {profileIncomplete && (
        <div className="mb-5 rounded-lg border border-[rgba(var(--accent)/0.35)] bg-[rgba(var(--accent)/0.06)] px-4 py-3 flex flex-col sm:flex-row sm:items-center gap-3">
          <div className="flex-1 min-w-0">
            <div className="font-mono text-[10px] uppercase tracking-[.14em] text-accent mb-1">
              Profile {stepsComplete}/2 complete
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              {[
                { label: "Risk profile", done: completeness.hasRiskProfile, step: 0 as const },
                { label: "Add a goal",   done: completeness.hasGoal,        step: 1 as const },
              ].map(s => (
                <button
                  key={s.label}
                  onClick={() => openWizard(s.step)}
                  className={cn(
                    "flex items-center gap-1.5 font-mono text-[11px] px-2.5 py-1 rounded-full border transition-all",
                    s.done
                      ? "border-[rgba(var(--pos)/0.3)] text-pos bg-[rgba(var(--pos)/0.08)] cursor-default"
                      : "border-[rgba(var(--accent)/0.4)] text-accent hover:bg-[rgba(var(--accent)/0.10)]"
                  )}
                >
                  {s.done ? <Check className="h-2.5 w-2.5" /> : <span className="h-2.5 w-2.5 rounded-full border border-current inline-block" />}
                  {s.label}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={() => openWizard(!completeness.hasRiskProfile ? 0 : 1)}
            className="shrink-0 flex items-center gap-1.5 px-4 py-2 rounded-lg bg-accent text-on-accent text-[12px] font-medium hover:opacity-90"
          >
            {stepsComplete === 0 ? "Get started" : "Continue"} <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

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

      {/* Persona card */}
      <div className="mt-7">
        <SafeWidget name="PersonaCard" flagKey="persona_card" retryDelayMs={5000}>
          <PersonaCard
            persona={persona}
            personaConfidence={casState.data?.persona_confidence}
            riskProfile={riskProfile}
            totalValue={summary.totalValue}
            holdingsCount={holdingsCount}
            onRiskProfileSaved={onRiskProfileSaved}
            onOpenWizard={openWizard}
          />
        </SafeWidget>
      </div>

      {/* Hero: value · health · risk */}
      <div className="rounded-lg bg-surface-1 border border-hairline shadow-card">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-y-7 md:divide-x md:divide-[rgb(var(--line)/0.10)] p-6 sm:p-7">
          <SafeWidget name="PortfolioValueCard" flagKey="portfolio_value_card">
            <PortfolioValueCard value={summary.totalValue} yearChangePct={summary.yearChange.pct} navHistory={navHistory} />
          </SafeWidget>
          <SafeWidget name="HealthScoreCard" flagKey="health_score_card">
            <HealthScoreCard score={summary.healthScore} verdict={verdict} breakdown={healthBreakdown} />
          </SafeWidget>
          <div className="md:pl-7 relative">
            <SafeWidget name="RiskMeterCard" flagKey="risk_profile_card">
              <RiskMeterCard level={summary.riskBucketIndex as 1|2|3|4|5} bucket={summary.riskBucket} />
            </SafeWidget>
          </div>
        </div>

        {/* info row */}
        <div className="border-t border-hairline grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-[rgb(var(--line)/0.08)]">
          <div className="px-6 py-2.5" />
          <div className="px-7 py-2.5 flex items-center gap-1.5">
            <span className="font-mono text-[10px] text-ink-4 uppercase tracking-[.08em]">How is this calculated?</span>
            <InfoTooltip>
              <p className="font-mono text-[10px] uppercase tracking-[.1em] text-ink-3 mb-2">Health Score · 0–100</p>
              <p className="text-[12.5px] text-ink-2 leading-relaxed">
                Weighted across 4 composites: <strong>Diversification</strong>, <strong>Risk</strong> (volatility + drawdown),{" "}
                <strong>Cost efficiency</strong> (TER vs peers), and <strong>Performance</strong> (vs category peers).
              </p>
            </InfoTooltip>
          </div>
          <div className="px-7 py-2.5 flex items-center gap-1.5">
            <span className="font-mono text-[10px] text-ink-4 uppercase tracking-[.08em]">How is risk calculated?</span>
            <InfoTooltip>
              <p className="font-mono text-[10px] uppercase tracking-[.1em] text-ink-3 mb-2">Risk Level · 1–5</p>
              <p className="text-[12.5px] text-ink-2 leading-relaxed">
                Weighted portfolio <strong>beta vs Nifty 500</strong> across all holdings. Beta &lt; 0.8 = Low, 0.8–1.0 = Moderate, &gt; 1.3 = Very High.
              </p>
            </InfoTooltip>
          </div>
        </div>
      </div>

      {/* Intelligence feed + Quick actions (side-by-side on desktop) */}
      {((insights && insights.length > 0) || allocationDrift) && (
        <div className="mt-7 grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-4">
          <SafeWidget name="IntelligenceFeed" flagKey="intelligence_feed" retryDelayMs={5000}>
            <IntelligenceFeed insights={insights ?? []} allocationDrift={allocationDrift} />
          </SafeWidget>
          <SafeWidget name="QuickActions" flagKey="quick_actions">
            <QuickActions persona={persona} riskCategory={riskProfile?.category} />
          </SafeWidget>
        </div>
      )}
      {(!insights || insights.length === 0) && !allocationDrift && (
        <div className="mt-7">
          <SafeWidget name="QuickActions" flagKey="quick_actions">
            <QuickActions persona={persona} riskCategory={riskProfile?.category} />
          </SafeWidget>
        </div>
      )}

      {/* Action matrix */}
      <SafeWidget name="ActionMatrix" flagKey="action_matrix">
        <ActionMatrix actions={pending} total={totalPending} onViewAll={() => navigate("/recommendations")} />
      </SafeWidget>

      {/* The one thing */}
      {showCta && (
        <SafeWidget name="ImproveCTA" flagKey="improve_cta">
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
        </SafeWidget>
      )}
    </div>
  );
}
