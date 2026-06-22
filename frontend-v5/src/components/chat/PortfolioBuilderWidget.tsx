/**
 * portfolio_builder — an in-chat, multi-step portfolio builder rendered below
 * the copilot bubble, in V5 styling. Unlike the read-only widgets, this one is
 * interactive: it drives the EXISTING backend endpoints as the user advances
 * (see builder.adapter.ts). Flow: Goal → Money → Risk → Mix → Pick → Done.
 *
 * Every figure shown is real:
 *   - Risk profile           ← /api/risk-profile/* (services.risk_profile_chat)
 *   - Allocation + ranked MFs ← /api/portfolio-builder/generate (target_allocator
 *                               + goal_fund_picker, real V3 quality scores)
 *   - Projection / scenarios  ← /api/portfolio-builder/simulate (goal_engine)
 * There is NO sample-data fallback — if a call fails we say so (CONTEXT.md).
 *
 * The seed `data` from the chat stream is optional (goals list / existing
 * profile hint); the widget self-drives the risk chat if not pre-filled.
 */
import { useEffect, useRef, useState } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer } from "recharts";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Stepper } from "@/components/shared/Stepper";
import {
  builderAdapter,
  type RiskQuestion,
  type SleeveProposal,
  type GovSleeve,
  type Simulation,
} from "@/services/adapters/builder.adapter";

/* ── token colours per asset class (mirror AllocationDonut) ───────────────── */
const ASSET_COLOR: Record<string, string> = {
  equity: "rgb(var(--accent))",
  debt: "#A6A38E",
  hybrid: "#8FAE9D",
  gold: "rgb(var(--warm))",
  cash: "#CFCFC2",
};
const ASSET_LABEL: Record<string, string> = {
  equity: "Equity", debt: "Debt", hybrid: "Hybrid", gold: "Gold", cash: "Liquid / Cash",
};

const STEPS = ["Goal", "Money", "Risk", "Mix", "Pick", "Done"] as const;

const GOALS = [
  { id: "retire", label: "Retirement", emoji: "🌅", years: 20, hint: "Long-term wealth for after work" },
  { id: "home", label: "Buy a home", emoji: "🏠", years: 7, hint: "Down payment or full purchase" },
  { id: "child", label: "Child's future", emoji: "🎓", years: 12, hint: "Education or marriage" },
  { id: "wealth", label: "Grow wealth", emoji: "📈", years: 10, hint: "No fixed deadline" },
  { id: "safety", label: "Safety net", emoji: "🛡️", years: 2, hint: "Emergency / rainy-day fund" },
] as const;

/* ── money helpers (rupees in, never paise) ───────────────────────────────── */
const inr = (n: number) => "₹" + Math.round(n).toLocaleString("en-IN");
const compact = (n: number) =>
  n >= 1e7 ? "₹" + (n / 1e7).toFixed(2) + " Cr" : n >= 1e5 ? "₹" + (n / 1e5).toFixed(2) + " L" : inr(n);
/** Pull a readable reason out of an ApiError / Error so failures aren't hidden
 *  behind a generic line (CONTEXT.md: errors are surfaced, not swallowed). */
function reason(e: unknown): string {
  const a = e as { status?: number; detail?: string; message?: string };
  const detail = a?.detail || a?.message;
  if (a?.status) return ` (HTTP ${a.status}${detail ? `: ${detail}` : ""})`;
  return detail ? ` (${detail})` : "";
}
const bandOf = (s: number) =>
  s >= 80 ? { label: "Excellent", tone: "good" as const }
  : s >= 65 ? { label: "Strong", tone: "good" as const }
  : s >= 50 ? { label: "Average", tone: "warm" as const }
  : { label: "Weak", tone: "neg" as const };

interface SeedData {
  goals?: typeof GOALS;
  has_risk_profile?: boolean;
  existing_profile?: { category?: string; persona?: string; score?: number; horizon_years?: number };
}

export function PortfolioBuilderWidget({ data }: { data?: SeedData; onAction?: unknown }) {
  const [step, setStep] = useState(0);
  const [goal, setGoal] = useState<typeof GOALS[number] | null>(null);
  const [lumpsum, setLumpsum] = useState("");
  const [monthly, setMonthly] = useState("");

  // risk chat
  const [riskSession, setRiskSession] = useState<string | null>(null);
  const [question, setQuestion] = useState<RiskQuestion | null>(null);
  const [profile, setProfile] = useState<
    { category: string; persona?: string; score?: number; horizon_years?: number | null } | null
  >(data?.existing_profile ? { category: data.existing_profile.category ?? "moderate", ...data.existing_profile } : null);

  // governed sleeve proposal + (named-mode) selection + projection
  const [sleeve, setSleeve] = useState<SleeveProposal | null>(null);
  const [picks, setPicks] = useState<Set<string>>(new Set());
  const [sim, setSim] = useState<Simulation | null>(null);

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => () => abortRef.current?.abort(), []);

  const L = Number(lumpsum) || 0;
  const M = Number(monthly) || 0;
  const horizon = profile?.horizon_years ?? goal?.years ?? 10;

  /* ── async transitions (every figure real; errors surfaced, never faked) ── */
  async function beginRisk() {
    setErr(null); setBusy(true);
    abortRef.current = new AbortController();
    try {
      const r = await builderAdapter.startRisk(abortRef.current.signal);
      setRiskSession(r.session_id); setQuestion(r.question);
    } catch (e) { setErr("Couldn't start the risk profiler." + reason(e)); }
    finally { setBusy(false); }
  }

  async function answer(value: string) {
    if (!riskSession || !question) return;
    setErr(null); setBusy(true);
    abortRef.current = new AbortController();
    try {
      const r = await builderAdapter.answerRisk(riskSession, question.id, value, abortRef.current.signal);
      if (r.complete) {
        setProfile({ category: r.category ?? "moderate", persona: r.persona, score: r.score, horizon_years: r.horizon_years });
        setQuestion(null);
      } else if (r.question) {
        setQuestion(r.question);
      }
    } catch (e) { setErr("Couldn't record that answer." + reason(e)); }
    finally { setBusy(false); }
  }

  async function generate() {
    setErr(null); setBusy(true);
    abortRef.current = new AbortController();
    try {
      const p = await builderAdapter.generateSleeves(
        { monthly_sip_rs: M || undefined, lumpsum_rs: L || undefined, horizon_years: horizon, risk_bucket: profile?.category },
        abortRef.current.signal,
      );
      setSleeve(p);
      // pre-select any named funds (only present when Compliance enables named-scheme mode)
      const all = new Set<string>();
      (p.sleeves || []).forEach((s) => (s.funds || []).forEach((f) => f.isin && all.add(f.isin)));
      setPicks(all);
      setStep(3);
    } catch (e) { setErr("Couldn't generate the portfolio." + reason(e)); }
    finally { setBusy(false); }
  }

  async function project() {
    if (!sleeve) return;
    setErr(null); setBusy(true);
    abortRef.current = new AbortController();
    try {
      const s = await builderAdapter.simulate(
        { starting_corpus_rs: L, monthly_sip_rs: M, years: horizon, allocation: sleeve.allocation || {} },
        abortRef.current.signal,
      );
      setSim(s); setStep(5);
    } catch (e) { setErr("Couldn't run the projection." + reason(e)); setStep(5); }
    finally { setBusy(false); }
  }

  const togglePick = (isin?: string | null) =>
    setPicks((prev) => { if (!isin) return prev; const n = new Set(prev); n.has(isin) ? n.delete(isin) : n.add(isin); return n; });

  const canNext =
    (step === 0 && !!goal) ||
    (step === 1 && (L > 0 || M > 0)) ||
    (step === 2 && !!profile) ||
    step === 3 ||
    step === 4;

  function next() {
    if (step === 2) { void generate(); return; }     // Risk → generate → Mix
    if (step === 4) { void project(); return; }       // Pick → simulate → Done
    setStep((s) => Math.min(STEPS.length - 1, s + 1));
  }

  return (
    <div className="mt-1 w-full rounded-lg bg-surface-1 border border-hairline shadow-card p-5 animate-[widget-in_0.35s_ease]">
      {/* header + stepper */}
      <div className="flex items-center gap-2.5 mb-4">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-on-accent font-display text-[15px]">न</span>
        <div className="leading-tight">
          <div className="font-display text-[17px] text-ink tracking-tightish">Portfolio Builder</div>
          <div className="text-[12px] text-ink-3">Goal → risk → governed allocation model</div>
        </div>
      </div>
      <div className="overflow-x-auto pb-1 mb-4">
        <Stepper steps={STEPS as unknown as string[]} active={step} />
      </div>

      {err && (
        <div className="mb-3 rounded-md border border-[rgb(var(--neg)/0.30)] bg-[rgb(var(--neg)/0.08)] px-3.5 py-2.5 text-[13px] text-neg">{err}</div>
      )}

      {step === 0 && <GoalStep goal={goal} onPick={setGoal} />}
      {step === 1 && <MoneyStep lumpsum={lumpsum} monthly={monthly} setLumpsum={setLumpsum} setMonthly={setMonthly} years={horizon} />}
      {step === 2 && (
        <RiskStep
          profile={profile} question={question} busy={busy}
          onBegin={beginRisk} onAnswer={answer}
        />
      )}
      {step === 3 && sleeve && <MixStep sleeve={sleeve} />}
      {step === 4 && sleeve && <PickStep sleeve={sleeve} picks={picks} onToggle={togglePick} />}
      {step === 5 && sleeve && <DoneStep sleeve={sleeve} picks={picks} sim={sim} years={horizon} L={L} M={M} />}

      {/* nav */}
      <div className="mt-5 flex items-center gap-2.5">
        {step > 0 && step < 5 && (
          <Button variant="outline" size="sm" onClick={() => setStep((s) => s - 1)} disabled={busy}>← Back</Button>
        )}
        {step < 5 && (
          <Button
            variant="accent" size="sm" className="ml-auto"
            disabled={!canNext || busy}
            onClick={next}
          >
            {busy ? "Working…"
              : step === 2 ? "See my allocation"
              : step === 3 ? "Review the plan"
              : step === 4 ? "Project outcome"
              : "Continue"} →
          </Button>
        )}
        {step === 5 && (
          <Button variant="ghost" size="sm" className="ml-auto" onClick={() => { setStep(0); setSleeve(null); setSim(null); setProfile(data?.existing_profile ? profile : null); setRiskSession(null); setQuestion(null); }}>
            ↺ Start over
          </Button>
        )}
      </div>
    </div>
  );
}

/* ── Step 0: goal ─────────────────────────────────────────────────────────── */
function GoalStep({ goal, onPick }: { goal: typeof GOALS[number] | null; onPick: (g: typeof GOALS[number]) => void }) {
  return (
    <Section title="What are you investing for?" sub="Your goal sets the horizon and how much risk makes sense.">
      <div className="grid gap-2.5">
        {GOALS.map((g) => {
          const active = goal?.id === g.id;
          return (
            <button
              key={g.id} type="button" onClick={() => onPick(g)}
              className={cn(
                "flex items-center gap-3.5 rounded-md border px-4 py-3 text-left transition-colors",
                active ? "border-accent bg-[rgb(var(--accent)/0.10)]" : "border-hairline bg-surface-1 hover:bg-surface-2",
              )}
            >
              <span className="text-[22px] leading-none">{g.emoji}</span>
              <span className="flex-1">
                <span className="block text-[14.5px] font-medium text-ink">{g.label}</span>
                <span className="text-[12.5px] text-ink-3">{g.hint}</span>
              </span>
              <span className="num text-[12px] text-ink-3">~{g.years} yrs</span>
            </button>
          );
        })}
      </div>
    </Section>
  );
}

/* ── Step 1: money ────────────────────────────────────────────────────────── */
function MoneyStep({
  lumpsum, monthly, setLumpsum, setMonthly, years,
}: { lumpsum: string; monthly: string; setLumpsum: (v: string) => void; setMonthly: (v: string) => void; years: number }) {
  return (
    <Section title="How much would you invest?" sub="A one-time amount, a monthly SIP, or both. We'll split it across your mix.">
      <Field label="One-time investment (lumpsum)"><NumInput value={lumpsum} onChange={setLumpsum} placeholder="e.g. 1,00,000" /></Field>
      <Field label="Monthly SIP"><NumInput value={monthly} onChange={setMonthly} placeholder="e.g. 10,000" /></Field>
      <p className="text-[12.5px] text-ink-3">Planning horizon ~{years} years — refined by your risk answers next.</p>
    </Section>
  );
}

/* ── Step 2: risk (conversational, real scoring) ──────────────────────────── */
function RiskStep({
  profile, question, busy, onBegin, onAnswer,
}: {
  profile: { category: string; persona?: string; score?: number } | null;
  question: RiskQuestion | null; busy: boolean;
  onBegin: () => void; onAnswer: (v: string) => void;
}) {
  // start the chat on first entry
  useEffect(() => { if (!profile && !question && !busy) onBegin(); /* eslint-disable-next-line */ }, []);

  if (profile) {
    const score = Math.round(profile.score ?? 0);
    return (
      <Section title="Your risk profile" sub="Scored from your answers — used to shape the allocation.">
        <div className="flex items-center gap-4 rounded-md border border-hairline bg-surface-2/60 p-4">
          <div className="text-center">
            <div className="font-display text-[34px] leading-none text-accent num">{score}</div>
            <div className="text-[11px] text-ink-3">/ 100</div>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-display text-[18px] text-ink tracking-tightish capitalize">{profile.persona ?? profile.category}</span>
              <Badge tone="accent" className="capitalize">{profile.category}</Badge>
            </div>
            <p className="mt-1 text-[13px] text-ink-3">We'll build a {profile.category} mix and rank instruments to fit it.</p>
          </div>
        </div>
      </Section>
    );
  }

  if (!question) {
    return (
      <Section title="A few questions about risk" sub="No right answers — this calibrates the mix to your comfort.">
        <div className="flex items-center gap-2 text-[13px] text-ink-3">
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-hairline-2 border-t-accent" />
          Starting the risk profiler…
        </div>
      </Section>
    );
  }

  return (
    <Section title={question.section || "Risk"} sub={question.subtitle || undefined}>
      <div className="mb-3 text-[14.5px] font-medium text-ink">
        {question.step != null && <span className="mr-1.5 text-warm">{question.step}.</span>}
        {question.prompt}
      </div>
      <div className="grid gap-2">
        {question.choices.map((c) => (
          <button
            key={c.value} type="button" disabled={busy} onClick={() => onAnswer(c.value)}
            className="rounded-md border border-hairline bg-surface-1 px-4 py-3 text-left text-[14px] text-ink hover:border-accent hover:bg-[rgb(var(--accent)/0.10)] transition-colors disabled:opacity-60"
          >
            {c.label}
          </button>
        ))}
      </div>
      {question.total_steps != null && (
        <p className="mt-3 text-[12px] text-ink-4">Question {question.step} of {question.total_steps}</p>
      )}
    </Section>
  );
}

const ASSET_GROUP_ORDER = ["equity", "debt", "gold", "cash"];
const capWord = (s?: string | null) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
const horizonLabel = (b?: string | null) => (b === "short" ? "short-term" : b === "long" ? "long-term" : "medium-term");
function groupByAsset(sleeves: GovSleeve[]): [string, GovSleeve[]][] {
  const m = new Map<string, GovSleeve[]>();
  for (const s of sleeves) (m.get(s.asset_class) ?? m.set(s.asset_class, []).get(s.asset_class)!).push(s);
  return [...m.entries()].sort((a, b) => ASSET_GROUP_ORDER.indexOf(a[0]) - ASSET_GROUP_ORDER.indexOf(b[0]));
}

/* ── Step 3: strategic allocation donut (asset-class rollup) ───────────────── */
function MixStep({ sleeve }: { sleeve: SleeveProposal }) {
  const slices = Object.entries(sleeve.allocation || {})
    .filter(([, pct]) => pct > 0)
    .map(([assetClass, pct]) => ({ assetClass, pct, label: ASSET_LABEL[assetClass] ?? assetClass }));
  return (
    <Section
      title="Your strategic allocation"
      sub={`${capWord(sleeve.risk_profile)} · ${horizonLabel(sleeve.horizon_bucket)} horizon — set by the governed allocation policy.`}
    >
      <div className="flex flex-wrap items-center gap-5">
        <div className="h-[168px] w-[168px] shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={slices} dataKey="pct" nameKey="label" cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={1} stroke="none">
                {slices.map((s) => <Cell key={s.assetClass} fill={ASSET_COLOR[s.assetClass] ?? "#A6A38E"} />)}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="min-w-[170px] flex-1">
          {slices.map((s) => (
            <div key={s.assetClass} className="flex items-center gap-2.5 py-1">
              <span className="h-3 w-3 rounded-[3px]" style={{ background: ASSET_COLOR[s.assetClass] ?? "#A6A38E" }} />
              <span className="flex-1 text-[14px] text-ink-2">{s.label}</span>
              <span className="num font-display text-[15px] text-ink">{Math.round(s.pct)}%</span>
            </div>
          ))}
        </div>
      </div>
      {sleeve.policy_version && (
        <p className="mt-3 border-t border-hairline pt-3 text-[12px] text-ink-4">
          Allocation policy v{sleeve.policy_version} · strategic weights by risk × horizon, respecting the risk budget.
        </p>
      )}
    </Section>
  );
}

/* ── Step 4: governed sub-sleeve model (category level; funds only if allowed) ── */
function PickStep({
  sleeve, picks, onToggle,
}: { sleeve: SleeveProposal; picks: Set<string>; onToggle: (isin?: string | null) => void }) {
  const namesOn = !!sleeve.compliance?.names_allowed;
  return (
    <Section
      title="Your allocation model"
      sub={namesOn
        ? "Governed sleeves, filled with the top-ranked funds for your profile."
        : "Category and model level. Specific scheme names appear once advisory registration is enabled."}
    >
      {groupByAsset(sleeve.sleeves || []).map(([ac, items]) => (
        <div key={ac} className="mb-4">
          <div className="mb-2 flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: ASSET_COLOR[ac] ?? "#A6A38E" }} />
            <span className="text-[13px] font-medium text-ink">{ASSET_LABEL[ac] ?? ac}</span>
            <span className="num text-[12px] text-ink-3">{Math.round(items.reduce((a, s) => a + s.target_pct, 0))}%</span>
          </div>
          <div className="grid gap-2">
            {items.map((s) => <SleeveBlock key={s.key} s={s} picks={picks} onToggle={onToggle} />)}
          </div>
        </div>
      ))}
      {sleeve.compliance?.disclaimer && (
        <p className="mt-1 rounded-md border border-dashed border-hairline-2 px-3.5 py-2.5 text-[12px] text-ink-3 leading-relaxed">
          {sleeve.compliance.disclaimer}
        </p>
      )}
    </Section>
  );
}

function SleeveBlock({ s, picks, onToggle }: { s: GovSleeve; picks: Set<string>; onToggle: (isin?: string | null) => void }) {
  return (
    <div className="rounded-md border border-hairline bg-surface-1 px-3.5 py-3">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[14px] font-medium text-ink">{s.label}</div>
          {(s.category_members || []).length > 0 && (
            <div className="truncate text-[12px] text-ink-3">{s.category_members.join(" · ")}</div>
          )}
        </div>
        <div className="text-right">
          <div className="num font-display text-[18px] text-ink leading-none">{s.target_pct}%</div>
          {s.monthly_sip_rs ? <div className="num text-[11px] text-ink-3">{inr(s.monthly_sip_rs)}/mo</div>
            : s.lumpsum_rs ? <div className="num text-[11px] text-ink-3">{inr(s.lumpsum_rs)} once</div> : null}
        </div>
      </div>
      {(s.funds || []).length > 0 && (
        <div className="mt-2 grid gap-1.5 border-t border-hairline pt-2">
          {s.funds.map((f, i) => {
            const sel = !!f.isin && picks.has(f.isin);
            return (
              <button
                key={f.isin ?? i} type="button" onClick={() => onToggle(f.isin)}
                className={cn("flex items-center gap-2.5 rounded-md border px-2.5 py-1.5 text-left transition-colors",
                  sel ? "border-accent bg-[rgb(var(--accent)/0.08)]" : "border-hairline hover:bg-surface-2")}
              >
                {f.quality_score != null && <span className="num w-6 text-[12px] font-semibold text-ink">{Math.round(f.quality_score)}</span>}
                <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink-2">{f.scheme_name}</span>
                <span className="text-[13px] text-ink-3">{sel ? "✓" : "+"}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ── Step 5: done (projection + model summary + disclaimer) ───────────────── */
function DoneStep({
  sleeve, picks, sim, years, L, M,
}: { sleeve: SleeveProposal; picks: Set<string>; sim: Simulation | null; years: number; L: number; M: number }) {
  const namesOn = !!sleeve.compliance?.names_allowed;
  const chosen = namesOn
    ? (sleeve.sleeves || []).flatMap((s) => (s.funds || []).filter((f) => f.isin && picks.has(f.isin)))
    : [];
  const invested = L + M * years * 12;
  const base = sim?.scenarios?.base;
  const mc = sim?.monte_carlo;
  const mid = mc?.median_corpus_rs ?? base?.corpus_rs ?? null;
  const lo = mc?.p5_corpus_rs ?? sim?.scenarios?.bear?.corpus_rs ?? null;
  const hi = mc?.p95_corpus_rs ?? sim?.scenarios?.bull?.corpus_rs ?? null;

  return (
    <Section title="Your plan" sub={`${capWord(sleeve.risk_profile)} · ${(sleeve.sleeves || []).length} sleeves · ${years}-year horizon`}>
      {mid != null && (
        <div className="mb-3.5 rounded-md border border-hairline bg-surface-2/60 p-4">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-[13px] text-ink-3">Projected in {years} yrs</span>
            <span className="num font-display text-[28px] text-accent tracking-tightish">{compact(mid)}</span>
          </div>
          {lo != null && hi != null && (
            <div className="num mt-1 text-[12.5px] text-ink-3">Range {compact(lo)} – {compact(hi)} · you invest {compact(invested)}</div>
          )}
          {mc?.prob_success_pct != null && (
            <div className="mt-2"><Badge tone={mc.prob_success_pct >= 70 ? "good" : "warm"}>{Math.round(mc.prob_success_pct)}% success probability</Badge></div>
          )}
          {sim?.blended_return_pct != null && (
            <p className="mt-2 text-[12px] text-ink-4">Assumes ~{sim.blended_return_pct.toFixed(1)}% p.a. blended return on house capital-market assumptions.</p>
          )}
        </div>
      )}

      <div className="rounded-md border border-hairline bg-surface-1 p-4">
        <div className="mb-2 font-display text-[15px] text-ink">{namesOn ? "Holdings" : "Allocation model"}</div>
        <div className="grid gap-1.5">
          {namesOn && chosen.length > 0
            ? chosen.map((f, i) => (
                <div key={f.isin ?? i} className="flex items-center gap-2.5 rounded-md border border-hairline px-3 py-2">
                  {f.quality_score != null && <span className="num w-7 text-[13px] font-semibold text-ink">{Math.round(f.quality_score)}</span>}
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink-2">{f.scheme_name}</span>
                  <span className="text-[11.5px] text-ink-4">{f.sub_category}</span>
                </div>
              ))
            : (sleeve.sleeves || []).map((s) => (
                <div key={s.key} className="flex items-center gap-2.5 rounded-md border border-hairline px-3 py-2">
                  <span className="h-2 w-2 rounded-[2px]" style={{ background: ASSET_COLOR[s.asset_class] ?? "#A6A38E" }} />
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink-2">
                    {s.label}{(s.category_members || []).length > 0 && <span className="text-ink-4"> · {s.category_members.join(", ")}</span>}
                  </span>
                  <span className="num text-[13px] font-semibold text-ink">{s.target_pct}%</span>
                </div>
              ))}
        </div>
      </div>

      <div className="mt-3.5">
        <Button variant="accent" size="md" className="w-full">{namesOn ? "Confirm & set up SIP →" : "Save this plan →"}</Button>
      </div>
      <p className="mt-3 text-[11.5px] text-ink-4 leading-relaxed">
        {sleeve.compliance?.disclaimer
          ?? "Model and category-level guidance, not a recommendation of specific schemes or stocks. Projections use house capital-market assumptions and ignore taxes; mutual funds are subject to market risk."}
      </p>
    </Section>
  );
}

/* ── small atoms ──────────────────────────────────────────────────────────── */
function Section({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="font-display text-[19px] text-ink tracking-tightish leading-snug">{title}</h3>
      {sub && <p className="mt-1 mb-4 text-[13px] text-ink-3 leading-relaxed">{sub}</p>}
      {!sub && <div className="mb-4" />}
      {children}
    </div>
  );
}
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <label className="mb-1.5 block text-[13.5px] font-medium text-ink">{label}</label>
      {children}
    </div>
  );
}
function NumInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div className="flex items-center overflow-hidden rounded-md border border-hairline bg-surface-1 focus-within:border-accent">
      <span className="px-3 font-medium text-ink-3">₹</span>
      <input
        inputMode="numeric" value={value} placeholder={placeholder}
        onChange={(e) => onChange(e.target.value.replace(/[^0-9]/g, ""))}
        className="num flex-1 bg-transparent py-3 pr-3 text-[15px] text-ink outline-none placeholder:text-ink-4"
      />
    </div>
  );
}
