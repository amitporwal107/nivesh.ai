/**
 * Risk Desk (desk tab 04) — the reads this tab adds to risk-controls.ts, risk-profile.ts and fnolab/governance-data.ts,
 * and the pure arithmetic of "used / left".
 *
 *   GET /api/risk/freshness[?symbol=]          the risk service's inputs judged now, with the same budgets a decision uses
 *                                              (routes/risk_controls.py freshness): market state (regime, India VIX),
 *                                              and, for a share, its last close and sector               (useRiskFreshness)
 *   GET /api/admin/risk/jobs/{job}             a scheduled job's health: state, reason, last run, last success
 *                                              (admin only; services/job_runs.read_health)                 (useJobHealth)
 *
 * Reads trust nothing: a missing figure is null and the screen says "unknown", never 0. Paper risk only: the risk
 * service judges paper entries against paper equity and the paper book, never the user's real holdings.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { num } from "../../desk-data";
import type { RiskLive } from "../../risk-profile";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

const KEY = ["copilot", "desk", "risk", "desk-tab"] as const;
const isForbidden = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1;

// ── freshness ────────────────────────────────────────────────────────────

/** ok, stale (dated, too old), unknown (no value or no date), not_checked (a share input without ?symbol=). */
export type FreshStatus = "ok" | "stale" | "unknown" | "not_checked";

export interface FreshInput {
  status: FreshStatus;
  asOf: string | null;
  ageSessions: number | null;
  budget: number | null;
  reason: string | null;
  source: string | null;
  /** last close: the price; sector: its name. */
  value: string | number | null;
}

export interface RiskFreshness {
  symbol: string | null;
  market: FreshInput & { regime: string | null; vix: number | null };
  lastClose: FreshInput;
  sector: FreshInput;
  allOk: boolean | null;
  referenceSession: string | null;
  asOf: string | null;
  rule: string | null;
  version: string | null;
}

function readInput(v: unknown): FreshInput {
  const r = rec(v);
  const s = str(r.status);
  const status: FreshStatus = s === "ok" || s === "stale" || s === "not_checked" ? s : "unknown";
  const value = typeof r.value === "number" ? num(r.value) : str(r.value);
  return {
    status, asOf: str(r.as_of), ageSessions: num(r.age_sessions), budget: num(r.budget),
    reason: str(r.reason), source: str(r.source), value,
  };
}

export function readRiskFreshness(body: unknown): RiskFreshness {
  const d = rec(body);
  const inputs = rec(d.inputs);
  if (!Object.keys(inputs).length) throw ApiError.contractDrift("risk.freshness: no inputs");
  const m = rec(inputs.market_state);
  return {
    symbol: str(d.symbol),
    market: { ...readInput(m), regime: str(m.regime)?.toUpperCase() ?? null, vix: num(m.vix) },
    lastClose: readInput(inputs.last_close),
    sector: readInput(inputs.sector),
    allOk: typeof d.all_ok === "boolean" ? d.all_ok : null,
    referenceSession: str(d.reference_session),
    asOf: str(d.as_of),
    rule: str(d.rule),
    version: str(d.freshness_version),
  };
}

export function useRiskFreshness(symbol: string | null) {
  const profile = useImpersonationStore((st) => st.profileId);
  return useQuery<RiskFreshness>({
    queryKey: [...KEY, "freshness", profile ?? "self", symbol ?? ""],
    staleTime: 60_000,
    retry,
    queryFn: async ({ signal }) =>
      readRiskFreshness((await http({ path: "/api/risk/freshness", query: symbol ? { symbol } : undefined, signal, noRetry: true })).data),
  });
}

// ── the regime / VIX factor (services/ai_trader/risk_governor.py) ─────────

/** The governor's thresholds (risk_governor.Limits): VIX 25 halves the size limit, VIX 35 defers new entries. */
export const VIX_REDUCE_AT = 25;
export const VIX_DEFER_AT = 35;
const SIZE_FACTOR = 0.5; // bear_regime_size_factor and vix_size_factor

export interface RegimeFactor {
  /** The size-limit multiplier; null when new entries are deferred (VIX at or above 35). */
  factor: number | null;
  parts: string[];
  regimeKnown: boolean;
  deferred: boolean;
}

/** The cut the governor applies to the size LIMIT (never the ask), from the regime and India VIX. */
export function regimeFactor(regime: string | null, vix: number | null): RegimeFactor {
  let factor = 1;
  const parts: string[] = [];
  const deferred = vix != null && vix >= VIX_DEFER_AT;
  if (vix != null && vix >= VIX_REDUCE_AT && vix < VIX_DEFER_AT) {
    factor *= SIZE_FACTOR;
    parts.push(`India VIX ${vix} (at or above ${VIX_REDUCE_AT})`);
  }
  if (regime === "BEAR") {
    factor *= SIZE_FACTOR;
    parts.push("BEAR regime");
  }
  return { factor: deferred ? null : factor, parts, regimeKnown: regime != null, deferred };
}

/** "×0.5", "×0.25", "×1". */
export const factorText = (f: number) => `×${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 4 }).format(f)}`;

// ── used / left ──────────────────────────────────────────────────────────

/** The governor's open-positions cap: a fixed limit, not part of the profile (risk_governor.Limits.max_open_positions). */
export const MAX_OPEN_POSITIONS = 10;

export interface LimitUse {
  /** % of the basis used now; null when unknown or when the limit is judged per entry. */
  usedPct: number | null;
  /** % left before the limit; negative when over. */
  leftPct: number | null;
  /** Rupees used and the rupee cap, where the limit has one. */
  usedRs: number | null;
  capRs: number | null;
  /** The limit is judged on each new entry, not on a running total (per trade, position, min R:R). */
  perEntry: boolean;
  /** What "used" is measured as, in words (e.g. "Financials, the largest sector"). */
  note: string | null;
  /** Why the figure is unknown, when it is. */
  unknown: string | null;
}

const pctOf = (rs: number | null, base: number | null) => (rs == null || base == null || base <= 0 ? null : (rs / base) * 100);

function loss(p: RiskLive["day"]): { pct: number | null; rs: number | null; why: string | null } {
  if (p.pnlRs == null || p.startEquityRs == null || p.startEquityRs <= 0) {
    return { pct: null, rs: null, why: p.unknownReasons.length ? p.unknownReasons.join("; ") : "the P&L is unknown" };
  }
  const rs = Math.max(0, -p.pnlRs);
  return { pct: (rs / p.startEquityRs) * 100, rs, why: null };
}

/**
 * Used and left for one of the eight limits, from the live block of GET /api/risk/profile. The arithmetic is the risk
 * service's own (services/risk_gate/service.py): open risk and sector exposure as a share of equity, the day's and the
 * week's loss as a share of the period's starting equity, drawdown from the peak.
 */
export function limitUse(field: string, limit: number | null, live: RiskLive | null, liveError: string | null): LimitUse {
  const base: LimitUse = { usedPct: null, leftPct: null, usedRs: null, capRs: null, perEntry: false, note: null, unknown: null };
  if (field === "per_trade_risk_pct" || field === "max_position_pct" || field === "min_reward_risk") {
    const key = field === "per_trade_risk_pct" ? "per_trade" : field === "max_position_pct" ? "position" : null;
    return { ...base, perEntry: true, capRs: key && live ? live.budgetsRs[key] ?? null : null };
  }
  if (!live) return { ...base, unknown: liveError ?? "the live figures could not be read" };
  const left = (used: number | null) => (used == null || limit == null ? null : limit - used);
  const eq = live.equityRs;
  switch (field) {
    case "max_open_risk_pct": {
      const used = pctOf(live.open.riskRs, eq);
      return { ...base, usedPct: used, leftPct: left(used), usedRs: live.open.riskRs, capRs: live.budgetsRs.open_risk ?? null,
        unknown: used == null ? "paper equity or open risk is unknown" : null };
    }
    case "max_sector_pct": {
      const top = live.open.sectors[0] ?? null;
      if (!top) return { ...base, usedPct: 0, leftPct: left(0), usedRs: 0, capRs: live.budgetsRs.sector ?? null, note: "no open sector exposure" };
      const used = pctOf(top.rs, eq);
      return { ...base, usedPct: used, leftPct: left(used), usedRs: top.rs, capRs: live.budgetsRs.sector ?? null,
        note: `${top.sector}, the largest sector`, unknown: used == null ? "paper equity is unknown" : null };
    }
    case "daily_loss_pct":
    case "weekly_loss_pct": {
      const l = loss(field === "daily_loss_pct" ? live.day : live.week);
      return { ...base, usedPct: l.pct, leftPct: left(l.pct), usedRs: l.rs, unknown: l.why,
        note: field === "daily_loss_pct" ? "of the day's starting equity" : "of the week's starting equity" };
    }
    case "max_drawdown_pct": {
      const used = live.drawdownPct;
      return { ...base, usedPct: used, leftPct: left(used), note: "below the peak", unknown: used == null ? "drawdown is unknown" : null };
    }
    default:
      return { ...base, unknown: "no running figure for this limit" };
  }
}

// ── admin: job health ────────────────────────────────────────────────────

export const JOBS = [
  { job: "check_desk_alerts", label: "Exit check" },
  { job: "positional_engine", label: "AI scanner" },
] as const;

export interface JobHealth {
  job: string;
  /** never_run | running | failed | partial | no_data | missed | ok | skipped | calendar_not_ready | refused; null if unread. */
  state: string | null;
  healthy: boolean | null;
  reason: string | null;
  schedule: string | null;
  lastSuccessAt: string | null;
  lastRunAt: string | null;
  lastRunSession: string | null;
}

export function readJobHealth(body: unknown, job: string): JobHealth {
  const d = rec(body);
  const last = rec(d.last_run);
  const ok = rec(d.last_success);
  return {
    job: str(d.job) ?? job, state: str(d.state), healthy: typeof d.healthy === "boolean" ? d.healthy : null,
    reason: str(d.reason), schedule: str(d.schedule), lastSuccessAt: str(d.last_success_at) ?? str(ok.started_at),
    lastRunAt: str(last.started_at), lastRunSession: str(last.session),
  };
}

export function useJobHealth(job: string, enabled: boolean) {
  return useQuery<JobHealth>({
    queryKey: [...KEY, "job", job],
    enabled,
    staleTime: 60_000,
    retry,
    queryFn: async ({ signal }) => readJobHealth((await http({ path: `/api/admin/risk/jobs/${job}`, signal, noRetry: true })).data, job),
  });
}
