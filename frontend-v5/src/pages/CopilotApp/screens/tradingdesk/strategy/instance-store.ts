/**
 * Strategy instances: Save version, Clone and the lists, for Strategy Lab › Build a trade (the wizard's step 4).
 *
 * ONE STORE (owner, 28 Oct, "One store"): a saved structure is a Strategy Builder strategy in its Postgres tables
 * (strategies, strategy_versions, strategy_runs, strategy_trades, strategy_audit), with one version history; each
 * backtest run points at an immutable version. The routes are backend/routes/strategy_builder.py (PR #398, the shared
 * strategy store v2; docs/API_DOCUMENTATION.md "Strategy store v2"); the document is validated by
 * backend/services/strategy_store.py. The body definitionOf builds is pinned in
 * frontend-v5/e2e/fixtures/contract-strategy-store-v2.json, which the backend's tests read too.
 *
 *   createStrategy   POST /strategies + Idempotency-Key → 201 { strategy_id, version_id, version_no: 1, checks }; a
 *                    replayed key answers the first create (200 replayed)
 *   saveVersion      POST /strategies/{id}/versions + Idempotency-Key, { definition, parent_version_id, change_summary }
 *                    → 201 { version_id, version_no, diff, checks }; 409 stale_parent when another save came first
 *   cloneStrategy    POST /strategies/{id}/clone { name?, version_id? } → 201 a strategy you own, version 1
 *   listStrategies   GET /strategies?include=summary → rows with source, latest_version, last_backtest, paper_live
 *   getStrategy      GET /strategies/{id} → the active version's definition, for Open on a saved structure
 *   listVersions     GET /strategies/{id}/versions → newest first
 *
 * Every call answers `{ ok: true, value }` or `{ ok: false, code, reason }`, never throws. `not_available` (NOT_YET) is
 * a server whose store is not upgraded yet: 503 store_not_migrated, or an older backend that has no such route or cannot
 * take a legs document; the wizard says so next to the buttons and keeps the legs on the page.
 *
 * `checks` are the store's own answer on what a saved structure can be used for (derived, never stored): a naked short
 * option is saved as a draft marked blocking for backtest and paper (owner decision D2).
 *
 * Status words (derived, never stored): PAPER LIVE, BACKTEST FAILED, BACKTESTED, STALE, DRAFT. "BACKTEST PASSED" needs a
 * pass rule the owner has not set (open question Q3): never shown.
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { isIndexUnderlying } from "../../trading/fno";
import type { BuildConfig, WLeg } from "../tabs/trade-desk/lab/wizard-data";

export const NOT_YET = "Saving is not available on this server yet: its strategy store is not upgraded. Your legs stay on this page.";

/** Save version and Clone are offered; a server that cannot store legs yet answers `not_available` (NOT_YET). */
export const STORE_AVAILABLE = true;

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

// ── the calls ────────────────────────────────────────────────────────────

export type StoreCode = "not_available" | "stale_parent" | "invalid" | "limit" | "conflict" | "not_found" | "error";
export type StoreFailure = {
  ok: false; reason: string; code: StoreCode;
  /** stale_parent: the version that was saved after the one the wizard loaded. */
  activeVersionId?: string | null; activeVersionNo?: number | null;
  /** invalid: each problem next to its field (`definition.legs[0].lots`). */
  problems?: Array<{ field: string; code: string; message: string }>;
};
export type StoreAnswer<T> = { ok: true; value: T } | StoreFailure;
export interface StoreCheck { code: string; severity: "blocking" | "warning" | "info"; blockingFor: string[]; message: string }
export interface Created { strategyId: string; versionId: string; versionNo: number; checks: StoreCheck[]; replayed: boolean }
export interface SavedVersion { versionId: string; versionNo: number; diff: Array<{ path: string; before: unknown; after: unknown }>; checks: StoreCheck[]; replayed: boolean }
export interface StoreRow {
  strategyId: string;
  name: string;
  source: "user" | "ai" | "template" | "clone" | "plan";
  templateId: string | null;
  underlying: string | null;
  assetClass: string;
  schemaVersion: string | null;
  latestVersion: { id: string; versionNo: number; createdAt: string | null } | null;
  lastBacktest: { runId: string; status: "OK" | "FAILED"; finishedAt: string | null; versionNo: number | null; isCurrentVersion: boolean } | null;
  /** null when the desk's paper trades could not be read (the route says so). */
  paperLive: { open: number | null };
}
export interface VersionRow { versionId: string; versionNo: number; createdAt: string | null; changeSummary: string | null; parentVersionId: string | null; schemaVersion: string | null }
export interface StoredStrategy { strategyId: string; name: string; templateId: string | null; underlying: string | null; versionId: string; versionNo: number; definition: V2Definition | null; checks: StoreCheck[] }

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);
const int = (v: unknown): number | null => (typeof v === "number" && Number.isInteger(v) ? v : null);
const BASE = "/api/strategy-builder/strategies";
const IDEMPOTENCY_HEADER = "Idempotency-Key";
const FAILED_NOW = "The strategy store did not answer just now; nothing was saved. Try again.";

function readChecks(v: unknown): StoreCheck[] {
  return (Array.isArray(v) ? v : []).flatMap((x): StoreCheck[] => {
    const c = rec(x);
    const sev = c.severity === "blocking" || c.severity === "warning" || c.severity === "info" ? c.severity : null;
    const code = str(c.code);
    return code && sev ? [{ code, severity: sev, blockingFor: (Array.isArray(c.blocking_for) ? c.blocking_for : []).filter((b): b is string => typeof b === "string"), message: str(c.message) ?? code }] : [];
  });
}

/** What a refusal means for the wizard. An older server (no route, or its v1 body check) is `not_available`. */
export function failureOf(e: unknown): StoreFailure {
  if (!(e instanceof ApiError) || e.status == null) return { ok: false, code: "error", reason: FAILED_NOW };
  const detail = rec(e.body).detail;
  const d = rec(detail);
  const code = str(d.code);
  const message = str(d.message) ?? (typeof detail === "string" ? detail : null) ?? FAILED_NOW;
  if (code === "store_not_migrated") return { ok: false, code: "not_available", reason: NOT_YET };
  if (e.status === 404 && detail === "Not Found") return { ok: false, code: "not_available", reason: NOT_YET };
  if (e.status === 422 && Array.isArray(detail)) return { ok: false, code: "not_available", reason: NOT_YET };
  if (code === "stale_parent") return { ok: false, code: "stale_parent", reason: message, activeVersionId: str(d.active_version_id), activeVersionNo: int(d.active_version_no) };
  if (code === "strategy_limit" || code === "version_limit") return { ok: false, code: "limit", reason: message };
  if (code === "idempotency_conflict") return { ok: false, code: "conflict", reason: message };
  if (e.status === 404) return { ok: false, code: "not_found", reason: "That strategy is not in your store (it may have been archived)." };
  if (e.status === 422) {
    const problems = (Array.isArray(d.problems) ? d.problems : []).flatMap((x) => {
      const p = rec(x);
      return str(p.field) && str(p.message) ? [{ field: str(p.field) as string, code: str(p.code) ?? "invalid", message: str(p.message) as string }] : [];
    });
    return { ok: false, code: "invalid", reason: message, problems };
  }
  return { ok: false, code: "error", reason: FAILED_NOW };
}

async function call<T>(read: (d: Raw) => T, req: Parameters<typeof http>[0]): Promise<StoreAnswer<T>> {
  try {
    const res = await http({ ...req, noRetry: true, timeoutMs: 20_000 });
    return { ok: true, value: read(rec(res.data)) };
  } catch (e) {
    return failureOf(e);
  }
}

/** The asset class the store derives from the legs (backend strategy_store.asset_class_of); sent so the body states it. */
export function assetClassOf(def: Pick<V2Definition, "legs">): "STOCK" | "FNO" | "MIXED" {
  const kinds = new Set(def.legs.map((l) => l.instrument));
  if (kinds.size === 1 && kinds.has("STOCK")) return "STOCK";
  return kinds.has("STOCK") ? "MIXED" : "FNO";
}

/** JSON with object keys sorted at every level: Postgres JSONB hands a stored document back in its own key order. */
export function canonicalJson(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonicalJson).join(",")}]`;
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    return `{${Object.keys(o).sort().map((k) => `${JSON.stringify(k)}:${canonicalJson(o[k])}`).join(",")}}`;
  }
  return JSON.stringify(v ?? null);
}

/** A comparison key for "unsaved changes": the document, in any key order, without the chain date it was laid out on. */
export function contentKey(def: V2Definition | null): string {
  if (!def) return "";
  return canonicalJson({ ...def, build_constraints: { ...def.build_constraints, chain_as_of: null } });
}

/** POST /api/strategy-builder/strategies (v2 definition, Idempotency-Key). */
export async function createStrategy(b: { source: "user" | "ai" | "template"; definition: V2Definition }, idempotencyKey: string): Promise<StoreAnswer<Created>> {
  const body = { name: b.definition.name, asset_class: assetClassOf(b.definition), source: b.source, template_id: b.definition.template_id, definition: b.definition };
  return call((d) => ({ strategyId: str(d.strategy_id) ?? "", versionId: str(d.version_id) ?? "", versionNo: int(d.version_no) ?? 1, checks: readChecks(d.checks), replayed: d.replayed === true }),
    { method: "POST", path: BASE, body, headers: { [IDEMPOTENCY_HEADER]: idempotencyKey } });
}

/** POST /api/strategy-builder/strategies/{id}/versions with the parent_version_id the wizard loaded (409 stale_parent). */
export async function saveVersion(strategyId: string, b: { definition: V2Definition; parentVersionId: string; changeSummary: string | null }, idempotencyKey: string): Promise<StoreAnswer<SavedVersion>> {
  const body = { definition: b.definition, parent_version_id: b.parentVersionId, ...(b.changeSummary ? { change_summary: b.changeSummary } : {}) };
  return call((d) => ({
    versionId: str(d.version_id) ?? "", versionNo: int(d.version_no) ?? 0, checks: readChecks(d.checks), replayed: d.replayed === true,
    diff: (Array.isArray(d.diff) ? d.diff : []).map((x) => { const r = rec(x); return { path: str(r.path) ?? "", before: r.before ?? null, after: r.after ?? null }; }),
  }), { method: "POST", path: `${BASE}/${encodeURIComponent(strategyId)}/versions`, body, headers: { [IDEMPOTENCY_HEADER]: idempotencyKey } });
}

/** POST /api/strategy-builder/strategies/{id}/clone. */
export async function cloneStrategy(strategyId: string, b: { name?: string; versionId?: string } = {}): Promise<StoreAnswer<Created>> {
  const body = { ...(b.name ? { name: b.name } : {}), ...(b.versionId ? { version_id: b.versionId } : {}) };
  return call((d) => ({ strategyId: str(d.strategy_id) ?? "", versionId: str(d.version_id) ?? "", versionNo: int(d.version_no) ?? 1, checks: readChecks(d.checks), replayed: false }),
    { method: "POST", path: `${BASE}/${encodeURIComponent(strategyId)}/clone`, body });
}

const SOURCES = new Set(["user", "ai", "template", "clone", "plan"]);

/** GET /api/strategy-builder/strategies?include=summary. */
export async function listStrategies(): Promise<StoreAnswer<StoreRow[]>> {
  return call((d) => (Array.isArray(d.strategies) ? d.strategies : []).flatMap((x): StoreRow[] => {
    const r = rec(x);
    const id = str(r.id);
    if (!id) return [];
    const lv = rec(r.latest_version);
    const lb = rec(r.last_backtest);
    const status = lb.status === "OK" || lb.status === "FAILED" ? lb.status : null;
    const source = str(r.source) ?? "user";
    return [{
      strategyId: id, name: str(r.name) ?? "Untitled", source: (SOURCES.has(source) ? source : "user") as StoreRow["source"],
      templateId: str(r.template_id), underlying: str(r.underlying), assetClass: str(r.asset_class) ?? "", schemaVersion: str(r.schema_version),
      latestVersion: str(lv.id) ? { id: str(lv.id) as string, versionNo: int(lv.version_no) ?? 0, createdAt: str(lv.created_at) } : null,
      lastBacktest: str(lb.run_id) && status ? { runId: str(lb.run_id) as string, status, finishedAt: str(lb.finished_at), versionNo: int(lb.version_no), isCurrentVersion: lb.is_current_version === true } : null,
      paperLive: { open: typeof rec(r.paper_live).open === "number" ? (rec(r.paper_live).open as number) : null },
    }];
  }), { path: BASE, query: { include: "summary" } });
}

/** GET /api/strategy-builder/strategies/{id}: the active version, for Open on a saved structure. */
export async function getStrategy(strategyId: string): Promise<StoreAnswer<StoredStrategy>> {
  return call((d) => {
    const v = rec(d.active_version);
    const def = rec(v.definition);
    return {
      strategyId: str(d.id) ?? strategyId, name: str(d.name) ?? "Untitled", templateId: str(d.template_id), underlying: str(d.underlying),
      versionId: str(v.id) ?? "", versionNo: int(v.version_no) ?? 0,
      definition: def.schema_version === "2" ? (def as unknown as V2Definition) : null, checks: readChecks(d.checks),
    };
  }, { path: `${BASE}/${encodeURIComponent(strategyId)}` });
}

/** GET /api/strategy-builder/strategies/{id}/versions, newest first. */
export async function listVersions(strategyId: string): Promise<StoreAnswer<VersionRow[]>> {
  return call((d) => (Array.isArray(d.versions) ? d.versions : []).map((x) => {
    const r = rec(x);
    return { versionId: str(r.version_id) ?? "", versionNo: int(r.version_no) ?? 0, createdAt: str(r.created_at), changeSummary: str(r.change_summary), parentVersionId: str(r.parent_version_id), schemaVersion: str(r.schema_version) };
  }), { path: `${BASE}/${encodeURIComponent(strategyId)}/versions` });
}

/** A stored v2 document's legs as the wizard's legs (concrete legs only; a rule-based strike or expiry loads empty).
 *  `newId` is the wizard's leg id maker (wizard-data legId), passed in so this module does not import the wizard. */
export function legsOf(def: V2Definition, newId: () => string): WLeg[] {
  return def.legs.map((l): WLeg => ({
    id: newId(),
    kind: l.instrument === "STOCK" ? "cash" : l.instrument === "FUTURE" ? "future" : "option",
    side: l.side === "SELL" ? "sell" : "buy",
    optionType: l.instrument === "CALL" ? "call" : l.instrument === "PUT" ? "put" : null,
    strike: l.strike && l.strike.rule === "fixed" ? l.strike.value : null,
    expiry: l.expiry && l.expiry.rule === "specific" ? l.expiry.date : null,
    lots: (l.instrument === "STOCK" ? l.shares : l.lots) ?? 1,
    price: l.entry_price_at_save?.value ?? null,
    priceSource: l.entry_price_at_save?.source || null,
  }));
}

/** Whether an underlying is an index, for the document's underlying.kind (trading/fno INDEX_UNDERLYINGS). */
export const isIndex = (symbol: string) => isIndexUnderlying(symbol);

/**
 * The status word for a stored strategy (in this order): PAPER LIVE when an open desk paper trade cites a version,
 * BACKTEST FAILED when the latest run failed, BACKTESTED when the latest OK run is on the current version, STALE when it
 * is on an older one, DRAFT with no run. Never "BACKTEST PASSED" (no pass rule yet).
 */
export function storeStatus(r: Pick<StoreRow, "paperLive" | "lastBacktest">): "PAPER LIVE" | "BACKTEST FAILED" | "BACKTESTED" | "STALE" | "DRAFT" {
  if ((r.paperLive.open ?? 0) > 0) return "PAPER LIVE";
  if (!r.lastBacktest) return "DRAFT";
  if (r.lastBacktest.status === "FAILED") return "BACKTEST FAILED";
  return r.lastBacktest.isCurrentVersion ? "BACKTESTED" : "STALE";
}
