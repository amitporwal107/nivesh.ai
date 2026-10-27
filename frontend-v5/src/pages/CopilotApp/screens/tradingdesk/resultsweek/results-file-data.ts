/**
 * Results week · one stock's results file — the data (docs/EARNINGS_SURPRISE_TRACKER.md §9b).
 *
 *   GET /api/desk/results-week/stock/{symbol}?date=YYYY-MM-DD
 *        { schema: "results-stock-v1", symbol, name, sector, event_date, status, filed_at, first_reaction_session,
 *          period_label, row, preview{…}, commentary{pre[], results[], post[], sentiment, coverage}, analyst_views,
 *          track{sessions[], before, after, notes[]}, sources, gaps[] }
 *        Signed in. 404 {code: "no_results_meeting"} when the symbol has no results meeting in the week of `date`;
 *        422 for a bad symbol or date.
 *
 * Every commentary text (summary, positives, negatives) is the route's, from stored filing analyses; nothing here writes
 * any. `preview.lines` are the route's deterministic sentences. A block the route did not send (an older backend) is
 * null and the screen says "not available"; a missing figure is null, never 0. Percent fields are percent points.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import {
  at, bool, day, isRec, num, numAt, readResult, readSnap, rec, safeUrl, str, strAt, strs,
  type Raw, type RwResult, type RwSnap, type RwStatus,
} from "./results-week-data";

// ── view model ───────────────────────────────────────────────────────────

export type RfKind = "results" | "presentation" | "press_release" | "earnings_call" | "business_update" | "board_outcome" | "other";
export interface RfItem {
  at: string | null;
  kind: RfKind;
  title: string | null;
  band: string | null;
  /** −100..100, the filing analysis's net impact. */
  impact: number | null;
  /** 0–100. */
  confidence: number | null;
  /** The analysis's own sub-type (e.g. "Q2 FY27 results"), as stored. */
  subtype: string | null;
  summary: string | null;
  positives: string[];
  negatives: string[];
  /** Amounts the analysis read from the filing ("Revenue: 3420 ₹ crore"), as the route formats them. */
  amounts: string[];
  /** What the analysis could not settle from the filing. */
  openQuestions: string[];
  announcementId: string | null;
  url: string | null;
}
export interface RfRange { low: number | null; mid: number | null; high: number | null; reliable: boolean | null; note: string | null; unit: string | null }
export interface RfQuarter {
  periodEnd: string | null; revenue: number | null; ebitda: number | null; pat: number | null;
  marginPct: number | null; revenueYoy: number | null; patYoy: number | null;
}
export interface RfPast { n: number | null; eventDay: number | null; d1: number | null; w1: number | null; upShare: number | null }
export interface RfPreview {
  asOf: string | null;
  lines: string[];
  expected: { revenue: RfRange | null; pat: RfRange | null };
  lastQuarters: RfQuarter[];
  past: RfPast | null;
  positioning: RwSnap | null;
}
export interface RfSentiment { band: string | null; impact: number | null; confidence: number | null; basis: string | null; n: number | null }
export interface RfCommentary {
  pre: RfItem[];
  results: RfItem[];
  post: RfItem[];
  sentiment: RfSentiment | null;
  /** `analysed`: filings with a stored analysis; `filings`: exchange filings in the window (null when the list could not
   *  be read); `note`: the route's own coverage sentence. */
  coverage: { analysed: number | boolean | null; filings: number | null; note: string | null };
}
export interface RfFut {
  totalOi: number | null; oiPct: number | null; nearPrice: number | null; pricePct: number | null;
  state: string | null; text: string | null; nextPremiumPct: number | null; expiryDay: boolean;
  /** Only on a monthly-expiry day (§9b): later-month OI ÷ the eve's total OI − 1, minus the stock's own usual. */
  carryVsUsualPp: number | null;
}
export interface RfSession {
  date: string | null; rel: number | null; close: number | null; chgPct: number | null; excessPct: number | null;
  volumeX: number | null; fut: RfFut | null; pcrNext: number | null;
}
export interface RfTrack { sessions: RfSession[]; before: RwSnap | null; after: RwSnap | null; notes: string[] }
export interface ResultsFileData {
  symbol: string;
  name: string | null;
  sector: string | null;
  eventDate: string | null;
  status: RwStatus | null;
  filedAt: string | null;
  firstReactionSession: string | null;
  periodLabel: string | null;
  /** The results-week row for this symbol, parsed as the list parses it; null when the route sent none. */
  row: RwResult | null;
  preview: RfPreview | null;
  commentary: RfCommentary | null;
  /** Always shown: no analyst-views source is connected in P1 (`available: false`). */
  analystViews: { available: boolean; note: string | null };
  track: RfTrack | null;
  sources: Array<[string, string]>;
  gaps: string[];
}

// ── parsing ──────────────────────────────────────────────────────────────

const Envelope = z.object({ symbol: z.string().min(1) }).passthrough();

const KINDS: RfKind[] = ["results", "presentation", "press_release", "earnings_call", "business_update", "board_outcome", "other"];
const asKind = (v: unknown): RfKind => {
  const s = str(v)?.toLowerCase().replace(/[\s-]+/g, "_");
  return s && (KINDS as string[]).includes(s) ? (s as RfKind) : "other";
};

function readItem(v: unknown): RfItem | null {
  if (!isRec(v)) return null;
  const it: RfItem = {
    at: str(v.at),
    kind: asKind(v.kind),
    title: str(v.title),
    band: strAt(v, ["band", "net_band"]),
    impact: numAt(v, ["impact", "net_impact_score"]),
    confidence: numAt(v, ["confidence", "confidence_score"]),
    subtype: str(v.subtype),
    summary: str(v.summary),
    positives: strs(v.positives),
    negatives: strs(v.negatives),
    amounts: strs(v.amounts),
    openQuestions: strs(v.open_questions),
    announcementId: str(v.announcement_id) ?? (typeof v.announcement_id === "number" ? String(v.announcement_id) : null),
    url: safeUrl(v.url),
  };
  return it.title == null && it.summary == null && it.band == null && !it.positives.length && !it.negatives.length ? null : it;
}
const items = (v: unknown): RfItem[] => (Array.isArray(v) ? v.map(readItem).filter((i): i is RfItem => i != null) : []);

function readRange(v: unknown): RfRange | null {
  if (!isRec(v)) return null;
  const r: RfRange = { low: num(v.low), mid: num(v.mid), high: num(v.high), reliable: bool(v.reliable), note: str(v.note) ?? str(v.reason), unit: str(v.unit) };
  return r.low == null && r.mid == null && r.high == null && r.reliable == null && r.note == null ? null : r;
}

function readQuarter(v: unknown): RfQuarter | null {
  if (!isRec(v)) return null;
  const q: RfQuarter = {
    periodEnd: day(at(v, ["period_end", "quarter", "period"])),
    revenue: num(v.revenue), ebitda: num(v.ebitda), pat: num(v.pat),
    marginPct: num(v.ebitda_margin_pct), revenueYoy: num(v.revenue_yoy_pct), patYoy: num(v.pat_yoy_pct),
  };
  return q.periodEnd == null && q.revenue == null && q.pat == null ? null : q;
}

function readPast(v: unknown): RfPast | null {
  if (!isRec(v)) return null;
  const p: RfPast = { n: num(v.n), eventDay: num(v.event_day_avg_pct), d1: num(v.d1_avg_pct), w1: num(v.w1_avg_pct), upShare: num(v.up_share_pct) };
  return p.eventDay == null && p.d1 == null && p.w1 == null && p.upShare == null ? null : p;
}

function readPreview(v: unknown): RfPreview | null {
  if (!isRec(v)) return null;
  const e = rec(v.expected);
  const lastQuarters = Array.isArray(v.last_quarters) ? v.last_quarters.map(readQuarter).filter((q): q is RfQuarter => q != null) : [];
  // Newest first, as a results preview reads (the route may send either order).
  lastQuarters.sort((a, b) => (b.periodEnd ?? "").localeCompare(a.periodEnd ?? ""));
  return {
    asOf: str(v.as_of),
    lines: strs(v.lines),
    expected: { revenue: readRange(e.revenue), pat: readRange(e.pat) },
    lastQuarters,
    past: readPast(v.past_reactions),
    positioning: readSnap(isRec(v.positioning) ? { ...v.positioning, date: v.positioning.date ?? v.positioning.as_of } : null),
  };
}

function readSentiment(v: unknown): RfSentiment | null {
  if (!isRec(v)) return null;
  const s: RfSentiment = { band: str(v.band), impact: num(v.impact), confidence: num(v.confidence), basis: str(v.basis), n: num(v.n) };
  return s.band == null && s.impact == null ? null : s;
}

function readCommentary(v: unknown): RfCommentary | null {
  if (!isRec(v)) return null;
  const c = rec(v.coverage);
  const analysed = num(c.analysed) ?? bool(c.analysed);
  return {
    pre: items(v.pre), results: items(v.results), post: items(v.post),
    sentiment: readSentiment(v.sentiment),
    coverage: { analysed, filings: num(c.filings), note: str(c.note) },
  };
}

function readFut(v: unknown): RfFut | null {
  if (!isRec(v)) return null;
  const f: RfFut = {
    totalOi: num(v.total_oi), oiPct: num(v.oi_pct), nearPrice: num(v.near_price), pricePct: num(v.price_pct),
    state: str(v.state), text: str(v.text), nextPremiumPct: num(v.next_premium_pct), expiryDay: v.expiry_day === true,
    carryVsUsualPp: num(v.carry_vs_usual_pp),
  };
  return f.totalOi == null && f.oiPct == null && f.state == null && f.pricePct == null && f.nextPremiumPct == null ? null : f;
}

function readSession(v: unknown): RfSession | null {
  if (!isRec(v)) return null;
  const s: RfSession = {
    date: day(v.date), rel: num(v.rel), close: num(v.close), chgPct: num(v.chg_pct), excessPct: num(v.excess_pct),
    volumeX: num(v.volume_x), fut: readFut(v.fut), pcrNext: num(v.pcr_next),
  };
  return s.date == null && s.rel == null ? null : s;
}

function readTrack(v: unknown): RfTrack | null {
  if (!isRec(v)) return null;
  const sessions = Array.isArray(v.sessions) ? v.sessions.map(readSession).filter((s): s is RfSession => s != null) : [];
  sessions.sort((a, b) => (a.rel ?? 0) - (b.rel ?? 0) || (a.date ?? "").localeCompare(b.date ?? ""));
  return { sessions, before: readSnap(v.before), after: readSnap(v.after), notes: strs(v.notes) };
}

function readSources(v: unknown): Array<[string, string]> {
  if (!isRec(v)) return [];
  return Object.entries(v).flatMap(([k, x]): Array<[string, string]> => {
    const s = str(x) ?? str(rec(x).source) ?? str(rec(x).label);
    return s ? [[k, s]] : [];
  });
}

const asStatus = (v: unknown): RwStatus | null => {
  const s = (str(v) ?? "").toLowerCase();
  return s === "declared" || s === "pending" || s === "upcoming" ? s : null;
};

export function readResultsFile(data: unknown): ResultsFileData {
  const parsed = Envelope.safeParse(data);
  if (!parsed.success) throw ApiError.contractDrift(`desk.results-week.stock: ${parsed.error.issues[0]?.message ?? "unexpected shape"}`, parsed.error);
  const d = parsed.data as Raw;
  const av = rec(d.analyst_views);
  return {
    symbol: String(d.symbol).trim(),
    name: str(d.name),
    sector: str(d.sector),
    eventDate: day(d.event_date),
    status: asStatus(d.status),
    filedAt: str(d.filed_at),
    firstReactionSession: day(d.first_reaction_session),
    periodLabel: str(d.period_label),
    row: isRec(d.row) ? readResult(d.row, 0) : null,
    preview: readPreview(d.preview),
    commentary: readCommentary(d.commentary),
    analystViews: { available: av.available === true, note: str(av.note) },
    track: readTrack(d.track),
    sources: readSources(d.sources),
    gaps: strs(d.gaps),
  };
}

const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

export async function fetchResultsFile(symbol: string, date: string, signal?: AbortSignal): Promise<ResultsFileData> {
  const res = await http({ path: `/api/desk/results-week/stock/${encodeURIComponent(symbol)}`, query: { date }, signal });
  return readResultsFile(res.data);
}

/** One request when the file opens; kept 5 minutes (the list itself is rebuilt at most every 10). */
export function useResultsFile(symbol: string, date: string) {
  return useQuery<ResultsFileData>({
    queryKey: ["copilot", "desk", "results-week", "stock", symbol, date],
    staleTime: 5 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchResultsFile(symbol, date, signal),
  });
}

/** The route's 404 code (`no_results_meeting`), read from FastAPI's `{detail: {code}}` or a bare `{code}`. */
export function errorCode(e: unknown): string | null {
  if (!(e instanceof ApiError)) return null;
  const b = rec(e.body);
  return str(rec(b.detail).code) ?? str(b.code);
}
