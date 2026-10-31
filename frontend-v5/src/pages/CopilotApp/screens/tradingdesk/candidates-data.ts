/**
 * Smart trading desk — Options & futures lab: the Candidates view's data.
 *
 *   GET /api/fno/scan/candidates?date=   the top candidates of each build-up category among the liquid F&O stocks (backend/routes/fno.py,
 *                                        services/fno_candidates): three SEPARATE scores (signal strength, tradeability, strategy quality),
 *                                        each with its coverage and the inputs it could not earn; six checks; a fundamental context
 *                                        rating that is not part of any score; and the research status block (experiments, data window).
 *
 * The route's ranking is an order for review, not a proven method: back-tests found no skill beyond a random pick from the same pool.
 * Nothing here trusts the response shape: a missing or non-numeric field is null, never 0, and a body without `categories` throws a
 * contract error. Scores are never blended or renormalised here; a missing input stays missing.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { num } from "./desk-data";
import { BUILDUP_LABELS, type BuildupQuadrant } from "./fno-buildup";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

export const CANDIDATES_PATH = "/api/fno/scan/candidates";

export interface ScoreMissing { key: string; label: string; weight: number | null; reason: string | null }
export interface Score {
  points: number | null;
  maxPoints: number | null;
  /** Share of the weight whose inputs were read, 0..1. */
  coverage: number | null;
  complete: boolean;
  missing: ScoreMissing[];
}
export interface CandidateCheck { key: string; label: string; state: boolean | null; observed: string | null }
export interface Candidate {
  symbol: string;
  sector: string | null;
  label: BuildupQuadrant;
  priceChgPct: number | null;
  oiChgPct: number | null;
  cashChgPct: number | null;
  nearExpiry: string | null;
  daysToExpiry: number | null;
  futTurnoverCr: number | null;
  signal: Score;
  tradeability: Score;
  strategyQualityReasons: string[];
  checks: CandidateCheck[];
  entryViable: boolean | null;
  /** strong | mixed | weak | unavailable: context only, never part of a score. */
  fundamentalRating: string | null;
  riskFlags: string[];
}
export interface Unranked { symbol: string; reason: string | null; signalCoverage: number | null }
export interface CandidateCategory {
  label: BuildupQuadrant;
  meaning: string | null;
  inScan: number | null;
  pool: number | null;
  excluded: Record<string, number>;
  candidates: Candidate[];
  unranked: Unranked[];
}
export interface ResearchExperiment { id: string; stage: string; finding: string | null; doc: string | null }
export interface Research {
  status: string;
  experimentId: string | null;
  dataWindow: { from: string | null; to: string | null } | null;
  lastUpdated: string | null;
  experiments: ResearchExperiment[];
  note: string | null;
}
export interface Candidates {
  asOf: string | null;
  featuresAsOf: string | null;
  research: Research;
  categories: Record<BuildupQuadrant, CandidateCategory>;
  disclosure: string | null;
  gaps: string[];
}

function score(v: unknown): Score {
  const s = rec(v);
  return {
    points: num(s.points), maxPoints: num(s.max_points), coverage: num(s.coverage), complete: s.complete === true,
    missing: list(s.missing).map((m) => {
      const r = rec(m);
      return { key: str(r.key) ?? "", label: str(r.label) ?? str(r.key) ?? "input", weight: num(r.weight), reason: str(r.reason) };
    }),
  };
}

function candidate(v: unknown, label: BuildupQuadrant): Candidate | null {
  const r = rec(v);
  const symbol = str(r.symbol);
  if (!symbol) return null;
  const scores = rec(r.scores);
  return {
    symbol, sector: str(r.sector), label,
    priceChgPct: num(r.price_chg_pct), oiChgPct: num(r.oi_chg_pct), cashChgPct: num(r.cash_chg_pct),
    nearExpiry: str(r.near_expiry), daysToExpiry: num(r.days_to_expiry), futTurnoverCr: num(r.fut_turnover_cr),
    signal: score(scores.signal_strength), tradeability: score(scores.tradeability),
    strategyQualityReasons: list(rec(scores.strategy_quality).reasons).map(str).filter((x): x is string => x != null),
    checks: list(r.checks).map((c) => {
      const k = rec(c);
      return { key: str(k.key) ?? "", label: str(k.label) ?? "", state: typeof k.state === "boolean" ? k.state : null, observed: str(k.observed) };
    }).filter((c) => c.key),
    entryViable: typeof r.entry_viable === "boolean" ? r.entry_viable : null,
    fundamentalRating: str(rec(r.fundamental_context).rating),
    riskFlags: list(r.risk_flags).map(str).filter((x): x is string => x != null),
  };
}

export function parseCandidates(body: unknown): Candidates {
  const b = rec(body);
  const cats = rec(b.categories);
  if (Object.keys(cats).length === 0) throw ApiError.contractDrift("fno.scan.candidates: no categories");
  const out = {} as Record<BuildupQuadrant, CandidateCategory>;
  for (const label of BUILDUP_LABELS) {
    const c = rec(cats[label]);
    out[label] = {
      label, meaning: str(c.meaning), inScan: num(c.in_scan), pool: num(c.pool),
      excluded: Object.fromEntries(Object.entries(rec(c.excluded)).map(([k, x]) => [k, num(x) ?? 0])),
      candidates: list(c.candidates).map((x) => candidate(x, label)).filter((x): x is Candidate => x != null),
      unranked: list(c.unranked).map((u) => {
        const r = rec(u);
        return { symbol: str(r.symbol) ?? "", reason: str(r.reason), signalCoverage: num(r.signal_coverage) };
      }).filter((u) => u.symbol),
    };
  }
  const rs = rec(b.research);
  const win = rec(rs.data_window);
  return {
    asOf: str(b.as_of), featuresAsOf: str(b.features_as_of),
    research: {
      status: str(rs.status) ?? "research_setting_not_validated", experimentId: str(rs.experiment_id),
      dataWindow: rs.data_window ? { from: str(win.from), to: str(win.to) } : null, lastUpdated: str(rs.last_updated),
      experiments: list(rs.experiments).map((e) => {
        const r = rec(e);
        return { id: str(r.id) ?? "", stage: str(r.stage) ?? "", finding: str(r.finding), doc: str(r.doc) };
      }).filter((e) => e.id),
      note: str(rs.note),
    },
    categories: out, disclosure: str(b.disclosure), gaps: list(b.gaps).map(str).filter((x): x is string => x != null),
  };
}

export function useCandidates(enabled: boolean) {
  return useQuery<Candidates>({
    queryKey: ["copilot", "desk", "fno-candidates"],
    enabled,
    staleTime: 10 * 60_000,
    retry: noRetry4xx,
    queryFn: async ({ signal }) => parseCandidates((await http({ path: CANDIDATES_PATH, timeoutMs: 30_000, signal })).data),
  });
}
