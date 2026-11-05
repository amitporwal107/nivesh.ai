/**
 * Paper Trading v2 (builder B) — the reads and writes of 03 Capital allocation, 04 Portfolio risk and 05 Real-time P&L
 * (docs/scanner_paper_trading/UI_DESIGN_V2.md §2.03–§2.05, §3, §7). New routes, parsed here against the §7 contract:
 *
 *   GET  /api/v1/paper/accounts/{id}/policy         the combined policy (§3): every field's value, default, range, store,
 *                                                    whether it is overridden and whether loosening it needs an admin; derived
 *   PUT  /api/v1/paper/accounts/{id}/policy         {expected_version, values: {key: number|null}, reason?} → 200 {policy};
 *                                                    403 {detail:{code:"admin_required", loosened}} · 409 version_conflict ·
 *                                                    422 {detail:{code, field, message}}
 *   GET / PUT /api/admin/spt/{user_id}/policy       the admin variant (PUT: reason required). The GET mirrors the admin config
 *                                                    route (/api/admin/spt/{user_id}/config); §7 names only the PUT.
 *   GET  /api/v1/risk/correlation/{id}?with=&days=  60-day return correlations of the open positions (+ a candidate)
 *   GET  /api/v1/paper/fno-structures               the desk's open paper F&O structures: margin, max loss, Greeks, fills, scenarios
 *   GET  /api/v1/risk/stress-test/{id}              (existing) — read here for its named scenarios list as well
 *
 * Reused, not re-written: risk/account, exposures and allocation recommendations (../../risk-desk/spt-risk-api.ts), the P&L
 * snapshot and exit watch (../pnl-data.ts), the F&O structure caps and the gate (../../../risk-controls.ts).
 *
 * Reads trust nothing: a missing or non-numeric figure is null and the screen shows "—" with the reason, never 0.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { num } from "../../../desk-data";
import { readSptStress, type SptStress } from "../../risk-desk/spt-risk-api";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);
const isObj = (v: unknown): v is Raw => !!v && typeof v === "object" && !Array.isArray(v);
/** Strings, or objects carrying a text / reason / message, as sentences. */
const sentences = (v: unknown): string[] => arr(v).flatMap((x) => {
  if (typeof x === "string") return x.trim() ? [x.trim()] : [];
  const o = rec(x);
  const t = str(o.text) ?? str(o.reason) ?? str(o.message) ?? str(o.note);
  return t ? [t] : [];
});

export const PV2_KEY = ["copilot", "desk", "paper-v2"] as const;
const isForbidden = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && (e.kind === "contract_drift" || e.status === 404)) && count < 1;
const REFRESH_MS = 30_000;

function useProfileKey() {
  return useImpersonationStore((st) => st.profileId) ?? "self";
}

// ── policy (§3, §7) ──────────────────────────────────────────────────────

export const ALLOCATION_KEYS = ["bucket_positional_pct", "bucket_intraday_pct", "bucket_fno_pct", "per_trade_risk_pct", "max_positions"] as const;
export const RISK_KEYS = ["max_open_risk_pct", "daily_loss_pct", "weekly_loss_pct", "restrict_at_pct", "halt_at_pct", "max_position_pct",
  "max_sector_pct", "margin_util_pct", "fno_max_loss_pct"] as const;
export const BUCKET_KEYS = ["bucket_positional_pct", "bucket_intraday_pct", "bucket_fno_pct"] as const;
export type PolicyKey = (typeof ALLOCATION_KEYS)[number] | (typeof RISK_KEYS)[number];
export const POLICY_KEYS: readonly PolicyKey[] = [...ALLOCATION_KEYS, ...RISK_KEYS];

/** The design's field labels (§2.03, §2.04), used in place of the route's own label so the copy is the owner's. */
export const FIELD_LABEL: Record<PolicyKey, string> = {
  bucket_positional_pct: "Equity positional %", bucket_intraday_pct: "Equity intraday %", bucket_fno_pct: "F&O strategies %",
  per_trade_risk_pct: "Risk per trade %", max_positions: "Max open positions",
  max_open_risk_pct: "Max total open risk %", daily_loss_pct: "Daily loss limit %", weekly_loss_pct: "Weekly loss limit %",
  restrict_at_pct: "Drawdown restricted at %", halt_at_pct: "Trading halt at %", max_position_pct: "Max single stock %",
  max_sector_pct: "Max sector exposure %", margin_util_pct: "Max margin utilization %", fno_max_loss_pct: "F&O max loss per strategy %",
};
export const labelOf = (k: string): string => (FIELD_LABEL as Record<string, string>)[k] ?? k.replace(/_/g, " ");

export interface PolicyField {
  key: string;
  value: number | null;
  default: number | null;
  min: number | null;
  max: number | null;
  step: number | null;
  unit: "%" | "" | "₹";
  store: string | null;
  overridden: boolean;
  loosenNeedsAdmin: boolean;
  label: string | null;
}

export interface PaperPolicy {
  accountId: string | null;
  version: number | null;
  savedAt: string | null;
  savedBy: string | null;
  fields: Record<string, PolicyField>;
  derived: { reservePct: number | null; riskBudgetLeftPct: number | null; riskBudgetLeftRs: number | null; perTradeRiskRs: number | null };
}

export function readPolicy(body: unknown): PaperPolicy {
  const b0 = rec(body);
  // PUT answers {policy}; GET answers the policy itself.
  const b = isObj(b0.policy) ? rec(b0.policy) : b0;
  if (!isObj(b.fields)) throw ApiError.contractDrift("paper.policy: no fields");
  const fields: Record<string, PolicyField> = {};
  for (const [k, v] of Object.entries(b.fields)) {
    const f = rec(v);
    const unit = str(f.unit);
    fields[k] = {
      key: k, value: num(f.value), default: num(f.default), min: num(f.min), max: num(f.max), step: num(f.step),
      unit: unit === "%" || unit === "₹" ? unit : "", store: str(f.store), overridden: f.overridden === true,
      loosenNeedsAdmin: f.loosen_needs_admin === true, label: str(f.label),
    };
  }
  const d = rec(b.derived);
  return {
    accountId: str(b.account_id), version: num(b.version), savedAt: str(b.saved_at), savedBy: str(b.saved_by), fields,
    derived: { reservePct: num(d.reserve_pct), riskBudgetLeftPct: num(d.risk_budget_left_pct), riskBudgetLeftRs: num(d.risk_budget_left_rs), perTradeRiskRs: num(d.per_trade_risk_rs) },
  };
}

/** Where a policy is read and written: the caller's own account, or (an admin) another user's. */
export type PolicyTarget = { kind: "self"; accountId: string } | { kind: "admin"; userId: string };
export const targetKey = (t: PolicyTarget | null): string => (!t ? "" : t.kind === "self" ? `self:${t.accountId}` : `admin:${t.userId}`);
const policyPath = (t: PolicyTarget) =>
  t.kind === "self" ? `/api/v1/paper/accounts/${encodeURIComponent(t.accountId)}/policy` : `/api/admin/spt/${encodeURIComponent(t.userId)}/policy`;

export function usePolicy(target: PolicyTarget | null) {
  const profile = useProfileKey();
  return useQuery<PaperPolicy>({
    queryKey: [...PV2_KEY, "policy", profile, targetKey(target)],
    enabled: !!target,
    staleTime: 30_000,
    retry: target?.kind === "admin" ? false : retry,
    queryFn: async ({ signal }) => readPolicy((await http({ path: policyPath(target as PolicyTarget), signal, noRetry: true, timeoutMs: 20_000 })).data),
  });
}

export interface PolicyBody { expected_version: number | null; values: Record<string, number | null>; reason?: string }

export function usePutPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ target, body }: { target: PolicyTarget; body: PolicyBody }): Promise<PaperPolicy> =>
      readPolicy((await http({ method: "PUT", path: policyPath(target), body, noRetry: true, timeoutMs: 20_000 })).data),
    // Every limit-dependent read (risk/account, exposures, ranking, the SPT config) changes with a saved policy.
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: PV2_KEY });
      void qc.invalidateQueries({ queryKey: ["copilot", "desk", "risk", "spt"] });
      void qc.invalidateQueries({ queryKey: ["copilot", "desk", "spt"] });
    },
  });
}

/** A refused save in words: the code, the field it names, the fields loosened, the server's message. */
export interface PolicyProblem { status: number | null; code: string | null; field: string | null; loosened: string[]; message: string }
export function policyProblem(e: unknown): PolicyProblem {
  if (e instanceof ApiError) {
    const d = rec(e.body).detail;
    const o = rec(d);
    const code = typeof d === "string" ? d : str(o.code);
    const message = str(o.message) ?? (typeof d === "string" ? d : null)
      ?? (e.kind === "network" ? "The network request failed. Nothing was saved." : e.kind === "timeout" ? "The request took too long. Reload before trying again." : e.detail ?? e.message ?? `HTTP ${e.status ?? "error"}`);
    return { status: e.status ?? null, code, field: str(o.field), loosened: arr(o.loosened).map(str).filter((x): x is string => !!x), message };
  }
  return { status: null, code: null, field: null, loosened: [], message: e instanceof Error && e.message ? e.message : "The request failed. Nothing was saved." };
}

// ── correlation (§7) ─────────────────────────────────────────────────────

export interface Correlation { symbols: string[]; matrix: Array<Array<number | null>>; days: number | null; threshold: number | null; basis: string | null; notes: string[] }

export function readCorrelation(body: unknown): Correlation {
  const b = rec(body);
  if (!Array.isArray(b.symbols) || !Array.isArray(b.matrix)) throw ApiError.contractDrift("risk.correlation: no symbols or matrix");
  const symbols = b.symbols.map((s) => str(s) ?? "—");
  const rows = b.matrix as unknown[];
  const matrix = symbols.map((_, i) => symbols.map((__, j) => num(arr(rows[i])[j])));
  return { symbols, matrix, days: num(b.days), threshold: num(b.threshold), basis: str(b.basis), notes: sentences(b.notes) };
}

export function useCorrelation(accountId: string | null, withSymbol: string | null = null) {
  const profile = useProfileKey();
  return useQuery<Correlation>({
    queryKey: [...PV2_KEY, "correlation", profile, accountId ?? "", withSymbol ?? ""],
    enabled: !!accountId,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    retry,
    queryFn: async ({ signal }) => {
      const query: Record<string, string> = { days: "60" };
      if (withSymbol) query.with = withSymbol;
      return readCorrelation((await http({ path: `/api/v1/risk/correlation/${encodeURIComponent(accountId as string)}`, query, signal, noRetry: true, timeoutMs: 30_000 })).data);
    },
  });
}

// ── F&O structures (§7) ──────────────────────────────────────────────────

export interface FnoNet { delta: number | null; gamma: number | null; thetaRsDay: number | null; vegaRsPt: number | null }
export interface FnoLeg { side: "BUY" | "SELL" | null; contract: string; entry: number | null; ltp: number | null; filledQty: number | null; qty: number | null; pnlRs: number | null; pending: boolean }
export interface FnoScenario { name: string; label: string; pnlRs: number | null }
export interface FnoStructure {
  id: string;
  name: string;
  underlying: string | null;
  underlyingLtp: number | null;
  expiry: string | null;
  daysToExpiry: number | null;
  lots: number | null;
  lotSize: number | null;
  status: "filled" | "partial" | null;
  hedged: boolean | null;
  maxLossRs: number | null;
  maxProfitRs: number | null;
  /** True when the route says the profit has no cap (then maxProfitRs is null by design, not unknown). */
  profitUnbounded: boolean;
  breakevens: number[];
  net: FnoNet;
  marginRs: number | null;
  pnlRs: number | null;
  legs: FnoLeg[];
  scenarios: FnoScenario[];
  /** The route's own sentences about the structure (its notes; why max loss or margin is null), joined; null when none. */
  note: string | null;
}
export interface FnoBook {
  structures: FnoStructure[];
  totals: { marginRs: number | null; maxLossRs: number | null; net: FnoNet };
  limits: { fnoMaxLossPct: number | null; marginUtilPct: number | null };
  basis: string | null;
  notes: string[];
}

const readNet = (v: unknown): FnoNet => {
  const n = rec(v);
  return { delta: num(n.delta), gamma: num(n.gamma), thetaRsDay: num(n.theta_rs_day), vegaRsPt: num(n.vega_rs_pt) };
};

export function readFnoBook(body: unknown): FnoBook {
  const b = rec(body);
  if (!Array.isArray(b.structures)) throw ApiError.contractDrift("paper.fno-structures: no structures list");
  const t = rec(b.totals);
  const l = rec(b.limits);
  const structures = b.structures.flatMap((x): FnoStructure[] => {
    const s = rec(x);
    const id = str(s.id);
    if (!id) return [];
    const status = str(s.status);
    return [{
      id, name: str(s.name) ?? "Structure", underlying: str(s.underlying), underlyingLtp: num(s.underlying_ltp), expiry: str(s.expiry),
      daysToExpiry: num(s.days_to_expiry), lots: num(s.lots), lotSize: num(s.lot_size),
      status: status === "filled" || status === "partial" ? status : null, hedged: bool(s.hedged),
      maxLossRs: num(s.max_loss_rs), maxProfitRs: num(s.max_profit_rs), profitUnbounded: s.profit_unbounded === true,
      breakevens: arr(s.breakevens).map(num).filter((n): n is number => n != null),
      net: readNet(s.net), marginRs: num(s.margin_rs), pnlRs: num(s.pnl_rs),
      legs: arr(s.legs).map((y) => {
        const g = rec(y);
        const side = str(g.side);
        return {
          side: side === "BUY" || side === "SELL" ? side : null, contract: str(g.contract) ?? "—", entry: num(g.entry), ltp: num(g.ltp),
          filledQty: num(g.filled_qty), qty: num(g.qty), pnlRs: num(g.pnl_rs), pending: g.pending === true,
        };
      }),
      scenarios: arr(s.scenarios).flatMap((y) => {
        const c = rec(y);
        const name = str(c.name);
        return name ? [{ name, label: str(c.label) ?? name.replace(/_/g, " "), pnlRs: num(c.pnl_rs) }] : [];
      }),
      note: [str(s.note), ...sentences(s.notes), num(s.max_loss_rs) == null ? str(s.max_loss_reason) : null, num(s.margin_rs) == null ? str(s.margin_reason) : null]
        .filter(Boolean).join(" ") || null,
    }];
  });
  return {
    structures,
    totals: { marginRs: num(t.margin_rs), maxLossRs: num(t.max_loss_rs), net: readNet(t.net) },
    limits: { fnoMaxLossPct: num(l.fno_max_loss_pct), marginUtilPct: num(l.margin_util_pct) },
    basis: str(b.basis), notes: sentences(b.notes),
  };
}

export function useFnoStructures(enabled = true) {
  const profile = useProfileKey();
  return useQuery<FnoBook>({
    queryKey: [...PV2_KEY, "fno-structures", profile],
    enabled,
    staleTime: 10_000,
    refetchInterval: REFRESH_MS,
    refetchIntervalInBackground: false,
    retry,
    queryFn: async ({ signal }) => readFnoBook((await http({ path: "/api/v1/paper/fno-structures", signal, noRetry: true, timeoutMs: 30_000 })).data),
  });
}

// ── stress test, with the named scenarios (§7) ───────────────────────────

export interface StressRow { key: string; label: string; lossRs: number | null; assumption: string | null }

const SCENARIO_LABEL: Record<string, string> = {
  index_down: "Nifty −2%", sector_gap: "Largest sector gap −3%", correlated_stops: "Correlated stops hit", gap_beyond_stops: "Gap beyond stops +25%",
  iv_up: "IV +10 pts (F&O)", gap_through_stop: "Gap through every stop", sector_shock: "Sector shock",
};
const signedPct = (v: number | null) => (v == null ? "" : `${v < 0 ? "−" : "+"}${Math.abs(v)}%`);

/** Every scenario the route sends, one row each (a market shock's results one row per shock), with the route's assumption. */
export function readStressRows(body: unknown): StressRow[] {
  const sc = arr(rec(body).scenarios).map(rec);
  return sc.flatMap((s, i): StressRow[] => {
    const name = str(s.name) ?? `scenario-${i}`;
    const assumption = str(s.assumption) ?? str(s.text);
    if (name === "market_shock" && Array.isArray(s.results)) {
      return s.results.map((x, j) => {
        const r = rec(x);
        const shock = num(r.shock_pct);
        const beta = num(r.beta);
        return {
          key: `${name}-${j}`, label: `Market ${signedPct(shock)}`.trim(), lossRs: num(r.loss_rs),
          assumption: [assumption, r.beta_assumed === true && beta != null ? `Beta ${beta} assumed.` : null].filter(Boolean).join(" ") || null,
        };
      });
    }
    const loss = num(s.loss_rs) ?? num(s.stressed_rs) ?? num(s.worst_loss_rs);
    const label = str(s.label) ?? (name === "sector_shock" && num(s.shock_pct) != null ? `Sector shock ${signedPct(num(s.shock_pct))}` : SCENARIO_LABEL[name] ?? name.replace(/_/g, " "));
    return [{ key: name, label, lossRs: loss, assumption }];
  });
}

export function useStress(accountId: string | null) {
  const profile = useProfileKey();
  return useQuery<{ base: SptStress; rows: StressRow[] }>({
    queryKey: [...PV2_KEY, "stress", profile, accountId ?? ""],
    enabled: !!accountId,
    staleTime: 15_000,
    refetchInterval: REFRESH_MS,
    retry,
    queryFn: async ({ signal }) => {
      const body = (await http({ path: `/api/v1/risk/stress-test/${encodeURIComponent(accountId as string)}`, signal, noRetry: true })).data;
      return { base: readSptStress(body), rows: readStressRows(body) };
    },
  });
}
