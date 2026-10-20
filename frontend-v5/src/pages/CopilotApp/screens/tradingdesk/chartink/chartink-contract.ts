/**
 * Chartink scans as opportunity sources - the routes' contract (signed in, user-scoped).
 *
 *   GET/PUT/DELETE /api/desk/chartink/source      the saved dashboard and its scans (never the scan clauses)
 *   PATCH /api/desk/chartink/scans/{id}           enabled / direction
 *   POST  /api/desk/chartink/refresh              runs the enabled scans (10-minute cooldown, 429 + retry_after_s)
 *   GET   /api/desk/chartink/hits                 the latest hits, merged by symbol, with the AI scanner join
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
  last_hits: numOrNull.optional(),
  last_ok: z.boolean().nullable().catch(null).optional(),
  last_error: strOrNull.optional(),
  last_fetched_at: strOrNull.optional(),
}).passthrough();
export type ChartinkScan = z.infer<typeof ScanSchema>;

export const SourceDocSchema = z.object({
  dashboard_id: z.union([z.string(), z.number()]).transform(String),
  url: z.string(),
  title: strOrNull,
  fetched_at: strOrNull,
  scans: z.array(ScanSchema),
}).passthrough();
export type ChartinkSourceDoc = z.infer<typeof SourceDocSchema>;

/** GET /source: the saved document, or `{source: null}` when nothing is connected. */
export const SourceSchema = z.union([
  z.object({ source: z.null() }).passthrough().transform(() => null),
  SourceDocSchema,
]);
export type ChartinkSource = ChartinkSourceDoc | null;

export const RefreshSchema = z.object({
  scans: z.array(z.object({
    id: z.union([z.string(), z.number()]).transform(String),
    name: z.string(),
    ok: z.boolean().catch(false),
    hits: numOrNull,
    error: strOrNull,
    seconds: numOrNull,
  }).passthrough()),
  fetched_at: strOrNull,
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
  in_ai_scanner: z.boolean().catch(false),
  ai_score: numOrNull,
  fno_eligible: z.boolean().nullable().catch(null),
}).passthrough();
export type ChartinkHitSymbol = z.infer<typeof HitSymbolSchema>;

export const HitsSchema = z.object({
  as_of_date: strOrNull,
  fetched_at: strOrNull,
  mode: strOrNull,
  scans: z.array(z.object({
    id: z.union([z.string(), z.number()]).transform(String),
    name: z.string(),
    direction: Direction,
    hits: numOrNull,
    ok: z.boolean().catch(false),
    error: strOrNull,
    uses_intraday_candles: z.boolean().catch(false),
  }).passthrough()),
  symbols: z.array(HitSymbolSchema),
  unknown_symbols: z.array(z.object({ symbol: z.string(), suggestions: z.array(z.object({ symbol: z.string(), name: strOrNull }).passthrough()).catch([]) }).passthrough()).catch([]),
  source_failures: z.array(z.unknown()).catch([]),
}).passthrough();
export type ChartinkHits = z.infer<typeof HitsSchema>;
