/**
 * Risk Desk › Scanner-to-Paper Trading (SPT) reads: Trading overview, Capital allocation, Portfolio risk (owner, 5 Nov 2026;
 * docs/scanner_paper_trading/DESIGN.md; PRD §12.1/§12.3/§12.4/§19.2/§19.4/§19.5, Workflow §9/§18/§19).
 *
 *   GET  /api/v1/paper/accounts                          the caller's account id (= user id, DESIGN D3) and the SPT mode
 *   GET  /api/v1/risk/account/{account_id}               equity, cash, deployed, reserved, open / SPT risk, loss used,
 *                                                        drawdown + ladder, kill switch, limits, utilisation
 *   GET  /api/v1/risk/exposures/{account_id}             exposure by sector, instrument and bucket (503 when unreadable)
 *   GET  /api/v1/risk/stress-test/{account_id}           the deterministic scenarios on the open SPT entries
 *   GET  /api/v1/allocation/recommendations/{account_id} QUALIFIED opportunities ranked, each sized by the account's limits
 *   POST /api/v1/allocation/recalculate/{account_id}     re-size the caller's proposals awaiting approval (nothing ordered)
 *   GET  /api/v1/proposals?state=AWAITING_USER_APPROVAL  the caller's proposals awaiting approval
 *   GET  /api/v1/opportunities?state=QUALIFIED           market-wide qualified opportunities (count only)
 *   GET  /api/v1/paper/positions?status=open|all         the caller's SPT paper positions
 *   GET  /api/v1/paper/orders?state=LIVE                 the caller's live (pending) SPT paper orders
 *
 * Reads trust nothing: a missing figure is null and the screen shows "—" with the API's reason, never 0. Paper only.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { num } from "../../desk-data";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);
const strs = (v: unknown): string[] => arr(v).map(str).filter((s): s is string => s != null);

const KEY = ["copilot", "desk", "risk", "spt"] as const;
const isForbidden = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1;
const REFRESH_MS = 30_000;

function useProfileKey() {
  return useImpersonationStore((st) => st.profileId) ?? "self";
}

// ── the account (GET /api/v1/paper/accounts) ─────────────────────────────

export interface SptLadderThresholds { reduceAtPct: number | null; restrictAtPct: number | null; haltAtPct: number | null; reduceFactor: number | null }

export interface SptAccount {
  accountId: string;
  mode: string | null;
  modes: string[];
  configVersion: number | null;
  configStored: boolean | null;
  bucketsPct: Record<string, number | null>;
  ladder: SptLadderThresholds;
  note: string | null;
}

const readThresholds = (v: unknown): SptLadderThresholds => {
  const t = rec(v);
  return { reduceAtPct: num(t.reduce_at_pct), restrictAtPct: num(t.restrict_at_pct), haltAtPct: num(t.halt_at_pct), reduceFactor: num(t.reduce_factor) };
};

const readBuckets = (v: unknown): Record<string, number | null> =>
  Object.fromEntries(Object.entries(rec(v)).map(([k, x]) => [k, num(x)]));

export function readSptAccounts(body: unknown): SptAccount | null {
  const a = rec(arr(rec(body).accounts)[0]);
  const id = str(a.account_id);
  if (!id) return null;
  const cfg = rec(a.config);
  const extras = rec(cfg.extras);
  return {
    accountId: id, mode: str(cfg.mode), modes: strs(a.modes), configVersion: num(cfg.version), configStored: bool(cfg.stored),
    bucketsPct: readBuckets(extras.allocation_buckets_pct), ladder: readThresholds(extras.drawdown_ladder), note: str(a.note),
  };
}

export function useSptAccount() {
  const profile = useProfileKey();
  return useQuery<SptAccount | null>({
    queryKey: [...KEY, "account", profile],
    staleTime: 60_000,
    retry,
    queryFn: async ({ signal }) => readSptAccounts((await http({ path: "/api/v1/paper/accounts", signal, noRetry: true })).data),
  });
}

// ── risk / account ───────────────────────────────────────────────────────

export interface SptLoss { pnlRs: number | null; startEquityRs: number | null; lossPct: number | null; limitPct: number | null; breached: boolean | null }
export interface SptReason { code: string | null; text: string }
export interface SptLadder {
  band: string | null;
  drawdownPct: number | null;
  factor: number | null;
  blocksNewEntries: boolean | null;
  text: string | null;
  thresholds: SptLadderThresholds;
}
export interface SptKillSwitch {
  state: string | null;
  entriesBlocked: boolean | null;
  killSwitch: boolean | null;
  halted: boolean | null;
  reason: string | null;
  reasons: SptReason[];
  text: string | null;
}
export interface SptPending { orderId: string | null; symbol: string | null; reservedRs: number | null; orderState: string | null }
export interface SptBucketUse { usedRs: number | null; capRs: number | null }

export interface SptRiskAccount {
  accountId: string | null;
  asOf: string | null;
  error: string | null;
  equityRs: number | null;
  equityBasis: string | null;
  equityUnknownReasons: string[];
  cashRs: number | null;
  availableRs: number | null;
  blockedRs: number | null;
  deployedRs: number | null;
  reservedRs: number | null;
  pending: SptPending[];
  reserveBucketRs: number | null;
  openRisk: { rs: number | null; basis: string | null; capRs: number | null; limitPct: number | null; usedPctOfEquity: number | null };
  /** null when the API sent none (the account could not be read). */
  sptRisk: { plannedRs: number | null; stressedRs: number | null; entries: number | null; unpriced: string[]; stressedGapPct: number | null; basis: string | null } | null;
  dailyLoss: SptLoss;
  weeklyLoss: SptLoss;
  drawdown: { pct: number | null; peakRs: number | null; profileHaltPct: number | null; ladder: SptLadder };
  killSwitch: SptKillSwitch;
  limits: { profile: Record<string, number | null>; limitsVersion: string | null; sptConfigVersion: number | null; bucketsPct: Record<string, number | null> };
  utilisation: {
    positionsOpen: number | null; positionsMax: number | null; newToday: number | null; newTodayMax: number | null;
    buckets: Record<string, SptBucketUse>; exposureRs: number | null; exposurePctOfEquity: number | null;
  };
  mode: string | null;
}

const readLoss = (v: unknown): SptLoss => {
  const l = rec(v);
  return { pnlRs: num(l.pnl_rs), startEquityRs: num(l.start_equity_rs), lossPct: num(l.loss_pct), limitPct: num(l.limit_pct), breached: bool(l.breached) };
};

const readReasons = (v: unknown): SptReason[] =>
  arr(v).map((x) => {
    const r = rec(x);
    const text = str(r.text) ?? str(r.message);
    return text ? { code: str(r.code), text } : null;
  }).filter((x): x is SptReason => x != null);

export const readLadder = (v: unknown): SptLadder => {
  const l = rec(v);
  return {
    band: str(l.band), drawdownPct: num(l.drawdown_pct), factor: num(l.factor), blocksNewEntries: bool(l.blocks_new_entries),
    text: str(l.text), thresholds: readThresholds(l.thresholds),
  };
};

export function readSptRiskAccount(body: unknown): SptRiskAccount {
  const d = rec(body);
  if (!Object.keys(d).length) throw ApiError.contractDrift("spt.risk.account: empty body");
  const or = rec(d.open_risk);
  const sr = d.spt_risk && typeof d.spt_risk === "object" ? rec(d.spt_risk) : null;
  const dd = rec(d.drawdown);
  const ks = rec(d.kill_switch);
  const lim = rec(d.limits);
  const ut = rec(d.utilisation);
  const pos = rec(ut.positions);
  const nt = rec(ut.new_today);
  return {
    accountId: str(d.account_id), asOf: str(d.as_of), error: str(d.error),
    equityRs: num(d.equity_rs), equityBasis: str(d.equity_basis), equityUnknownReasons: strs(d.equity_unknown_reasons),
    cashRs: num(d.cash_rs), availableRs: num(d.available_rs), blockedRs: num(d.blocked_rs), deployedRs: num(d.deployed_rs),
    reservedRs: num(d.reserved_rs),
    pending: arr(d.pending_entries).map((x) => {
      const p = rec(x);
      return { orderId: str(p.order_id), symbol: str(p.symbol), reservedRs: num(p.reserved_rs), orderState: str(p.order_state) };
    }),
    reserveBucketRs: num(d.reserve_bucket_rs),
    openRisk: { rs: num(or.rs), basis: str(or.basis), capRs: num(or.cap_rs), limitPct: num(or.limit_pct), usedPctOfEquity: num(or.used_pct_of_equity) },
    sptRisk: sr
      ? { plannedRs: num(sr.planned_rs), stressedRs: num(sr.stressed_rs), entries: num(sr.entries), unpriced: strs(sr.unpriced),
          stressedGapPct: num(sr.stressed_gap_pct), basis: str(sr.basis) }
      : null,
    dailyLoss: readLoss(d.daily_loss), weeklyLoss: readLoss(d.weekly_loss),
    drawdown: { pct: num(dd.pct), peakRs: num(dd.peak_rs), profileHaltPct: num(dd.profile_halt_pct), ladder: readLadder(dd.ladder) },
    killSwitch: {
      state: str(ks.state), entriesBlocked: bool(ks.entries_blocked), killSwitch: bool(ks.kill_switch), halted: bool(ks.halted),
      reason: str(ks.reason), reasons: readReasons(ks.reasons), text: str(ks.text),
    },
    limits: {
      profile: Object.fromEntries(Object.entries(rec(lim.profile)).map(([k, v]) => [k, num(v)])),
      limitsVersion: str(lim.limits_version), sptConfigVersion: num(lim.spt_config_version),
      bucketsPct: readBuckets(rec(lim.spt).allocation_buckets_pct),
    },
    utilisation: {
      positionsOpen: num(pos.open), positionsMax: num(pos.max), newToday: num(nt.count), newTodayMax: num(nt.max),
      buckets: Object.fromEntries(Object.entries(rec(ut.buckets)).map(([k, v]) => [k, { usedRs: num(rec(v).used_rs), capRs: num(rec(v).cap_rs) }])),
      exposureRs: num(ut.exposure_rs), exposurePctOfEquity: num(ut.exposure_pct_of_equity),
    },
    mode: str(d.mode),
  };
}

export function useSptRiskAccount(accountId: string | null) {
  const profile = useProfileKey();
  return useQuery<SptRiskAccount>({
    queryKey: [...KEY, "risk-account", profile, accountId ?? ""],
    enabled: !!accountId,
    staleTime: 15_000,
    refetchInterval: REFRESH_MS,
    retry,
    queryFn: async ({ signal }) =>
      readSptRiskAccount((await http({ path: `/api/v1/risk/account/${encodeURIComponent(accountId as string)}`, signal, noRetry: true })).data),
  });
}

// ── exposures ────────────────────────────────────────────────────────────

export interface SptExposureRow { key: string; exposureRs: number | null; pctOfEquity: number | null; limitPct: number | null }
export interface SptBucketRow { category: string; usedRs: number | null; capRs: number | null; bucketPct: number | null }
export interface SptExposures {
  asOf: string | null;
  equityRs: number | null;
  bySector: SptExposureRow[];
  unclassifiedRs: number | null;
  byInstrument: SptExposureRow[];
  byCategory: SptBucketRow[];
  totalRs: number | null;
  basis: string | null;
}

export function readSptExposures(body: unknown): SptExposures {
  const d = rec(body);
  if (!Array.isArray(d.by_sector) && !Array.isArray(d.by_category)) throw ApiError.contractDrift("spt.risk.exposures: no rows");
  const row = (k: string) => (x: unknown): SptExposureRow => {
    const r = rec(x);
    return { key: str(r[k]) ?? "—", exposureRs: num(r.exposure_rs), pctOfEquity: num(r.pct_of_equity), limitPct: num(r.limit_pct) };
  };
  return {
    asOf: str(d.as_of), equityRs: num(d.equity_rs), bySector: arr(d.by_sector).map(row("sector")),
    unclassifiedRs: num(d.unclassified_exposure_rs), byInstrument: arr(d.by_instrument).map(row("symbol")),
    byCategory: arr(d.by_category).map((x) => {
      const r = rec(x);
      return { category: str(r.category) ?? "—", usedRs: num(r.used_rs), capRs: num(r.cap_rs), bucketPct: num(r.bucket_pct) };
    }),
    totalRs: num(d.total_exposure_rs), basis: str(d.basis),
  };
}

export function useSptExposures(accountId: string | null) {
  const profile = useProfileKey();
  return useQuery<SptExposures>({
    queryKey: [...KEY, "exposures", profile, accountId ?? ""],
    enabled: !!accountId,
    staleTime: 15_000,
    refetchInterval: REFRESH_MS,
    retry,
    queryFn: async ({ signal }) =>
      readSptExposures((await http({ path: `/api/v1/risk/exposures/${encodeURIComponent(accountId as string)}`, signal, noRetry: true })).data),
  });
}

// ── stress test ──────────────────────────────────────────────────────────

export interface SptStressPosition {
  orderId: string | null; symbol: string | null; sector: string | null; quantity: number | null; entry: number | null; stop: number | null;
  plannedRs: number | null; stressedRs: number | null; valueRs: number | null; source: string | null;
}
export interface SptMarketShock { shockPct: number | null; beta: number | null; betaAssumed: boolean | null; lossRs: number | null }
export interface SptStress {
  asOf: string | null;
  equityRs: number | null;
  version: string | null;
  positions: SptStressPosition[];
  unpriced: string[];
  totals: { plannedRs: number | null; stressedRs: number | null; valueRs: number | null };
  gap: { gapPct: number | null; plannedRs: number | null; stressedRs: number | null; text: string | null } | null;
  sector: { shockPct: number | null; bySectorRs: Array<{ sector: string; lossRs: number | null }>; worstSector: string | null; worstLossRs: number | null; text: string | null } | null;
  market: { results: SptMarketShock[]; text: string | null } | null;
  basis: string | null;
}

export function readSptStress(body: unknown): SptStress {
  const d = rec(body);
  if (!Array.isArray(d.scenarios) && !d.totals) throw ApiError.contractDrift("spt.risk.stress: no scenarios");
  const sc = arr(d.scenarios).map(rec);
  const byName = (n: string) => sc.find((s) => str(s.name) === n) ?? null;
  const g = byName("gap_through_stop");
  const s = byName("sector_shock");
  const m = byName("market_shock");
  const t = rec(d.totals);
  return {
    asOf: str(d.as_of), equityRs: num(d.equity_rs), version: str(d.version),
    positions: arr(d.positions).map((x) => {
      const p = rec(x);
      return {
        orderId: str(p.order_id), symbol: str(p.symbol), sector: str(p.sector), quantity: num(p.quantity), entry: num(p.entry), stop: num(p.stop),
        plannedRs: num(p.planned_rs), stressedRs: num(p.stressed_rs), valueRs: num(p.value_rs), source: str(p.source),
      };
    }),
    unpriced: strs(d.unpriced),
    totals: { plannedRs: num(t.planned_rs), stressedRs: num(t.stressed_rs), valueRs: num(t.value_rs) },
    gap: g ? { gapPct: num(g.gap_pct), plannedRs: num(g.planned_rs), stressedRs: num(g.stressed_rs), text: str(g.text) } : null,
    sector: s
      ? {
          shockPct: num(s.shock_pct),
          bySectorRs: Object.entries(rec(s.by_sector_rs)).map(([k, v]) => ({ sector: k, lossRs: num(v) })).sort((a, b) => (b.lossRs ?? 0) - (a.lossRs ?? 0)),
          worstSector: str(s.worst_sector), worstLossRs: num(s.worst_loss_rs), text: str(s.text),
        }
      : null,
    market: m
      ? {
          results: arr(m.results).map((x) => {
            const r = rec(x);
            return { shockPct: num(r.shock_pct), beta: num(r.beta), betaAssumed: bool(r.beta_assumed), lossRs: num(r.loss_rs) };
          }),
          text: str(m.text),
        }
      : null,
    basis: str(d.basis),
  };
}

export function useSptStress(accountId: string | null) {
  const profile = useProfileKey();
  return useQuery<SptStress>({
    queryKey: [...KEY, "stress", profile, accountId ?? ""],
    enabled: !!accountId,
    staleTime: 15_000,
    refetchInterval: REFRESH_MS,
    retry,
    queryFn: async ({ signal }) =>
      readSptStress((await http({ path: `/api/v1/risk/stress-test/${encodeURIComponent(accountId as string)}`, signal, noRetry: true })).data),
  });
}

/** Planned and stressed risk summed per key (sector or symbol) over the stress test's priced positions. */
export function riskBy(positions: SptStressPosition[], key: "sector" | "symbol"): Array<{ key: string; plannedRs: number; stressedRs: number; count: number }> {
  const out = new Map<string, { key: string; plannedRs: number; stressedRs: number; count: number }>();
  for (const p of positions) {
    const k = (key === "sector" ? p.sector : p.symbol) ?? (key === "sector" ? "unclassified" : "—");
    const cur = out.get(k) ?? { key: k, plannedRs: 0, stressedRs: 0, count: 0 };
    cur.plannedRs += p.plannedRs ?? 0;
    cur.stressedRs += p.stressedRs ?? 0;
    cur.count += 1;
    out.set(k, cur);
  }
  return [...out.values()].sort((a, b) => b.stressedRs - a.stressedRs);
}

// ── ranked opportunities (GET /api/v1/allocation/recommendations/{id}) ────

export interface SptAllocReason { code: string | null; message: string }
export interface SptRankedItem {
  rank: number | null;
  opportunityId: string | null;
  symbol: string | null;
  opportunityScore: number | null;
  rrT2: number | null;
  rrMin: number | null;
  entryPrice: number | null;
  stopLoss: number | null;
  outcome: string | null;
  reasonCodes: string[];
  explanations: string[];
  proposal: { proposalId: string | null; state: string | null } | null;
  sizing: { quantity: number | null; capitalRs: number | null; plannedRiskRs: number | null; stressedRiskRs: number | null; blocked: SptAllocReason[] } | null;
  allocation: { decision: string | null; requestedQty: number | null; quantity: number | null; capitalRs: number | null; stressedRiskRs: number | null; reasons: SptAllocReason[] } | null;
}
export interface SptRanked { asOf: string | null; mode: string | null; items: SptRankedItem[]; rankBasis: string | null; priceSource: string | null }

const readAllocReasons = (v: unknown): SptAllocReason[] =>
  arr(v).map((x) => {
    const r = rec(x);
    const message = str(r.message) ?? str(r.text);
    return message ? { code: str(r.code), message } : null;
  }).filter((x): x is SptAllocReason => x != null);

export function readSptRanked(body: unknown): SptRanked {
  const d = rec(body);
  if (!Array.isArray(d.items)) throw ApiError.contractDrift("spt.allocation.ranked: no items");
  return {
    asOf: str(d.as_of), mode: str(d.mode), rankBasis: str(d.rank_basis), priceSource: str(d.price_source),
    items: d.items.map((x) => {
      const r = rec(x);
      const rr = rec(r.rr);
      const pr = r.proposal && typeof r.proposal === "object" ? rec(r.proposal) : null;
      const sz = r.sizing && typeof r.sizing === "object" ? rec(r.sizing) : null;
      const al = r.allocation && typeof r.allocation === "object" ? rec(r.allocation) : null;
      return {
        rank: num(r.rank), opportunityId: str(r.opportunity_id), symbol: str(r.symbol), opportunityScore: num(r.opportunity_score),
        rrT2: num(rr.t2), rrMin: num(rr.min_rr), entryPrice: num(rec(r.entry).price), stopLoss: num(r.stop_loss),
        outcome: str(r.outcome), reasonCodes: strs(r.reason_codes), explanations: strs(r.explanations),
        proposal: pr ? { proposalId: str(pr.proposal_id), state: str(pr.state) } : null,
        sizing: sz
          ? { quantity: num(sz.quantity), capitalRs: num(sz.capital_required), plannedRiskRs: num(sz.planned_risk), stressedRiskRs: num(sz.stressed_risk),
              blocked: readAllocReasons(sz.blocked) }
          : null,
        allocation: al
          ? { decision: str(al.decision), requestedQty: num(al.requested_qty), quantity: num(al.quantity), capitalRs: num(al.capital_rs),
              stressedRiskRs: num(al.stressed_risk_rs), reasons: readAllocReasons(al.reasons) }
          : null,
      };
    }),
  };
}

export function useSptRanked(accountId: string | null) {
  const profile = useProfileKey();
  return useQuery<SptRanked>({
    queryKey: [...KEY, "ranked", profile, accountId ?? ""],
    enabled: !!accountId,
    staleTime: 15_000,
    refetchInterval: REFRESH_MS,
    retry,
    queryFn: async ({ signal }) =>
      readSptRanked((await http({ path: `/api/v1/allocation/recommendations/${encodeURIComponent(accountId as string)}`, signal, noRetry: true })).data),
  });
}

// ── proposals awaiting approval, and the recalculation ───────────────────

export interface SptProposalBrief {
  proposalId: string;
  symbol: string | null;
  state: string | null;
  sizedQty: number | null;
  allocationDecision: string | null;
  allocatedQty: number | null;
  recalculatedAt: string | null;
}

export function readSptProposals(body: unknown): { items: SptProposalBrief[]; count: number } {
  const d = rec(body);
  if (!Array.isArray(d.items)) throw ApiError.contractDrift("spt.proposals: no items");
  const items = d.items.map((x) => {
    const p = rec(x);
    const sz = rec(p.sizing);
    const al = rec(p.allocation);
    return {
      proposalId: str(p.proposal_id) ?? "", symbol: str(p.symbol), state: str(p.state), sizedQty: num(sz.quantity),
      allocationDecision: str(al.decision), allocatedQty: num(al.quantity), recalculatedAt: str(p.recalculated_at),
    };
  }).filter((p) => p.proposalId);
  return { items, count: num(d.count) ?? items.length };
}

export const AWAITING = "AWAITING_USER_APPROVAL";

export function useSptAwaiting(enabled = true) {
  const profile = useProfileKey();
  return useQuery({
    queryKey: [...KEY, "proposals", profile, AWAITING],
    enabled,
    staleTime: 15_000,
    refetchInterval: REFRESH_MS,
    retry,
    queryFn: async ({ signal }) =>
      readSptProposals((await http({ path: "/api/v1/proposals", query: { state: AWAITING, limit: 200 }, signal, noRetry: true })).data),
  });
}

export interface SptRecalcRow { proposalId: string | null; symbol: string | null; rank: number | null; quantity: number | null; allocation: string | null; allocatedQty: number | null; recorded: boolean | null }
export interface SptRecalc { asOf: string | null; rows: SptRecalcRow[] }

export function readSptRecalc(body: unknown): SptRecalc {
  const d = rec(body);
  if (!Array.isArray(d.recalculated)) throw ApiError.contractDrift("spt.allocation.recalculate: no rows");
  return {
    asOf: str(d.as_of),
    rows: d.recalculated.map((x) => {
      const r = rec(x);
      return { proposalId: str(r.proposal_id), symbol: str(r.symbol), rank: num(r.rank), quantity: num(r.quantity), allocation: str(r.allocation),
        allocatedQty: num(r.allocated_qty), recorded: bool(r.recorded) };
    }),
  };
}

export function useSptRecalculate(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<SptRecalc> =>
      readSptRecalc((await http({ method: "POST", path: `/api/v1/allocation/recalculate/${encodeURIComponent(accountId as string)}`, body: {}, noRetry: true })).data),
    // The ranked list, the proposals and the account all read the recorded figures: re-read them.
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

// ── counts: qualified opportunities, live orders ─────────────────────────

/** The opportunities route caps a page at 500; `capped` = the page was full (there may be more). */
export const OPP_PAGE = 500;

export function useSptQualifiedCount() {
  return useQuery<{ count: number; capped: boolean }>({
    queryKey: [...KEY, "qualified-count"],
    staleTime: 15_000,
    refetchInterval: REFRESH_MS,
    retry,
    queryFn: async ({ signal }) => {
      const d = rec((await http({ path: "/api/v1/opportunities", query: { state: "QUALIFIED", limit: OPP_PAGE }, signal, noRetry: true })).data);
      if (!Array.isArray(d.opportunities)) throw ApiError.contractDrift("spt.opportunities: no list");
      const count = num(d.count) ?? d.opportunities.length;
      return { count, capped: count >= OPP_PAGE };
    },
  });
}

export interface SptOrderBrief { orderId: string | null; symbol: string | null; purpose: string | null; state: string | null }

export function useSptLiveOrders() {
  const profile = useProfileKey();
  return useQuery<SptOrderBrief[]>({
    queryKey: [...KEY, "orders-live", profile],
    staleTime: 15_000,
    refetchInterval: REFRESH_MS,
    retry,
    queryFn: async ({ signal }) => {
      const d = rec((await http({ path: "/api/v1/paper/orders", query: { state: "LIVE", limit: 500 }, signal, noRetry: true })).data);
      if (!Array.isArray(d.orders)) throw ApiError.contractDrift("spt.paper.orders: no list");
      return d.orders.map((x) => {
        const o = rec(x);
        return { orderId: str(o.order_id) ?? str(o._id), symbol: str(o.symbol), purpose: str(o.purpose), state: str(o.state) };
      });
    },
  });
}

// ── positions ────────────────────────────────────────────────────────────

export interface SptPosition {
  positionId: string;
  symbol: string | null;
  state: string | null;
  isOpen: boolean;
  quantity: number | null;
  avgEntryPrice: number | null;
  stopLoss: number | null;
  nextTarget: number | null;
  investedRs: number | null;
  riskAtStopRs: number | null;
  realizedNetRs: number | null;
  mark: { price: number | null; basis: string | null; at: string | null; unrealizedNetRs: number | null } | null;
}

const OPEN_STATES_CLOSED = "CLOSED";

export function readSptPositions(body: unknown): { items: SptPosition[]; count: number } {
  const d = rec(body);
  if (!Array.isArray(d.positions)) throw ApiError.contractDrift("spt.paper.positions: no list");
  const items = d.positions.map((x) => {
    const p = rec(x);
    const m = p.mark && typeof p.mark === "object" ? rec(p.mark) : null;
    const state = str(p.state);
    return {
      positionId: str(p.position_id) ?? str(p._id) ?? "",
      symbol: str(p.symbol), state, isOpen: state != null ? state !== OPEN_STATES_CLOSED : bool(p.is_open) === true,
      quantity: num(p.quantity), avgEntryPrice: num(p.avg_entry_price), stopLoss: num(p.stop_loss), nextTarget: num(p.next_target),
      investedRs: num(p.invested_rs), riskAtStopRs: num(p.risk_at_stop_rs), realizedNetRs: num(p.realized_net_rs),
      mark: m ? { price: num(m.price), basis: str(m.basis), at: str(m.at), unrealizedNetRs: num(m.unrealized_net_rs) } : null,
    };
  }).filter((p) => p.positionId);
  return { items, count: num(d.count) ?? items.length };
}

/** The positions route caps a page at 500. */
export const POSITION_PAGE = 500;

export function useSptPositions(status: "open" | "all") {
  const profile = useProfileKey();
  return useQuery({
    queryKey: [...KEY, "positions", profile, status],
    staleTime: 15_000,
    refetchInterval: REFRESH_MS,
    retry,
    queryFn: async ({ signal }) =>
      readSptPositions((await http({ path: "/api/v1/paper/positions", query: { status, limit: POSITION_PAGE }, signal, noRetry: true })).data),
  });
}

export interface PnlSum { rs: number | null; counted: number; missing: number; capped: boolean }

/** Unrealized P&L: the sum of the open positions' live marks (`mark.unrealized_net_rs`); unmarked positions are counted, not guessed. */
export function unrealizedOf(open: SptPosition[]): PnlSum {
  const marked = open.filter((p) => p.mark?.unrealizedNetRs != null);
  return {
    rs: marked.length ? marked.reduce((s, p) => s + (p.mark!.unrealizedNetRs as number), 0) : open.length ? null : 0,
    counted: marked.length, missing: open.length - marked.length, capped: false,
  };
}

/** Realized P&L: the sum of `realized_net_rs` over every SPT position (closed, and the part-exited open ones). */
export function realizedOf(all: SptPosition[], count: number): PnlSum {
  const known = all.filter((p) => p.realizedNetRs != null);
  return {
    rs: known.reduce((s, p) => s + (p.realizedNetRs as number), 0),
    counted: known.length, missing: all.length - known.length, capped: count >= POSITION_PAGE,
  };
}

/** Risk from the current price to the stop: (price − stop) × quantity, floored at 0; null without a live mark or a stop. */
export function riskToStop(p: SptPosition): number | null {
  const px = p.mark?.price ?? null;
  if (px == null || p.stopLoss == null || p.quantity == null) return null;
  return Math.max(0, (px - p.stopLoss) * p.quantity);
}
