/**
 * The Idea scorecard — the data (docs/desk_redesign_20261027/PLAN.md §2a, the P4 row).
 *
 *   GET /api/desk/idea-scorecard   the Phase 4.3 pre-registered study as committed (backend/services/idea_scorecard.py):
 *                                  `study`, `splits[]` (discovery / validation / test, each with its arms B0 A1 A2 A3),
 *                                  `decision` (the verdict and each arm's pre-registered checks), `rs63`, `coverage`,
 *                                  `units`, `disclaimer`, `sources[]` (path, role, kind, sha256, bytes, present, reason):
 *                                  kind "data" is result.json, read and hashed; kind "reference" is a study document the
 *                                  server lists and never opens (present null; the backend image has no docs/).
 *                                  503 {detail: {code: scorecard_unavailable | scorecard_out_of_date, reason}} when the
 *                                  committed results cannot be served as they are.
 *
 * Every figure is copied from the body. A missing or non-numeric figure is null and the screen shows "—"; it is never 0.
 * Negative figures stay negative. A body without `study`, `splits` (with arms) or `decision.verdict` is a contract error,
 * so an empty table is never presented as the study's result.
 *
 * Wording: the scanner produces ideas. Nothing here calls them picks or recommendations.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const isRec = (v: unknown): v is Raw => !!v && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);

export const SCORECARD_PATH = "/api/desk/idea-scorecard";

export interface Study {
  id: string;
  phase: string | null;
  title: string | null;
  runDate: string | null;
  registrationCommit: string | null;
  codeSha: string | null;
  signalDates: number | null;
  sessions: number | null;
  barRows: number | null;
  inputHash: string | null;
  outcome: string | null;
}

export interface ArmResult {
  arm: string;
  label: string | null;
  icMean: number | null;
  icT: number | null;
  icN: number | null;
  /** Null for the baseline (B0): it is not compared with itself. */
  deltaIc: number | null;
  deltaT: number | null;
  permutationP: number | null;
  topDecileNet: number | null;
  hitRate: number | null;
  isBaseline: boolean;
}

export interface SplitResult {
  name: string;
  from: string | null;
  to: string | null;
  dates: number | null;
  namesPerDate: number | null;
  outsideUniverse: number | null;
  arms: ArmResult[];
}

export interface ArmChecks {
  arm: string;
  checks: Array<{ key: string; pass: boolean | null }>;
  adopt: boolean | null;
}

export interface Source {
  path: string;
  role: string | null;
  /** "data" (read and hashed by the server) or "reference" (listed, never opened); null from an older server. */
  kind: string | null;
  present: boolean | null;
  sha256: string | null;
  bytes: number | null;
  reason: string | null;
}

export interface IdeaScorecard {
  study: Study;
  splits: SplitResult[];
  verdict: string;
  studyVerdict: string | null;
  adopted: string | null;
  checks: ArmChecks[];
  rs63: { arm: string | null; label: string | null; status: string | null; adopted: boolean | null; confirmation: string | null } | null;
  units: Array<{ key: string; text: string }>;
  disclaimer: string | null;
  sources: Source[];
}

/** The body did not have what the scorecard needs: said, never drawn as an empty result. */
export class ScorecardContractError extends Error {
  constructor(what: string) {
    super(`The scorecard answer had no ${what}.`);
    this.name = "ScorecardContractError";
  }
}

function readArm(v: unknown): ArmResult | null {
  const a = rec(v);
  const arm = str(a.arm);
  if (!arm) return null;
  const ic = rec(a.rank_ic);
  const vs = isRec(a.vs_b0) ? a.vs_b0 : null;
  return {
    arm,
    label: str(a.label),
    icMean: num(ic.mean),
    icT: num(ic.nw_t),
    icN: num(ic.n),
    deltaIc: vs ? num(vs.delta_ic) : null,
    deltaT: vs ? num(vs.nw_t) : null,
    permutationP: num(a.permutation_p) ?? (vs ? num(vs.permutation_p) : null),
    topDecileNet: num(a.top_decile_net_mean),
    hitRate: num(a.top_decile_hit_rate),
    isBaseline: vs === null,
  };
}

export function readScorecard(body: unknown): IdeaScorecard {
  const b = rec(body);
  if (!isRec(b.study) || !str(b.study.id)) throw new ScorecardContractError("study");
  const s = b.study;
  if (!Array.isArray(b.splits) || !b.splits.length) throw new ScorecardContractError("splits");
  const splits: SplitResult[] = b.splits.map((raw) => {
    const sp = rec(raw);
    const name = str(sp.name);
    const arms = Array.isArray(sp.arms) ? sp.arms.map(readArm).filter((x): x is ArmResult => !!x) : [];
    if (!name || !arms.length) throw new ScorecardContractError("arms in a split");
    return {
      name, from: str(sp.from), to: str(sp.to), dates: num(sp.dates), namesPerDate: num(sp.names_per_date_median),
      outsideUniverse: num(sp.coverage_top_movers_outside_universe), arms,
    };
  });
  const d = rec(b.decision);
  const verdict = str(d.verdict);
  if (!verdict) throw new ScorecardContractError("verdict");
  const checks: ArmChecks[] = Object.entries(rec(d.per_arm)).map(([arm, v]) => {
    const c = rec(v);
    return { arm, checks: Object.entries(rec(c.checks)).map(([key, pass]) => ({ key, pass: bool(pass) })), adopt: bool(c.adopt) };
  });
  const r = isRec(b.rs63) ? b.rs63 : null;
  return {
    study: {
      id: str(s.id) as string, phase: str(s.phase), title: str(s.title), runDate: str(s.run_date), registrationCommit: str(s.registration_commit),
      codeSha: str(s.code_sha), signalDates: num(s.signal_dates), sessions: num(s.sessions), barRows: num(s.bar_rows), inputHash: str(s.input_hash),
      outcome: str(s.outcome),
    },
    splits,
    verdict,
    studyVerdict: str(d.study_verdict),
    adopted: str(d.adopted),
    checks,
    rs63: r ? { arm: str(r.arm), label: str(r.label), status: str(r.status), adopted: bool(r.adopted), confirmation: str(r.confirmation) } : null,
    units: Object.entries(rec(b.units)).flatMap(([key, v]) => (str(v) ? [{ key, text: str(v) as string }] : [])),
    disclaimer: str(b.disclaimer),
    sources: (Array.isArray(b.sources) ? b.sources : []).flatMap((v) => {
      const x = rec(v);
      const path = str(x.path);
      return path ? [{ path, role: str(x.role), kind: str(x.kind), present: bool(x.present), sha256: str(x.sha256), bytes: num(x.bytes), reason: str(x.reason) }] : [];
    }),
  };
}

/** The route's own 503 answer: its code and reason (services/idea_scorecard.py ScorecardUnavailable.detail()). */
export function unavailableOf(e: unknown): { code: string; reason: string } | null {
  if (!(e instanceof ApiError) || e.status !== 503) return null;
  const d = rec(rec(e.body).detail);
  const code = str(d.code);
  const reason = str(d.reason);
  return code || reason ? { code: code ?? "scorecard_unavailable", reason: reason ?? "The route gave no reason." } : null;
}

const noRetry = (count: number, e: unknown) =>
  !(e instanceof ScorecardContractError) && !(e instanceof ApiError && (e.status === 503 || e.status === 403 || e.kind === "forbidden")) && count < 1;

export function useIdeaScorecard() {
  return useQuery<IdeaScorecard>({
    queryKey: ["copilot", "desk", "idea-scorecard"],
    staleTime: 10 * 60_000,
    retry: noRetry,
    queryFn: async ({ signal }) => readScorecard((await http({ path: SCORECARD_PATH, signal, noRetry: true })).data),
  });
}

// ── formatting: the true minus sign, nulls as "—" ──

const MINUS = "−";
const signed = (v: number, digits: number) => `${v < 0 ? MINUS : v > 0 ? "+" : ""}${Math.abs(v).toFixed(digits)}`;

/** Rank IC and its Δ: four decimals, signed. */
export const fmtIc = (v: number | null) => (v == null ? "—" : signed(v, 4));
/** A t-statistic: two decimals, signed only when negative. */
export const fmtT = (v: number | null) => (v == null ? "—" : `${v < 0 ? MINUS : ""}${Math.abs(v).toFixed(2)}`);
/** A p-value: three decimals. */
export const fmtP = (v: number | null) => (v == null ? "—" : v.toFixed(3));
/** A fraction as a signed percent (−0.00992 → −0.99%). */
export const fmtRet = (v: number | null) => (v == null ? "—" : `${signed(v * 100, 2)}%`);
/** A fraction as a percent (0.4494 → 44.9%). */
export const fmtShare = (v: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

/** "2026-10-27" → "27 Oct 2026"; anything else as it came. */
export function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m[2]) - 1];
  return month ? `${Number(m[3])} ${month} ${m[1]}` : iso;
}

/** The pre-registered checks in words (research/p4_adx_rs: a–d). */
export const CHECK_LABEL: Record<string, string> = {
  a_validation: "(a) beats B0 on validation",
  b_test: "(b) beats B0 on test",
  c_test_net_spread_not_below_B0: "(c) test net spread not below B0",
  d_test_same_sign_both_regimes: "(d) same sign in up and down regimes (test)",
};

export const SPLIT_LABEL: Record<string, string> = { discovery: "Discovery", validation: "Validation", test: "Test (held out)" };
