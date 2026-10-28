/**
 * Strategy instances: Save version, Clone and the list, for Strategy Lab › Build a trade (the wizard's step 4).
 *
 * ONE STORE (owner, 28 Oct, "One store"): a saved structure is a Strategy Builder strategy in its Postgres tables
 * (strategies, strategy_versions, strategy_runs, strategy_trades, strategy_audit), with one version history; each
 * backtest run points at an immutable version. The schema and the save API belong to the strategy-builder session
 * (nivesh-ai-fc), which proposes `strategy_versions` v2. Today's routes cannot hold a legs config:
 * `strategies.asset_class` is CHECK IN ('STOCK','MF') (route pattern ^(STOCK|MF)$), and DSL v1 needs version "1" +
 * universe / entry / exit and DROPS unknown keys — legs must never be put into a v1 document. So every call below
 * answers `{ ok: false, reason: NOT_YET }` until v2 lands; wiring it is one change in this file.
 *
 * The proposed v2 interface this module is written against:
 *   POST /api/strategy-builder/strategies                  create (version 1)
 *   POST /api/strategy-builder/strategies/{id}/versions    an immutable version N+1, with an Idempotency-Key
 *   POST /api/strategy-builder/strategies/{id}/clone       a new strategy whose version 1 copies the source's latest
 *   GET  /api/strategy-builder/strategies                  list: source, latest version, last backtest status, paper_live
 *   version document: schema_version "2", underlying, legs 1–4 (kind / side / lots / lot_size / expiry or expiry_rule /
 *   strike or strike_rule / option_type), build constraints, entry assumption, source ai | user | template | clone,
 *   parent_version_id, change_summary.
 *
 * Validation rules to fold into the v2 validator (from the wizard's Mongo prototype, reverted, commit 960cf954):
 *   · 1 to 4 legs. A leg's fields are an allow-list: kind (option | future | cash), side (buy | sell), lots (whole,
 *     1–1000; shares for cash), lot_size (whole, 1–100000; 1 for cash), entry_price (> 0), expiry (YYYY-MM-DD, required
 *     for option and future, null for cash), strike (> 0, options only), option_type (call | put, options only),
 *     price_source (text ≤ 120). Any other field is refused (unknown_field), never dropped.
 *   · name ≤ 80, note / change_summary ≤ 300, the wizard's config object ≤ 4 KB of JSON, stored as sent.
 *   · template, when given, must be a name in GET /api/desk/strategy/templates.
 *   · At most 200 strategies per user (instance_limit) and 50 versions per strategy (version_limit); versions are
 *     immutable; two saves racing for the same N answer version_conflict.
 *   · Scoped to the owner: another user's id answers 404, the same as a missing one. Nothing is sent to a broker.
 */
import type { WLeg } from "../tabs/trade-desk/lab/wizard-data";

export const NOT_YET = "Saving arrives with the shared strategy store.";

export type StoreSource = "ai" | "user" | "template" | "clone";

export interface StoredLeg {
  kind: "option" | "future" | "cash";
  side: "buy" | "sell";
  lots: number;
  lot_size: number;
  entry_price: number | null;
  expiry: string | null;
  strike?: number | null;
  option_type?: "call" | "put" | null;
  price_source?: string;
}

/** The v2 version body the wizard would send. */
export interface VersionBody {
  schema_version: "2";
  underlying: string;
  legs: StoredLeg[];
  build_constraints: { max_loss_rs: number | null; max_capital_rs: number | null };
  entry_assumption: "market_slippage" | "limit_mid" | "next_open";
  source: StoreSource;
  template: string | null;
  parent_version_id: string | null;
  change_summary: string | null;
}

export interface StoredVersion { id: string; version: number; savedAt: string | null; body: VersionBody }
export interface StoredStrategy {
  id: string;
  name: string;
  source: StoreSource;
  latestVersion: number;
  lastBacktestStatus: "passed" | "failed" | "run" | null;
  paperLive: boolean;
  versions: StoredVersion[];
}

export type StoreAnswer<T> = { ok: true; value: T } | { ok: false; reason: string };

/** Whether saving works yet. The wizard disables Save version and Clone with `reason` while it does not. */
export const STORE_AVAILABLE = false;

export function versionBody(o: { underlying: string; legs: WLeg[]; lotSize: number | null; maxLossRs: number | null; maxCapitalRs: number | null;
  source: StoreSource; template: string | null; parentVersionId: string | null; changeSummary: string | null }): VersionBody {
  return {
    schema_version: "2", underlying: o.underlying, source: o.source, template: o.template, parent_version_id: o.parentVersionId,
    change_summary: o.changeSummary, entry_assumption: "market_slippage",
    build_constraints: { max_loss_rs: o.maxLossRs, max_capital_rs: o.maxCapitalRs },
    legs: o.legs.map((l) => ({
      kind: l.kind, side: l.side, lots: l.lots, lot_size: l.kind === "cash" ? 1 : o.lotSize ?? 1, entry_price: l.price, expiry: l.kind === "cash" ? null : l.expiry,
      ...(l.kind === "option" ? { strike: l.strike, option_type: l.optionType } : {}), price_source: (l.priceSource ?? "").slice(0, 120),
    })),
  };
}

/** Create a strategy with version 1. Not available yet: answers the reason. */
export async function createStrategy(_name: string, _body: VersionBody): Promise<StoreAnswer<StoredStrategy>> {
  return { ok: false, reason: NOT_YET };
}

/** Save an immutable version N+1 (with an Idempotency-Key once wired). Not available yet. */
export async function saveVersion(_strategyId: string, _body: VersionBody, _idempotencyKey: string): Promise<StoreAnswer<StoredStrategy>> {
  return { ok: false, reason: NOT_YET };
}

/** Clone a strategy: a new one whose version 1 copies the source's latest. Not available yet. */
export async function cloneStrategy(_strategyId: string): Promise<StoreAnswer<StoredStrategy>> {
  return { ok: false, reason: NOT_YET };
}

/** The user's stored structures (source, latest version, last backtest status, paper_live). Not available yet. */
export async function listStrategies(): Promise<StoreAnswer<StoredStrategy[]>> {
  return { ok: false, reason: NOT_YET };
}
