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
  type Proposal,
  type ProposalBucket,
  type ProposalFund,
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

  // generated proposal + selection + projection
  const [proposal, setProposal] = useState<Proposal | null>(null);
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
    } catch { setErr("Couldn't start the risk profiler. Try again."); }
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
    } catch { setErr("Couldn't record that answer. Try again."); }
    finally { setBusy(false); }
  }

  async function generate() {
    setErr(null); setBusy(true);
    abortRef.current = new AbortController();
    try {
      const p = await builderAdapter.generate(
        { monthly_sip_rs: M || undefined, lumpsum_rs: L || undefined, horizon_years: horizon, risk_bucket: profile?.category },
        abortRef.current.signal,
      );
      setProposal(p);
      // pre-select every picked fund
      const all = new Set<string>();
      p.buckets.forEach((b) => b.funds.forEach((f) => f.isin && all.add(f.isin)));
      setPicks(all);
      setStep(3);
    } catch { setErr("Couldn't generate the portfolio. The data service may be unavailable."); }
    finally { setBusy(false); }
  }

  async function project() {
    if (!proposal) return;
    setErr(null); setBusy(true);
    abortRef.current = new AbortController();
    try {
      const s = await builderAdapter.simulate(
        { starting_corpus_rs: L, monthly_sip_rs: M, years: horizon, allocation: proposal.allocation },
        abortRef.current.signal,
      );
      setSim(s); setStep(5);
    } catch { setErr("Couldn't run the projection. Showing your holdings without it."); setStep(5); }
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
          <div className="text-[12px] text-ink-3">Goal → mix → ranked picks, on your real risk profile</div>
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
      {step === 3 && proposal && <MixStep proposal={proposal} />}
      {step === 4 && proposal && <PickStep proposal={proposal} picks={picks} onToggle={togglePick} />}
      {step === 5 && proposal && <DoneStep proposal={proposal} picks={picks} sim={sim} years={horizon} L={L} M={M} />}

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
              : step === 2 ? "See my mix"
              : step === 3 ? "Pick instruments"
              : step === 4 ? "Review portfolio"
              : "Continue"} →
          </Button>
        )}
        {step === 5 && (
          <Button variant="ghost" size="sm" className="ml-auto" onClick={() => { setStep(0); setProposal(null); setSim(null); setProfile(data?.existing_profile ? profile : null); setRiskSession(null); setQuestion(null); }}>
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
                active ? "border-accent bg-accent-soft" : "border-hairline bg-surface-1 hover:bg-surface-2",
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
            className="rounded-md border border-hairline bg-surface-1 px-4 py-3 text-left text-[14px] text-ink hover:border-accent hover:bg-accent-soft transition-colors disabled:opacity-60"
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

/* ── Step 3: mix (allocation donut) ───────────────────────────────────────── */
function MixStep({ proposal }: { proposal: Proposal }) {
  const slices = Object.entries(proposal.allocation)
    .filter(([, pct]) => pct > 0)
    .map(([assetClass, pct]) => ({ assetClass, pct, label: ASSET_LABEL[assetClass] ?? assetClass }));
  return (
    <Section title="Recommended mix" sub={`Derived from your ${proposal.risk_profile ?? ""} risk profile.`}>
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
      {proposal.rationale.length > 0 && (
        <ul className="mt-3 border-t border-hairline pt-3 text-[13px] text-ink-3 leading-relaxed">
          {proposal.rationale.map((r, i) => <li key={i}>· {r}</li>)}
        </ul>
      )}
    </Section>
  );
}

/* ── Step 4: pick (ranked real instruments per bucket) ────────────────────── */
function PickStep({
  proposal, picks, onToggle,
}: { proposal: Proposal; picks: Set<string>; onToggle: (isin?: string | null) => void }) {
  return (
    <Section title="Fill your mix" sub="Each sleeve is filled with the highest-scoring funds for your profile. Toggle any off.">
      {proposal.buckets.map((b) => (
        <BucketBlock key={b.bucket} bucket={b} picks={picks} onToggle={onToggle} />
      ))}
    </Section>
  );
}

function BucketBlock({ bucket, picks, onToggle }: { bucket: ProposalBucket; picks: Set<string>; onToggle: (isin?: string | null) => void }) {
  const color = ASSET_COLOR[bucket.bucket] ?? "#A6A38E";
  return (
    <div className="mb-5">
      <div className="mb-2.5 flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: color }} />
        <span className="text-[14px] font-medium text-ink">{ASSET_LABEL[bucket.bucket] ?? bucket.bucket}</span>
        <span className="num text-[12px] text-ink-3">
          {Math.round(bucket.target_pct)}%
          {bucket.monthly_sip_rs ? ` · ${inr(bucket.monthly_sip_rs)}/mo` : ""}
          {bucket.target_rs ? ` · ${inr(bucket.target_rs)} once` : ""}
        </span>
      </div>
      {bucket.funds.length === 0 ? (
        // Honest gap: some sleeves (e.g. gold/cash) may have no ranked picks yet.
        <p className="rounded-md border border-dashed border-hairline-2 px-3.5 py-2.5 text-[12.5px] text-ink-3">
          Ranked fund picks for this sleeve aren't available yet — allocate it via a Gold ETF / liquid fund of your choice.
        </p>
      ) : (
        <div className="grid gap-2">
          {bucket.funds.map((f, i) => <FundRow key={f.isin ?? i} fund={f} rank={i + 1} selected={!!f.isin && picks.has(f.isin)} onToggle={() => onToggle(f.isin)} />)}
        </div>
      )}
    </div>
  );
}

function FundRow({ fund, rank, selected, onToggle }: { fund: ProposalFund; rank: number; selected: boolean; onToggle: () => void }) {
  const q = fund.quality_score ?? null;
  const band = q != null ? bandOf(q) : null;
  return (
    <div className={cn("rounded-md border bg-surface-1 px-3.5 py-3", selected ? "border-accent" : "border-hairline")}>
      <div className="flex items-center gap-3">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-[6px] bg-surface-2 num text-[12px] font-medium text-ink-3">{rank}</span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[14px] font-medium text-ink">{fund.scheme_name ?? "Fund"}</div>
          <div className="truncate text-[12px] text-ink-3">{fund.sub_category ?? fund.category ?? ""}{fund.rationale ? ` · ${fund.rationale}` : ""}</div>
        </div>
        {q != null && (
          <div className="text-center">
            <div className={cn("num font-display text-[20px] leading-none", band?.tone === "good" ? "text-pos" : band?.tone === "warm" ? "text-warm" : "text-ink")}>{Math.round(q)}</div>
            <div className="text-[10px] text-ink-4">quality</div>
          </div>
        )}
        <button
          type="button" onClick={onToggle}
          aria-pressed={selected}
          className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-md border text-[15px] font-medium transition-colors",
            selected ? "border-accent bg-accent text-on-accent" : "border-hairline-2 text-ink-3 hover:border-accent")}
        >{selected ? "✓" : "+"}</button>
      </div>
    </div>
  );
}

/* ── Step 5: done (projection + holdings) ─────────────────────────────────── */
function DoneStep({
  proposal, picks, sim, years, L, M,
}: { proposal: Proposal; picks: Set<string>; sim: Simulation | null; years: number; L: number; M: number }) {
  const chosen = proposal.buckets.flatMap((b) => b.funds.filter((f) => f.isin && picks.has(f.isin)).map((f) => ({ ...f, bucket: b.bucket })));
  const invested = L + M * years * 12;
  const base = sim?.scenarios?.base;
  const mc = sim?.monte_carlo;
  const mid = mc?.median_corpus_rs ?? base?.corpus_rs ?? null;
  const lo = mc?.p5_corpus_rs ?? sim?.scenarios?.bear?.corpus_rs ?? null;
  const hi = mc?.p95_corpus_rs ?? sim?.scenarios?.bull?.corpus_rs ?? null;

  return (
    <Section title="Your portfolio" sub={`${proposal.risk_profile ?? ""} · ${chosen.length} holdings · ${years}-year plan`}>
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
            <p className="mt-2 text-[12px] text-ink-4">Assumes ~{sim.blended_return_pct.toFixed(1)}% p.a. blended return at your allocation.</p>
          )}
        </div>
      )}

      <div className="rounded-md border border-hairline bg-surface-1 p-4">
        <div className="mb-2 font-display text-[15px] text-ink">Holdings</div>
        {chosen.length === 0 ? (
          <p className="text-[13px] text-ink-3">No funds selected.</p>
        ) : (
          <div className="grid gap-1.5">
            {chosen.map((f, i) => (
              <div key={f.isin ?? i} className="flex items-center gap-2.5 rounded-md border border-hairline px-3 py-2">
                <span className="h-2 w-2 rounded-[2px]" style={{ background: ASSET_COLOR[f.bucket] ?? "#A6A38E" }} />
                {f.quality_score != null && <span className="num text-[13px] font-semibold text-ink w-7">{Math.round(f.quality_score)}</span>}
                <span className="min-w-0 flex-1 truncate text-[13px] text-ink-2">{f.scheme_name}</span>
                {f.lumpsum_rs != null && <span className="num text-[11.5px] text-ink-3">{inr(f.lumpsum_rs)} once</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mt-3.5">
        <Button variant="accent" size="md" className="w-full">Confirm &amp; set up SIP →</Button>
      </div>
      <p className="mt-3 text-[11.5px] text-ink-4 leading-relaxed">
        Projections assume steady returns and ignore inflation, taxes, and market risk. Mutual funds are subject to market
        risk. Personalised securities advice in India is SEBI-regulated — confirm your RIA / distributor structure before acting.
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
