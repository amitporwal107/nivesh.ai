/**
 * Scanner-to-Paper Trading (SPT) — the reads and writes of Trade Desk › Paper Trading › Opportunities · Analytics · Settings
 * (owner, 5 Nov 2026: "plain, functional screens on real data inside today's Trader workspace"; docs/scanner_paper_trading/DESIGN.md).
 * Every shape below is read from the backend code, never guessed:
 *
 *   GET  /api/v1/opportunities?state=&horizon=&direction=&symbol=&limit=   market-wide opportunities (routes/spt_signals.py),
 *                                                     oldest first signal first; the full documents (signals, validation, plan)
 *   GET  /api/v1/opportunities/{id}                   one opportunity
 *   POST /api/v1/opportunities/{id}/validate          revalidate now (CREATED / CONDITIONAL / WATCHLIST / DATA_INSUFFICIENT)
 *   GET  /api/v1/proposals?limit=                     the caller's proposals, newest first (routes/spt_risk.py; whole documents,
 *                                                     services/spt/proposals.public)
 *   POST /api/v1/opportunities/{id}/approve           → {proposal, idempotent, order{_id,state,order_type,quantity,…}}; refusals
 *                                                     409/404/422 {detail:{code, message, reason_codes?, decision?}}
 *   POST /api/v1/opportunities/{id}/reject {reason}   → {proposal, idempotent}; 422 reason_required
 *   GET  /api/v1/analytics/scanners?from=&to=&kind=   signal outcomes per scanner / category / score band
 *                                                     (services/spt/outcomes/analytics.py)
 *   GET  /api/v1/paper/trades?limit=                  the caller's CLOSED SPT positions (routes/spt_paper.py _trade)
 *   GET  /api/v1/paper/accounts                       {accounts:[{account_id, account, config, modes, note}]} (one per user)
 *   GET  /api/v1/paper/accounts/{id}                  the same + config_versions
 *   PUT  /api/v1/paper/accounts/{id}/config           {mode?, extras?: partial nested (a null leaf resets it), reason?,
 *                                                     expected_version?}; 403 admin_required {loosened}, 409 concurrent_change,
 *                                                     422 {code, message, field}
 *   GET/PUT /api/admin/spt/{user_id}/config           admin: any user's config ({reason} required on PUT)
 *   GET/PUT /api/admin/spt/settings                   admin: the market-wide SPT settings {values:{…}, reason, expected_version}
 *
 * The config parser takes the owner's 5 Nov shape (extras = EFFECTIVE values, overrides, defaults + defaults_source per leaf,
 * profile limits, warnings) and the earlier one (extras + defaults_source per group, no overrides/defaults).
 * Reads trust nothing: a missing or non-numeric figure is null (shown "—"), never 0. Nothing here reaches a broker.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { num } from "../../desk-data";

type Raw = Record<string, unknown>;
export const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const strs = (v: unknown): string[] => arr(v).map((x) => (typeof x === "string" ? x : x == null ? "" : String(x))).filter(Boolean);
const isObj = (v: unknown): v is Raw => !!v && typeof v === "object" && !Array.isArray(v);

const isForbidden = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && (e.kind === "contract_drift" || e.status === 404)) && count < 1;

// ── modes ────────────────────────────────────────────────────────────────

export type SptMode = "off" | "tracking" | "approval" | "auto";
export const MODES: readonly SptMode[] = ["off", "tracking", "approval", "auto"];
export const MODE_WORDS: Record<SptMode, { label: string; line: string }> = {
  off: { label: "Off", line: "Nothing is proposed for your paper account. Opportunities are still listed." },
  tracking: { label: "Tracking", line: "Proposals are sized and risk-checked, then only tracked: no paper order is placed." },
  approval: { label: "Approval", line: "A risk-approved proposal waits for you: Approve places the paper order, Reject records why." },
  auto: { label: "Auto", line: "Every risk-approved proposal becomes a paper order at once, without asking you." },
};
export const asMode = (v: unknown): SptMode | null => (typeof v === "string" && (MODES as readonly string[]).includes(v) ? (v as SptMode) : null);

// ── config (services/spt/policy.py public()) ─────────────────────────────

export type Unit = "pct" | "factor" | "count" | "rs" | "min" | "ratio";
export interface LeafDef { path: string; label: string; unit: Unit; group: string; step: number }

/** Every SPT config leaf (policy.RANGES), grouped for the form. */
export const LEAVES: readonly LeafDef[] = [
  { path: "risk_pct.positional", label: "Risk per trade · positional", unit: "pct", group: "Risk per trade", step: 0.01 },
  { path: "risk_pct.intraday", label: "Risk per trade · intraday", unit: "pct", group: "Risk per trade", step: 0.01 },
  { path: "risk_pct.fno", label: "Risk per trade · F&O", unit: "pct", group: "Risk per trade", step: 0.01 },
  { path: "drawdown_ladder.reduce_at_pct", label: "Reduce size from a drawdown of", unit: "pct", group: "Drawdown ladder", step: 0.01 },
  { path: "drawdown_ladder.restrict_at_pct", label: "Block new entries from a drawdown of", unit: "pct", group: "Drawdown ladder", step: 0.01 },
  { path: "drawdown_ladder.halt_at_pct", label: "Halt from a drawdown of", unit: "pct", group: "Drawdown ladder", step: 0.01 },
  { path: "drawdown_ladder.reduce_factor", label: "Size multiplier in the reduce band", unit: "factor", group: "Drawdown ladder", step: 0.05 },
  { path: "max_positions", label: "Open positions at most", unit: "count", group: "Positions", step: 1 },
  { path: "max_new_per_day", label: "New entries a day at most", unit: "count", group: "Positions", step: 1 },
  { path: "min_rr.positional", label: "Minimum reward:risk to target 2 · positional", unit: "ratio", group: "Reward and stress", step: 0.1 },
  { path: "stressed_gap_pct", label: "Stress gap through the stop loss", unit: "pct", group: "Reward and stress", step: 0.1 },
  { path: "allocation_buckets_pct.equity_positional", label: "Bucket · equity positional", unit: "pct", group: "Capital buckets (add up to 100)", step: 1 },
  { path: "allocation_buckets_pct.equity_intraday", label: "Bucket · equity intraday", unit: "pct", group: "Capital buckets (add up to 100)", step: 1 },
  { path: "allocation_buckets_pct.fno", label: "Bucket · F&O", unit: "pct", group: "Capital buckets (add up to 100)", step: 1 },
  { path: "allocation_buckets_pct.reserve", label: "Bucket · reserve", unit: "pct", group: "Capital buckets (add up to 100)", step: 1 },
  { path: "min_adv_rs", label: "Minimum average daily traded value", unit: "rs", group: "Liquidity and entry", step: 100000 },
  { path: "max_adv_participation_pct", label: "Most of a day's traded value one order may take", unit: "pct", group: "Liquidity and entry", step: 0.1 },
  { path: "max_chase_pct", label: "Most an immediate entry may be above the plan entry", unit: "pct", group: "Liquidity and entry", step: 0.1 },
  { path: "approval_expiry_minutes", label: "Approval window", unit: "min", group: "Liquidity and entry", step: 1 },
];

/** A nested object's numeric leaves as dotted paths ({a:{b:1}} → {"a.b": 1}); a non-numeric leaf is null. */
export function flatten(v: unknown, prefix = ""): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  for (const [k, x] of Object.entries(rec(v))) {
    const p = `${prefix}${k}`;
    if (isObj(x)) Object.assign(out, flatten(x, `${p}.`));
    else out[p] = num(x);
  }
  return out;
}

/** {"a.b": 1, "a.c": null} → {a: {b: 1, c: null}} (the PUT body's partial nested extras). */
export function nest(flat: Record<string, number | null>): Raw {
  const out: Raw = {};
  for (const [path, v] of Object.entries(flat)) {
    const parts = path.split(".");
    let cur = out;
    for (const p of parts.slice(0, -1)) cur = (cur[p] = isObj(cur[p]) ? cur[p] : {}) as Raw;
    cur[parts[parts.length - 1]] = v;
  }
  return out;
}

export interface SptConfig {
  mode: SptMode | null;
  version: number | null;
  /** The EFFECTIVE values, by dotted path. */
  extras: Record<string, number | null>;
  /** Only what was explicitly set; null when the API is the earlier shape (no overrides). */
  overrides: Record<string, number | null> | null;
  /** The profile-derived / SPT defaults; null in the earlier shape. */
  defaults: Record<string, number | null> | null;
  /** The source of each default, by dotted path (the earlier shape names groups: looked up by the leaf's group). */
  sources: Record<string, string | null>;
  profile: { name: string | null; limitsVersion: string | null; limits: Record<string, number | null>; stored: boolean | null } | null;
  warnings: string[];
  updatedAt: string | null;
  updatedBy: string | null;
  reason: string | null;
  stored: boolean | null;
  policyVersion: string | null;
  /** v2 = the owner's 5 Nov shape (overrides + defaults); v1 = the earlier one. */
  shape: "v2" | "v1";
}

export function readConfig(v: unknown): SptConfig | null {
  const c = rec(v);
  if (!Object.keys(c).length) return null;
  const v2 = isObj(c.overrides) && isObj(c.defaults);
  const extras = flatten(c.extras);
  const src = rec(c.defaults_source);
  const sources: Record<string, string | null> = {};
  for (const l of LEAVES) sources[l.path] = str(src[l.path]) ?? str(src[l.path.split(".")[0]]);
  const p = c.profile == null ? null : rec(c.profile);
  return {
    mode: asMode(c.mode), version: num(c.version), extras,
    overrides: v2 ? flatten(c.overrides) : null, defaults: v2 ? flatten(c.defaults) : null, sources,
    profile: p ? { name: str(p.profile), limitsVersion: str(p.limits_version) ?? (num(p.limits_version) != null ? String(p.limits_version) : null), limits: flatten(p.limits), stored: typeof p.stored === "boolean" ? p.stored : null } : null,
    warnings: strs(c.warnings), updatedAt: str(c.updated_at), updatedBy: str(c.updated_by), reason: str(c.reason),
    stored: typeof c.stored === "boolean" ? c.stored : null, policyVersion: str(c.policy_version), shape: v2 ? "v2" : "v1",
  };
}

export interface ConfigVersion { id: string; version: number | null; at: string | null; actor: string | null; actorIsAdmin: boolean | null; changed: string[]; loosened: string[]; reason: string | null; status: string | null }

export function readVersions(v: unknown): ConfigVersion[] {
  return arr(v).map((x, i) => {
    const r = rec(x);
    return { id: str(r.version_id) ?? str(r._id) ?? `v-${i}`, version: num(r.version), at: str(r.at), actor: str(r.actor),
      actorIsAdmin: typeof r.actor_is_admin === "boolean" ? r.actor_is_admin : null, changed: strs(r.changed), loosened: strs(r.loosened),
      reason: str(r.reason), status: str(r.status) };
  });
}

export interface SptAccount { accountId: string; config: SptConfig | null; note: string | null; versions: ConfigVersion[] | null }

function readAccount(v: unknown): SptAccount | null {
  const a = rec(v);
  const id = str(a.account_id);
  if (!id) return null;
  return { accountId: id, config: readConfig(a.config), note: str(a.note), versions: Array.isArray(a.config_versions) ? readVersions(a.config_versions) : null };
}

const useProfile = () => useImpersonationStore((st) => st.profileId) ?? "self";
export const SPT_KEY = ["copilot", "desk", "spt"] as const;

/** GET /api/v1/paper/accounts — the caller's one paper account and its SPT config (DESIGN D3). */
export function useSptAccount() {
  const profile = useProfile();
  return useQuery<SptAccount>({
    queryKey: [...SPT_KEY, "account", profile],
    staleTime: 15_000,
    retry,
    queryFn: async ({ signal }) => {
      const b = rec((await http({ path: "/api/v1/paper/accounts", signal, noRetry: true, timeoutMs: 20_000 })).data);
      if (!Array.isArray(b.accounts)) throw ApiError.contractDrift("spt.accounts: no accounts list");
      const acc = readAccount(b.accounts[0]);
      if (!acc) throw ApiError.contractDrift("spt.accounts: no account_id");
      return acc;
    },
  });
}

/** GET /api/v1/paper/accounts/{id} — the config with its recent version history. */
export function useSptAccountDetail(accountId: string | null) {
  const profile = useProfile();
  return useQuery<SptAccount>({
    queryKey: [...SPT_KEY, "account-detail", accountId ?? "", profile],
    enabled: !!accountId,
    staleTime: 15_000,
    retry,
    queryFn: async ({ signal }) => {
      const acc = readAccount((await http({ path: `/api/v1/paper/accounts/${encodeURIComponent(accountId as string)}`, signal, noRetry: true, timeoutMs: 20_000 })).data);
      if (!acc) throw ApiError.contractDrift("spt.account: no account_id");
      return acc;
    },
  });
}

// ── opportunities (routes/spt_signals.py; DESIGN.md §4) ──────────────────

export interface SptSignal { signalId: string; scannerId: string | null; scannerName: string | null; detectedAt: string | null; detectedPrice: number | null; score: number | null; category: string | null; family: string | null }
export interface ScorePart { name: string; points: number | null; max: number | null; note: string | null }
export interface SptValidation {
  at: string | null; decision: string | null; reasonCodes: string[]; explanations: string[]; score: number | null; parts: ScorePart[];
  market: Raw | null; stock: Raw | null; liquidity: Raw | null; derivatives: Raw | null; dataAsOf: Raw | null; revalidateAt: string | null; version: string | null;
}
export interface SptPlan { rules: string | null; entry: number | null; stopLoss: number | null; target1: number | null; target2: number | null; atr: number | null; sma20: number | null; planOk: boolean | null; note: string | null }
export interface SptOpportunity {
  id: string; symbol: string; direction: string | null; horizon: string | null; category: string | null; family: string | null; state: string | null;
  day: string | null; firstSeenAt: string | null; windowUntil: string | null; expiresAt: string | null; signals: SptSignal[]; conflicts: number;
  plan: SptPlan | null; validation: SptValidation | null;
}

function readSignal(v: unknown): SptSignal {
  const s = rec(v);
  return { signalId: str(s.signal_id) ?? "", scannerId: str(s.scanner_id), scannerName: str(s.scanner_name) ?? str(s.scanner_id), detectedAt: str(s.detected_at),
    detectedPrice: num(s.detected_price), score: num(s.scanner_score), category: str(s.category), family: str(s.family) };
}

function readValidation(v: unknown): SptValidation | null {
  if (!isObj(v)) return null;
  const parts: ScorePart[] = isObj(v.score_parts)
    ? Object.entries(v.score_parts).map(([name, x]) => ({ name, points: num(rec(x).points), max: num(rec(x).max), note: str(rec(x).note) }))
    : arr(v.score_parts).map((x) => ({ name: str(rec(x).name) ?? "—", points: num(rec(x).points), max: num(rec(x).max), note: str(rec(x).note) }));
  const o = (x: unknown) => (isObj(x) ? x : null);
  return { at: str(v.at), decision: str(v.decision), reasonCodes: strs(v.reason_codes), explanations: strs(v.explanations), score: num(v.opportunity_score), parts,
    market: o(v.market), stock: o(v.stock), liquidity: o(v.liquidity), derivatives: o(v.derivatives), dataAsOf: o(v.data_as_of), revalidateAt: str(v.revalidate_at), version: str(v.version) };
}

export function readOpportunity(v: unknown): SptOpportunity | null {
  const o = rec(v);
  const id = str(o._id) ?? str(o.opportunity_id);
  if (!id) return null;
  const plan = rec(rec(o.strong).plan);
  return {
    id, symbol: str(o.symbol) ?? "—", direction: str(o.direction), horizon: str(o.horizon), category: str(o.category), family: str(o.family), state: str(o.state),
    day: str(o.day), firstSeenAt: str(o.first_seen_at), windowUntil: str(o.window_until), expiresAt: str(o.expires_at),
    signals: arr(o.signals).map(readSignal), conflicts: arr(o.conflicts).length,
    plan: Object.keys(plan).length ? { rules: str(plan.rules), entry: num(plan.entry), stopLoss: num(plan.stop_loss), target1: num(plan.target_1), target2: num(plan.target_2),
      atr: num(plan.atr), sma20: num(plan.sma20), planOk: typeof plan.plan_ok === "boolean" ? plan.plan_ok : null, note: str(plan.plan_note) } : null,
    validation: readValidation(o.validation),
  };
}

export interface OppFilters { state: string; horizon: string; direction: string }
export const OPP_LIMIT = 500;

/** GET /api/v1/opportunities with the filters the route takes; every 30 s. */
export function useOpportunities(f: OppFilters) {
  const profile = useProfile();
  return useQuery<{ items: SptOpportunity[]; scoreLabel: string | null; limit: number | null }>({
    queryKey: [...SPT_KEY, "opportunities", f.state, f.horizon, f.direction, profile],
    staleTime: 10_000,
    retry,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    queryFn: async ({ signal }) => {
      const query = { state: f.state || undefined, horizon: f.horizon || undefined, direction: f.direction || undefined, limit: OPP_LIMIT };
      const b = rec((await http({ path: "/api/v1/opportunities", query, signal, noRetry: true, timeoutMs: 30_000 })).data);
      if (!Array.isArray(b.opportunities)) throw ApiError.contractDrift("spt.opportunities: no opportunities list");
      return { items: b.opportunities.map(readOpportunity).filter((x): x is SptOpportunity => !!x), scoreLabel: str(b.score_label), limit: num(b.limit) };
    },
  });
}

/** GET /api/v1/opportunities/{id} — the drawer's fresh copy. */
export function useOpportunity(id: string | null) {
  const profile = useProfile();
  return useQuery<SptOpportunity>({
    queryKey: [...SPT_KEY, "opportunity", id ?? "", profile],
    enabled: !!id,
    staleTime: 10_000,
    retry,
    queryFn: async ({ signal }) => {
      const o = readOpportunity(rec((await http({ path: `/api/v1/opportunities/${encodeURIComponent(id as string)}`, signal, noRetry: true, timeoutMs: 20_000 })).data).opportunity);
      if (!o) throw ApiError.contractDrift("spt.opportunity: no opportunity");
      return o;
    },
  });
}

// ── proposals (services/spt/proposals.py, pipeline.py, risk.py) ──────────

export interface SptRisk {
  decision: string | null; stage: string | null; reasonCodes: string[]; explanations: string[]; requestedQty: number | null; approvedQty: number | null;
  plannedRiskRs: number | null; stressedRiskRs: number | null; portfolioRiskBeforeRs: number | null; portfolioRiskAfterRs: number | null;
  exposureBeforeRs: number | null; exposureAfterRs: number | null; conditional: string | null; at: string | null;
}
export interface SptOrderSummary { orderId: string | null; state: string | null; orderType: string | null; quantity: number | null; limitPrice: number | null; rejectReason: string | null; expiresAt: string | null }
export interface SptProposal {
  id: string; opportunityId: string; symbol: string; direction: string | null; horizon: string | null; state: string | null;
  entry: { type: string | null; price: number | null; basis: string | null; limitPrice: number | null; timeInForce: string | null; expiresAt: string | null; rule: string | null; planEntry: number | null } | null;
  stopLoss: number | null; target1: number | null; target2: number | null; rr: { t1: number | null; t2: number | null; minRr: number | null; basis: string | null } | null;
  sizing: { quantity: number | null; capitalRequired: number | null; plannedRisk: number | null; stressedRisk: number | null; blocked: Array<{ code: string; message: string | null }>; riskPct: number | null } | null;
  allocation: { decision: string | null; quantity: number | null; requestedQty: number | null } | null;
  risk: SptRisk | null;
  approval: { requestedAt: string | null; expiresAt: string | null; decidedAt: string | null; decision: string | null; reason: string | null } | null;
  order: SptOrderSummary | null; orderRejected: boolean;
  reasonCodes: string[]; explanations: string[];
  exitPlan: Raw | null; price: { price: number | null; basis: string | null; receivedAt: string | null; ageS: number | null } | null;
  createdAt: string | null; history: Array<{ from: string | null; to: string | null; at: string | null; reason: string | null }>;
}

function readRisk(v: unknown): SptRisk | null {
  if (!isObj(v)) return null;
  return { decision: str(v.decision), stage: str(v.stage), reasonCodes: strs(v.reason_codes), explanations: strs(v.explanations), requestedQty: num(v.requested_qty),
    approvedQty: num(v.approved_qty), plannedRiskRs: num(v.planned_risk_rs), stressedRiskRs: num(v.stressed_risk_rs), portfolioRiskBeforeRs: num(v.portfolio_risk_before_rs),
    portfolioRiskAfterRs: num(v.portfolio_risk_after_rs), exposureBeforeRs: num(v.exposure_before_rs), exposureAfterRs: num(v.exposure_after_rs),
    conditional: str(rec(v.conditional).text), at: str(v.at) };
}

function readOrder(v: unknown): SptOrderSummary | null {
  if (!isObj(v)) return null;
  return { orderId: str(v.order_id) ?? str(v._id), state: str(v.state), orderType: str(v.order_type), quantity: num(v.quantity), limitPrice: num(v.limit_price),
    rejectReason: str(v.reject_reason), expiresAt: str(v.expires_at) };
}

export function readProposal(v: unknown): SptProposal | null {
  const p = rec(v);
  const id = str(p.proposal_id) ?? str(p._id);
  const oid = str(p.opportunity_id);
  if (!id || !oid) return null;
  const e = isObj(p.entry) ? p.entry : null;
  const rr = isObj(p.rr) ? p.rr : null;
  const sz = isObj(p.sizing) ? p.sizing : null;
  const al = isObj(p.allocation) ? p.allocation : null;
  const ap = isObj(p.approval) ? p.approval : null;
  const pr = isObj(p.price) ? p.price : null;
  return {
    id, opportunityId: oid, symbol: str(p.symbol) ?? "—", direction: str(p.direction), horizon: str(p.horizon), state: str(p.state),
    entry: e ? { type: str(e.type), price: num(e.price), basis: str(e.basis), limitPrice: num(e.limit_price), timeInForce: str(e.time_in_force), expiresAt: str(e.expires_at), rule: str(e.rule), planEntry: num(e.plan_entry) } : null,
    stopLoss: num(p.stop_loss), target1: num(p.target_1), target2: num(p.target_2),
    rr: rr ? { t1: num(rr.t1), t2: num(rr.t2), minRr: num(rr.min_rr), basis: str(rr.basis) } : null,
    sizing: sz ? { quantity: num(sz.quantity), capitalRequired: num(sz.capital_required), plannedRisk: num(sz.planned_risk), stressedRisk: num(sz.stressed_risk),
      blocked: arr(sz.blocked).map((b) => ({ code: str(rec(b).code) ?? "—", message: str(rec(b).message) })), riskPct: num(rec(sz.risk_pct).pct) } : null,
    allocation: al ? { decision: str(al.decision), quantity: num(al.quantity), requestedQty: num(al.requested_qty) } : null,
    risk: readRisk(p.risk),
    approval: ap ? { requestedAt: str(ap.requested_at), expiresAt: str(ap.expires_at), decidedAt: str(ap.decided_at), decision: str(ap.decision), reason: str(ap.reason) } : null,
    order: readOrder(p.order), orderRejected: p.order_rejected === true,
    reasonCodes: strs(p.reason_codes), explanations: strs(p.explanations),
    exitPlan: isObj(p.exit_plan) ? p.exit_plan : null,
    price: pr ? { price: num(pr.price), basis: str(pr.basis), receivedAt: str(pr.received_at), ageS: num(pr.age_s) } : null,
    createdAt: str(p.created_at),
    history: arr(p.state_history).map((h) => ({ from: str(rec(h).from), to: str(rec(h).to), at: str(rec(h).at), reason: str(rec(h).reason) })),
  };
}

/** The quantity the paper account would trade: the risk engine's approved quantity once it has decided, else the sizing's. */
export function qtyOf(p: SptProposal): { qty: number | null; basis: "approved" | "sized" | null } {
  if (p.risk?.approvedQty != null && p.risk.approvedQty > 0) return { qty: p.risk.approvedQty, basis: "approved" };
  if (p.sizing?.quantity != null) return { qty: p.sizing.quantity, basis: "sized" };
  return { qty: null, basis: null };
}
/** Capital for that quantity: the sizing's figure when the quantity is the sized one, else quantity × entry. */
export function capitalOf(p: SptProposal): number | null {
  const q = qtyOf(p);
  if (q.basis === "sized") return p.sizing?.capitalRequired ?? null;
  if (q.basis === "approved" && q.qty != null && p.entry?.price != null) return Math.round(q.qty * p.entry.price * 100) / 100;
  return null;
}
export const plannedRiskOf = (p: SptProposal): number | null => p.risk?.plannedRiskRs ?? p.sizing?.plannedRisk ?? null;

export const PROPOSAL_LIMIT = 200;

/** GET /api/v1/proposals — the caller's proposals, newest first; every 30 s. */
export function useProposals() {
  const profile = useProfile();
  return useQuery<SptProposal[]>({
    queryKey: [...SPT_KEY, "proposals", profile],
    staleTime: 10_000,
    retry,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    queryFn: async ({ signal }) => {
      const b = rec((await http({ path: "/api/v1/proposals", query: { limit: PROPOSAL_LIMIT }, signal, noRetry: true, timeoutMs: 30_000 })).data);
      if (!Array.isArray(b.items)) throw ApiError.contractDrift("spt.proposals: no items list");
      return b.items.map(readProposal).filter((x): x is SptProposal => !!x);
    },
  });
}

/** A refusal in words: {code, message, field, loosened, reasonCodes} from detail (an object or a plain code string). */
export interface SptProblem { status: number | null; code: string | null; message: string; field: string | null; loosened: string[]; reasonCodes: string[] }
export function sptProblem(e: unknown): SptProblem {
  if (e instanceof ApiError) {
    const d = rec(e.body).detail;
    const o = rec(d);
    const code = typeof d === "string" ? d : str(o.code);
    const message = str(o.message) ?? (typeof d === "string" ? d : null) ?? (e.kind === "network" ? "The network request failed." : e.kind === "timeout" ? "The request took too long." : e.detail ?? e.message ?? `HTTP ${e.status ?? "error"}`);
    return { status: e.status ?? null, code, message, field: str(o.field), loosened: strs(o.loosened), reasonCodes: strs(o.reason_codes) };
  }
  if (e instanceof Error && e.name === "ZodError") {
    // A body that failed the shape check: name the fields, never show the validator's raw dump to the user.
    const issues = (e as Error & { issues?: Array<{ path?: unknown[] }> }).issues ?? [];
    const fields = [...new Set(issues.map((i) => (i.path ?? []).join(".")).filter(Boolean))].slice(0, 3);
    return { status: null, code: "unexpected_shape", message: `unexpected response shape${fields.length ? ` (${fields.join(", ")})` : ""}`, field: null, loosened: [], reasonCodes: [] };
  }
  return { status: null, code: null, message: e instanceof Error && e.message ? e.message : "The request failed.", field: null, loosened: [], reasonCodes: [] };
}

function useInvalidateSpt() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: SPT_KEY });
}

/** POST /api/v1/paper/positions/{id}/exit {} — a manual exit of a scanner paper position (the P&L dashboard's Simulate exit
 *  on a scanner row). The paper monitor fills it at the live bid in the session. 200 {order, duplicate}. */
export function useSptExit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (positionId: string): Promise<{ order: SptOrderSummary | null; duplicate: boolean }> => {
      const b = rec((await http({ method: "POST", path: `/api/v1/paper/positions/${encodeURIComponent(positionId)}/exit`, body: {}, noRetry: true, timeoutMs: 20_000 })).data);
      return { order: readOrder(b.order), duplicate: b.duplicate === true };
    },
    // The P&L dashboard's own body is a stream (3 s in the session), so only the SPT reads are refreshed here.
    onSettled: () => qc.invalidateQueries({ queryKey: SPT_KEY }),
  });
}

export interface ApproveResult { proposal: SptProposal | null; order: SptOrderSummary | null; idempotent: boolean }

/** POST /api/v1/opportunities/{id}/approve. */
export function useApprove() {
  const invalidate = useInvalidateSpt();
  return useMutation({
    mutationFn: async (opportunityId: string): Promise<ApproveResult> => {
      const b = rec((await http({ method: "POST", path: `/api/v1/opportunities/${encodeURIComponent(opportunityId)}/approve`, body: {}, noRetry: true, timeoutMs: 30_000 })).data);
      return { proposal: readProposal(b.proposal), order: readOrder(b.order), idempotent: b.idempotent === true };
    },
    onSettled: invalidate,
  });
}

/** POST /api/v1/opportunities/{id}/reject {reason}. */
export function useReject() {
  const invalidate = useInvalidateSpt();
  return useMutation({
    mutationFn: async ({ opportunityId, reason }: { opportunityId: string; reason: string }) => {
      const b = rec((await http({ method: "POST", path: `/api/v1/opportunities/${encodeURIComponent(opportunityId)}/reject`, body: { reason }, noRetry: true, timeoutMs: 20_000 })).data);
      return { proposal: readProposal(b.proposal), idempotent: b.idempotent === true };
    },
    onSettled: invalidate,
  });
}

/** POST /api/v1/opportunities/{id}/validate — revalidate now. */
export function useRevalidate() {
  const invalidate = useInvalidateSpt();
  return useMutation({
    mutationFn: async (opportunityId: string) => {
      const b = rec((await http({ method: "POST", path: `/api/v1/opportunities/${encodeURIComponent(opportunityId)}/validate`, body: {}, noRetry: true, timeoutMs: 60_000 })).data);
      return { state: str(b.state), validation: readValidation(b.validation) };
    },
    onSettled: invalidate,
  });
}

// ── config writes ────────────────────────────────────────────────────────

export interface ConfigBody { mode?: SptMode; extras?: Raw; reason?: string; expected_version?: number }

/** PUT /api/v1/paper/accounts/{id}/config. */
export function usePutConfig() {
  const invalidate = useInvalidateSpt();
  return useMutation({
    mutationFn: async ({ accountId, body }: { accountId: string; body: ConfigBody }) => {
      const b = rec((await http({ method: "PUT", path: `/api/v1/paper/accounts/${encodeURIComponent(accountId)}/config`, body, noRetry: true, timeoutMs: 20_000 })).data);
      return readConfig(b.config);
    },
    onSuccess: invalidate,
  });
}

/** GET /api/admin/spt/{user_id}/config. */
export function useAdminConfig(userId: string | null) {
  return useQuery<{ accountId: string; config: SptConfig | null; versions: ConfigVersion[] }>({
    queryKey: [...SPT_KEY, "admin-config", userId ?? ""],
    enabled: !!userId,
    retry: false,
    queryFn: async ({ signal }) => {
      const b = rec((await http({ path: `/api/admin/spt/${encodeURIComponent(userId as string)}/config`, signal, noRetry: true, timeoutMs: 20_000 })).data);
      if (!isObj(b.config)) throw ApiError.contractDrift("spt.admin.config: no config");
      return { accountId: str(b.account_id) ?? (userId as string), config: readConfig(b.config), versions: readVersions(b.versions) };
    },
  });
}

/** PUT /api/admin/spt/{user_id}/config {mode?, extras?, reason, expected_version?}. */
export function usePutAdminConfig() {
  const invalidate = useInvalidateSpt();
  return useMutation({
    mutationFn: async ({ userId, body }: { userId: string; body: ConfigBody }) => {
      const b = rec((await http({ method: "PUT", path: `/api/admin/spt/${encodeURIComponent(userId)}/config`, body, noRetry: true, timeoutMs: 20_000 })).data);
      return readConfig(b.config);
    },
    onSuccess: invalidate,
  });
}

export interface MarketSettings {
  values: Record<string, number | null>; sources: Record<string, string | null>; stored: Record<string, number | null>; version: number | null;
  fields: Record<string, { env: string | null; default: number | null; range: [number | null, number | null]; usedBy: string | null }>;
  updatedAt: string | null; updatedBy: string | null; reason: string | null; versions: ConfigVersion[];
}

/** GET /api/admin/spt/settings — the market-wide SPT settings (services/spt/settings.py public()). */
export function useAdminSettings(enabled: boolean) {
  return useQuery<MarketSettings>({
    queryKey: [...SPT_KEY, "admin-settings"],
    enabled,
    retry: false,
    queryFn: async ({ signal }) => {
      const b = rec((await http({ path: "/api/admin/spt/settings", signal, noRetry: true, timeoutMs: 20_000 })).data);
      if (!isObj(b.values)) throw ApiError.contractDrift("spt.admin.settings: no values");
      const sources: Record<string, string | null> = {};
      for (const [k, x] of Object.entries(rec(b.sources))) sources[k] = str(x);
      const fields: MarketSettings["fields"] = {};
      for (const [k, x] of Object.entries(rec(b.fields))) {
        const f = rec(x);
        const r = arr(f.range);
        fields[k] = { env: str(f.env), default: num(f.default), range: [num(r[0]), num(r[1])], usedBy: str(f.used_by) };
      }
      return { values: flatten(b.values), sources, stored: flatten(b.stored), version: num(b.version), fields, updatedAt: str(b.updated_at), updatedBy: str(b.updated_by),
        reason: str(b.reason), versions: readVersions(b.versions) };
    },
  });
}

/** PUT /api/admin/spt/settings {values: {field: value | null}, reason, expected_version?}. */
export function usePutAdminSettings() {
  const invalidate = useInvalidateSpt();
  return useMutation({
    mutationFn: async (body: { values: Record<string, number | null>; reason: string; expected_version?: number }) =>
      (await http({ method: "PUT", path: "/api/admin/spt/settings", body, noRetry: true, timeoutMs: 20_000 })).data,
    onSuccess: invalidate,
  });
}

// ── analytics ────────────────────────────────────────────────────────────

export const HORIZONS = ["t1", "t5", "t10", "t20"] as const;
export type HorizonKey = (typeof HORIZONS)[number];
export interface HorizonStat { n: number | null; hitRatePct: number | null; ci: [number, number] | null; avgReturnPct: number | null; medianReturnPct: number | null; avgMfePct: number | null; avgMaePct: number | null; smallSample: boolean | null }
export interface OutcomeRow { key: string; signals: number | null; horizons: Partial<Record<HorizonKey, HorizonStat>>; smallSample: boolean | null; note: string | null;
  plan: { decided: number | null; target1RatePct: number | null; stopRatePct: number | null; avgR: number | null; smallSample: boolean | null } | null;
  fade: { n: number | null; fadedRatePct: number | null } | null }
export interface ScannerAnalytics { from: string | null; to: string | null; kind: string | null; minSample: number | null; note: string | null; version: string | null;
  totals: OutcomeRow | null; byScanner: OutcomeRow[]; byCategory: OutcomeRow[]; byBand: OutcomeRow[] }

function readOutcomeRow(v: unknown, key?: string): OutcomeRow {
  const r = rec(v);
  const hz = rec(r.horizons);
  const horizons: OutcomeRow["horizons"] = {};
  for (const h of HORIZONS) {
    if (!isObj(hz[h])) continue;
    const x = hz[h] as Raw;
    const ci = arr(x.hit_rate_ci95_pct);
    const lo = num(ci[0]), hi = num(ci[1]);
    horizons[h] = { n: num(x.n), hitRatePct: num(x.hit_rate_pct), ci: lo != null && hi != null ? [lo, hi] : null, avgReturnPct: num(x.avg_return_pct),
      medianReturnPct: num(x.median_return_pct), avgMfePct: num(x.avg_mfe_pct), avgMaePct: num(x.avg_mae_pct), smallSample: typeof x.small_sample === "boolean" ? x.small_sample : null };
  }
  const plan = isObj(r.plan) ? r.plan : null;
  const fade = isObj(r.fade) ? r.fade : null;
  return { key: key ?? str(r.key) ?? (r.key != null ? String(r.key) : "—"), signals: num(r.signals), horizons, smallSample: typeof r.small_sample === "boolean" ? r.small_sample : null, note: str(r.note),
    plan: plan ? { decided: num(plan.decided), target1RatePct: num(plan.target_1_rate_pct), stopRatePct: num(plan.stop_rate_pct), avgR: num(plan.avg_r_multiple), smallSample: typeof plan.small_sample === "boolean" ? plan.small_sample : null } : null,
    fade: fade ? { n: num(fade.n), fadedRatePct: num(fade.faded_rate_pct) } : null };
}

/** GET /api/v1/analytics/scanners. */
export function useScannerAnalytics(q: { from: string; to: string; kind: string }) {
  const profile = useProfile();
  return useQuery<ScannerAnalytics>({
    queryKey: [...SPT_KEY, "analytics-scanners", q.from, q.to, q.kind, profile],
    staleTime: 60_000,
    retry,
    queryFn: async ({ signal }) => {
      const b = rec((await http({ path: "/api/v1/analytics/scanners", query: { from: q.from || undefined, to: q.to || undefined, kind: q.kind || undefined }, signal, noRetry: true, timeoutMs: 60_000 })).data);
      if (!Array.isArray(b.by_scanner)) throw ApiError.contractDrift("spt.analytics: no by_scanner list");
      return { from: str(b.from), to: str(b.to), kind: str(b.kind), minSample: num(b.min_sample), note: str(b.note), version: str(b.version),
        totals: isObj(b.totals) ? readOutcomeRow(b.totals, "All signals") : null, byScanner: b.by_scanner.map((x) => readOutcomeRow(x)),
        byCategory: arr(b.by_category).map((x) => readOutcomeRow(x)), byBand: arr(b.by_score_band).map((x) => readOutcomeRow(x)) };
    },
  });
}

export interface SptTrade {
  id: string; symbol: string; direction: string | null; quantity: number | null; avgEntry: number | null; avgExit: number | null; grossRs: number | null; netRs: number | null;
  costsRs: number | null; r: number | null; exitReason: string | null; openedAt: string | null; closedAt: string | null; proposalId: string | null; opportunityId: string | null; signalIds: string[];
}

export function readTrade(v: unknown): SptTrade | null {
  const t = rec(v);
  const id = str(t.trade_id) ?? str(t.position_id);
  if (!id) return null;
  return { id, symbol: str(t.symbol) ?? "—", direction: str(t.direction), quantity: num(t.quantity), avgEntry: num(t.avg_entry_price), avgExit: num(t.avg_exit_price),
    grossRs: num(t.realized_gross_rs), netRs: num(t.realized_net_rs), costsRs: num(t.costs_rs), r: num(t.r_multiple), exitReason: str(t.exit_reason),
    openedAt: str(t.opened_at), closedAt: str(t.closed_at), proposalId: str(t.proposal_id), opportunityId: str(t.opportunity_id), signalIds: strs(t.signal_ids) };
}

export const TRADES_LIMIT = 500;

/** GET /api/v1/paper/trades — the caller's closed SPT positions. */
export function useSptTrades() {
  const profile = useProfile();
  return useQuery<{ trades: SptTrade[]; count: number | null }>({
    queryKey: [...SPT_KEY, "trades", profile],
    staleTime: 30_000,
    retry,
    queryFn: async ({ signal }) => {
      const b = rec((await http({ path: "/api/v1/paper/trades", query: { limit: TRADES_LIMIT }, signal, noRetry: true, timeoutMs: 30_000 })).data);
      if (!Array.isArray(b.trades)) throw ApiError.contractDrift("spt.trades: no trades list");
      return { trades: b.trades.map(readTrade).filter((x): x is SptTrade => !!x), count: num(b.count) };
    },
  });
}

/** The scanner id inside a signal id (services/spt/signals/ingest.py: sig:<day>:<scanner_id>:<SYMBOL>); null when not that form. */
export function scannerOfSignalId(id: string): string | null {
  const parts = id.split(":");
  if (parts.length < 4 || parts[0] !== "sig") return null;
  return parts.slice(2, -1).join(":") || null;
}

export interface ResultStats {
  trades: number; wins: number; losses: number; flat: number; winRatePct: number | null; avgWinRs: number | null; avgLossRs: number | null;
  expectancyRs: number | null; expectancyR: number | null; withR: number; profitFactor: number | null; netRs: number | null; grossProfitRs: number; grossLossRs: number;
  avgHoldingDays: number | null; withHolding: number; withoutNet: number;
}

/** The paper results of `trades` — computed ONLY from the returned trades (PRD §13.2–13.4); a trade without a net P&L is left out. */
export function resultStats(trades: SptTrade[]): ResultStats {
  const priced = trades.filter((t) => t.netRs != null);
  const wins = priced.filter((t) => (t.netRs as number) > 0);
  const losses = priced.filter((t) => (t.netRs as number) < 0);
  const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
  const gp = sum(wins.map((t) => t.netRs as number));
  const gl = sum(losses.map((t) => t.netRs as number));
  const n = priced.length;
  const avgWin = wins.length ? gp / wins.length : null;
  const avgLoss = losses.length ? gl / losses.length : null;
  const wr = n ? wins.length / n : null;
  const lr = n ? losses.length / n : null;
  const rs = trades.map((t) => t.r).filter((x): x is number => x != null);
  const holds = trades.map((t) => {
    const a = t.openedAt ? Date.parse(t.openedAt) : NaN, b = t.closedAt ? Date.parse(t.closedAt) : NaN;
    return Number.isFinite(a) && Number.isFinite(b) && b >= a ? (b - a) / 86_400_000 : null;
  }).filter((x): x is number => x != null);
  return {
    trades: n, wins: wins.length, losses: losses.length, flat: n - wins.length - losses.length,
    winRatePct: wr == null ? null : wr * 100, avgWinRs: avgWin, avgLossRs: avgLoss,
    // Expectancy = WinRate × AverageWin − LossRate × |AverageLoss| (PRD §13.3), on net P&L (costs included).
    expectancyRs: n ? (wr as number) * (avgWin ?? 0) - (lr as number) * Math.abs(avgLoss ?? 0) : null,
    expectancyR: rs.length ? sum(rs) / rs.length : null, withR: rs.length,
    // Profit factor = gross profit ÷ |gross loss| (PRD §13.4); no loss → not defined.
    profitFactor: gl < 0 ? gp / Math.abs(gl) : null,
    netRs: n ? sum(priced.map((t) => t.netRs as number)) : null, grossProfitRs: gp, grossLossRs: gl,
    avgHoldingDays: holds.length ? sum(holds) / holds.length : null, withHolding: holds.length, withoutNet: trades.length - n,
  };
}
