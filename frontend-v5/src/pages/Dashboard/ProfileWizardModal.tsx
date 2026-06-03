/**
 * ProfileWizardModal — 3-step profile completion wizard.
 *
 * Step 0: Risk profile   (6 questions — mirrors RiskProfileModal)
 * Step 1: Goal setup     (goal type + target + horizon + SIP)
 * Step 2: Snapshot       (age / income / expenses — optional, skippable)
 *
 * Opens at the first incomplete step. After all steps, refreshes the active
 * plan so the new goals flow into the recommendation engine immediately.
 */
import { useState, useEffect } from "react";
import { X, Check, ChevronLeft, ChevronRight, Target, Home, GraduationCap, Briefcase, Landmark, Sparkles, SkipForward } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSaveRiskProfile, type RiskAnswer, type RiskProfile } from "@/hooks/use-risk-profile";
import { goalsService } from "@/services";
import { plansService } from "@/services";
import { http } from "@/services/api/http";

// ── Types ────────────────────────────────────────────────────────────────────

export interface WizardCompleteness {
  hasRiskProfile: boolean;
  hasGoal: boolean;
  hasSnapshot: boolean;
}

interface Props {
  open: boolean;
  onClose: () => void;
  completeness: WizardCompleteness;
  existingProfile?: RiskProfile | null;
  /** Called after wizard completes so parent can invalidate queries */
  onComplete: () => void;
  /** Open at a specific step (0=risk, 1=goal, 2=snapshot) */
  startStep?: 0 | 1 | 2;
}

// ── Risk questions (mirrors RiskProfileModal) ─────────────────────────────────

const RISK_QUESTIONS = [
  {
    id: "market_drop",
    question: "If markets drop 20% tomorrow, what would you do?",
    options: [
      { value: "buy_more",  label: "Buy more",    sub: "Great opportunity to accumulate" },
      { value: "hold",      label: "Hold steady", sub: "Stay the course, it will recover" },
      { value: "sell_some", label: "Sell some",   sub: "Reduce exposure to limit losses" },
      { value: "sell_all",  label: "Exit fully",  sub: "Capital preservation is priority" },
    ],
  },
  {
    id: "investment_horizon",
    question: "What is your investment time horizon?",
    options: [
      { value: "10yr_plus", label: "10+ years",  sub: "Long-term wealth creation" },
      { value: "5_10yr",    label: "5–10 years", sub: "Medium-to-long term" },
      { value: "3_5yr",     label: "3–5 years",  sub: "Medium term" },
      { value: "1_3yr",     label: "1–3 years",  sub: "Short-to-medium term" },
      { value: "less_1yr",  label: "< 1 year",   sub: "Short term / liquidity" },
    ],
  },
  {
    id: "loss_tolerance",
    question: "Maximum annual loss you can tolerate?",
    options: [
      { value: "up_to_50", label: "Up to 50%", sub: "High risk tolerance" },
      { value: "up_to_25", label: "Up to 25%", sub: "Moderate risk tolerance" },
      { value: "up_to_10", label: "Up to 10%", sub: "Low risk tolerance" },
      { value: "none",     label: "No loss",   sub: "Capital preservation" },
    ],
  },
  {
    id: "income_stability",
    question: "How stable is your primary income?",
    options: [
      { value: "very_stable", label: "Very stable", sub: "Govt / salaried, predictable" },
      { value: "stable",      label: "Stable",      sub: "Regular employment" },
      { value: "moderate",    label: "Moderate",    sub: "Business / freelance" },
      { value: "unstable",    label: "Variable",    sub: "Commission / seasonal income" },
    ],
  },
  {
    id: "investment_knowledge",
    question: "How would you rate your investment knowledge?",
    options: [
      { value: "expert",       label: "Expert",       sub: "CFA / fund manager level" },
      { value: "advanced",     label: "Advanced",     sub: "Active investor, reads research" },
      { value: "intermediate", label: "Intermediate", sub: "Understands markets" },
      { value: "beginner",     label: "Beginner",     sub: "Just starting out" },
    ],
  },
  {
    id: "goal_priority",
    question: "What is your primary investment goal?",
    options: [
      { value: "aggressive_growth", label: "Aggressive growth", sub: "Maximise long-term returns" },
      { value: "growth",            label: "Growth",            sub: "Beat inflation comfortably" },
      { value: "income",            label: "Regular income",    sub: "Dividends / interest flow" },
      { value: "safety",            label: "Capital safety",    sub: "Preserve purchasing power" },
    ],
  },
];

// ── Goal types ────────────────────────────────────────────────────────────────

const GOAL_TYPES = [
  { value: "retirement", label: "Retirement",  icon: Landmark,     defaultName: "My Retirement Fund",    defaultHorizon: 20, defaultTarget: 10_000_000 },
  { value: "home",       label: "Home",         icon: Home,         defaultName: "Dream Home",             defaultHorizon: 7,  defaultTarget: 5_000_000  },
  { value: "education",  label: "Education",    icon: GraduationCap,defaultName: "Child's Education",     defaultHorizon: 10, defaultTarget: 2_500_000  },
  { value: "wealth",     label: "Wealth",       icon: Briefcase,    defaultName: "Wealth Creation",       defaultHorizon: 10, defaultTarget: 5_000_000  },
  { value: "other",      label: "Custom",       icon: Sparkles,     defaultName: "My Goal",               defaultHorizon: 5,  defaultTarget: 1_000_000  },
];

// ── Step 0: Risk Profile ──────────────────────────────────────────────────────

function RiskStep({
  existingProfile,
  onSaved,
  onSkip,
}: {
  existingProfile?: RiskProfile | null;
  onSaved: (p: RiskProfile) => void;
  onSkip: () => void;
}) {
  const [qIdx, setQIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>(existingProfile?.answers ?? {});
  const save = useSaveRiskProfile();

  const q = RISK_QUESTIONS[qIdx];
  const answered = q ? answers[q.id] : null;
  const total = RISK_QUESTIONS.length;

  async function submit() {
    const payload: RiskAnswer[] = Object.entries(answers).map(([question_id, answer]) => ({ question_id, answer }));
    const profile = await save.mutateAsync(payload);
    onSaved(profile);
  }

  return (
    <div>
      {/* progress dots */}
      <div className="flex gap-1 mb-5">
        {RISK_QUESTIONS.map((_, i) => (
          <div key={i} className={cn("h-1 rounded-full flex-1 transition-all",
            i < qIdx ? "bg-accent" : i === qIdx ? "bg-accent/60" : "bg-surface-2")} />
        ))}
      </div>

      <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3 mb-1">
        Question {qIdx + 1} of {total}
      </div>
      <h3 className="font-display text-[19px] leading-snug tracking-tightish mb-5">{q.question}</h3>

      <div className="space-y-2">
        {q.options.map(opt => (
          <button
            key={opt.value}
            onClick={() => setAnswers(prev => ({ ...prev, [q.id]: opt.value }))}
            className={cn(
              "w-full flex items-start gap-3 px-4 py-3 rounded-lg border text-left transition-all",
              answered === opt.value
                ? "border-accent bg-[rgba(var(--accent)/0.08)] text-ink"
                : "border-hairline bg-surface-2 text-ink-2 hover:border-ink-3 hover:text-ink"
            )}
          >
            <div className={cn("shrink-0 mt-0.5 h-4 w-4 rounded-full border-2 flex items-center justify-center",
              answered === opt.value ? "border-accent bg-accent" : "border-ink-3")}>
              {answered === opt.value && <div className="h-1.5 w-1.5 rounded-full bg-on-accent" />}
            </div>
            <div>
              <div className="text-[13px] font-medium">{opt.label}</div>
              {opt.sub && <div className="text-[11px] text-ink-3 mt-0.5">{opt.sub}</div>}
            </div>
          </button>
        ))}
      </div>

      <div className="flex items-center justify-between mt-6">
        <button
          onClick={() => qIdx === 0 ? onSkip() : setQIdx(i => i - 1)}
          className="flex items-center gap-1.5 text-[13px] text-ink-3 hover:text-ink"
        >
          <ChevronLeft className="h-4 w-4" />{qIdx === 0 ? "Skip" : "Back"}
        </button>

        {qIdx < total - 1 ? (
          <button
            onClick={() => answered && setQIdx(i => i + 1)}
            disabled={!answered}
            className="flex items-center gap-1.5 px-5 py-2 rounded-lg bg-accent text-on-accent text-[13px] font-medium hover:opacity-90 disabled:opacity-40"
          >
            Next<ChevronRight className="h-4 w-4" />
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={!answered || save.isPending}
            className="flex items-center gap-1.5 px-5 py-2 rounded-lg bg-accent text-on-accent text-[13px] font-medium hover:opacity-90 disabled:opacity-40"
          >
            {save.isPending ? "Saving…" : "Save profile"}<Check className="h-4 w-4" />
          </button>
        )}
      </div>
      {save.isError && <p className="mt-2 text-[12px] text-neg text-center">Something went wrong — try again.</p>}
    </div>
  );
}

// ── Step 1: Goal Setup ────────────────────────────────────────────────────────

function fmt(n: number): string {
  if (n >= 1_00_00_000) return `₹${(n / 1_00_00_000).toFixed(1)} Cr`;
  if (n >= 1_00_000) return `₹${(n / 1_00_000).toFixed(1)} L`;
  return `₹${Math.round(n / 1000)}k`;
}

// Crore-based defaults (1 Cr = 1,00,00,000 ₹)
const GOAL_DEFAULTS_CR: Record<string, { targetCr: number; horizon: number }> = {
  retirement: { targetCr: 5,    horizon: 20 },
  home:       { targetCr: 1.5,  horizon: 7  },
  education:  { targetCr: 0.5,  horizon: 10 },
  wealth:     { targetCr: 2,    horizon: 10 },
  other:      { targetCr: 0.5,  horizon: 5  },
};
const MAX_GOAL_CR = 500; // ₹500 Cr upper guard

function GoalStep({ onSaved, onSkip }: { onSaved: () => void; onSkip: () => void }) {
  const [typeVal, setTypeVal] = useState<string>("retirement");
  const [name, setName] = useState("My Retirement Fund");
  const [targetCr, setTargetCr] = useState("5");       // input in Crore
  const [horizon, setHorizon] = useState(20);
  const [sipK, setSipK] = useState("");                 // monthly SIP in ₹ thousands
  const [corpusCr, setCorpusCr] = useState("");         // already saved, in Crore
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function selectType(val: string) {
    const t = GOAL_TYPES.find(g => g.value === val);
    const d = GOAL_DEFAULTS_CR[val];
    if (!t || !d) return;
    setTypeVal(val);
    setName(t.defaultName);
    setTargetCr(String(d.targetCr));
    setHorizon(d.horizon);
  }

  async function save() {
    const cr = parseFloat(targetCr);
    if (!cr || cr <= 0)           { setErr("Enter a target amount in Crore."); return; }
    if (cr > MAX_GOAL_CR)         { setErr(`Cap is ₹${MAX_GOAL_CR} Cr. Split into multiple goals if needed.`); return; }
    if (!horizon || horizon <= 0) { setErr("Enter a horizon in years."); return; }
    if (horizon > 50)             { setErr("Horizon can't exceed 50 years."); return; }

    // Convert to ₹ — 1 Crore = 1,00,00,000
    const target_amount_rs   = Math.round(cr * 1_00_00_000);
    const current_corpus_rs  = Math.round((parseFloat(corpusCr || "0") * 1_00_00_000));
    const monthly_sip_rs     = Math.round((parseFloat(sipK || "0") * 1_000));

    setSaving(true); setErr(null);
    try {
      await goalsService.create({
        goal_type:        typeVal,
        goal_name:        (name || "My Goal").trim(),
        target_amount_rs,
        horizon_years:    horizon,
        priority:         "medium",
        current_corpus_rs,
        monthly_sip_rs,
      } as any);
      onSaved();
    } catch (e: unknown) {
      const msg = (e as { message?: string })?.message ?? "";
      if (msg.includes("already exists") || msg.toLowerCase().includes("goal_type")) {
        setErr(`A ${typeVal} goal already exists. Go to Goals to edit it instead of creating a duplicate.`);
      } else if (msg.includes("limit")) {
        setErr(msg);
      } else {
        setErr("Could not save goal — please check your values and try again.");
      }
    } finally {
      setSaving(false);
    }
  }

  const targetRs = (parseFloat(targetCr || "0") * 1_00_00_000);

  return (
    <div>
      {/* type selector */}
      <div className="grid grid-cols-5 gap-1.5 mb-5">
        {GOAL_TYPES.map(t => {
          const Icon = t.icon;
          const active = typeVal === t.value;
          return (
            <button
              key={t.value}
              onClick={() => selectType(t.value)}
              className={cn(
                "flex flex-col items-center gap-1 py-3 rounded-lg border text-[11px] font-medium transition-all",
                active ? "border-accent bg-[rgba(var(--accent)/0.10)] text-accent" : "border-hairline bg-surface-2 text-ink-3 hover:text-ink hover:border-ink-3"
              )}
            >
              <Icon className="h-4 w-4" />
              {t.label}
            </button>
          );
        })}
      </div>

      {/* goal name */}
      <div className="mb-3">
        <label className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 mb-1 block">Goal name</label>
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          className="w-full rounded-lg border border-hairline bg-surface-2 px-3 py-2 text-[13px] text-ink focus:outline-none focus:border-accent"
          placeholder="e.g. My Retirement Fund"
        />
      </div>

      {/* target + horizon side by side */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 mb-1 block">
            Target amount{targetRs > 0 && <span className="text-ink-4 normal-case ml-1">({fmt(targetRs)})</span>}
          </label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3 text-[13px]">₹</span>
            <input
              type="number"
              value={targetCr}
              onChange={e => setTargetCr(e.target.value)}
              min={0.1}
              max={MAX_GOAL_CR}
              step={0.5}
              className="w-full rounded-lg border border-hairline bg-surface-2 pl-6 pr-10 py-2 text-[13px] text-ink focus:outline-none focus:border-accent"
              placeholder="5"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-4 text-[10px] font-mono">Cr</span>
          </div>
          <div className="text-[10px] text-ink-4 mt-0.5">Enter in Crore (1 = ₹1,00,00,000)</div>
        </div>
        <div>
          <label className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 mb-1 block">
            Horizon <span className="text-ink-4 normal-case">(years)</span>
          </label>
          <input
            type="number"
            value={horizon}
            onChange={e => setHorizon(Math.min(50, parseInt(e.target.value) || 0))}
            min={1}
            max={50}
            className="w-full rounded-lg border border-hairline bg-surface-2 px-3 py-2 text-[13px] text-ink focus:outline-none focus:border-accent"
            placeholder="10"
          />
        </div>
      </div>

      {/* optional: SIP + current corpus */}
      <div className="grid grid-cols-2 gap-3 mb-5">
        <div>
          <label className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 mb-1 block">
            Monthly SIP <span className="text-ink-4 normal-case">(₹ thousands, optional)</span>
          </label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3 text-[13px]">₹</span>
            <input
              type="number"
              value={sipK}
              onChange={e => setSipK(e.target.value)}
              min={0}
              className="w-full rounded-lg border border-hairline bg-surface-2 pl-6 pr-8 py-2 text-[13px] text-ink focus:outline-none focus:border-accent"
              placeholder="10"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-4 text-[10px] font-mono">k</span>
          </div>
        </div>
        <div>
          <label className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 mb-1 block">
            Already saved <span className="text-ink-4 normal-case">(₹ Cr, optional)</span>
          </label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3 text-[13px]">₹</span>
            <input
              type="number"
              value={corpusCr}
              onChange={e => setCorpusCr(e.target.value)}
              min={0}
              className="w-full rounded-lg border border-hairline bg-surface-2 pl-6 pr-10 py-2 text-[13px] text-ink focus:outline-none focus:border-accent"
              placeholder="0"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-4 text-[10px] font-mono">Cr</span>
          </div>
        </div>
      </div>

      {err && <p className="mb-3 text-[12px] text-neg">{err}</p>}

      <div className="flex items-center justify-between">
        <button onClick={onSkip} className="flex items-center gap-1.5 text-[13px] text-ink-3 hover:text-ink">
          <SkipForward className="h-3.5 w-3.5" />Skip for now
        </button>
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-1.5 px-5 py-2 rounded-lg bg-accent text-on-accent text-[13px] font-medium hover:opacity-90 disabled:opacity-40"
        >
          {saving ? "Saving…" : "Add goal"}<ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// ── Step 2: Financial Snapshot (optional) ─────────────────────────────────────

function SnapshotStep({ onSaved, onSkip }: { onSaved: () => void; onSkip: () => void }) {
  const [age, setAge] = useState("");
  const [income, setIncome] = useState("");
  const [expenses, setExpenses] = useState("");
  const [dependents, setDependents] = useState("0");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await http({
        method: "PUT",
        path: "/api/goals/snapshot",
        body: {
          age: age ? parseInt(age) : undefined,
          monthly_income_rs: income ? parseFloat(income) : undefined,
          monthly_expenses_rs: expenses ? parseFloat(expenses) : undefined,
          dependents: parseInt(dependents) || 0,
        },
      });
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 mb-1 block">Your age</label>
          <input type="number" value={age} onChange={e => setAge(e.target.value)} placeholder="35"
            className="w-full rounded-lg border border-hairline bg-surface-2 px-3 py-2 text-[13px] text-ink focus:outline-none focus:border-accent" />
        </div>
        <div>
          <label className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 mb-1 block">Dependents</label>
          <select value={dependents} onChange={e => setDependents(e.target.value)}
            className="w-full rounded-lg border border-hairline bg-surface-2 px-3 py-2 text-[13px] text-ink focus:outline-none focus:border-accent">
            {[0,1,2,3,4,5].map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-5">
        <div>
          <label className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 mb-1 block">Monthly income <span className="text-ink-4 normal-case">(₹)</span></label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3 text-[13px]">₹</span>
            <input type="number" value={income} onChange={e => setIncome(e.target.value)} placeholder="1,50,000"
              className="w-full rounded-lg border border-hairline bg-surface-2 pl-6 py-2 text-[13px] text-ink focus:outline-none focus:border-accent" />
          </div>
        </div>
        <div>
          <label className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 mb-1 block">Monthly expenses <span className="text-ink-4 normal-case">(₹)</span></label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3 text-[13px]">₹</span>
            <input type="number" value={expenses} onChange={e => setExpenses(e.target.value)} placeholder="80,000"
              className="w-full rounded-lg border border-hairline bg-surface-2 pl-6 py-2 text-[13px] text-ink focus:outline-none focus:border-accent" />
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <button onClick={onSkip} className="flex items-center gap-1.5 text-[13px] text-ink-3 hover:text-ink">
          <SkipForward className="h-3.5 w-3.5" />Skip for now
        </button>
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-1.5 px-5 py-2 rounded-lg bg-accent text-on-accent text-[13px] font-medium hover:opacity-90 disabled:opacity-40"
        >
          {saving ? "Saving…" : "Save & finish"}<Check className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// ── Done screen ───────────────────────────────────────────────────────────────

function DoneScreen({ onClose }: { onClose: () => void }) {
  return (
    <div className="text-center py-4">
      <div className="inline-flex h-16 w-16 rounded-full bg-[rgba(var(--pos)/0.12)] items-center justify-center mb-4">
        <Check className="h-7 w-7 text-pos" />
      </div>
      <div className="font-display text-[22px] tracking-tightish mt-1">Profile complete</div>
      <p className="text-[13px] text-ink-3 mt-2 leading-relaxed max-w-[300px] mx-auto">
        Your risk profile and goal are saved. We've refreshed your action plan with goal-aware recommendations.
      </p>
      <button
        onClick={onClose}
        className="mt-6 w-full py-3 rounded-lg bg-accent text-on-accent font-medium text-[14px] hover:opacity-90 transition-opacity"
      >
        View my action plan →
      </button>
    </div>
  );
}

// ── Shell / orchestrator ──────────────────────────────────────────────────────

const STEP_META = [
  { label: "Risk profile",         key: "risk"     },
  { label: "Goals",                key: "goal"     },
  { label: "Snapshot (optional)",  key: "snapshot" },
];

export function ProfileWizardModal({ open, onClose, completeness, existingProfile, onComplete, startStep }: Props) {
  // Determine first incomplete step
  function firstIncomplete(): number {
    if (!completeness.hasRiskProfile) return 0;
    if (!completeness.hasGoal) return 1;
    return 2;
  }

  const [wizardStep, setWizardStep] = useState<number>(startStep ?? firstIncomplete());
  const [done, setDone] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    if (open) {
      setWizardStep(startStep ?? firstIncomplete());
      setDone(false);
    }
  }, [open]);

  if (!open) return null;

  async function finish() {
    setRefreshing(true);
    try {
      await plansService.refresh();
    } catch {
      // non-fatal — plan refresh is best-effort
    } finally {
      setRefreshing(false);
    }
    setDone(true);
    onComplete();
  }

  function advance() {
    if (wizardStep < 2) {
      setWizardStep(s => s + 1);
    } else {
      finish();
    }
  }

  const stepsDone = [
    completeness.hasRiskProfile,
    completeness.hasGoal,
    completeness.hasSnapshot,
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm" onClick={onClose} />

      <div className="relative bg-surface-1 border border-hairline rounded-2xl shadow-2xl w-full max-w-[500px] p-6 max-h-[90vh] overflow-y-auto">
        <button onClick={onClose} className="absolute top-4 right-4 text-ink-4 hover:text-ink-2">
          <X className="h-4 w-4" />
        </button>

        {done ? (
          <DoneScreen onClose={() => { onClose(); }} />
        ) : (
          <>
            {/* step header */}
            <div className="mb-5">
              <div className="font-mono text-[10px] uppercase tracking-[.16em] text-ink-3 mb-3">
                Complete your profile
              </div>
              <div className="flex items-center gap-2">
                {STEP_META.map((s, i) => (
                  <button
                    key={s.key}
                    onClick={() => setWizardStep(i)}
                    className={cn(
                      "flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono transition-all border",
                      i === wizardStep
                        ? "bg-accent text-on-accent border-accent"
                        : stepsDone[i]
                          ? "bg-[rgba(var(--pos)/0.12)] text-pos border-[rgba(var(--pos)/0.2)]"
                          : "bg-surface-2 text-ink-3 border-hairline hover:text-ink"
                    )}
                  >
                    {stepsDone[i] && i !== wizardStep ? <Check className="h-2.5 w-2.5" /> : <span>{i + 1}</span>}
                    {s.label}
                  </button>
                ))}
              </div>
            </div>

            {/* step title */}
            <div className="font-display text-[20px] tracking-tightish mb-4">
              {wizardStep === 0 && "What's your risk tolerance?"}
              {wizardStep === 1 && "Add your first goal"}
              {wizardStep === 2 && "Financial snapshot"}
            </div>
            {wizardStep === 2 && (
              <p className="text-[12.5px] text-ink-3 -mt-2 mb-4 leading-relaxed">
                Helps us calibrate your plan. All optional — skip if you'd rather not share now.
              </p>
            )}

            {/* step body */}
            {wizardStep === 0 && (
              <RiskStep
                existingProfile={existingProfile}
                onSaved={() => advance()}
                onSkip={advance}
              />
            )}
            {wizardStep === 1 && (
              <GoalStep
                onSaved={advance}
                onSkip={advance}
              />
            )}
            {wizardStep === 2 && (
              <SnapshotStep
                onSaved={finish}
                onSkip={finish}
              />
            )}

            {refreshing && (
              <p className="mt-3 text-[12px] text-ink-3 text-center">Refreshing your action plan…</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
