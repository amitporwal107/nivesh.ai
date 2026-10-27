/**
 * Smart trading desk — the account's risk profile: the limits the universal risk service enforces on every paper entry
 * (backend/routes/risk_controls.py, services/risk_profile.py, services/risk_book.py).
 *
 *   GET /api/risk/profile   the profile (eight limits, version and limits_version, capital basis, effective date, who set
 *                           it and why), the live equity basis (paper equity, peak, drawdown, day and week P&L, open risk
 *                           and the rupee budgets) or the reason it could not be read, the change log, whether this
 *                           session may loosen a limit (`can_loosen`), the catalogue of definitions and ranges, and the
 *                           risk estimate's note                                                       (useRiskProfile)
 *   PUT /api/risk/profile   { changes: { limit: value }, reason } or { profile: name, reason }: anyone may TIGHTEN a
 *                           limit; LOOSENING needs an admin (403 admin_required); 422 invalid_input, 409 no_change /
 *                           concurrent_change; 200 answers with the same body as the GET           (useSetRiskProfile)
 *
 * Reads trust nothing: a missing or non-numeric figure is null and the screen says "unknown", never 0; a body without
 * `profile.limits` throws a contract error. Paper equity starts at a SIMULATION DEFAULT (Rs 10,00,000), labelled so by
 * the route. Nothing here places an order.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { num } from "./desk-data";
import { controlProblem, detailOf } from "./risk-controls";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);
const strings = (v: unknown): string[] => (Array.isArray(v) ? v.flatMap((x) => (str(x) ? [str(x) as string] : [])) : []);

const isForbidden = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1;

const KEY = ["copilot", "desk", "risk", "profile"] as const;

/** The eight limits in the route's order (services/risk_profile.py FIELDS); used when the catalogue sends no order. */
export const LIMIT_FIELDS = [
  "per_trade_risk_pct", "max_open_risk_pct", "max_position_pct", "max_sector_pct",
  "daily_loss_pct", "weekly_loss_pct", "max_drawdown_pct", "min_reward_risk",
] as const;

/** The one limit where a HIGHER value is tighter; every other limit is tighter when lower. */
export const HIGHER_IS_TIGHTER = new Set(["min_reward_risk"]);

/** Which limit each of the live view's rupee budgets belongs to (routes/risk_controls.py _profile_view). */
export const BUDGET_OF: Record<string, string> = {
  per_trade_risk_pct: "per_trade",
  max_open_risk_pct: "open_risk",
  max_position_pct: "position",
  max_sector_pct: "sector",
};

export interface LimitDefinition {
  label: string;
  basis: string | null;
  reset: string | null;
  breach: string | null;
}

export interface RiskProfile {
  /** owner-default-2026-10-27, engineering-comparison, or custom. */
  name: string | null;
  /** Field -> value; null when the body did not carry a number for it. */
  limits: Record<string, number | null>;
  version: number | null;
  limitsVersion: string | null;
  capitalBasis: string | null;
  capitalBasisText: string | null;
  startingCapitalRs: number | null;
  startingCapitalLabel: string | null;
  effectiveFrom: string | null;
  setBy: string | null;
  setAt: string | null;
  reason: string | null;
  /** False: the account has no stored profile and runs on the owner defaults. */
  stored: boolean;
}

export interface PeriodPnl {
  start: string | null;
  pnlRs: number | null;
  startEquityRs: number | null;
  unknownReasons: string[];
}

export interface RiskLive {
  equityRs: number | null;
  cashRs: number | null;
  netUnrealisedRs: number | null;
  unknownReasons: string[];
  marksAsOf: string | null;
  fnoMarksAsOf: string | null;
  peakRs: number | null;
  drawdownPct: number | null;
  day: PeriodPnl;
  week: PeriodPnl;
  open: {
    positions: number | null;
    legacyPositions: number | null;
    /** Total open risk: reserved at entry plus the estimate on positions opened before the profile (risk_book.read). */
    riskRs: number | null;
    /** The part reserved at entry by the risk service's decisions; null when the route did not send it. */
    reservedRiskRs: number | null;
    legacyRiskRs: number | null;
    exposureRs: number | null;
    sectors: Array<{ sector: string; rs: number }>;
  };
  /** per_trade, open_risk, position, sector -> rupees; null when equity is unknown. */
  budgetsRs: Record<string, number | null>;
}

export interface ProfileFieldChange {
  field: string;
  before: number | null;
  after: number | null;
  loosened: boolean;
}

export interface ProfileChange {
  at: string | null;
  actor: string | null;
  actorIsAdmin: boolean;
  action: string | null;
  fields: ProfileFieldChange[];
  reason: string | null;
  versionAfter: number | null;
  effectiveFrom: string | null;
}

export interface RiskProfileView {
  profile: RiskProfile;
  /** Null when the route could not read the account (liveError says why) or sent no live block. */
  live: RiskLive | null;
  liveError: string | null;
  changes: ProfileChange[];
  canLoosen: boolean;
  fields: string[];
  definitions: Record<string, LimitDefinition>;
  namedProfiles: Record<string, string | null>;
  ranges: Record<string, [number, number]>;
  estimate: { gapStressPct: number | null; gapStressText: string | null; version: string | null; costModel: string | null } | null;
  riskPolicyVersion: string | null;
  fnoAdditional: { flag: string | null; enabled: boolean | null } | null;
}

function readPeriod(v: unknown): PeriodPnl {
  const p = rec(v);
  return { start: str(p.start), pnlRs: num(p.pnl_rs), startEquityRs: num(p.start_equity_rs), unknownReasons: strings(p.unknown_reasons) };
}

function readLive(v: unknown): { live: RiskLive | null; error: string | null } {
  const l = rec(v);
  if (!Object.keys(l).length) return { live: null, error: "the route sent no live figures" };
  const error = str(l.error);
  if (error) return { live: null, error };
  const eq = rec(l.equity);
  const peak = rec(l.peak);
  const open = rec(l.open);
  const budgets = rec(l.budgets_rs);
  const sectors = Object.entries(rec(open.sector_rs)).flatMap(([sector, rs]) => {
    const n = num(rs);
    return n != null ? [{ sector, rs: n }] : [];
  }).sort((a, b) => b.rs - a.rs);
  return {
    error: null,
    live: {
      equityRs: num(eq.equity_rs), cashRs: num(eq.cash_rs), netUnrealisedRs: num(eq.net_unrealised_rs),
      unknownReasons: strings(eq.unknown_reasons), marksAsOf: str(eq.marks_as_of), fnoMarksAsOf: str(eq.fno_marks_as_of),
      peakRs: num(peak.peak_rs), drawdownPct: num(l.drawdown_pct),
      day: readPeriod(l.day), week: readPeriod(l.week),
      open: {
        positions: num(open.positions), legacyPositions: num(open.legacy_positions),
        riskRs: num(open.risk_rs), reservedRiskRs: num(open.reserved_risk_rs), legacyRiskRs: num(open.legacy_risk_rs),
        exposureRs: num(open.exposure_rs), sectors,
      },
      budgetsRs: Object.fromEntries(Object.values(BUDGET_OF).map((k) => [k, num(budgets[k])])),
    },
  };
}

export function readRiskProfile(body: unknown): RiskProfileView {
  const d = rec(body);
  const p = rec(d.profile);
  if (!p.limits || typeof p.limits !== "object" || Array.isArray(p.limits)) throw ApiError.contractDrift("risk.profile: no profile.limits");
  const limitsRaw = rec(p.limits);
  const cat = rec(d.catalogue);
  const catFields = strings(cat.fields);
  const fields = catFields.length ? catFields : [...LIMIT_FIELDS];
  const definitions: Record<string, LimitDefinition> = {};
  for (const [field, v] of Object.entries(rec(cat.definitions))) {
    const def = rec(v);
    definitions[field] = { label: str(def.label) ?? field, basis: str(def.basis), reset: str(def.reset), breach: str(def.breach) };
  }
  const ranges: Record<string, [number, number]> = {};
  for (const [field, v] of Object.entries(rec(cat.ranges))) {
    if (!Array.isArray(v)) continue;
    const lo = num(v[0]);
    const hi = num(v[1]);
    if (lo != null && hi != null && lo <= hi) ranges[field] = [lo, hi];
  }
  const namedProfiles: Record<string, string | null> = {};
  for (const [name, v] of Object.entries(rec(cat.named_profiles))) namedProfiles[name] = str(rec(v).text);

  const { live, error } = readLive(d.live);
  const changes = (Array.isArray(d.changes) ? d.changes : []).map((v): ProfileChange => {
    const c = rec(v);
    const loosened = new Set(strings(c.loosened));
    return {
      at: str(c.at), actor: str(c.actor), actorIsAdmin: c.actor_is_admin === true, action: str(c.action),
      fields: Object.entries(rec(c.changes)).map(([field, ch]) => {
        const x = rec(ch);
        return { field, before: num(x.before), after: num(x.after), loosened: loosened.has(field) };
      }),
      reason: str(c.reason), versionAfter: num(c.version_after), effectiveFrom: str(c.effective_from),
    };
  });
  const est = rec(d.estimate);
  const fno = rec(d.fno_additional_checks);
  return {
    profile: {
      name: str(p.profile),
      limits: Object.fromEntries(fields.map((f) => [f, num(limitsRaw[f])])),
      version: num(p.version), limitsVersion: str(p.limits_version),
      capitalBasis: str(p.capital_basis), capitalBasisText: str(p.capital_basis_text),
      startingCapitalRs: num(p.starting_capital_rs), startingCapitalLabel: str(p.starting_capital_label),
      effectiveFrom: str(p.effective_from), setBy: str(p.set_by), setAt: str(p.set_at), reason: str(p.reason),
      stored: p.stored === true,
    },
    live,
    liveError: error,
    changes,
    canLoosen: d.can_loosen === true,
    fields,
    definitions,
    namedProfiles,
    ranges,
    estimate: Object.keys(est).length
      ? { gapStressPct: num(est.gap_stress_pct), gapStressText: str(est.gap_stress_text), version: str(est.version), costModel: str(est.cost_model) }
      : null,
    riskPolicyVersion: str(d.risk_policy_version),
    fnoAdditional: Object.keys(fno).length ? { flag: str(fno.flag), enabled: bool(fno.enabled) } : null,
  };
}

export function useRiskProfile() {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<RiskProfileView>({
    queryKey: [...KEY, profile ?? "self"],
    staleTime: 30_000,
    retry,
    queryFn: async ({ signal }) => readRiskProfile((await http({ path: "/api/risk/profile", signal, noRetry: true })).data),
  });
}

/** PUT /api/risk/profile — the body exactly as the route takes it. A reason is required. */
export type RiskProfileChange =
  | { changes: Record<string, number>; reason: string }
  | { profile: string; reason: string };

export function useSetRiskProfile() {
  const qc = useQueryClient();
  const profile = useImpersonationStore((st) => st.profileId);
  return useMutation({
    mutationFn: async (body: RiskProfileChange): Promise<RiskProfileView> =>
      readRiskProfile((await http({ method: "PUT", path: "/api/risk/profile", body, noRetry: true })).data),
    // The PUT answers with the same body as the GET: show it as is. The gate's decisions re-read on their own.
    onSuccess: (view) => qc.setQueryData([...KEY, profile ?? "self"], view),
  });
}

/** Whether `after` loosens the limit (a higher % or a lower minimum reward:risk); null when either side is unknown. */
export function isLooser(field: string, before: number | null, after: number | null): boolean | null {
  if (before == null || after == null) return null;
  return HIGHER_IS_TIGHTER.has(field) ? after < before : after > before;
}

/** The admin-only rule, in the words the screen uses for it and for a 403 admin_required. */
export const LOOSEN_ADMIN_ONLY = "Only an admin can loosen a limit; you can tighten any limit.";

/** A failed profile change in words: the admin-only rule, else the server's own message with its code. */
export function profileProblem(e: unknown): string {
  const d = detailOf(e);
  const code = str(d.code);
  if (code === "admin_required") return `${LOOSEN_ADMIN_ONLY} (admin_required)`;
  if (code === "invalid_input" || code === "no_change" || code === "concurrent_change") {
    return `${str(d.message) ?? "The change was not accepted."} (${code})`;
  }
  return controlProblem(e);
}
