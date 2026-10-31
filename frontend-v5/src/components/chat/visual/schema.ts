/**
 * The Copilot's visual answer — the `visual_answer` widget's payload (contract `visual-answer-v1`,
 * docs/daily_trader_copilot/VISUAL_ANSWER_CONTRACT.md; backend services/copilot_visual/).
 *
 * Tolerant by design: the payload is parsed in two steps so one bad part never hides the rest.
 *   parseVisualAnswer   the envelope (title, as_of, mode, headline, decision, evidence, data quality, follow-ups,
 *                       caveat). Optional parts that do not parse are dropped; only a payload without blocks fails.
 *   parseBlock          each block on its own: a known type whose data parses, a known type whose data does not
 *                       ("bad", shown as a short note), or a type this build does not know ("unsupported").
 * Nothing here fills in a number: a missing value stays missing (null) and the renderer says so.
 */
import { z } from "zod";

const str = z.string();
const num = z.number().finite();
const optStr = str.nullish();
const tone = z.enum(["up", "down", "neutral", "warn"]);
/** A tone the renderer knows, or undefined (an unknown tone is drawn neutral, never an error). */
const optTone = z.preprocess((v) => (typeof v === "string" && (tone.options as readonly string[]).includes(v) ? v : undefined), tone.optional());

const base = { id: str.optional(), title: optStr, note: optStr };

export const kpisBlock = z.object({
  ...base, type: z.literal("kpis"),
  items: z.array(z.object({ label: str, value: z.union([str, num]).nullable(), sub: optStr, tone: optTone })),
});

const bar = z.object({ d: str, o: num, h: num, l: num, c: num, v: num.nullish() });
const series = z.array(num.nullable());
export const LEVEL_KINDS = ["support", "resistance", "entry", "stop", "target", "wall_call", "wall_put", "max_pain"] as const;
export const candlesBlock = z.object({
  ...base, type: z.literal("candles"),
  symbol: str,
  bars: z.array(bar).min(1),
  overlays: z.object({ ema20: series.optional(), ema50: series.optional(), ema200: series.optional() }).partial().nullish(),
  levels: z.array(z.object({ kind: str, price: num, label: optStr })).nullish(),
  band: z.object({ low: num, high: num, label: optStr }).nullish(),
});

export const BAR_UNITS = ["₹ Cr", "%", "×", "count"] as const;
export const barsBlock = z.object({
  ...base, type: z.literal("bars"),
  unit: str,
  orientation: z.enum(["h", "v"]).catch("h"),
  items: z.array(z.object({ label: str, value: num.nullable(), tone: optTone, sub: optStr })).min(1),
  baseline: num.nullish(),
});

export const heatmapBlock = z.object({
  ...base, type: z.literal("heatmap"),
  unit: str.catch("%"),
  cells: z.array(z.object({
    label: str, value: num.nullable(), group: optStr, sub: optStr,
    /** The stocks behind a tile (the sector rotation answer: a sector's strongest five), shown when the tile is selected. */
    members: z.array(z.object({ label: str, value: num.nullable(), sub: optStr, ask: optStr })).optional().catch(undefined),
  })).min(1),
});

export const quadrantBlock = z.object({
  ...base, type: z.literal("quadrant"),
  /** "fno": a point or row opens that stock's F&O detail (option chain and futures build-up) inside the app shell. */
  detail: z.enum(["fno"]).optional().catch(undefined),
  x: z.object({ label: str, unit: str }),
  y: z.object({ label: str, unit: str }),
  quadrants: z.object({ tr: str, tl: str, br: str, bl: str }),
  points: z.array(z.object({ label: str, x: num, y: num, quadrant: optStr })).min(1),
});

export const RANKED_FORMATS = ["price", "pct", "x", "int", "text"] as const;
const cell = z.union([str, num, z.boolean()]).nullable();
const baseRow = z.object({
  symbol: optStr, cells: z.record(cell), tone: optTone, plan_id: optStr, ask: optStr,
  /** A short tag by the symbol: "Live", or the close the row was priced at. */
  badge: optStr,
  /** A tooltip per cell key. */
  tips: z.record(str).optional().catch(undefined),
});
/** A row may carry its other structures, one level deep (the F&O board folds an underlying's alternatives under its lead). */
const rankedRow = baseRow.extend({ alternatives: z.array(baseRow).optional().catch(undefined) });
export const rankedBlock = z.object({
  ...base, type: z.literal("ranked"),
  /** "fno": a row with a symbol gets a Details › button that opens that stock's F&O detail inside the app shell. */
  detail: z.enum(["fno"]).optional().catch(undefined),
  columns: z.array(z.object({
    key: str, label: str,
    align: z.enum(["left", "right"]).optional().catch(undefined),
    format: z.enum(RANKED_FORMATS).optional().catch(undefined),
  })).min(1),
  rows: z.array(rankedRow),
});

export const tradePlanBlock = z.object({ ...base, type: z.literal("trade_plan"), plan_id: str.min(1) });

export const listBlock = z.object({
  ...base, type: z.literal("list"),
  items: z.array(z.object({ text: str, tone: optTone, sub: optStr })).min(1),
});

export const NOTICE_ACTIONS = ["kite_login", "connect_broker", "set_risk_profile"] as const;
export const noticeBlock = z.object({
  ...base, type: z.literal("notice"), tone: z.enum(["warn", "info"]).catch("info"), text: str,
  /** What the reader can do about it: log in to Kite (admins), connect a broker, set up a risk profile. */
  actions: z.array(z.object({ kind: z.enum(NOTICE_ACTIONS), label: str })).optional().catch(undefined),
});

const BLOCKS = {
  kpis: kpisBlock, candles: candlesBlock, bars: barsBlock, heatmap: heatmapBlock, quadrant: quadrantBlock,
  ranked: rankedBlock, trade_plan: tradePlanBlock, list: listBlock, notice: noticeBlock,
} as const;
export type BlockType = keyof typeof BLOCKS;
export const BLOCK_TYPES = Object.keys(BLOCKS) as BlockType[];

export type KpisBlock = z.infer<typeof kpisBlock>;
export type CandlesBlock = z.infer<typeof candlesBlock>;
export type BarsBlock = z.infer<typeof barsBlock>;
export type HeatmapBlock = z.infer<typeof heatmapBlock>;
export type QuadrantBlock = z.infer<typeof quadrantBlock>;
export type RankedBlock = z.infer<typeof rankedBlock>;
export type TradePlanBlock = z.infer<typeof tradePlanBlock>;
export type ListBlock = z.infer<typeof listBlock>;
export type NoticeBlock = z.infer<typeof noticeBlock>;
export type KnownBlock = KpisBlock | CandlesBlock | BarsBlock | HeatmapBlock | QuadrantBlock | RankedBlock | TradePlanBlock | ListBlock | NoticeBlock;

/** One block after parsing: drawn, or a short note saying why not. */
export type ParsedBlock =
  | { kind: "ok"; key: string; block: KnownBlock }
  | { kind: "bad"; key: string; type: string; title: string | null; problem: string }
  | { kind: "unsupported"; key: string; type: string; title: string | null };

export function parseBlock(raw: unknown, index: number): ParsedBlock {
  const obj = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const type = typeof obj.type === "string" ? obj.type : "";
  const key = `${typeof obj.id === "string" && obj.id ? obj.id : "block"}-${index}`;
  const title = typeof obj.title === "string" ? obj.title : null;
  if (!(type in BLOCKS)) return { kind: "unsupported", key, type: type || "unnamed", title };
  const r = BLOCKS[type as BlockType].safeParse(obj);
  if (r.success) return { kind: "ok", key, block: r.data as KnownBlock };
  const issue = r.error.issues[0];
  return { kind: "bad", key, type, title, problem: issue ? `${issue.path.join(".") || "block"}: ${issue.message}` : "the data did not match" };
}

const decision = z.object({
  status: str,
  label: optStr,
  reason: optStr,
  conditions: z.array(z.object({ text: str, met: z.boolean().nullable().catch(null) })).catch([]).default([]),
  invalidation: optStr,
  plan_id: optStr,
});
export type Decision = z.infer<typeof decision>;

const source = z.object({ name: str, as_of: optStr, status: str.catch("missing"), note: optStr });
export type Source = z.infer<typeof source>;

/** The envelope. Optional parts that do not parse become empty, so the blocks still show. */
export const visualAnswer = z.object({
  schema: z.literal("visual-answer-v1"),
  intent: str.catch("unknown"),
  title: str.catch("Copilot answer"),
  as_of: optStr.catch(null),
  generated_at: optStr.catch(null),
  mode: z.enum(["live", "eod", "mixed"]).nullable().catch(null).default(null),
  headline: z.object({ text: str, tone: optTone }).nullable().catch(null).default(null),
  decision: decision.nullable().catch(null).default(null),
  blocks: z.array(z.unknown()),
  evidence: z.array(z.object({ label: str, value: z.union([str, num]).nullable(), source: optStr, as_of: optStr })).catch([]).default([]),
  data_quality: z.object({
    sources: z.array(source).catch([]).default([]),
    stale: z.boolean().catch(false).default(false),
    missing: z.array(str).catch([]).default([]),
  }).nullable().catch(null).default(null),
  follow_ups: z.array(z.object({ label: str, query: str })).catch([]).default([]),
  caveat: optStr.catch(null),
});
export type VisualAnswerPayload = z.infer<typeof visualAnswer>;

export type ParsedAnswer = { ok: true; answer: VisualAnswerPayload; blocks: ParsedBlock[] } | { ok: false; problem: string };

export function parseVisualAnswer(raw: unknown): ParsedAnswer {
  const r = visualAnswer.safeParse(raw);
  if (!r.success) {
    const issue = r.error.issues[0];
    return { ok: false, problem: issue ? `${issue.path.join(".") || "payload"}: ${issue.message}` : "the payload did not match" };
  }
  return { ok: true, answer: r.data, blocks: r.data.blocks.map(parseBlock) };
}
