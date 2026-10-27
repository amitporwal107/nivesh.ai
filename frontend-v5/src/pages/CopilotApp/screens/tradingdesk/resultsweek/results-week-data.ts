/**
 * Smart trading desk · Results week — the data (docs/EARNINGS_SURPRISE_TRACKER.md §5).
 *
 *   GET /api/desk/results-week?date=YYYY-MM-DD
 *        { date, as_of, week{from,to}, basis, consensus_available, label, counts{…}, results[], ideas{fno[],all[],note},
 *          sources, gaps[] }
 *        Signed in. A past date answers from the stored nightly snapshot; today is built live and cached up to 10 min.
 *
 * The market strip and this week's macro releases are NOT read from this route: the view composes them from the desk's
 * existing reads (GET /api/markets/home, /api/markets/sector-returns, /api/markets/macro-calendar), the same hooks and
 * caches the Overview and the Events calendar use (ResultsWeekMarket.tsx).
 *
 * Basis: every verdict is "vs historical trend" — the company's own past quarters — never vs an analyst consensus (none
 * is held in P1). Percent fields are percent points (1.2 = +1.2 %).
 *
 * The §5 contract writes several blocks as `{...}` (components.surprise / trend / outlook, reaction, fno_buildup,
 * technical). Their readers below accept the field names the spec's §3–§4 use, and a missing or non-numeric field is
 * null, shown as "not available" / "not analysed", never as 0 and never as neutral. Nothing here computes a verdict or a
 * score: they are the route's.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";

// ── tolerant readers ─────────────────────────────────────────────────────

type Raw = Record<string, unknown>;
const isRec = (v: unknown): v is Raw => !!v && typeof v === "object" && !Array.isArray(v);
const rec = (v: unknown): Raw => (isRec(v) ? v : {});
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() !== "" ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.map((x) => (typeof x === "string" ? x.trim() : str(rec(x).label) ?? str(rec(x).name) ?? str(rec(x).code) ?? "")).filter(Boolean) : []);
/** The first path that holds a value: "a.b" walks objects. */
function at(o: unknown, paths: string[]): unknown {
  for (const p of paths) {
    let cur: unknown = o;
    for (const k of p.split(".")) cur = isRec(cur) ? cur[k] : undefined;
    if (cur !== undefined && cur !== null) return cur;
  }
  return undefined;
}
const numAt = (o: unknown, paths: string[]) => {
  const v = at(o, paths);
  return num(v) ?? num(rec(v).value) ?? num(rec(v).avg);
};
const strAt = (o: unknown, paths: string[]) => str(at(o, paths));
const day = (v: unknown): string | null => { const s = str(v); return s ? s.slice(0, 10) : null; };

// ── view model ───────────────────────────────────────────────────────────

export type Verdict = "above" | "in_line" | "below";
export type Intensity = "outstanding" | "well_below";
export type RwStatus = "declared" | "pending" | "upcoming";
export type Phase = "declared" | "upcoming";

export interface RwRange { low: number | null; mid: number | null; high: number | null }
export interface RwMetric {
  key: string;
  unit: string | null;
  filed: number | null;
  expected: RwRange | null;
  vsMid: number | null;
  z: number | null;
  verdict: Verdict | null;
  /** The route's own reliability flag; null when it did not say. */
  reliable: boolean | null;
  note: string | null;
}
export interface RwGrowth { yoy: number | null; qoq: number | null }
export interface RwTrend { revenue: RwGrowth; ebitda: RwGrowth; pat: RwGrowth; marginChangePp: number | null; score: number | null }
export interface RwOutlook {
  /** The filing-analysis score, −100..100 (Mongo event_ai_analysis.net_impact_score). */
  netImpact: number | null;
  /** The 0–100 component the route made of it. */
  score: number | null;
  band: string | null;
  confidence: number | null;
  summary: string | null;
  label: string | null;
}
export interface RwQuality { flags: string[]; notChecked: string[] }
export interface RwReaction { excess: number | null; stock: number | null; nifty: number | null; session: string | null; volumeX: number | null; note: string | null }
export interface RwBuildup { state: string | null; date: string | null; oiChange: number | null; priceChange: number | null }
export interface RwTechnical { stage: string | null; score: number | null; setup: string | null; trend: string | null; note: string | null }
export interface RwPast { n: number | null; eventDay: number | null; d1: number | null; w1: number | null }
export interface RwResult {
  id: string;
  symbol: string;
  name: string;
  sector: string | null;
  eventDate: string | null;
  status: RwStatus;
  fno: boolean | null;
  periodLabel: string | null;
  basis: string | null;
  verdict: { label: Verdict | null; intensity: Intensity | null; reason: string | null };
  score: { value: number | null; band: Verdict | null; present: string[]; missing: string[] };
  surprise: { metrics: RwMetric[]; score: number | null } | null;
  trend: RwTrend | null;
  outlook: RwOutlook | null;
  quality: RwQuality | null;
  reaction: RwReaction | null;
  buildup: RwBuildup | null;
  technical: RwTechnical | null;
  chartink: { scans: string[]; scanDate: string | null } | null;
  past: RwPast | null;
  evidence: Array<{ label: string; url: string | null }>;
  gaps: string[];
}
export interface RwIdeaPart { key: string; label: string; value: number | null }
export interface RwIdea { rank: number | null; symbol: string; name: string | null; phase: Phase | null; signal: number | null; signalLabel: string | null; parts: RwIdeaPart[]; why: string[] }
export interface RwCounts { declared: number | null; pending: number | null; upcoming: number | null; above: number | null; inLine: number | null; below: number | null; notRated: number | null }
export interface ResultsWeek {
  date: string;
  asOf: string | null;
  week: { from: string | null; to: string | null };
  basis: string | null;
  consensusAvailable: boolean;
  label: string | null;
  counts: RwCounts;
  results: RwResult[];
  ideas: { fno: RwIdea[]; all: RwIdea[]; note: string | null };
  sources: Array<[string, string]>;
  gaps: string[];
}

// ── parsing ──────────────────────────────────────────────────────────────

const Envelope = z.object({
  date: z.string(),
  as_of: z.string().nullable().optional(),
  week: z.object({ from: z.string().nullable().optional(), to: z.string().nullable().optional() }).partial().nullable().optional(),
  basis: z.string().nullable().optional(),
  consensus_available: z.boolean().nullable().optional(),
  label: z.string().nullable().optional(),
  counts: z.record(z.string(), z.unknown()).nullable().optional(),
  results: z.array(z.record(z.string(), z.unknown())),
  ideas: z.record(z.string(), z.unknown()).nullable().optional(),
  sources: z.unknown().optional(),
  gaps: z.array(z.unknown()).nullable().optional(),
});

const asVerdict = (v: unknown): Verdict | null => {
  const s = str(v)?.toLowerCase().replace(/[\s-]+/g, "_");
  return s === "above" || s === "in_line" || s === "below" ? s : null;
};
const asIntensity = (v: unknown): Intensity | null => {
  const s = str(v)?.toLowerCase().replace(/[\s-]+/g, "_");
  return s === "outstanding" || s === "well_below" ? s : null;
};
const asStatus = (row: Raw): RwStatus => {
  const s = (str(row.status) ?? "").toLowerCase();
  if (s === "upcoming" || s === "awaited") return "upcoming";
  if (s.includes("pending") || str(row.filed_state) === "pending") return "pending";
  return s === "declared" ? "declared" : "upcoming";
};

function readRange(v: unknown): RwRange | null {
  if (!isRec(v)) return null;
  const r = { low: num(v.low), mid: num(v.mid), high: num(v.high) };
  return r.low == null && r.mid == null && r.high == null ? null : r;
}

function readMetric(key: string, v: unknown): RwMetric {
  const m = rec(v);
  return {
    key,
    unit: str(m.unit),
    filed: num(m.filed) ?? num(rec(m.filed).value),
    expected: readRange(m.expected),
    vsMid: num(m.vs_mid_pct),
    z: num(m.z),
    verdict: asVerdict(m.verdict) ?? asVerdict(rec(m.verdict).label),
    reliable: bool(m.reliable),
    note: str(m.note) ?? str(m.reason),
  };
}

const METRIC_KEYS = ["pat", "revenue", "eps"];
function readSurprise(v: unknown): RwResult["surprise"] {
  if (v == null) return null;
  let metrics: RwMetric[] = [];
  if (Array.isArray(v)) metrics = v.map((x) => readMetric(str(rec(x).key) ?? str(rec(x).metric) ?? "metric", x));
  else if (isRec(v)) {
    if (Array.isArray(v.metrics)) metrics = v.metrics.map((x) => readMetric(str(rec(x).key) ?? str(rec(x).metric) ?? "metric", x));
    else if (isRec(v.metrics)) metrics = Object.entries(v.metrics).map(([k, x]) => readMetric(k, x));
    else metrics = METRIC_KEYS.filter((k) => isRec(v[k])).map((k) => readMetric(k, v[k]));
  }
  const order = (k: string) => { const i = METRIC_KEYS.indexOf(k); return i < 0 ? 9 : i; };
  metrics.sort((a, b) => order(a.key) - order(b.key));
  return { metrics, score: numAt(v, ["score", "value"]) };
}

const growth = (t: unknown, m: string): RwGrowth => ({
  yoy: numAt(t, [`${m}_yoy_pct`, `${m}.yoy_pct`, `${m}.yoy`, `yoy.${m}`, `yoy_pct.${m}`]),
  qoq: numAt(t, [`${m}_qoq_pct`, `${m}.qoq_pct`, `${m}.qoq`, `qoq.${m}`, `qoq_pct.${m}`]),
});
function readTrend(v: unknown): RwTrend | null {
  if (!isRec(v)) return null;
  return {
    revenue: growth(v, "revenue"), ebitda: growth(v, "ebitda"), pat: growth(v, "pat"),
    marginChangePp: numAt(v, ["ebitda_margin_change_pp", "ebitda_margin_change", "margin_change_pp", "ebitda_margin.change_pp"]),
    score: numAt(v, ["score"]),
  };
}

function readOutlook(v: unknown): RwOutlook | null {
  if (!isRec(v)) return null;
  const o: RwOutlook = {
    netImpact: numAt(v, ["net_impact_score", "net_impact"]),
    score: numAt(v, ["score"]),
    band: strAt(v, ["net_band", "band"]),
    confidence: numAt(v, ["confidence_score", "confidence"]),
    summary: strAt(v, ["summary", "sum", "analysis.sum"]),
    label: strAt(v, ["label", "basis"]),
  };
  // An outlook block that carries nothing measured is "not analysed", never a neutral reading.
  return o.netImpact == null && o.score == null && o.band == null ? null : o;
}

function readQuality(v: unknown): RwQuality | null {
  if (!isRec(v)) return null;
  return { flags: strs(v.flags), notChecked: strs(v.not_checked) };
}

function readReaction(v: unknown): RwReaction | null {
  if (!isRec(v)) return null;
  const r: RwReaction = {
    excess: numAt(v, ["excess_vs_nifty_pct", "excess_pct", "excess_return_pct", "vs_nifty_pct", "excess"]),
    stock: numAt(v, ["stock_pct", "return_pct", "stock_return_pct", "change_pct"]),
    nifty: numAt(v, ["nifty_pct", "nifty_return_pct", "index_pct"]),
    session: day(at(v, ["session", "first_session", "date", "session_date"])),
    volumeX: numAt(v, ["volume_x", "volume_ratio", "volume_multiple", "rvol"]),
    note: strAt(v, ["note", "reason"]),
  };
  return r.excess == null && r.stock == null && r.nifty == null ? (r.note ? r : null) : r;
}

function readBuildup(v: unknown): RwBuildup | null {
  if (!isRec(v)) return null;
  const b: RwBuildup = {
    state: strAt(v, ["state", "buildup", "label", "signal"]),
    date: day(at(v, ["date", "as_of", "trade_date"])),
    oiChange: numAt(v, ["oi_change_pct", "oi_chg_pct", "oi_pct"]),
    priceChange: numAt(v, ["price_change_pct", "price_chg_pct", "price_pct"]),
  };
  return b.state == null && b.oiChange == null ? null : b;
}

function readTechnical(v: unknown): RwTechnical | null {
  if (!isRec(v)) return null;
  const t: RwTechnical = {
    stage: strAt(v, ["stage", "scanner_stage", "status"]),
    score: numAt(v, ["score", "final_score"]),
    setup: strAt(v, ["setup", "bucket", "pattern"]),
    trend: strAt(v, ["trend", "trend_label"]),
    note: strAt(v, ["note", "reason"]),
  };
  return t.stage == null && t.score == null && t.setup == null && t.trend == null ? null : t;
}

function readPast(row: Raw): RwPast | null {
  const v = at(row, ["past_reactions", "past_results", "history", "reaction.past"]);
  if (!isRec(v)) return null;
  const p: RwPast = {
    n: numAt(v, ["n", "count"]),
    eventDay: numAt(v, ["event_day_avg_pct", "event_day.avg", "stats.event_day.avg", "event_day_pct", "avg_event_day_pct"]),
    d1: numAt(v, ["d1_avg_pct", "d1.avg", "stats.d1.avg", "d1_pct", "avg_d1_pct"]),
    w1: numAt(v, ["w1_avg_pct", "w1.avg", "stats.w1.avg", "w1_pct", "avg_w1_pct"]),
  };
  return p.eventDay == null && p.d1 == null && p.w1 == null ? null : p;
}

const safeUrl = (u: unknown): string | null => {
  const s = str(u);
  if (!s) return null;
  try { const x = new URL(s); return x.protocol === "http:" || x.protocol === "https:" ? x.toString() : null; } catch { return null; }
};

function readResult(row: Raw, i: number): RwResult | null {
  const symbol = str(row.symbol);
  if (!symbol) return null;
  const v = rec(row.verdict);
  const s = rec(row.score);
  const cov = rec(s.coverage);
  const comp = rec(row.components);
  const ck = row.chartink;
  return {
    id: `${symbol}|${day(row.event_date) ?? i}`,
    symbol,
    name: str(row.name) ?? symbol,
    sector: str(row.sector),
    eventDate: day(row.event_date),
    status: asStatus(row),
    fno: bool(row.fno),
    periodLabel: str(row.period_label),
    basis: str(row.basis),
    verdict: { label: asVerdict(v.label), intensity: asIntensity(v.intensity), reason: str(v.reason) },
    score: { value: num(s.value), band: asVerdict(s.band), present: strs(cov.present), missing: strs(cov.missing) },
    surprise: readSurprise(comp.surprise),
    trend: readTrend(comp.trend),
    outlook: readOutlook(comp.outlook),
    quality: readQuality(comp.quality),
    reaction: readReaction(row.reaction),
    buildup: readBuildup(row.fno_buildup),
    technical: readTechnical(row.technical),
    chartink: isRec(ck) ? { scans: strs(ck.scans), scanDate: day(ck.scan_date) } : null,
    past: readPast(row),
    evidence: (Array.isArray(row.evidence) ? row.evidence : []).flatMap((e) => {
      const label = str(rec(e).label) ?? str(rec(e).title);
      return label ? [{ label, url: safeUrl(rec(e).url) }] : [];
    }),
    gaps: strs(row.gaps),
  };
}

export const PART_LABEL: Record<string, string> = {
  earnings: "Earnings", earnings_score: "Earnings", surprise: "Earnings",
  reaction: "Reaction",
  oi: "OI build-up", oi_buildup: "OI build-up", fno_buildup: "OI build-up", buildup: "OI build-up",
  technical: "Technical", technicals: "Technical",
  past_reactions: "Past reactions", history: "Past reactions", past: "Past reactions",
  trend: "Operating trend", operating_trend: "Operating trend",
};
const partLabel = (k: string) => PART_LABEL[k] ?? k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

function readParts(v: unknown): RwIdeaPart[] {
  if (Array.isArray(v)) {
    return v.flatMap((x) => {
      const key = str(rec(x).key) ?? str(rec(x).name);
      return key ? [{ key, label: str(rec(x).label) ?? partLabel(key), value: numAt(x, ["value", "score", "points"]) }] : [];
    });
  }
  if (isRec(v)) return Object.entries(v).map(([key, x]) => ({ key, label: partLabel(key), value: num(x) ?? numAt(x, ["value", "score", "points"]) }));
  return [];
}

function readIdea(v: unknown): RwIdea | null {
  const r = rec(v);
  const symbol = str(r.symbol);
  if (!symbol) return null;
  const ph = (str(r.phase) ?? "").toLowerCase();
  const why = r.why;
  return {
    rank: num(r.rank),
    symbol,
    name: str(r.name),
    phase: ph === "declared" ? "declared" : ph === "upcoming" ? "upcoming" : null,
    signal: num(r.signal) ?? numAt(r.signal, ["value", "score"]),
    signalLabel: typeof r.signal === "string" ? str(r.signal) : str(rec(r.signal).label),
    parts: readParts(r.parts),
    why: typeof why === "string" ? [why] : strs(why),
  };
}

function readSources(v: unknown): Array<[string, string]> {
  if (!isRec(v)) return [];
  return Object.entries(v).flatMap(([k, x]): Array<[string, string]> => {
    const s = str(x) ?? str(rec(x).source) ?? str(rec(x).label);
    return s ? [[k, s]] : [];
  });
}

export function readResultsWeek(data: unknown): ResultsWeek {
  const parsed = Envelope.safeParse(data);
  if (!parsed.success) throw ApiError.contractDrift(`desk.results-week: ${parsed.error.issues[0]?.message ?? "unexpected shape"}`, parsed.error);
  const d = parsed.data;
  const c = rec(d.counts);
  const ideas = rec(d.ideas);
  const list = (x: unknown) => (Array.isArray(x) ? x.map(readIdea).filter((i): i is RwIdea => i != null) : []);
  return {
    date: d.date.slice(0, 10),
    asOf: d.as_of ?? null,
    week: { from: day(d.week?.from), to: day(d.week?.to) },
    basis: d.basis ?? null,
    consensusAvailable: d.consensus_available === true,
    label: d.label ?? null,
    counts: {
      declared: num(c.declared), pending: num(c.declared_pending), upcoming: num(c.upcoming),
      above: num(c.above), inLine: num(c.in_line), below: num(c.below), notRated: num(c.not_rated),
    },
    results: d.results.map(readResult).filter((r): r is RwResult => r != null),
    ideas: { fno: list(ideas.fno), all: list(ideas.all), note: str(ideas.note) },
    sources: readSources(d.sources),
    gaps: strs(d.gaps),
  };
}

const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

export async function fetchResultsWeek(date: string, signal?: AbortSignal): Promise<ResultsWeek> {
  const res = await http({ path: "/api/desk/results-week", query: { date }, signal });
  return readResultsWeek(res.data);
}

/** One read for the Events view and the Scanner ideas (the same key, so the second screen gets it from the cache). */
export function useResultsWeek(date: string) {
  return useQuery<ResultsWeek>({
    queryKey: ["copilot", "desk", "results-week", date],
    staleTime: 5 * 60_000,
    refetchInterval: 10 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchResultsWeek(date, signal),
  });
}

// ── words ────────────────────────────────────────────────────────────────

/** Always on screen, whatever the route sends: the verdicts' basis. */
export const BASIS_LABEL = "vs historical trend — the company’s own past quarters, not analyst consensus";
export const VERDICT_WORD: Record<Verdict, string> = { above: "Above", in_line: "In line", below: "Below" };
export const INTENSITY_WORD: Record<Intensity, string> = { outstanding: "Outstanding", well_below: "Well below" };
export const METRIC_WORD: Record<string, string> = { pat: "PAT", revenue: "Revenue", eps: "EPS", ebitda: "EBITDA" };
export const metricWord = (k: string) => METRIC_WORD[k] ?? k.replace(/_/g, " ").toUpperCase();
export const COMPONENT_WORD: Record<string, string> = {
  surprise: "Surprise vs historical trend", trend: "Operating trend", outlook: "Outlook (filing analysis)", quality: "Earnings quality",
};
export const componentWord = (k: string) => COMPONENT_WORD[k] ?? k.replace(/_/g, " ");

const BUILDUP: Record<string, { word: string; tone: "up" | "down" }> = {
  long_buildup: { word: "Long build-up", tone: "up" },
  short_covering: { word: "Short covering", tone: "up" },
  short_buildup: { word: "Short build-up", tone: "down" },
  long_unwinding: { word: "Long unwinding", tone: "down" },
};
export function buildupWord(state: string | null): { word: string; tone: "up" | "down" | null } {
  if (!state) return { word: "not available", tone: null };
  const k = state.toLowerCase().replace(/[\s-]+/g, "_").replace("build_up", "buildup");
  return BUILDUP[k] ?? { word: state.replace(/_/g, " "), tone: null };
}
/** "moderately_positive" → "moderately positive". */
export const plainWords = (s: string | null) => (s ? s.replace(/_/g, " ") : null);
