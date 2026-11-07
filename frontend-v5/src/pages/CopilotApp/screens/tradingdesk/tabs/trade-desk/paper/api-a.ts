/**
 * Paper Trading v2 (builder A) — the reads and writes of the shell, 01 Overview, 02 Scanner opportunities and 06 Strategy
 * analytics (owner's design of 5 Nov 2026; docs/scanner_paper_trading/UI_DESIGN_V2.md; the contract is its §7):
 *
 *   GET  /api/v1/paper/overview                 status strip (feed, session, kill switch, policy, mode), KPIs, today's pipeline,
 *                                               warnings, the headline counts (§7; new)
 *   GET  /api/v1/paper/accounts                 the caller's paper account (services/paper_account.public: starting capital,
 *                                               cash) and its SPT config (mode, version) — routes/spt_accounts.py
 *   PUT  /api/v1/paper/accounts/{id}/config     {mode, expected_version} — the mode chooser (spt-api.ts usePutConfig)
 *   GET  /api/v1/opportunities?limit=           market-wide opportunities (routes/spt_signals.py; spt-api.ts readOpportunity)
 *   GET  /api/v1/proposals?limit=               the caller's proposals (routes/spt_risk.py; spt-api.ts readProposal) plus the
 *                                               risk record's checks[] and the instrument, which spt-api.ts does not read
 *   GET  /api/v1/proposals?state=AWAITING_USER_APPROVAL   the 02 chip's badge count
 *   POST /api/v1/opportunities/{id}/approve | reject      spt-api.ts useApprove / useReject
 *   GET  /api/v1/analytics/account/{id}?days=90 KPIs, by setup, by regime, the certification checklist (§7; new)
 *   GET  /api/v1/analytics/scanners?from=       signal outcomes per scanner (spt-api.ts useScannerAnalytics)
 *   GET  /api/watchlists · POST /api/watchlists/{id}/symbols   "Add to watchlist" (workspace/personal-lists.ts)
 *
 * Every key sits under spt-api.ts SPT_KEY, so an approve / reject / mode change re-reads all of them. Reads trust nothing:
 * a missing or non-numeric figure is null (shown "—"), never 0; a body without its main fields is a contract error, not an
 * empty screen. Nothing here reaches a broker.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { num } from "../../../desk-data";
import { SPT_KEY, readConfig, readOpportunity, readProposal, type SptConfig, type SptOpportunity, type SptProposal } from "../spt-api";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);
const isObj = (v: unknown): v is Raw => !!v && typeof v === "object" && !Array.isArray(v);

const isForbidden = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);
const retry = (count: number, e: unknown) => !isForbidden(e) && !(e instanceof ApiError && (e.kind === "contract_drift" || e.status === 404)) && count < 1;
const useProfile = () => useImpersonationStore((st) => st.profileId) ?? "self";

// ── the paper account (GET /api/v1/paper/accounts) ───────────────────────

export interface PaperAccount {
  accountId: string;
  startingCapitalRs: number | null;
  cashRs: number | null;
  config: SptConfig | null;
}

export function readPaperAccounts(body: unknown): PaperAccount {
  const b = rec(body);
  if (!Array.isArray(b.accounts)) throw ApiError.contractDrift("paper.accounts: no accounts list");
  const a = rec(b.accounts[0]);
  const id = str(a.account_id);
  if (!id) throw ApiError.contractDrift("paper.accounts: no account_id");
  const acc = rec(a.account);
  return { accountId: id, startingCapitalRs: num(acc.starting_capital_rs), cashRs: num(acc.cash_rs), config: readConfig(a.config) };
}

export function usePaperAccount() {
  const profile = useProfile();
  return useQuery<PaperAccount>({
    queryKey: [...SPT_KEY, "pv2-account", profile],
    staleTime: 15_000,
    retry,
    queryFn: async ({ signal }) => readPaperAccounts((await http({ path: "/api/v1/paper/accounts", signal, noRetry: true, timeoutMs: 20_000 })).data),
  });
}

// ── the overview (GET /api/v1/paper/overview, §7) ────────────────────────

export type FeedState = "live" | "stale" | "down" | "closed";
export interface PaperStatus {
  feedState: FeedState | null;
  lastTickAgeS: number | null;
  session: "open" | "closed" | null;
  killSwitch: { state: string | null; entriesBlocked: boolean | null; text: string | null; reason: string | null };
  policyVersion: string | null;
  mode: string | null;
}
export interface PaperKpis {
  equityRs: number | null; startEquityRs: number | null; dayPnlRs: number | null; dayLossLimitPct: number | null; dayLossUsedPct: number | null;
  deployedRs: number | null; deployedPct: number | null; cashRs: number | null; openRiskPct: number | null; openRiskLimitPct: number | null;
  drawdownPct: number | null; drawdownWarnPct: number | null; positionsOpen: number | null; positionsMax: number | null; ordersPending: number | null;
}
export const PIPELINE_STAGES = ["signals", "opportunities", "qualified", "risk_approved", "orders_filled", "open_positions"] as const;
export type PipelineStageKey = (typeof PIPELINE_STAGES)[number];
export interface PipelineStage { stage: string; label: string | null; count: number | null }
export interface PaperWarning { level: "danger" | "amber" | "mint"; title: string; code: string | null; at: string | null; symbol: string | null }
export interface PaperHeadline {
  setupsCleared: number | null;
  worstConcentration: { name: string; pctOfOpenRisk: number | null } | null;
  signals: number | null; opportunities: number | null; blocked: number | null; reduced: number | null;
}
export interface PaperOverview {
  accountId: string | null; asOf: string | null; status: PaperStatus | null; kpis: PaperKpis | null; pipeline: PipelineStage[];
  warnings: PaperWarning[]; headline: PaperHeadline | null;
}

const FEEDS: readonly string[] = ["live", "stale", "down", "closed"];
const LEVELS: readonly string[] = ["danger", "amber", "mint"];
/** "7" → "7", 7 → "7", "spt-config-v2" → "spt-config-v2"; null when absent. */
const version = (v: unknown): string | null => (typeof v === "number" && Number.isFinite(v) ? String(v) : str(v));

export function readOverview(body: unknown): PaperOverview {
  const d = rec(body);
  if (!isObj(d.status) && !isObj(d.kpis)) throw ApiError.contractDrift("paper.overview: no status or kpis");
  const s = isObj(d.status) ? d.status : null;
  const k = isObj(d.kpis) ? d.kpis : null;
  const h = isObj(d.headline) ? d.headline : null;
  const ks = rec(s?.kill_switch);
  const wc = h && isObj(h.worst_concentration) ? h.worst_concentration : null;
  return {
    accountId: str(d.account_id), asOf: str(d.as_of),
    status: s ? {
      feedState: FEEDS.includes(String(s.feed_state)) ? (s.feed_state as FeedState) : null, lastTickAgeS: num(s.last_tick_age_s),
      session: s.session === "open" || s.session === "closed" ? s.session : null,
      killSwitch: { state: str(ks.state), entriesBlocked: bool(ks.entries_blocked), text: str(ks.text), reason: str(ks.reason) },
      policyVersion: version(s.policy_version), mode: str(s.mode),
    } : null,
    kpis: k ? {
      equityRs: num(k.equity_rs), startEquityRs: num(k.start_equity_rs), dayPnlRs: num(k.day_pnl_rs), dayLossLimitPct: num(k.day_loss_limit_pct),
      dayLossUsedPct: num(k.day_loss_used_pct), deployedRs: num(k.deployed_rs), deployedPct: num(k.deployed_pct), cashRs: num(k.cash_rs),
      openRiskPct: num(k.open_risk_pct), openRiskLimitPct: num(k.open_risk_limit_pct), drawdownPct: num(k.drawdown_pct), drawdownWarnPct: num(k.drawdown_warn_pct),
      positionsOpen: num(k.positions_open), positionsMax: num(k.positions_max), ordersPending: num(k.orders_pending),
    } : null,
    pipeline: arr(d.pipeline).map((x) => { const r = rec(x); return { stage: str(r.stage) ?? "", label: str(r.label), count: num(r.count) }; }).filter((x) => x.stage),
    warnings: arr(d.warnings).map((x) => {
      const r = rec(x);
      const title = str(r.title);
      if (!title) return null;
      return { level: (LEVELS.includes(String(r.level)) ? r.level : "amber") as PaperWarning["level"], title, code: str(r.code), at: str(r.at), symbol: str(r.symbol) };
    }).filter((x): x is PaperWarning => x != null),
    headline: h ? {
      setupsCleared: num(h.setups_cleared), worstConcentration: wc && str(wc.name) ? { name: str(wc.name) as string, pctOfOpenRisk: num(wc.pct_of_open_risk) } : null,
      signals: num(h.signals), opportunities: num(h.opportunities), blocked: num(h.blocked), reduced: num(h.reduced),
    } : null,
  };
}

/** GET /api/v1/paper/overview — the shell's status strip and 01 Overview share this one read (every 10 s). */
export function usePaperOverview() {
  const profile = useProfile();
  return useQuery<PaperOverview>({
    queryKey: [...SPT_KEY, "pv2-overview", profile],
    staleTime: 5_000,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
    retry,
    queryFn: async ({ signal }) => readOverview((await http({ path: "/api/v1/paper/overview", signal, noRetry: true, timeoutMs: 20_000 })).data),
  });
}

// ── opportunities + proposals, joined (02 Scanner opportunities) ─────────

export interface RiskCheck { check: string; status: string; detail: string | null; message: string | null; source: string | null }
export interface PaperOpp { o: SptOpportunity; instrument: string | null; exchange: string | null }
export interface PaperProposal { p: SptProposal; instrument: string | null; checks: RiskCheck[]; requestedQty: number | null }

export const OPP_LIMIT = 500;
export const PROPOSAL_LIMIT = 200;

/** GET /api/v1/opportunities (all states; the view leaves expired ones out); every 30 s. */
export function usePaperOpportunities() {
  const profile = useProfile();
  return useQuery<PaperOpp[]>({
    queryKey: [...SPT_KEY, "pv2-opps", profile],
    staleTime: 10_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    retry,
    queryFn: async ({ signal }) => {
      const b = rec((await http({ path: "/api/v1/opportunities", query: { limit: OPP_LIMIT }, signal, noRetry: true, timeoutMs: 30_000 })).data);
      if (!Array.isArray(b.opportunities)) throw ApiError.contractDrift("spt.opportunities: no opportunities list");
      return b.opportunities.map((x) => {
        const o = readOpportunity(x);
        if (!o) return null;
        const r = rec(x);
        return { o, instrument: str(r.instrument) ?? str(r.segment), exchange: str(r.exchange) };
      }).filter((x): x is PaperOpp => !!x);
    },
  });
}

export function readChecks(risk: unknown): RiskCheck[] {
  const r = rec(risk);
  const reasons = arr(r.reasons).map(rec);
  return arr(r.checks).map((x) => {
    const c = rec(x);
    const check = str(c.check) ?? str(c.name) ?? str(c.code);
    if (!check) return null;
    const why = reasons.find((y) => str(y.check) === check);
    return { check, status: str(c.status) ?? "unknown", detail: str(c.detail) ?? str(c.value), message: str(c.message) ?? (why ? str(why.message) : null), source: str(c.source) };
  }).filter((x): x is RiskCheck => x != null);
}

/** GET /api/v1/proposals — the caller's proposals with the risk record's checks; every 30 s. */
export function usePaperProposals() {
  const profile = useProfile();
  return useQuery<PaperProposal[]>({
    queryKey: [...SPT_KEY, "pv2-proposals", profile],
    staleTime: 10_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    retry,
    queryFn: async ({ signal }) => {
      const b = rec((await http({ path: "/api/v1/proposals", query: { limit: PROPOSAL_LIMIT }, signal, noRetry: true, timeoutMs: 30_000 })).data);
      if (!Array.isArray(b.items)) throw ApiError.contractDrift("spt.proposals: no items list");
      return b.items.map((x) => {
        const p = readProposal(x);
        if (!p) return null;
        const r = rec(x);
        const risk = rec(r.risk);
        return { p, instrument: str(r.instrument), checks: readChecks(risk), requestedQty: num(risk.requested_qty) ?? num(rec(r.allocation).requested_qty) };
      }).filter((x): x is PaperProposal => !!x);
    },
  });
}

export const AWAITING = "AWAITING_USER_APPROVAL";

/** The 02 chip's badge: the caller's proposals awaiting approval, counted from the items (state checked here, not trusted). */
export function useAwaitingCount() {
  const profile = useProfile();
  return useQuery<{ count: number; capped: boolean }>({
    queryKey: [...SPT_KEY, "pv2-awaiting", profile],
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    retry,
    queryFn: async ({ signal }) => {
      const b = rec((await http({ path: "/api/v1/proposals", query: { state: AWAITING, limit: PROPOSAL_LIMIT }, signal, noRetry: true, timeoutMs: 20_000 })).data);
      if (!Array.isArray(b.items)) throw ApiError.contractDrift("spt.proposals: no items list");
      const count = b.items.filter((x) => rec(x).state === AWAITING).length;
      return { count, capped: b.items.length >= PROPOSAL_LIMIT };
    },
  });
}

// ── account analytics (GET /api/v1/analytics/account/{id}?days=90, §7) ───

export interface SetupRow { setup: string; trades: number | null; expectancyR: number | null; profitFactor: number | null; winRatePct: number | null }
export interface RegimeRow { regime: string; trades: number | null; expectancyR: number | null }
export interface Criterion { key: string; label: string; status: "pass" | "warn" | "fail" | "not_measured"; value: string | null }
export interface Certification { setup: string; criteria: Criterion[]; certified: boolean | null }
export interface AccountAnalytics {
  days: number | null; trades: number | null; wins: number | null; losses: number | null; winRatePct: number | null; avgWinR: number | null; avgLossR: number | null;
  expectancyR: number | null; profitFactor: number | null; profitFactorReason: string | null; maxDrawdownPct: number | null; sharpe: number | null; sortino: number | null; ratioReason: string | null;
  bySetup: SetupRow[]; byRegime: RegimeRow[]; certification: Certification[]; basis: string | null; notes: string[];
}

const STATUSES: readonly string[] = ["pass", "warn", "fail", "not_measured"];
const valueText = (v: unknown): string | null => (v == null ? null : typeof v === "number" ? (Number.isFinite(v) ? String(v) : null) : typeof v === "boolean" ? (v ? "yes" : "no") : str(v));

export function readAccountAnalytics(body: unknown): AccountAnalytics {
  const d = rec(body);
  if (!("trades" in d) && !Array.isArray(d.by_setup)) throw ApiError.contractDrift("analytics.account: no trades");
  return {
    days: num(d.days), trades: num(d.trades), wins: num(d.wins), losses: num(d.losses), winRatePct: num(d.win_rate_pct), avgWinR: num(d.avg_win_r),
    avgLossR: num(d.avg_loss_r), expectancyR: num(d.expectancy_r), profitFactor: num(d.profit_factor), profitFactorReason: str(d.profit_factor_reason),
    maxDrawdownPct: num(d.max_drawdown_pct),
    sharpe: num(d.sharpe), sortino: num(d.sortino), ratioReason: str(d.ratio_reason),
    bySetup: arr(d.by_setup).map((x) => {
      const r = rec(x);
      return { setup: str(r.setup) ?? "—", trades: num(r.trades), expectancyR: num(r.expectancy_r), profitFactor: num(r.profit_factor), winRatePct: num(r.win_rate_pct) };
    }),
    byRegime: arr(d.by_regime).map((x) => { const r = rec(x); return { regime: str(r.regime) ?? "unknown", trades: num(r.trades), expectancyR: num(r.expectancy_r) }; }),
    certification: arr(d.certification).map((x) => {
      const r = rec(x);
      return {
        setup: str(r.setup) ?? "—", certified: bool(r.certified),
        criteria: arr(r.criteria).map((y) => {
          const c = rec(y);
          const st = String(c.status);
          return { key: str(c.key) ?? str(c.label) ?? "—", label: str(c.label) ?? str(c.key) ?? "—", status: (STATUSES.includes(st) ? st : "warn") as Criterion["status"], value: valueText(c.value) };
        }),
      };
    }),
    basis: str(d.basis), notes: arr(d.notes).map(str).filter((x): x is string => !!x),
  };
}

export function useAccountAnalytics(accountId: string | null, days = 90) {
  const profile = useProfile();
  return useQuery<AccountAnalytics>({
    queryKey: [...SPT_KEY, "pv2-analytics", profile, accountId ?? "", days],
    enabled: !!accountId,
    staleTime: 60_000,
    retry,
    queryFn: async ({ signal }) =>
      readAccountAnalytics((await http({ path: `/api/v1/analytics/account/${encodeURIComponent(accountId as string)}`, query: { days }, signal, noRetry: true, timeoutMs: 60_000 })).data),
  });
}

/** The ISO date `days` before today in IST (the scanner analytics' `from=`). */
export function daysAgoIst(days: number, now = new Date()): string {
  const ist = new Date(now.getTime() + 5.5 * 3600_000 - days * 86_400_000);
  return ist.toISOString().slice(0, 10);
}
