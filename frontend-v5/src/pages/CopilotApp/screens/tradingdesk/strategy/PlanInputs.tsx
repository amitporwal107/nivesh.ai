/**
 * Strategy Builder — the inputs panel (PRD §16.2) and the defaults the plan applied.
 *
 * Underlying (any NSE symbol, as the header search takes), direction, horizon (intraday is shown disabled with
 * its reason), instrument, capital, a risk budget in rupees or a risk percentage (one of the two), the most to
 * put in one idea, the minimum reward : risk, whether to avoid event windows, whether multi-leg is allowed and an
 * optional expiry. A field left blank is a default the route applies and names; after a build those defaults
 * show as chips beside the plan, each editable here and applied on the next build. The browser checks the
 * route's own limits; the route's 422 problems are shown on the field they name. "Build the plan" is a
 * read-only call: nothing is written and nothing goes to a broker.
 */
import { useId, type CSSProperties, type ReactNode } from "react";
import { StockIcon } from "../../../components/EntityIcon";
import { Btn, Section } from "../../../components/ui";
import { INPUT_STYLE } from "../../trading/parts";
import type { DeskPersona } from "../context";
import { DIRECTIONS, HORIZONS, INSTRUMENTS, type FieldProblem, type StrategyPlan } from "./plan-contract";
import {
  DEFAULT_KEYS, DIRECTION_LABEL, HORIZON_LABEL, INSTRUMENT_LABEL, INTRADAY_REASON, SYMBOL_RE, type DefaultKey, type FormState,
} from "./plan-form";

const note: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };

export function Field({ label, htmlFor, problems, hint, children, testId }: { label: ReactNode; htmlFor?: string; problems: FieldProblem[]; hint?: ReactNode; children: ReactNode; testId: string }) {
  return (
    <div data-testid={`field-${testId}`} className="flex min-w-0 flex-col" style={{ gap: 5 }}>
      <label htmlFor={htmlFor} className="cp-eyebrow" style={{ fontSize: 10 }}>{label}</label>
      {children}
      {hint && <span style={note}>{hint}</span>}
      {problems.map((p) => (
        <span key={`${p.code}:${p.message}`} role="alert" data-testid={`problem-${testId}`} style={{ fontSize: 12, color: "var(--cp-danger)" }}>Problem: {p.message}</span>
      ))}
    </div>
  );
}

function Seg<T extends string>({ label, value, options, onChange, testId, disabled }: {
  label: string; value: T | null; options: Array<{ value: T; label: string }>; onChange: (v: T) => void; testId: string; disabled?: Partial<Record<T, string>>;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap" style={{ gap: 6 }}>
      {options.map((o) => {
        const on = o.value === value;
        const off = disabled?.[o.value];
        return (
          <button
            key={o.value} type="button" className="cp-chip" aria-pressed={on} disabled={!!off} title={off ? `Not available: ${off}` : undefined}
            data-testid={`${testId}-${o.value}`} onClick={() => onChange(o.value)}
            style={{ ...(on ? { borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" } : undefined), ...(off ? { opacity: 0.55, cursor: "not-allowed" } : undefined) }}
          >
            {o.label}{off ? ` (${off})` : ""}
          </button>
        );
      })}
    </div>
  );
}

export interface PlanInputsProps {
  form: FormState;
  onChange: (next: FormState) => void;
  onBuild: () => void;
  pending: boolean;
  /** Browser-side and server-side problems together, by field. */
  problems: FieldProblem[];
  persona: DeskPersona;
  /** The plan on screen, for the defaults it applied. */
  plan: StrategyPlan | null;
  rulesDefaults: Record<string, unknown>;
}

const FIELD_OF: Record<string, string> = {
  underlying: "underlying", direction: "direction", horizon: "horizon", instrument: "instrument", horizon_days: "horizon_days", capital: "capital",
  risk_budget_inr: "risk", risk_pct: "risk", max_allocation_pct: "max_allocation_pct", min_reward_risk: "min_reward_risk", avoid_events: "avoid_events",
  allow_multi_leg: "allow_multi_leg", expiry: "expiry",
};

export function PlanInputs({ form, onChange, onBuild, pending, problems, persona, plan, rulesDefaults }: PlanInputsProps) {
  const id = useId();
  const plain = persona === "investor";
  const set = (patch: Partial<FormState>) => onChange({ ...form, ...patch });
  const by = (field: string) => problems.filter((p) => FIELD_OF[p.field] === field);
  const known = new Set(Object.keys(FIELD_OF));
  const other = problems.filter((p) => !known.has(p.field));
  const symOk = SYMBOL_RE.test(form.sym.trim());
  const L = (a: { trader: string; plain: string }) => (plain ? a.plain : a.trader);

  const textInput = (key: keyof FormState, extra: { placeholder?: string; inputMode?: "decimal" | "numeric" | "text"; testId: string; fieldId: string }) => (
    <input
      id={`${id}-${extra.fieldId}`} data-testid={extra.testId} value={String(form[key] ?? "")} inputMode={extra.inputMode ?? "decimal"} placeholder={extra.placeholder}
      aria-invalid={by(extra.fieldId).length > 0 || undefined} onChange={(e) => set({ [key]: e.target.value } as Partial<FormState>)} style={INPUT_STYLE}
    />
  );

  return (
    <Section title={plain ? "What do you want to plan?" : "Inputs"} note={plain ? "Leave a box blank to use the default" : "Blank fields use the default, and the plan lists it"}>
      <form
        data-testid="plan-inputs" className="flex min-w-0 flex-col" style={{ gap: 16 }}
        onSubmit={(e) => { e.preventDefault(); onBuild(); }}
      >
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,240px),1fr))", gap: "14px 18px" }}>
          <Field testId="underlying" label={plain ? "Stock" : "Underlying (NSE symbol)"} htmlFor={`${id}-underlying`} problems={by("underlying")}>
            <span className="flex items-center" style={{ gap: 8 }}>
              {symOk && <StockIcon symbol={form.sym.trim().toUpperCase()} size={26} />}
              <input
                id={`${id}-underlying`} data-testid="in-symbol" value={form.sym} placeholder="e.g. RELIANCE" autoCapitalize="characters" autoComplete="off" spellCheck={false}
                aria-invalid={by("underlying").length > 0 || undefined} onChange={(e) => set({ sym: e.target.value.toUpperCase() })} style={INPUT_STYLE}
              />
            </span>
          </Field>
          <Field testId="expiry" label={plain ? "Option expiry (optional)" : "Expiry (optional)"} htmlFor={`${id}-expiry`} problems={by("expiry")} hint="YYYY-MM-DD. Blank lets the rules pick one.">
            {textInput("expiry", { placeholder: "2026-11-24", inputMode: "text", testId: "in-expiry", fieldId: "expiry" })}
          </Field>
        </div>

        <Field testId="direction" label={plain ? "What do you expect?" : "Direction"} problems={by("direction")}>
          <Seg
            label="Direction" value={form.direction || null} testId="in-direction" onChange={(v) => set({ direction: v })}
            options={DIRECTIONS.map((d) => ({ value: d, label: L(DIRECTION_LABEL[d]) }))}
          />
        </Field>

        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: "14px 18px" }}>
          <Field testId="horizon" label={plain ? "How long do you plan to hold?" : "Holding horizon"} problems={by("horizon")} hint={form.horizon ? undefined : "Default: positional"}>
            <Seg
              label="Horizon" value={form.horizon ?? "positional"} testId="in-horizon" onChange={(v) => set({ horizon: v })}
              options={HORIZONS.map((h) => ({ value: h, label: L(HORIZON_LABEL[h]) }))} disabled={{ intraday: INTRADAY_REASON }}
            />
          </Field>
          <Field testId="instrument" label={plain ? "Which kind of trade?" : "Instrument"} problems={by("instrument")} hint={form.instrument ? undefined : "Default: compare all"}>
            <Seg
              label="Instrument" value={form.instrument ?? "all"} testId="in-instrument" onChange={(v) => set({ instrument: v })}
              options={INSTRUMENTS.map((i) => ({ value: i, label: L(INSTRUMENT_LABEL[i]) }))}
            />
          </Field>
        </div>

        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,200px),1fr))", gap: "14px 18px" }}>
          <Field testId="capital" label={plain ? "Money you can use (₹)" : "Capital (₹)"} htmlFor={`${id}-capital`} problems={by("capital")} hint="Needed with a risk percentage and for the allocation cap.">
            {textInput("capital", { placeholder: "1000000", testId: "in-capital", fieldId: "capital" })}
          </Field>
          <Field
            testId="risk" htmlFor={`${id}-risk`} problems={by("risk")} hint="One of the two. Blank means sizing is incomplete, with no quantity."
            label={
              <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
                {plain ? "The most you accept losing" : "Risk"}
                <span role="group" aria-label="Risk as" className="flex" style={{ gap: 4 }}>
                  {(["inr", "pct"] as const).map((m) => (
                    <button
                      key={m} type="button" className="cp-chip" aria-pressed={form.riskMode === m} data-testid={`in-risk-mode-${m}`} onClick={() => set({ riskMode: m, risk: "" })}
                      style={{ padding: "2px 8px", fontSize: 11, ...(form.riskMode === m ? { borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" } : undefined) }}
                    >
                      {m === "inr" ? "₹ budget" : "% of capital"}
                    </button>
                  ))}
                </span>
              </span>
            }
          >
            {textInput("risk", { placeholder: form.riskMode === "inr" ? "10000" : "1", testId: "in-risk", fieldId: "risk" })}
          </Field>
          <Field testId="max_allocation_pct" label={plain ? "Biggest share of your money in one idea (%)" : "Maximum allocation (%)"} htmlFor={`${id}-max_allocation_pct`} problems={by("max_allocation_pct")} hint={`Default ${String(rulesDefaults.max_allocation_pct ?? "—")}`}>
            {textInput("maxAlloc", { placeholder: String(rulesDefaults.max_allocation_pct ?? ""), testId: "in-alloc", fieldId: "max_allocation_pct" })}
          </Field>
          <Field testId="min_reward_risk" label={plain ? "Reward you want for each ₹1 risked" : "Minimum reward : risk"} htmlFor={`${id}-min_reward_risk`} problems={by("min_reward_risk")} hint={`Default ${String(rulesDefaults.min_reward_risk ?? "—")}`}>
            {textInput("minRr", { placeholder: String(rulesDefaults.min_reward_risk ?? ""), testId: "in-minrr", fieldId: "min_reward_risk" })}
          </Field>
          <Field testId="horizon_days" label={plain ? "Days to hold" : "Horizon (sessions)"} htmlFor={`${id}-horizon_days`} problems={by("horizon_days")} hint="Blank uses the horizon's default.">
            {textInput("horizonDays", { placeholder: "10", inputMode: "numeric", testId: "in-horizon-days", fieldId: "horizon_days" })}
          </Field>
        </div>

        <div className="flex flex-wrap" style={{ gap: "10px 24px" }}>
          <label className="flex items-center" style={{ gap: 8, fontSize: 13 }}>
            <input
              type="checkbox" data-testid="in-avoid-events" checked={form.avoidEvents ?? Boolean(rulesDefaults.avoid_events ?? true)} onChange={(e) => set({ avoidEvents: e.target.checked })}
            />
            {plain ? "Stay clear of results and other events" : "Avoid event windows"}
            {form.avoidEvents == null && <span style={note}>(default)</span>}
          </label>
          <label className="flex items-center" style={{ gap: 8, fontSize: 13 }}>
            <input
              type="checkbox" data-testid="in-multi-leg" checked={form.allowMultiLeg ?? Boolean(rulesDefaults.allow_multi_leg ?? true)} onChange={(e) => set({ allowMultiLeg: e.target.checked })}
            />
            {plain ? "Allow combined option trades (spreads)" : "Allow multi-leg"}
            {form.allowMultiLeg == null && <span style={note}>(default)</span>}
          </label>
        </div>

        {other.length > 0 && (
          <ul data-testid="problems-other" className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18 }}>
            {other.map((p) => <li key={`${p.field}:${p.code}`} role="alert" style={{ fontSize: 12, color: "var(--cp-danger)" }}>{p.field ? `${p.field}: ` : ""}{p.message}</li>)}
          </ul>
        )}

        <div className="flex flex-wrap items-center" style={{ gap: "8px 14px" }}>
          <Btn variant="primary" type="submit" data-testid="build-plan" disabled={pending} aria-busy={pending}>{pending ? "Building…" : plain ? "Build the plan" : "Build the plan"}</Btn>
          <span style={note}>Reads end-of-day data and writes nothing. Nothing is sent to a broker.</span>
        </div>
      </form>

      {plan && <DefaultChips plan={plan} form={form} onChange={onChange} plain={plain} />}
    </Section>
  );
}

// ── the defaults the plan applied ────────────────────────────────────────

const CHIP_LABEL: Record<DefaultKey, { trader: string; plain: string }> = {
  horizon: { trader: "Horizon", plain: "Hold for" },
  instrument: { trader: "Instrument", plain: "Kind of trade" },
  horizon_days: { trader: "Horizon (sessions)", plain: "Days to hold" },
  max_allocation_pct: { trader: "Max allocation %", plain: "Biggest share in one idea %" },
  min_reward_risk: { trader: "Min reward : risk", plain: "Reward wanted per ₹1 risked" },
  avoid_events: { trader: "Avoid events", plain: "Stay clear of events" },
  allow_multi_leg: { trader: "Multi-leg", plain: "Combined option trades" },
};

function DefaultChips({ plan, form, onChange, plain }: { plan: StrategyPlan; form: FormState; onChange: (f: FormState) => void; plain: boolean }) {
  const keys = DEFAULT_KEYS.filter((k) => plan.inputs.defaults_applied.includes(k));
  if (!keys.length) return null;
  const inputs = plan.inputs as unknown as Record<string, unknown>;
  const reason = (k: DefaultKey) => `Default from ${plan.rules_version} (rules.defaults.${k === "horizon" || k === "instrument" ? "—" : k}). Change it and build again.`;
  const num = (k: "horizon_days" | "max_allocation_pct" | "min_reward_risk", field: "horizonDays" | "maxAlloc" | "minRr") => (
    <input
      aria-label={CHIP_LABEL[k][plain ? "plain" : "trader"]} data-testid={`default-input-${k}`} inputMode="decimal" style={{ ...INPUT_STYLE, width: 74, padding: "3px 6px", fontSize: 12 }}
      value={form[field] || String(inputs[k] ?? "")} onChange={(e) => onChange({ ...form, [field]: e.target.value })}
    />
  );
  return (
    <div data-testid="defaults-applied" className="flex min-w-0 flex-col" style={{ gap: 8, paddingTop: 14, marginTop: 14, borderTop: "1px solid var(--cp-line)" }}>
      <span className="cp-eyebrow">Defaults applied · change and build again</span>
      <ul className="m-0 flex flex-wrap" style={{ padding: 0, listStyle: "none", gap: 8 }}>
        {keys.map((k) => (
          <li key={k} data-testid={`default-chip-${k}`} title={reason(k)} className="flex flex-wrap items-center" style={{ gap: 6, padding: "4px 10px", borderRadius: 999, border: "1px solid var(--line-2)", fontSize: 12 }}>
            <span style={{ color: "var(--cp-ink-3)" }}>{CHIP_LABEL[k][plain ? "plain" : "trader"]}</span>
            {k === "horizon" && <strong className="cp-num">{String(inputs.horizon)}</strong>}
            {k === "instrument" && <strong className="cp-num">{String(inputs.instrument)}</strong>}
            {k === "horizon_days" && num("horizon_days", "horizonDays")}
            {k === "max_allocation_pct" && num("max_allocation_pct", "maxAlloc")}
            {k === "min_reward_risk" && num("min_reward_risk", "minRr")}
            {k === "avoid_events" && (
              <input type="checkbox" aria-label={CHIP_LABEL[k].trader} data-testid="default-input-avoid_events" checked={form.avoidEvents ?? plan.inputs.avoid_events} onChange={(e) => onChange({ ...form, avoidEvents: e.target.checked })} />
            )}
            {k === "allow_multi_leg" && (
              <input type="checkbox" aria-label={CHIP_LABEL[k].trader} data-testid="default-input-allow_multi_leg" checked={form.allowMultiLeg ?? plan.inputs.allow_multi_leg} onChange={(e) => onChange({ ...form, allowMultiLeg: e.target.checked })} />
            )}
            <span style={{ color: "var(--cp-ink-3)", fontSize: 11 }}>default</span>
          </li>
        ))}
      </ul>
      <span data-testid="defaults-reason" style={note}>Each of these is the default of {plan.rules_version} (rules.defaults) because the input was left blank. Change one here, or in the form above, and build again.</span>
    </div>
  );
}
