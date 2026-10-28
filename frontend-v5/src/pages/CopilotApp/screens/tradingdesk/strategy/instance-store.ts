/**
 * Strategy instances: Save version, Clone and the lists, for Strategy Lab › Build a trade (the wizard's step 4).
 *
 * ONE STORE (owner, 28 Oct, "One store"): a saved structure is a Strategy Builder strategy in its Postgres tables
 * (strategies, strategy_versions, strategy_runs, strategy_trades, strategy_audit), with one version history; each
 * backtest run points at an immutable version. The schema and the API belong to the strategy-builder session:
 * docs/strategy_copilot_review_20261028/PROPOSAL_strategy_store_v2.md (§3 the v2 document, §4 the API, §5 what the
 * wizard calls). Today's routes cannot hold legs (asset_class CHECK IN ('STOCK','MF'); DSL v1 drops unknown keys, and
 * legs must never be put into a v1 document), so every call below answers `{ ok: false, reason: NOT_YET }` and the
 * wizard keeps Save version and Clone disabled with that reason. Wiring them is a change to this file only.
 *
 * The calls, as §4 / §5 propose them (all under /api/strategy-builder):
 *   createStrategy   POST /strategies + Idempotency-Key, { name, asset_class FNO | MIXED, source user | ai, template_id,
 *                    definition (v2) } → 201 { strategy_id, version_id, version_no: 1 }; a replayed key answers the first
 *   saveVersion      POST /strategies/{id}/versions + Idempotency-Key, { definition, parent_version_id, change_summary }
 *                    → 201 { version_id, version_no, diff }; 409 stale_parent when parent_version_id is not the active one
 *   cloneStrategy    POST /strategies/{id}/clone, { name?, version_id? } → 201 { strategy_id, version_id, version_no: 1 }
 *   listStrategies   GET /strategies?include=summary → rows with source, template_id, underlying, asset_class,
 *                    latest_version, last_backtest { status, is_current_version }, paper_live { open }
 *   listVersions     GET /strategies/{id}/versions → newest first
 *
 * The wizard's state in the v2 document (definitionOf):
 *   WLeg            legs[]: concrete, as laid out (§3 note): instrument CALL | PUT | FUTURE | STOCK, side BUY | SELL,
 *                   lots (or { shares } for STOCK), lot_size_at_save, expiry { rule: "specific", date },
 *                   strike { rule: "fixed", value }, entry_price_at_save { value: the leg's price, source }
 *   BuildConfig     the strike rule that laid the legs out (rule, anchor, width, target delta) in build_constraints, and the
 *                   lots in sizing; a backtest derives rules from the concrete legs (§3, Phase 2)
 *   build limits    max loss, max capital and the underlying stop in build_constraints (build limits, not risk policy)
 *   entry           the entry assumption: { type: "manual", assumption: market + the desk cost card's slippage, at once }
 *
 * Starting a simulated trade: once a version is saved, POST /api/desk/paper-trades carries
 * `strategy_ref: { strategy_id, version_id }` (§4, the field PAPER LIVE is derived from). Until then the trade cites the
 * template it came from in signal.source_refs (kind strategy_template), and the wizard derives PAPER LIVE from the desk
 * paper trades (an open trade's strategy_plan_id) and the AI Trader's own paper stage.
 *
 * Status words (§4, derived, never stored): PAPER LIVE, BACKTEST FAILED, BACKTESTED, STALE, DRAFT, and SAVED where a
 * saved version has no run. "BACKTEST PASSED" needs a pass rule the owner has not set (open question Q3): never shown.
 *
 * Validation rules for the v2 validator, from the wizard's reverted Mongo prototype (commit 960cf954):
 *   · 1 to 4 legs; a leg's fields are an allow-list, any other field is refused (unknown_field), never dropped;
 *   · lots whole 1–1000 (shares for STOCK), lot size whole 1–100000, entry price > 0, an expiry for every CALL / PUT /
 *     FUTURE leg and none for STOCK, a strike > 0 for CALL / PUT only;
 *   · name ≤ 80, change_summary ≤ 300, build_constraints ≤ 4 KB of JSON stored as sent; template_id must be a name in
 *     GET /api/desk/strategy/templates;
 *   · at most 200 strategies per user and 50 versions per strategy; versions immutable; another user's id answers 404.
 */
import type { BuildConfig, WLeg } from "../tabs/trade-desk/lab/wizard-data";

export const NOT_YET = "Saving arrives with the shared strategy store.";

/** Whether saving works yet. The wizard disables Save version and Clone with NOT_YET while it does not. */
export const STORE_AVAILABLE = false;

// ── the v2 document (§3) ─────────────────────────────────────────────────

export interface V2Leg {
  leg_id: string;
  instrument: "STOCK" | "FUTURE" | "CALL" | "PUT";
  side: "BUY" | "SELL";
  lots?: number;
  shares?: number;
  lot_size_at_save: number;
  expiry: { rule: "specific"; date: string } | null;
  strike: { rule: "fixed"; value: number } | null;
  entry_price_at_save: { value: number; source: string } | null;
  relationship: null;
}

export interface V2Definition {
  schema_version: "2";
  name: string;
  market: "NSE";
  underlying: { symbol: string; kind: "index" | "stock" };
  template_id: string | null;
  timeframe: "1d";
  legs: V2Leg[];
  entry: { type: "manual"; assumption: string };
  exit: { profit_target_pct_of_net_debit: null; stop_loss_pct_of_net_debit: null; time_exit_sessions: null; close_before_expiry_sessions: null };
  build_constraints: {
    max_loss_rs: number | null;
    max_capital_rs: number | null;
    stop_underlying: number | null;
    strike_rule: { rule: BuildConfig["rule"]; anchor_strikes: number; width_strikes: number; target_delta: number };
    chain_as_of: string | null;
  };
  sizing: { lots: number };
}

export const ENTRY_ASSUMPTION = "at once at the chain's end-of-day close, plus the desk cost card's slippage (market + slippage)";

/** The wizard's legs and settings as a v2 definition (concrete legs, as laid out). */
export function definitionOf(o: {
  name: string; underlying: string; index: boolean; template: string | null; legs: WLeg[]; lotSize: number | null; cfg: BuildConfig;
  maxLossRs: number | null; maxCapitalRs: number | null; stopUnderlying: number | null; chainAsOf: string | null;
}): V2Definition {
  return {
    schema_version: "2", name: o.name, market: "NSE", underlying: { symbol: o.underlying, kind: o.index ? "index" : "stock" },
    template_id: o.template, timeframe: "1d",
    legs: o.legs.map((l, i): V2Leg => ({
      leg_id: `L${i + 1}`,
      instrument: l.kind === "cash" ? "STOCK" : l.kind === "future" ? "FUTURE" : l.optionType === "put" ? "PUT" : "CALL",
      side: l.side === "buy" ? "BUY" : "SELL",
      ...(l.kind === "cash" ? { shares: l.lots } : { lots: l.lots }),
      lot_size_at_save: l.kind === "cash" ? 1 : o.lotSize ?? 1,
      expiry: l.kind !== "cash" && l.expiry ? { rule: "specific", date: l.expiry } : null,
      strike: l.kind === "option" && l.strike != null ? { rule: "fixed", value: l.strike } : null,
      entry_price_at_save: l.price != null ? { value: l.price, source: (l.priceSource ?? "").slice(0, 120) } : null,
      relationship: null,
    })),
    entry: { type: "manual", assumption: ENTRY_ASSUMPTION },
    exit: { profit_target_pct_of_net_debit: null, stop_loss_pct_of_net_debit: null, time_exit_sessions: null, close_before_expiry_sessions: null },
    build_constraints: {
      max_loss_rs: o.maxLossRs, max_capital_rs: o.maxCapitalRs, stop_underlying: o.stopUnderlying,
      strike_rule: { rule: o.cfg.rule, anchor_strikes: o.cfg.anchor, width_strikes: o.cfg.width, target_delta: o.cfg.delta },
      chain_as_of: o.chainAsOf,
    },
    sizing: { lots: o.cfg.lots },
  };
}

// ── the calls (§4 / §5), not available yet ───────────────────────────────

export type StoreAnswer<T> = { ok: true; value: T } | { ok: false; reason: string; code: "not_available" | "stale_parent" };
export interface Created { strategyId: string; versionId: string; versionNo: number }
export interface SavedVersion { versionId: string; versionNo: number; diff: Array<{ path: string; before: unknown; after: unknown }> }
export interface StoreRow {
  strategyId: string;
  name: string;
  source: "user" | "ai" | "template" | "clone";
  templateId: string | null;
  underlying: string | null;
  assetClass: string;
  latestVersion: { id: string; versionNo: number; createdAt: string } | null;
  lastBacktest: { runId: string; status: "OK" | "FAILED"; finishedAt: string | null; versionNo: number; isCurrentVersion: boolean } | null;
  paperLive: { open: number };
}
export interface VersionRow { versionId: string; versionNo: number; createdAt: string; changeSummary: string | null; parentVersionId: string | null; schemaVersion: string }

const notYet = { ok: false as const, reason: NOT_YET, code: "not_available" as const };

/** POST /api/strategy-builder/strategies (v2 definition, Idempotency-Key). */
export async function createStrategy(_b: { name: string; assetClass: "FNO" | "MIXED"; source: "user" | "ai"; templateId: string | null; definition: V2Definition }, _idempotencyKey: string): Promise<StoreAnswer<Created>> {
  return notYet;
}

/** POST /api/strategy-builder/strategies/{id}/versions with the parent_version_id the wizard loaded (409 stale_parent). */
export async function saveVersion(_strategyId: string, _b: { definition: V2Definition; parentVersionId: string; changeSummary: string | null }, _idempotencyKey: string): Promise<StoreAnswer<SavedVersion>> {
  return notYet;
}

/** POST /api/strategy-builder/strategies/{id}/clone. */
export async function cloneStrategy(_strategyId: string, _b: { name?: string; versionId?: string } = {}): Promise<StoreAnswer<Created>> {
  return notYet;
}

/** GET /api/strategy-builder/strategies?include=summary. */
export async function listStrategies(_include: "summary" = "summary"): Promise<StoreAnswer<StoreRow[]>> {
  return notYet;
}

/** GET /api/strategy-builder/strategies/{id}/versions, newest first. */
export async function listVersions(_strategyId: string): Promise<StoreAnswer<VersionRow[]>> {
  return notYet;
}

/**
 * The status word for a stored strategy (§4, in this order): PAPER LIVE when an open desk paper trade cites a version,
 * BACKTEST FAILED when the latest run failed, BACKTESTED when the latest OK run is on the current version, STALE when it
 * is on an older one, DRAFT with no run. Never "BACKTEST PASSED" (no pass rule yet).
 */
export function storeStatus(r: Pick<StoreRow, "paperLive" | "lastBacktest">): "PAPER LIVE" | "BACKTEST FAILED" | "BACKTESTED" | "STALE" | "DRAFT" {
  if (r.paperLive.open > 0) return "PAPER LIVE";
  if (!r.lastBacktest) return "DRAFT";
  if (r.lastBacktest.status === "FAILED") return "BACKTEST FAILED";
  return r.lastBacktest.isCurrentVersion ? "BACKTESTED" : "STALE";
}
