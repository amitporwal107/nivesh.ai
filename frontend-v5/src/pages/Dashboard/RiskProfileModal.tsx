import { useState } from "react";
import { X, ChevronRight, ChevronLeft, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSaveRiskProfile, type RiskProfile, type RiskAnswer, targetAllocationFor } from "@/hooks/use-risk-profile";

// ── Questions (mirrors V2 / backend score_map) ────────────────────────────────

const QUESTIONS: Array<{
  id: string;
  question: string;
  options: Array<{ value: string; label: string; sub?: string }>;
}> = [
  {
    id: "market_drop",
    question: "If markets drop 20% tomorrow, what would you do?",
    options: [
      { value: "buy_more",  label: "Buy more",    sub: "Great opportunity to accumulate" },
      { value: "hold",      label: "Hold steady", sub: "Stay the course, it will recover" },
      { value: "sell_some", label: "Sell some",   sub: "Reduce exposure to limit losses"  },
      { value: "sell_all",  label: "Exit fully",  sub: "Capital preservation is priority" },
    ],
  },
  {
    id: "investment_horizon",
    question: "What is your investment time horizon?",
    options: [
      { value: "10yr_plus", label: "10+ years",   sub: "Long-term wealth creation" },
      { value: "5_10yr",    label: "5–10 years",  sub: "Medium-to-long term"       },
      { value: "3_5yr",     label: "3–5 years",   sub: "Medium term"               },
      { value: "1_3yr",     label: "1–3 years",   sub: "Short-to-medium term"      },
      { value: "less_1yr",  label: "< 1 year",    sub: "Short term / liquidity"    },
    ],
  },
  {
    id: "loss_tolerance",
    question: "Maximum annual loss you can tolerate?",
    options: [
      { value: "up_to_50", label: "Up to 50%", sub: "High risk tolerance"    },
      { value: "up_to_25", label: "Up to 25%", sub: "Moderate risk tolerance" },
      { value: "up_to_10", label: "Up to 10%", sub: "Low risk tolerance"      },
      { value: "none",     label: "No loss",   sub: "Capital preservation"    },
    ],
  },
  {
    id: "income_stability",
    question: "How stable is your primary income?",
    options: [
      { value: "very_stable", label: "Very stable", sub: "Govt / salaried, predictable" },
      { value: "stable",      label: "Stable",      sub: "Regular employment"           },
      { value: "moderate",    label: "Moderate",    sub: "Business / freelance"          },
      { value: "unstable",    label: "Variable",    sub: "Commission / seasonal income"  },
    ],
  },
  {
    id: "investment_knowledge",
    question: "How would you rate your investment knowledge?",
    options: [
      { value: "expert",       label: "Expert",       sub: "CFA / fund manager level"   },
      { value: "advanced",     label: "Advanced",     sub: "Active investor, reads research" },
      { value: "intermediate", label: "Intermediate", sub: "Understands markets"         },
      { value: "beginner",     label: "Beginner",     sub: "Just starting out"           },
    ],
  },
  {
    id: "goal_priority",
    question: "What is your primary investment goal?",
    options: [
      { value: "aggressive_growth", label: "Aggressive growth", sub: "Maximise long-term returns"   },
      { value: "growth",            label: "Growth",            sub: "Beat inflation comfortably"    },
      { value: "income",            label: "Regular income",    sub: "Dividends / interest flow"     },
      { value: "safety",            label: "Capital safety",    sub: "Preserve purchasing power"     },
    ],
  },
];

// ── Result display ────────────────────────────────────────────────────────────

function ResultScreen({ profile, onDone }: { profile: RiskProfile; onDone: () => void }) {
  const alloc = targetAllocationFor(profile.category);
  const COLOR: Record<string, string> = {
    equity: "bg-[#3B82F6]", debt: "bg-[#10B981]", gold: "bg-[#F59E0B]", cash: "bg-ink-4",
  };
  return (
    <div className="text-center py-4">
      <div className="inline-flex h-16 w-16 rounded-full bg-[rgba(var(--pos)/0.12)] items-center justify-center mb-4">
        <Check className="h-7 w-7 text-pos" />
      </div>
      <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3">Your risk profile</div>
      <div className="font-display text-3xl mt-1">{profile.category}</div>
      <div className="font-mono text-[12px] text-ink-3 mt-1">Score {profile.score}/100</div>

      <div className="mt-6 rounded-lg bg-surface-2 border border-hairline p-4 text-left">
        <div className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 mb-3">Recommended target allocation</div>
        {alloc ? (
          <div className="space-y-2">
            {(["equity", "debt", "gold", "cash"] as const).map(k => (
              <div key={k} className="flex items-center gap-3">
                <span className="font-mono text-[11px] text-ink-3 w-10 uppercase">{k}</span>
                <div className="relative flex-1 h-1.5 rounded-full bg-surface-1">
                  <div className={cn("absolute inset-y-0 left-0 rounded-full", COLOR[k])} style={{ width: `${alloc[k]}%` }} />
                </div>
                <span className="font-mono text-[11px] text-ink-2 w-8 text-right">{alloc[k]}%</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="font-mono text-[11px] text-ink-3">Target allocation unavailable for this profile.</div>
        )}
      </div>

      <button
        onClick={onDone}
        className="mt-6 w-full py-3 rounded-lg bg-accent text-on-accent font-medium text-[14px] hover:opacity-90 transition-opacity"
      >
        Go to dashboard →
      </button>
    </div>
  );
}

// ── Modal ─────────────────────────────────────────────────────────────────────

interface Props {
  open: boolean;
  onClose: () => void;
  existingProfile?: RiskProfile | null;
  onSaved: () => void;
}

export function RiskProfileModal({ open, onClose, existingProfile, onSaved }: Props) {
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>(existingProfile?.answers ?? {});
  const [savedProfile, setSavedProfile] = useState<RiskProfile | null>(null);
  const save = useSaveRiskProfile();

  if (!open) return null;

  const q = QUESTIONS[step];
  const total = QUESTIONS.length;
  const answered = q ? answers[q.id] : null;

  function pick(val: string) {
    if (!q) return;
    setAnswers(prev => ({ ...prev, [q.id]: val }));
  }

  async function submit() {
    const payload: RiskAnswer[] = Object.entries(answers).map(([question_id, answer]) => ({ question_id, answer }));
    try {
      const profile = await save.mutateAsync(payload);
      setSavedProfile(profile);
    } catch {
      // error visible via save.isError
    }
  }

  function reset() {
    setStep(0);
    setAnswers({});
    setSavedProfile(null);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* backdrop */}
      <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm" onClick={onClose} />

      <div className="relative bg-surface-1 border border-hairline rounded-2xl shadow-2xl w-full max-w-[480px] p-6">
        {/* close */}
        <button onClick={onClose} className="absolute top-4 right-4 text-ink-4 hover:text-ink-2">
          <X className="h-4 w-4" />
        </button>

        {savedProfile ? (
          <ResultScreen profile={savedProfile} onDone={() => { onSaved(); reset(); }} />
        ) : (
          <>
            {/* progress */}
            <div className="flex items-center gap-1.5 mb-5">
              {QUESTIONS.map((_, i) => (
                <div
                  key={i}
                  className={cn(
                    "h-1 rounded-full transition-all flex-1",
                    i < step ? "bg-accent" : i === step ? "bg-accent/60" : "bg-surface-2"
                  )}
                />
              ))}
            </div>

            <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3 mb-1">
              Question {step + 1} of {total}
            </div>
            <h2 className="font-display text-[20px] tracking-tightish leading-snug mb-5">{q.question}</h2>

            <div className="space-y-2">
              {q.options.map(opt => (
                <button
                  key={opt.value}
                  onClick={() => pick(opt.value)}
                  className={cn(
                    "w-full flex items-start gap-3 px-4 py-3 rounded-lg border text-left transition-all",
                    answered === opt.value
                      ? "border-accent bg-[rgba(var(--accent)/0.08)] text-ink"
                      : "border-hairline bg-surface-2 text-ink-2 hover:border-ink-3 hover:text-ink"
                  )}
                >
                  <div className={cn(
                    "shrink-0 mt-0.5 h-4 w-4 rounded-full border-2 flex items-center justify-center",
                    answered === opt.value ? "border-accent bg-accent" : "border-ink-3"
                  )}>
                    {answered === opt.value && <div className="h-1.5 w-1.5 rounded-full bg-on-accent" />}
                  </div>
                  <div>
                    <div className="text-[13px] font-medium">{opt.label}</div>
                    {opt.sub && <div className="text-[11px] text-ink-3 mt-0.5">{opt.sub}</div>}
                  </div>
                </button>
              ))}
            </div>

            {/* nav */}
            <div className="flex items-center justify-between mt-6">
              <button
                onClick={() => setStep(s => Math.max(0, s - 1))}
                disabled={step === 0}
                className="flex items-center gap-1.5 text-[13px] text-ink-3 hover:text-ink disabled:opacity-30"
              >
                <ChevronLeft className="h-4 w-4" />Back
              </button>

              {step < total - 1 ? (
                <button
                  onClick={() => answered && setStep(s => s + 1)}
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
                  {save.isPending ? "Saving…" : "Get my profile"}
                  {!save.isPending && <Check className="h-4 w-4" />}
                </button>
              )}
            </div>

            {save.isError && (
              <p className="mt-3 text-[12px] text-neg text-center">Something went wrong — please try again.</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
