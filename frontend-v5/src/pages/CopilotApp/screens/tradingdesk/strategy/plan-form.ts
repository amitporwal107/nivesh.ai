/**
 * Strategy Builder — the inputs form's state, its browser-side validation and the request it makes (PRD §16.2).
 * The limits are the plan route's own (backend/services/strategy_plan/plan.py normalise_inputs); the route
 * checks them again and its 422 problems are shown per field. Nothing here changes a number: a field left
 * blank is left out of the request, so the route applies (and discloses) its default.
 */
import { DIRECTIONS, HORIZONS, INSTRUMENTS, type Direction, type FieldProblem, type Horizon, type Instrument } from "./plan-contract";
import type { PlanRequest } from "./plan-data";

export const SYMBOL_RE = /^[A-Za-z0-9&-]{1,20}$/;
export type RiskMode = "inr" | "pct";

export interface FormState {
  sym: string;
  direction: Direction | "";
  /** null: not chosen, so the route's default applies (and is listed in the plan's defaults). */
  horizon: Horizon | null;
  instrument: Instrument | null;
  capital: string;
  riskMode: RiskMode;
  risk: string;
  maxAlloc: string;
  minRr: string;
  horizonDays: string;
  /** null: the route's default. */
  avoidEvents: boolean | null;
  allowMultiLeg: boolean | null;
  /** null: the route's default (combinations included under "all"). */
  includeCombinations: boolean | null;
  expiry: string;
}

export const EMPTY_FORM: FormState = {
  sym: "", direction: "", horizon: null, instrument: null, capital: "", riskMode: "inr", risk: "", maxAlloc: "", minRr: "", horizonDays: "",
  avoidEvents: null, allowMultiLeg: null, includeCombinations: null, expiry: "",
};

/** One number from a text field: a finite number, else null. "1,00,000" is read as 100000. */
export function readNumber(text: string): number | null {
  const t = text.trim().replace(/,/g, "");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

const problem = (field: string, code: string, message: string): FieldProblem => ({ field, code, message });

function numberField(out: FieldProblem[], key: string, text: string, hi: number, label: string): number | undefined {
  if (!text.trim()) return undefined;
  const n = readNumber(text);
  if (n == null || n <= 0 || n > hi) {
    out.push(problem(key, `bad_${key}`, `${label} must be a number above 0 and at most ${hi.toLocaleString("en-IN")}.`));
    return undefined;
  }
  return n;
}

/** The request for the form, or the problems that stop it. Same limits as the route. */
export function validateForm(f: FormState): { request: PlanRequest | null; problems: FieldProblem[] } {
  const out: FieldProblem[] = [];
  const sym = f.sym.trim().toUpperCase();
  if (!SYMBOL_RE.test(sym)) out.push(problem("underlying", "bad_underlying", "Enter an NSE symbol: letters, digits, & or -, at most 20."));
  if (!f.direction || !(DIRECTIONS as readonly string[]).includes(f.direction)) out.push(problem("direction", "bad_direction", "Choose a direction."));
  const capital = numberField(out, "capital", f.capital, 1e12, "Capital");
  const risk = f.riskMode === "inr"
    ? numberField(out, "risk_budget_inr", f.risk, 1e12, "The risk budget")
    : numberField(out, "risk_pct", f.risk, 100, "The risk percentage");
  const alloc = numberField(out, "max_allocation_pct", f.maxAlloc, 100, "The maximum allocation");
  const minRr = numberField(out, "min_reward_risk", f.minRr, 100, "The minimum reward : risk");
  let horizonDays: number | undefined;
  if (f.horizonDays.trim()) {
    const n = readNumber(f.horizonDays);
    if (n == null || n !== Math.floor(n) || n < 1 || n > 250) out.push(problem("horizon_days", "bad_horizon_days", "The horizon must be a whole number of sessions from 1 to 250."));
    else horizonDays = n;
  }
  let expiry: string | undefined;
  if (f.expiry.trim()) {
    const t = f.expiry.trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(t) || Number.isNaN(Date.parse(`${t}T00:00:00Z`))) out.push(problem("expiry", "bad_expiry", "The expiry must be a date, YYYY-MM-DD."));
    else expiry = t;
  }
  if (f.horizon === "intraday") out.push(problem("horizon", "intraday_unsupported", "Intraday needs intraday data; this system holds end-of-day data only."));
  if (out.length) return { request: null, problems: out };
  const request: PlanRequest = {
    underlying: sym,
    direction: f.direction,
    ...(f.horizon ? { horizon: f.horizon } : {}),
    ...(f.instrument ? { instrument: f.instrument } : {}),
    ...(horizonDays != null ? { horizon_days: horizonDays } : {}),
    ...(capital != null ? { capital } : {}),
    ...(risk != null ? (f.riskMode === "inr" ? { risk_budget_inr: risk } : { risk_pct: risk }) : {}),
    ...(alloc != null ? { max_allocation_pct: alloc } : {}),
    ...(minRr != null ? { min_reward_risk: minRr } : {}),
    ...(f.avoidEvents != null ? { avoid_events: f.avoidEvents } : {}),
    ...(f.allowMultiLeg != null ? { allow_multi_leg: f.allowMultiLeg } : {}),
    ...(f.includeCombinations != null ? { include_combinations: f.includeCombinations } : {}),
    ...(expiry ? { expiry } : {}),
  };
  return { request, problems: [] };
}

/** The form for a URL (?sym=&direction=&instrument=&horizon=): only what the URL names. */
export function formFromParams(p: URLSearchParams): FormState {
  const sym = (p.get("sym") ?? "").toUpperCase();
  const direction = p.get("direction");
  const instrument = p.get("instrument");
  const horizon = p.get("horizon");
  // The inputs an idea of the AI opportunities board carries (see ideas-data paramsFromPlanInputs): only what the URL names.
  const text = (k: string) => { const v = p.get(k); return v && readNumber(v) != null ? v : ""; };
  const flag = (k: string) => { const v = p.get(k); return v === "true" ? true : v === "false" ? false : null; };
  const expiry = p.get("expiry") ?? "";
  return {
    ...EMPTY_FORM,
    sym: SYMBOL_RE.test(sym) ? sym : "",
    direction: (DIRECTIONS as readonly string[]).includes(direction ?? "") ? (direction as Direction) : "",
    instrument: (INSTRUMENTS as readonly string[]).includes(instrument ?? "") ? (instrument as Instrument) : null,
    horizon: (HORIZONS as readonly string[]).includes(horizon ?? "") ? (horizon as Horizon) : null,
    capital: text("capital"),
    riskMode: p.get("risk_pct") && !p.get("risk_inr") ? "pct" : "inr",
    risk: text("risk_inr") || text("risk_pct"),
    maxAlloc: text("max_alloc"),
    minRr: text("min_rr"),
    horizonDays: text("horizon_days"),
    avoidEvents: flag("avoid_events"),
    allowMultiLeg: flag("multi_leg"),
    includeCombinations: flag("combos"),
    expiry: /^\d{4}-\d{2}-\d{2}$/.test(expiry) ? expiry : "",
  };
}

/** A form as the plan's inputs have it (to rebuild or to change a saved plan's inputs). */
export function formFromRequest(r: PlanRequest): FormState {
  return {
    ...EMPTY_FORM,
    sym: r.underlying, direction: r.direction as Direction, horizon: (r.horizon as Horizon) ?? null, instrument: (r.instrument as Instrument) ?? null,
    capital: r.capital != null ? String(r.capital) : "", riskMode: r.risk_pct != null ? "pct" : "inr",
    risk: r.risk_pct != null ? String(r.risk_pct) : r.risk_budget_inr != null ? String(r.risk_budget_inr) : "",
    maxAlloc: r.max_allocation_pct != null ? String(r.max_allocation_pct) : "", minRr: r.min_reward_risk != null ? String(r.min_reward_risk) : "",
    horizonDays: r.horizon_days != null ? String(r.horizon_days) : "", avoidEvents: r.avoid_events ?? null, allowMultiLeg: r.allow_multi_leg ?? null, includeCombinations: r.include_combinations ?? null,
    expiry: r.expiry ?? "",
  };
}

// ── wording ──────────────────────────────────────────────────────────────

export const DIRECTION_LABEL: Record<Direction, { trader: string; plain: string }> = {
  bullish: { trader: "Bullish", plain: "Expect it to rise" },
  bearish: { trader: "Bearish", plain: "Expect it to fall" },
  neutral: { trader: "Neutral", plain: "Expect little movement" },
  vol_expansion: { trader: "Volatility expansion", plain: "Expect bigger swings" },
  vol_contraction: { trader: "Volatility contraction", plain: "Expect calmer trading" },
};

export const HORIZON_LABEL: Record<Horizon, { trader: string; plain: string }> = {
  intraday: { trader: "Intraday", plain: "Within a day" },
  positional: { trader: "Positional", plain: "Days to weeks" },
  longer_term: { trader: "Longer-term", plain: "Months" },
};

export const INSTRUMENT_LABEL: Record<Instrument, { trader: string; plain: string }> = {
  all: { trader: "Compare all", plain: "Compare all" },
  cash: { trader: "Cash", plain: "Shares" },
  futures: { trader: "Futures", plain: "Futures" },
  options: { trader: "Options", plain: "Options" },
  combination: { trader: "Combination", plain: "Shares plus options" },
};

export const INTRADAY_REASON = "end-of-day data only";

/** The default chips: what each defaulted input is called, its value and why it is a default. */
export const DEFAULT_KEYS = ["horizon", "instrument", "horizon_days", "max_allocation_pct", "min_reward_risk", "avoid_events", "allow_multi_leg"] as const;
export type DefaultKey = (typeof DEFAULT_KEYS)[number];
