/**
 * Chartink scans as opportunity sources - the routes' contract (signed in, user-scoped).
 *
 *   GET/PUT /api/desk/chartink/source             {source: {...}} the saved dashboard and its scans (`{source: null}` when none; never the clauses)
 *   DELETE  /api/desk/chartink/source             {deleted, hits_deleted}
 *   PATCH   /api/desk/chartink/scans/{id}         {scan: {...}} (enabled / direction)
 *   POST    /api/desk/chartink/refresh            runs the enabled scans (10-minute cooldown: 429, code refresh_cooldown, retry_after_s)
 *   GET     /api/desk/chartink/hits               the latest stored hits, merged by symbol, with the AI scanner join and a staleness note
 *
 * The zod schemas are what the screen trusts. The lists the screen cannot work without (`scans`, `symbols`) are
 * required: a body without them is a contract error, never an empty result. Extra fields pass through. A figure
 * the route does not send is null and shown as "-"; nothing here is recomputed.
 */
import { z } from "zod";

const numOrNull = z.number().nullable().catch(null);
const strOrNull = z.string().nullable().catch(null);

export const DIRECTIONS = ["bullish", "bearish", "neutral"] as const;
export type ScanDirection = (typeof DIRECTIONS)[number];
const Direction = z.enum(DIRECTIONS).catch("neutral");

const LastRun = z.object({ at: strOrNull, ok: z.boolean().nullable().catch(null), hits: numOrNull, error: strOrNull, seconds: numOrNull }).passthrough();
export type ScanLastRun = z.infer<typeof LastRun>;

export const ScanSchema = z.object({
  id: z.union([z.string(), z.number()]).transform(String),
  name: z.string(),
  description: strOrNull,
  kind: z.string().catch("stock_scan"),
  supported: z.boolean().catch(false),
  unsupported_reason: strOrNull,
  uses_intraday_candles: z.boolean().catch(false),
  enabled: z.boolean().catch(false),
  direction: Direction,
  last_run: LastRun.nullable().catch(null),
}).passthrough();
export type ChartinkScan = z.infer<typeof ScanSchema>;

export const SourceDocSchema = z.object({
  dashboard_id: z.union([z.string(), z.number()]).transform(String),
  url: z.string(),
  title: strOrNull,
  fetched_at: strOrNull,
  scans: z.array(ScanSchema),
  summary: z.object({ scans: z.number().catch(0), stock_scans: z.number().catch(0), supported: z.number().catch(0), enabled: z.number().catch(0) }).passthrough()
    .catch({ scans: 0, stock_scans: 0, supported: 0, enabled: 0 }),
  refresh: z.object({ last_started_at: strOrNull, retry_after_s: numOrNull }).passthrough().catch({ last_started_at: null, retry_after_s: null }),
}).passthrough();
export type ChartinkSourceDoc = z.infer<typeof SourceDocSchema>;

/** GET / PUT /source: `{source: <doc>}`, or `{source: null}` when nothing is connected. A body with no `source` key is a contract error. */
export const SourceSchema = z.object({ source: z.union([z.null(), SourceDocSchema]) }).passthrough().transform((x) => x.source);
export type ChartinkSource = ChartinkSourceDoc | null;

export const RefreshSchema = z.object({
  ran_at: strOrNull,
  scan_date: strOrNull,
  scans: z.array(z.object({
    id: z.union([z.string(), z.number()]).transform(String),
    name: z.string(),
    direction: Direction.optional(),
    ok: z.boolean().catch(false),
    hits: numOrNull,
    error: strOrNull,
    error_code: strOrNull.optional(),
    seconds: numOrNull,
  }).passthrough()),
  ok_count: numOrNull.optional(),
  failed_count: numOrNull.optional(),
  skipped_over_cap: z.unknown().optional(),
  uses_intraday_candles: z.unknown().optional(),
  /** A sentence when the refresh did not give usable hits (e.g. every scan failed; the AI scanner list is unaffected), else null. */
  degraded: strOrNull,
}).passthrough();
export type ChartinkRefresh = z.infer<typeof RefreshSchema>;

const HitScan = z.object({ id: z.union([z.string(), z.number()]).transform(String), name: z.string(), direction: Direction }).passthrough();
export type HitScanRef = z.infer<typeof HitScan>;

export const HitSymbolSchema = z.object({
  symbol: z.string(),
  name: strOrNull,
  scans: z.array(HitScan).catch([]),
  count: z.number().catch(0),
  close: numOrNull,
  pct_change: numOrNull,
  volume: numOrNull,
  /** null when the AI scanner could not be read (the reason is in `source_failures`): then nothing is claimed about the overlap. */
  in_ai_scanner: z.boolean().nullable().catch(null),
  ai_score: numOrNull,
  fno_eligible: z.boolean().nullable().catch(null),
}).passthrough();
export type ChartinkHitSymbol = z.infer<typeof HitSymbolSchema>;

export const UnknownSymbolSchema = z.object({
  symbol: z.string(),
  scans: z.array(HitScan).catch([]),
  count: z.number().catch(0),
  close: numOrNull,
  pct_change: numOrNull,
  suggestions: z.array(z.object({ symbol: z.string(), name: strOrNull }).passthrough()).catch([]),
  note: strOrNull,
}).passthrough();
export type ChartinkUnknownSymbol = z.infer<typeof UnknownSymbolSchema>;

export const HitsSchema = z.object({
  as_of_date: strOrNull,
  fetched_at: strOrNull,
  mode: strOrNull,
  is_today: z.boolean().nullable().catch(null),
  age_days: numOrNull,
  stale_note: strOrNull.optional().transform((v) => v ?? null),
  empty_reason: strOrNull.optional().transform((v) => v ?? null),
  scans: z.array(z.object({
    id: z.union([z.string(), z.number()]).transform(String),
    name: z.string(),
    direction: Direction,
    hits: numOrNull,
    ok: z.boolean().catch(false),
    error: strOrNull,
    uses_intraday_candles: z.boolean().catch(false),
    last_run_at: strOrNull.optional(),
  }).passthrough()),
  symbols: z.array(HitSymbolSchema),
  unknown_symbols: z.array(UnknownSymbolSchema).catch([]),
  source_failures: z.array(z.unknown()).catch([]),
}).passthrough();
export type ChartinkHits = z.infer<typeof HitsSchema>;

/** A source_failures entry as a sentence. */
export const failureText = (f: unknown): string => (typeof f === "string" ? f : f && typeof f === "object" && typeof (f as { message?: unknown }).message === "string" ? (f as { message: string }).message : JSON.stringify(f));
