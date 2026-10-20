/**
 * Strategy Builder, "From AI opportunities" mode - the scanner's top setups with the cash, futures, options and
 * combination strategies the rules built for each (POST /api/desk/strategy/ideas; reads sources, writes nothing).
 *
 * The header says where the ideas come from and by what rule, the data dates, and what was considered and left
 * out. Each idea is a card in the Overview opportunity rows' language: icon beside the symbol, scanner status,
 * "Score N/100", the setup, the scan close and date, liquidity and ATR risk; then the plan status with its
 * reasons, the evidence at a glance (technical, fundamental, open interest), and the strategies by segment. A
 * strategy that is not viable shows its reasons and "-", never a number. Every figure is the route's: nothing
 * is recomputed here. "Open full plan" and "Open this strategy" go to One stock mode with the idea's inputs in
 * the URL (and the build runs there); paper trade and save live in that view. Nothing places an order.
 */
import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { useSearchParams } from "react-router-dom";
import { StockIcon } from "../../../components/EntityIcon";
import { Btn, EmptyBlock, ErrorBlock, LoadingBlock, Pill, Section, fmtNum, humaniseTag, type Tone } from "../../../components/ui";
import { ApiError } from "@/services/api/errors";
import { INPUT_STYLE, fmtDay } from "../../trading/parts";
import { AddToList } from "../../workspace/PersonalLists";
import { useDesk, type DeskPersona } from "../context";
import { stampIst } from "../overview-data";
import { TrustLine } from "../trust";
import { Field } from "./PlanInputs";
import { SEGMENT_ORDER, type EvidenceCounts, type Idea, type IdeaStrategy, type IdeasBoard as Board } from "./ideas-contract";
import { ideasRequestFromForm, paramsFromPlanInputs, useStrategyIdeas, IDEAS_LIMIT, type IdeasRun } from "./ideas-data";
import type { FieldProblem } from "./plan-contract";
import { DIRECTION_LABEL } from "./plan-form";
import { EMPTY_FORM, type FormState } from "./plan-form";
import { isForbiddenPlan, planFailure, planProblems } from "./plan-data";
import { CHARTINK_CANDIDATE_NOTE, CHARTINK_FAMILY, DASH, StatusPill, noteStyle, ratio, rupees, rupeesAbs, valueText } from "./plan-format";
import { Switch } from "../chartink/ChartinkParts";
import { useChartinkSource } from "../chartink/chartink-data";
import type { PlanStatus } from "./plan-contract";

const SEGMENT_TITLE: Record<string, string> = { cash: "Cash", futures: "Futures", options: "Options", combination: "Combination" };
const STRATEGY_STATUS: Record<string, { label: string; tone: Tone; glyph: string }> = {
  candidate: { label: "Viable", tone: "mint", glyph: "✓" },
  wait: { label: "Wait", tone: "amber", glyph: "◔" },
  no_trade: { label: "No trade", tone: "danger", glyph: "✕" },
  avoid: { label: "Avoid", tone: "danger", glyph: "⊘" },
  insufficient_data: { label: "Insufficient data", tone: "ink", glyph: "?" },
};
const SCAN_STATUS: Record<string, { label: string; tone: Tone }> = {
  confirmed: { label: "Confirmed", tone: "mint" }, awaiting: { label: "Awaiting", tone: "amber" }, forming: { label: "Forming", tone: "ink" },
};
const PLAN_STATUSES = ["plan", "wait", "no_trade", "insufficient_data"];
const th: CSSProperties = { textAlign: "left", padding: "8px 10px", whiteSpace: "nowrap", borderBottom: "1px solid var(--cp-line)" };
const td: CSSProperties = { padding: "10px", verticalAlign: "top", borderBottom: "1px solid var(--cp-line)", fontSize: 12.5 };
const linkBtn: CSSProperties = { padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--mint)", fontFamily: "var(--sans)" };

const FIELD_OF: Record<string, string> = { capital: "capital", risk_budget_inr: "risk", risk_pct: "risk", max_allocation_pct: "max_allocation_pct", min_reward_risk: "min_reward_risk" };

// ── the board ────────────────────────────────────────────────────────────

export function IdeasBoard() {
  const { persona } = useDesk();
  const plain = persona === "investor";
  const [params] = useSearchParams();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [combos, setCombos] = useState(true);
  // The user's Chartink scans: the switch exists only with a connected dashboard (the route's default is "include" then).
  const ckSource = useChartinkSource();
  const ckConnected = ckSource.data != null;
  const [ckOn, setCkOn] = useState(true);
  const [clientProblems, setClientProblems] = useState<FieldProblem[]>([]);
  const [run, setRun] = useState<IdeasRun | null>(null);
  const q = useStrategyIdeas(run);
  const board = q.data ?? null;

  const start = (ck: boolean = ckOn) => {
    const { request, problems } = ideasRequestFromForm(form, combos, ckConnected ? ck : null);
    setClientProblems(problems);
    if (request) setRun((r) => ({ body: request, runId: (r?.runId ?? 0) + 1 }));
  };

  // Once on open, with the defaults (the user's inputs are blank): the route names what it defaulted.
  const autoRan = useRef(false);
  useEffect(() => {
    if (autoRan.current) return;
    autoRan.current = true;
    setRun({ body: { limit: IDEAS_LIMIT, include_combinations: true }, runId: 1 });
  }, []);

  // ?focus=<SYM> scrolls to that idea once the board is there.
  const focus = params.get("focus");
  const scrolled = useRef<string | null>(null);
  useEffect(() => {
    if (!focus || !board || scrolled.current === focus) return;
    const el = document.querySelector(`[data-testid="idea-${CSS.escape(focus.toUpperCase())}"]`);
    scrolled.current = focus;
    el?.scrollIntoView({ block: "start" });
  }, [focus, board]);

  const serverProblems = q.isError ? planProblems(q.error) : [];
  const failure = q.isError && serverProblems.length === 0 ? q.error : null;
  const scanDate = board?.selection.scan_date ?? null;

  return (
    <div data-testid="strategy-ideas" data-persona={persona} className="flex min-w-0 flex-col" style={{ gap: 18 }}>
      <header className="flex flex-col" style={{ gap: 8 }}>
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <span className="cp-eyebrow">Strategy Builder</span>
          <span className="cp-pill" data-tone="indigo">Analysis only</span>
          <span className="cp-pill">End of day</span>
        </span>
        <h1 className="cp-display m-0" data-testid="ideas-title" style={{ fontSize: 34, lineHeight: 1.1, letterSpacing: "-0.02em" }}>
          {plain ? <>Ways to trade the AI scanner's <em>top ideas</em></> : <>Strategies for the AI scanner's <em>top setups</em></>}
        </h1>
        <p data-testid="ideas-source" className="m-0" style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          Top setups from the AI scanner, end-of-day scan {scanDate ? fmtDay(scanDate) : DASH}; ranked by the scanner's rules-based score, not a probability.
        </p>
        <p className="m-0" style={noteStyle}>Conditional research plans, not instructions. Nivesh does not place orders; nothing here is sent to a broker.</p>
      </header>

      <IdeasInputs form={form} onChange={setForm} combos={combos} onCombos={setCombos} ck={ckConnected ? { on: ckOn, onChange: (v) => { setCkOn(v); start(v); } } : null} onBuild={() => start()} pending={q.isFetching} problems={[...clientProblems, ...serverProblems]} plain={plain} board={board} />

      {board == null && q.isPending && run != null && <LoadingBlock label="Picking the scanner's top setups and building their strategies" rows={4} />}

      {failure != null && (
        <div data-testid="ideas-error" className="flex flex-col" style={{ gap: 8 }}>
          {isForbiddenPlan(failure) || (failure instanceof ApiError && failure.kind === "auth") ? (
            <EmptyBlock title={failure instanceof ApiError && failure.kind === "auth" ? "Sign in to see strategies for the AI opportunities" : "The Strategy Builder is not enabled for this account"} body={planFailure(failure, "Not built")} />
          ) : (
            <ErrorBlock title={planFailure(failure, "The ideas were not built")} onRetry={() => q.refetch()} />
          )}
        </div>
      )}

      {board && (
        <div data-testid="ideas-view" aria-busy={q.isFetching} className="flex min-w-0 flex-col" style={{ gap: 18 }}>
          {q.isFetching && <p role="status" data-testid="ideas-updating" className="m-0" style={noteStyle}>Updating. The ideas below are from the previous run until this one finishes.</p>}
          <BoardHeader board={board} plain={plain} />
          {board.ideas.length === 0 ? (
            <div data-testid="ideas-empty">
              <EmptyBlock
                title="The scanner has no setups on its latest scan, so there is nothing to build strategies from"
                body={board.selection.empty_reason ?? board.selection.rule ?? "The scanner lists stocks only after its end-of-day run. Nothing is shown in place of a real scan."}
              />
            </div>
          ) : (
            <>
              <PartialNote ideas={board.ideas} />
              <ol className="m-0 flex min-w-0 flex-col p-0" style={{ listStyle: "none", gap: 16 }}>
                {board.ideas.map((idea) => (
                  <li key={idea.symbol} className="min-w-0"><IdeaCard idea={idea} board={board} persona={persona} /></li>
                ))}
              </ol>
              <p data-testid="ideas-paper-note" className="m-0" style={noteStyle}>
                Paper trade and save are in the full plan: they need its whole payoff, signals and plan. Use "Open full plan" or "Open this strategy".
              </p>
            </>
          )}
          {board.caveats.length > 0 && <Caveats items={board.caveats} />}
          <TrustLine
            testId="ideas-trust" source="Positional scanner (end-of-day scan), NSE F&O bhavcopy, strategy rules" mode="eod"
            asOf={board.data_as_of.price ? fmtDay(board.data_as_of.price) : null} maker="rules"
            method={[board.rules_version ? `rules ${board.rules_version}` : null, board.calculation_version ? `calculation ${board.calculation_version}` : null].filter(Boolean).join(" · ") || null}
          />
          {board.ideas.some((i) => i.chartink) && (
            <TrustLine
              testId="ideas-ck-trust" source="Chartink scans (your dashboard)" mode={null}
              asOf={(() => { const f = board.ideas.find((i) => i.chartink?.fetched_at)?.chartink?.fetched_at; return f ? `Chartink fetched ${stampIst(f)}` : null; })()}
              method="your scan rules, not validated signals"
            />
          )}
        </div>
      )}
    </div>
  );
}

function Caveats({ items }: { items: string[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="flex flex-col" style={{ gap: 6 }}>
      <button type="button" data-testid="ideas-caveats-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)} style={{ ...linkBtn, alignSelf: "flex-start", color: "var(--cp-ink-2)" }}>{open ? "▾" : "▸"} Caveats ({items.length})</button>
      <div id={id} hidden={!open} data-testid="ideas-caveats">
        <ul className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 18, fontSize: 12, color: "var(--cp-ink-3)" }}>
          {items.map((c) => <li key={c}>{c}</li>)}
        </ul>
      </div>
    </div>
  );
}

function PartialNote({ ideas }: { ideas: Idea[] }) {
  const n = ideas.filter((i) => i.plan_status === "insufficient_data").length;
  if (!n) return null;
  return (
    <p role="note" data-testid="ideas-partial" className="m-0" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
      {n} of {ideas.length} ideas have insufficient data, so no strategy is built for them. The others are unaffected.
    </p>
  );
}

// ── the header: data dates, ranking, what was considered ─────────────────

function BoardHeader({ board, plain }: { board: Board; plain: boolean }) {
  const sel = board.selection;
  const [open, setOpen] = useState(false);
  const id = useId();
  const a = board.data_as_of;
  const scanOlder = !!(sel.scan_date && a.price && sel.scan_date.slice(0, 10) < a.price.slice(0, 10));
  return (
    <section data-testid="ideas-header" aria-label="Where these ideas come from" className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: 16 }}>
      <p data-testid="ideas-asof" className="m-0" style={{ fontSize: 13 }}>
        Scan {sel.scan_date ? fmtDay(sel.scan_date) : DASH} · prices {a.price ? fmtDay(a.price) : DASH} · F&amp;O {a.fno ? fmtDay(a.fno) : DASH} · end of day, not live
      </p>
      {scanOlder && (
        <p role="note" data-testid="ideas-scan-older" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-amber, var(--cp-ink-2))" }}>
          <span aria-hidden>◔ </span>The scan is older than the price data: the setups are from {fmtDay(sel.scan_date)}, the strategies use prices from {fmtDay(a.price)}. The scanner's entry, stop and target may be out of date.
        </p>
      )}
      {sel.rule && <p data-testid="ideas-rule" className="m-0" style={noteStyle}>{plain ? "How they were picked" : "Selection rule"}: {sel.rule}</p>}
      {board.ranking_note && <p data-testid="ideas-ranking" className="m-0" style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{board.ranking_note}</p>}
      {board.inputs.defaults_applied.length > 0 && (
        <p data-testid="ideas-defaults" className="m-0" style={noteStyle}>
          Defaults applied because the input was left blank ({board.rules_version ?? "the rules"}): {board.inputs.defaults_applied.map((k) => { const v = (board.inputs as Record<string, unknown>)[k]; return `${humaniseTag(k).toLowerCase()}${typeof v === "number" || typeof v === "boolean" || typeof v === "string" ? ` ${String(v)}` : ""}`; }).join(", ")}. Set them above and build again.
        </p>
      )}
      <div className="flex flex-col" style={{ gap: 6 }}>
        <button type="button" data-testid="ideas-considered-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)} style={{ ...linkBtn, alignSelf: "flex-start", color: "var(--cp-ink-2)" }}>
          {open ? "▾" : "▸"} Considered {fmtNum(sel.considered)}, selected {fmtNum(sel.selected)}, left out {fmtNum(sel.excluded.length)}
        </button>
        <div id={id} hidden={!open} data-testid="ideas-considered">
          {sel.gate && <p data-testid="ideas-gate" className="m-0" style={{ ...noteStyle, paddingBottom: 6 }}>Eligibility: {sel.gate}.</p>}
          {sel.source_failures.length > 0 && <p role="note" data-testid="ideas-source-failures" className="m-0" style={{ fontSize: 12.5, paddingBottom: 6 }}>Source problems: {sel.source_failures.join("; ")}</p>}
          {sel.excluded.length === 0 ? (
            <p className="m-0" style={noteStyle}>Nothing was left out.</p>
          ) : (
            <>
              <ul className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18 }}>
                {sel.excluded.map((x) => (
                  <li key={x.symbol} data-testid="ideas-excluded" style={{ fontSize: 12.5 }}><strong className="cp-num" style={{ fontWeight: 500 }}>{x.symbol}</strong>: {x.reason || "no reason given"}</li>
                ))}
              </ul>
              {sel.excluded_note && <p data-testid="ideas-excluded-note" className="m-0" style={{ ...noteStyle, paddingTop: 6 }}>{sel.excluded_note}</p>}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

// ── the inputs ───────────────────────────────────────────────────────────

function IdeasInputs({ form, onChange, combos, onCombos, ck, onBuild, pending, problems, plain, board }: {
  form: FormState; onChange: (f: FormState) => void; combos: boolean; onCombos: (b: boolean) => void; ck: { on: boolean; onChange: (v: boolean) => void } | null; onBuild: () => void; pending: boolean; problems: FieldProblem[]; plain: boolean; board: Board | null;
}) {
  const id = useId();
  const set = (patch: Partial<FormState>) => onChange({ ...form, ...patch });
  const by = (f: string) => problems.filter((p) => FIELD_OF[p.field] === f);
  const other = problems.filter((p) => !(p.field in FIELD_OF));
  const text = (key: keyof FormState, fieldId: string, testId: string, placeholder: string) => (
    <input id={`${id}-${fieldId}`} data-testid={testId} value={String(form[key] ?? "")} inputMode="decimal" placeholder={placeholder} aria-invalid={by(fieldId).length > 0 || undefined} onChange={(e) => set({ [key]: e.target.value } as Partial<FormState>)} style={INPUT_STYLE} />
  );
  return (
    <Section title={plain ? "How much do you want to use?" : "Inputs"} note="Blank fields use the default, and the board lists it">
      <form data-testid="ideas-inputs" className="flex min-w-0 flex-col" style={{ gap: 14 }} onSubmit={(e) => { e.preventDefault(); onBuild(); }}>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,200px),1fr))", gap: "14px 18px" }}>
          <Field testId="capital" label={plain ? "Money you can use (₹)" : "Capital (₹)"} htmlFor={`${id}-capital`} problems={by("capital")} hint="Needed with a risk percentage and for the allocation cap.">
            {text("capital", "capital", "ideas-in-capital", "1000000")}
          </Field>
          <Field
            testId="risk" htmlFor={`${id}-risk`} problems={by("risk")} hint="One of the two. Blank means sizing is incomplete, with no quantity."
            label={
              <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
                {plain ? "The most you accept losing" : "Risk"}
                <span role="group" aria-label="Risk as" className="flex" style={{ gap: 4 }}>
                  {(["inr", "pct"] as const).map((m) => (
                    <button key={m} type="button" className="cp-chip" aria-pressed={form.riskMode === m} data-testid={`ideas-risk-mode-${m}`} onClick={() => set({ riskMode: m, risk: "" })}
                      style={{ padding: "2px 8px", fontSize: 11, ...(form.riskMode === m ? { borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" } : undefined) }}>
                      {m === "inr" ? "₹ budget" : "% of capital"}
                    </button>
                  ))}
                </span>
              </span>
            }
          >
            {text("risk", "risk", "ideas-in-risk", form.riskMode === "inr" ? "10000" : "1")}
          </Field>
          <Field testId="max_allocation_pct" label={plain ? "Biggest share of your money in one idea (%)" : "Maximum allocation (%)"} htmlFor={`${id}-max_allocation_pct`} problems={by("max_allocation_pct")}>
            {text("maxAlloc", "max_allocation_pct", "ideas-in-alloc", "")}
          </Field>
          <Field testId="min_reward_risk" label={plain ? "Reward you want for each ₹1 risked" : "Minimum reward : risk"} htmlFor={`${id}-min_reward_risk`} problems={by("min_reward_risk")}>
            {text("minRr", "min_reward_risk", "ideas-in-minrr", "")}
          </Field>
        </div>
        <div className="flex flex-wrap" style={{ gap: "10px 24px" }}>
          <label className="flex items-center" style={{ gap: 8, fontSize: 13 }}>
            <input type="checkbox" data-testid="ideas-in-avoid-events" checked={form.avoidEvents ?? true} onChange={(e) => set({ avoidEvents: e.target.checked })} />
            {plain ? "Stay clear of results and other events" : "Avoid event windows"}{form.avoidEvents == null && <span style={noteStyle}>(default)</span>}
          </label>
          <label className="flex items-center" style={{ gap: 8, fontSize: 13 }}>
            <input type="checkbox" data-testid="ideas-in-multi-leg" checked={form.allowMultiLeg ?? true} onChange={(e) => set({ allowMultiLeg: e.target.checked })} />
            {plain ? "Allow combined option trades (spreads)" : "Allow multi-leg"}{form.allowMultiLeg == null && <span style={noteStyle}>(default)</span>}
          </label>
          <label className="flex items-center" style={{ gap: 8, fontSize: 13 }}>
            <input type="checkbox" data-testid="ideas-in-combos" checked={combos} onChange={(e) => onCombos(e.target.checked)} />
            {plain ? "Include shares-plus-options combinations" : "Include combinations (covered call, protective put, collar)"}
          </label>
        </div>
        {ck && (
          <div className="flex flex-wrap items-center" style={{ gap: "6px 12px" }}>
            <Switch testId="ideas-in-chartink" label="Include my Chartink scans" on={ck.on} onChange={ck.onChange} />
            <span style={{ fontSize: 13 }}>Include my Chartink scans</span>
            <span style={noteStyle}>{ck.on ? "Chartink-only ideas follow the AI scanner’s, ranked by how many of your scans list them." : "Only the AI scanner’s ideas."}</span>
          </div>
        )}
        {other.length > 0 && (
          <ul data-testid="ideas-problems-other" className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18 }}>
            {other.map((p) => <li key={`${p.field}:${p.code}`} role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>{p.field ? `${p.field}: ` : ""}{p.message}</li>)}
          </ul>
        )}
        <div className="flex flex-wrap items-center" style={{ gap: "8px 14px" }}>
          <Btn variant="primary" type="submit" data-testid="build-ideas" disabled={pending} aria-busy={pending}>{pending ? "Building…" : board ? "Build ideas again" : "Build ideas"}</Btn>
          <span style={noteStyle}>Reads end-of-day data and writes nothing. Nothing is sent to a broker.</span>
        </div>
      </form>
    </Section>
  );
}

// ── one idea ─────────────────────────────────────────────────────────────

const countsText = (c: EvidenceCounts | undefined) => (c ? `${c.supports} support · ${c.conflicts} conflict · ${c.neutral} neutral · ${c.unavailable} unavailable` : `${DASH} not in the answer`);
const plainVal = (v: unknown) => (v == null || v === "" ? DASH : valueText(v));
const num2 = (n: number | null) => (n == null ? DASH : fmtNum(n, 2));

const SOURCE_TAG: Record<string, { label: string; tone: Tone }> = {
  ai_scanner: { label: "AI scanner", tone: "mint" },
  chartink: { label: "Chartink", tone: "indigo" },
  both: { label: "Both", tone: "indigo" },
};

function IdeaSourceTag({ idea }: { idea: Idea }) {
  const t = idea.source ? SOURCE_TAG[idea.source] : null;
  if (!t) return null;
  return (
    <span data-testid="idea-source" data-source={idea.source} title={idea.source === "both" ? "Listed by the AI scanner and by your Chartink scans" : idea.source === "chartink" ? "From your Chartink scans; the AI scanner does not list it" : "From the AI scanner"}>
      <Pill tone={t.tone}>{idea.source === "both" ? "AI scanner + Chartink" : t.label}</Pill>
    </span>
  );
}

function IdeaCard({ idea, board, persona }: { idea: Idea; board: Board; persona: DeskPersona }) {
  const plain = persona === "investor";
  const [, setParams] = useSearchParams();
  const sc = idea.scanner;
  const st = sc.status ? SCAN_STATUS[sc.status] : null;
  const dir = DIRECTION_LABEL[idea.direction as keyof typeof DIRECTION_LABEL];
  const planStatus = (PLAN_STATUSES.includes(idea.plan_status) ? idea.plan_status : "insufficient_data") as PlanStatus;
  const scanDate = board.selection.scan_date ?? sc.close_date;
  const titleId = `idea-title-${idea.symbol}`;

  const openPlan = (cand?: string) => setParams((prev) => {
    const p = new URLSearchParams(prev);
    for (const k of ["mode", "build", "plan", "cand", "focus", "sym", "direction", "instrument", "horizon", "horizon_days", "capital", "risk_inr", "risk_pct", "max_alloc", "min_rr", "avoid_events", "multi_leg", "expiry"]) p.delete(k);
    for (const [k, v] of Object.entries({ sym: idea.symbol, direction: idea.direction, ...paramsFromPlanInputs(idea.plan_inputs) })) if (v) p.set(k, v);
    p.set("mode", "stock");
    p.set("build", "1");
    p.set("src_kind", "ideas");
    if (sc.bucket) p.set("src_bucket", sc.bucket); else p.delete("src_bucket");
    if (scanDate) p.set("src_date", scanDate); else p.delete("src_date");
    if (cand) p.set("cand", cand);
    return p;
  });

  return (
    <article data-testid={`idea-${idea.symbol}`} data-symbol={idea.symbol} data-rank={idea.rank} data-plan-status={planStatus} aria-labelledby={titleId} className="cp-card flex min-w-0 flex-col" style={{ gap: 14, padding: 16 }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 14px" }}>
        <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 10px" }}>
          <span className="cp-num" data-testid="idea-rank" style={{ fontSize: 11, color: idea.rank === 1 ? "var(--mint)" : "var(--cp-ink-3)" }}>{String(idea.rank).padStart(2, "0")}</span>
          <StockIcon symbol={idea.symbol} name={idea.name} size={26} />
          <h2 id={titleId} data-testid="idea-symbol" className="cp-num m-0" style={{ fontSize: 17, fontWeight: 500 }}>{idea.symbol}</h2>
          <span data-testid="idea-name" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{idea.name ?? DASH}</span>
          <IdeaSourceTag idea={idea} />
          {st ? <span data-testid="idea-scan-status"><Pill tone={st.tone}>{st.label}</Pill></span> : <span data-testid="idea-scan-status" style={noteStyle}>Scanner status {DASH}</span>}
          <StatusPill status={planStatus} plain={plain} testId="idea-plan-status" />
        </span>
        <span data-testid="idea-score" className="cp-num" title="Rules-based scanner score, 0-100 (not a probability)" style={{ fontSize: 12, color: sc.score != null && sc.score >= 80 ? "var(--mint)" : "var(--cp-ink-2)" }}>
          {idea.source === "chartink" && sc.score == null ? "No AI score" : `Score ${sc.score == null ? DASH : `${fmtNum(sc.score)}/100`}`}
        </span>
      </div>

      <p data-testid="idea-facts" className="m-0 flex flex-wrap" style={{ gap: "2px 14px", fontSize: 12, color: "var(--cp-ink-2)" }}>
        <span data-testid="idea-setup">{plain ? "Shape" : "Setup"}: {sc.bucket ? humaniseTag(sc.bucket) : idea.source === "chartink" ? "Chartink scan (not an AI scanner setup)" : sc.stage ? `${humaniseTag(sc.stage.toLowerCase())} (scanner pick)` : DASH}</span>
        <span data-testid="idea-direction">{plain ? "Expected" : "Direction"}: {dir ? dir[plain ? "plain" : "trader"] : idea.direction || DASH}</span>
        <span data-testid="idea-close">Scan close: {sc.close != null ? rupees(sc.close) : DASH}{sc.close_date ? ` on ${fmtDay(sc.close_date)}` : ""}</span>
        <span data-testid="idea-liquidity">Liquidity: {sc.liquidity_cr != null ? `₹${fmtNum(sc.liquidity_cr, sc.liquidity_cr < 100 ? 1 : 0)} Cr/day` : DASH}</span>
        <span data-testid="idea-risk">{plain ? "Swings" : "Risk"}: {sc.atr_pct != null ? `ATR ${fmtNum(sc.atr_pct, 1)}% of price` : `${DASH} no ATR in the scanner's row for this stock`}</span>
      </p>

      {idea.chartink && idea.chartink.scans.length > 0 && (
        <p data-testid="idea-ck-scans" className="m-0" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
          On your Chartink {idea.chartink.scans.length === 1 ? "scan" : "scans"}: {idea.chartink.scans.map((x) => x.name).join(", ")}
          {idea.chartink.fetched_at ? <span style={noteStyle}> · fetched {stampIst(idea.chartink.fetched_at)}</span> : null}
        </p>
      )}

      <div data-testid="idea-reasons" className="flex flex-col" style={{ gap: 4 }}>
        {idea.status_reasons.length > 0 ? (
          <ul className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 18 }}>
            {idea.status_reasons.map((r) => <li key={r.code + r.message} style={{ fontSize: 12.5 }}>{r.message}</li>)}
          </ul>
        ) : (
          <span style={noteStyle}>The route gave no status reasons.</span>
        )}
        {idea.would_change_if.length > 0 && (
          <span data-testid="idea-would-change" style={noteStyle}>{plain ? "This could change if" : "Would change if"}: {idea.would_change_if.join("; ")}</span>
        )}
      </div>

      <Evidence idea={idea} plain={plain} />
      <Strategies idea={idea} plain={plain} onOpen={openPlan} />

      <div className="flex flex-wrap items-center" style={{ gap: "8px 16px" }}>
        <Btn variant="primary" data-testid="idea-open-plan" onClick={() => openPlan()} style={{ padding: "6px 12px", fontSize: 12 }}>Open full plan ›</Btn>
        <AddToList symbol={idea.symbol} name={idea.name ?? idea.symbol} />
      </div>
      <TrustLine testId="idea-trust" source="Scanner row and strategy rules" mode="eod" asOf={sc.close_date ? fmtDay(sc.close_date) : null} maker="rules" method={board.rules_version ? `rules ${board.rules_version}` : null} />
    </article>
  );
}

// ── evidence at a glance ─────────────────────────────────────────────────

function Evidence({ idea, plain }: { idea: Idea; plain: boolean }) {
  const ev = idea.evidence_summary;
  const oi = idea.oi_view;
  const missing = idea.fno_eligible === false ? "no futures and options for this stock, so no open-interest view" : "the F&O data gave no open-interest view for this stock";
  const empty = !oi || (oi.buildup == null && oi.cash_confirmation == null && oi.pcr == null && oi.call_wall == null && oi.put_wall == null && oi.max_pain == null);
  return (
    <div data-testid="idea-evidence" role="group" aria-label="Evidence at a glance" className="flex min-w-0 flex-col" style={{ gap: 4 }}>
      <span data-testid="idea-ev-technical" style={{ fontSize: 12.5 }}><b style={{ fontWeight: 500 }}>{plain ? "Price chart" : "Technical"}:</b> {countsText(ev.technical)}</span>
      <span data-testid="idea-ev-fundamental" style={{ fontSize: 12.5 }}><b style={{ fontWeight: 500 }}>{plain ? "Company" : "Fundamental"}:</b> {countsText(ev.fundamental)}</span>
      <span data-testid="idea-ev-oi" style={{ fontSize: 12.5, overflowWrap: "anywhere" }}>
        <b style={{ fontWeight: 500 }}>{plain ? "Open interest" : "OI"}:</b>{" "}
        {oi && !empty ? (
          <>
            build-up {plainVal(oi.buildup)} · cash confirmation {plainVal(oi.cash_confirmation)} · PCR {num2(oi.pcr)} · call wall {num2(oi.call_wall)} · put wall {num2(oi.put_wall)} · max pain {num2(oi.max_pain)}
            {oi.expected_move != null ? ` · expected move ±${num2(oi.expected_move)}${oi.chain_expiry ? ` to ${fmtDay(oi.chain_expiry)}` : ""}` : ""}
            {oi.atm_iv != null ? ` · ATM IV ${num2(oi.atm_iv)}%` : ""}
            {oi.source_as_of ? ` · as of ${fmtDay(oi.source_as_of)}` : ""}
            {oi.unavailable.length > 0 ? ` · missing: ${oi.unavailable.join("; ")}` : ""}
            {ev.derivatives ? ` · derivatives evidence: ${countsText(ev.derivatives)}` : ""}
          </>
        ) : (
          <>{DASH} {missing}{oi && oi.unavailable.length > 0 ? ` (${oi.unavailable.join("; ")})` : ""}</>
        )}
      </span>
    </div>
  );
}

// ── strategies by segment ────────────────────────────────────────────────

const flagText = (f: unknown) => (typeof f === "string" ? f : JSON.stringify(f));

function Strategies({ idea, plain, onOpen }: { idea: Idea; plain: boolean; onOpen: (cand: string) => void }) {
  // A stock outside F&O comes with one "no strategy" entry per F&O segment (code not_fno_eligible): one sentence, not three empty rows.
  const noFno = idea.strategies.filter((r) => r.reasons.some((x) => x.code === "not_fno_eligible"));
  const rows = idea.strategies.filter((r) => !noFno.includes(r));
  const noFnoReason = noFno[0]?.reasons.find((x) => x.code === "not_fno_eligible")?.message ?? null;
  const known = SEGMENT_ORDER.filter((s) => rows.some((r) => r.segment === s));
  const rest = Array.from(new Set(rows.map((r) => r.segment))).filter((s) => !(SEGMENT_ORDER as readonly string[]).includes(s));
  const segments = [...known, ...rest];
  const heads = plain
    ? ["Strategy", "Status", "What it is", "Most you could lose", "Money tied up", "Reward per ₹1 risked", "Most you could make", "Break-even", "Size", "Flags", ""]
    : ["Strategy", "Status", "Legs", "Max loss", "Capital at risk", "Reward : risk", "Max profit", "Breakeven", "Sizing", "Flags", ""];
  return (
    <div data-testid="idea-strategies" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      {(idea.fno_eligible === false || noFno.length > 0) && (
        <p data-testid="idea-not-fno" role="note" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>
          No futures and options for this stock: {noFnoReason ?? "it is not in the NSE futures and options list, so only cash is shown."}
        </p>
      )}
      {rows.length === 0 ? (
        <p data-testid="idea-no-strategies" className="m-0" style={noteStyle}>No strategy was built for this idea. See the reasons above.</p>
      ) : (
        <div tabIndex={0} role="region" aria-label={`${idea.symbol} strategies (scrolls sideways inside this box)`} className="cp-scroll" style={{ overflowX: "auto", maxWidth: "100%" }}>
          <table data-testid="idea-strategy-table" style={{ borderCollapse: "collapse", width: "100%", minWidth: 1180 }}>
            <caption className="cp-mono-note" style={{ textAlign: "left", paddingBottom: 6 }}>
              Strategies for {idea.symbol}. Max loss and capital at risk are in rupees for the sized position, shown beside reward : risk: read the ratio with them, because a hedged or income structure is not comparable with an unhedged one. A loss on futures can exceed the margin.
            </caption>
            <thead>
              <tr className="cp-mono-note">{heads.map((h, i) => <th key={h || `x${i}`} scope="col" style={th}>{h || <span className="sr-only">Action</span>}</th>)}</tr>
            </thead>
            {segments.map((seg) => (
              <tbody key={seg} data-testid={`idea-seg-${seg}`}>
                <tr>
                  <th colSpan={heads.length} scope="rowgroup" className="cp-eyebrow" style={{ ...th, fontSize: 10, background: "var(--bg-2)" }}>{SEGMENT_TITLE[seg] ?? humaniseTag(seg)}</th>
                </tr>
                {rows.filter((r) => r.segment === seg).map((r) => <StrategyRow key={r.id} s={r} preferred={idea.preferred === r.id} onOpen={onOpen} />)}
              </tbody>
            ))}
          </table>
        </div>
      )}
    </div>
  );
}

function StrategyRow({ s, preferred, onOpen }: { s: IdeaStrategy; preferred: boolean; onOpen: (cand: string) => void }) {
  const viable = s.status === "candidate";
  const w = STRATEGY_STATUS[s.status] ?? { label: humaniseTag(s.status), tone: "ink" as Tone, glyph: "?" };
  const flags = [...s.liquidity_flags, ...s.flags].map(flagText);
  const sz = s.sizing;
  const sizing = !viable ? DASH
    : sz?.lots != null ? `${fmtNum(sz.lots)} lot${sz.lots === 1 ? "" : "s"}${sz.quantity != null ? ` (${fmtNum(sz.quantity)} units)` : ""}`
    : sz?.quantity != null ? `${fmtNum(sz.quantity)} ${sz.unit === "shares" || sz.unit == null ? "shares" : "units"}`
    : DASH;
  const basis = s.max_loss_basis;
  const openable = s.status === "candidate" || s.status === "wait";
  return (
    <tr data-testid={`idea-strat-${s.id}`} data-status={s.status} data-preferred={preferred}>
      <th scope="row" style={{ ...td, textAlign: "left", fontWeight: 400, minWidth: 190 }}>
        <span className="flex flex-col" style={{ gap: 3 }}>
          <span style={{ fontSize: 13, fontWeight: 500 }}>{s.label}</span>
          {s.family === CHARTINK_FAMILY && <span data-testid="idea-strat-ck-note" className="cp-mono-note">{CHARTINK_CANDIDATE_NOTE}</span>}
          {preferred && <span data-testid="idea-preferred" className="cp-mono-note" style={{ color: "var(--mint)" }}>★ Preferred strategy</span>}
          {s.why && <span style={noteStyle}>{s.why}</span>}
          {!viable && s.reasons.length > 0 && (
            <ul data-testid="idea-strat-reasons" className="m-0" style={{ paddingLeft: 16, fontSize: 12, color: "var(--cp-ink-2)" }}>{s.reasons.map((r) => <li key={r.code + r.message}>{r.message}</li>)}</ul>
          )}
        </span>
      </th>
      <td style={td} data-testid="idea-strat-status"><Pill tone={w.tone}><span aria-hidden>{w.glyph} </span>{w.label}</Pill></td>
      <td style={{ ...td, minWidth: 190 }} data-testid="idea-strat-legs">{s.legs_text ?? DASH}</td>
      <td className="cp-num" style={{ ...td, minWidth: 150 }} data-testid="idea-strat-maxloss">{viable && s.max_loss != null ? <>{rupeesAbs(s.max_loss)}{basis && <><br /><span style={{ ...noteStyle, fontFamily: "var(--sans)" }}>{basis}</span></>}</> : DASH}</td>
      <td className="cp-num" style={td} data-testid="idea-strat-capital">{viable ? rupees(s.capital_at_risk) : DASH}</td>
      <td className="cp-num" style={td} data-testid="idea-strat-rr">{viable ? <>{ratio(s.reward_risk_net)} net<br /><span style={noteStyle}>{ratio(s.reward_risk_gross)} gross</span></> : DASH}</td>
      <td className="cp-num" style={td} data-testid="idea-strat-maxprofit">{viable ? (s.profit_unbounded ? "Unlimited" : rupees(s.max_profit)) : DASH}</td>
      <td className="cp-num" style={td} data-testid="idea-strat-breakeven">{viable && s.breakeven.length ? s.breakeven.map((b) => fmtNum(b, 2)).join(", ") : DASH}</td>
      <td style={td} data-testid="idea-strat-sizing">{sizing}{viable && sz?.binding ? <><br /><span style={noteStyle}>limited by {humaniseTag(sz.binding).toLowerCase()}</span></> : null}{viable && sz?.status && sz.status !== "complete" ? <><br /><span style={noteStyle}>{humaniseTag(sz.status)}{sz.missing.length ? `: ${sz.missing.join(", ")}` : ""}</span></> : null}</td>
      <td style={{ ...td, minWidth: 150 }} data-testid="idea-strat-flags">{viable ? (flags.length ? flags.join("; ") : "None flagged") : DASH}</td>
      <td style={td}>
        {openable && <button type="button" data-testid="idea-open-strategy" aria-label={`Open this strategy: ${s.label}`} onClick={() => onOpen(s.id)} style={{ ...linkBtn, whiteSpace: "nowrap" }}>Open this strategy ›</button>}
      </td>
    </tr>
  );
}
