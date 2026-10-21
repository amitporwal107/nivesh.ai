/**
 * Portfolio analysis — concentration, fund overlap and the remediation plan.
 *
 * The derivations are copied from the AI Insights page
 * (src/pages/Concentration/ConcentrationAnalytics.tsx), which does not export
 * them; each function names the one it copies. They differ from that page in
 * one way only: where it fills a gap with a made-up value (coverage 100%, a
 * leverage score of 50, 0 for a missing figure) the value stays null here and
 * the screen prints "—".
 *
 * Endpoints (all read through shared hooks, see the screens that use these):
 *   GET /api/portfolio/exposure/concentration        readConcentration
 *   GET /api/portfolio/exposure/fund-overlap/matrix  readOverlap
 *   GET /api/portfolio/exposure/remediation          readRemediation
 *
 * Percentages are in percent units (12.4 = 12.4%); money is RUPEES.
 */
import type { ConcentrationAxisC, ConcentrationBreakdownC } from "@/services/contracts/portfolio.contract";
import type { Tone } from "../../components/ui";
import { humanise, num, rec, str } from "./data";

// ── verdicts ─────────────────────────────────────────────────────────────

export type Verdict = "balanced" | "elevated" | "over-concentrated";

export const VERDICT_META: Record<Verdict, { label: string; tone: Tone }> = {
  balanced: { label: "Balanced", tone: "mint" },
  elevated: { label: "Elevated", tone: "amber" },
  "over-concentrated": { label: "Over-concentrated", tone: "danger" },
};

const SEVERITY: Record<Verdict, number> = { balanced: 0, elevated: 1, "over-concentrated": 2 };

function readVerdict(v: unknown): Verdict | null {
  return v === "balanced" || v === "elevated" || v === "over-concentrated" ? v : null;
}

// ── one axis (the old page's "lens") ─────────────────────────────────────

export type AxisId = "sector" | "company" | "amc" | "group";

export interface AxisMeta {
  id: AxisId;
  /** As the old page names it: "Sector", "Company", "AMC", "Group". */
  label: string;
  plural: string;
  /** How the headline counts it: "98 companies", "5.8 groups", "7 fund houses". */
  countNoun: string;
  /** What an item's percentage is a share of (the backend divides by the axis total). */
  basis: string;
}

export const AXES: AxisMeta[] = [
  { id: "sector", label: "Sector", plural: "sectors", countNoun: "sectors", basis: "of the portfolio" },
  { id: "company", label: "Company", plural: "companies", countNoun: "companies", basis: "of the company exposure Nivesh can see through your funds and direct stocks" },
  { id: "amc", label: "AMC", plural: "AMCs", countNoun: "fund houses", basis: "of your fund holdings" },
  { id: "group", label: "Group", plural: "groups", countNoun: "groups", basis: "of your exposure to identified business groups" },
];

export interface LensItem {
  name: string;
  /** Share of the axis total — the figure the cap applies to. */
  pct: number | null;
  /** null when the backend sent no cap for the axis. */
  capPct: number | null;
  /** "Unclassified" / "Other" buckets: listed, never judged against the cap. */
  isResidual: boolean;
}

export interface Lens extends AxisMeta {
  /** null when the backend sent no cap, so nothing can be judged. */
  verdict: Verdict | null;
  /** Why the verdict is not Balanced; empty when it is. */
  reasons: string[];
  effectiveN: number | null;
  /** Herfindahl index × 10,000. */
  hhi: number | null;
  largestPct: number | null;
  largestName: string;
  /** Classification coverage, only when the backend reports one for the axis. */
  coveragePct: number | null;
  top3Pct: number | null;
  capPct: number | null;
  items: LensItem[];
}

const RESIDUAL = ["unclassified", "other", "unknown", "residual"];

/** Copy of mapLens(). */
function readLens(meta: AxisMeta, axis: ConcentrationAxisC): Lens {
  const cap = num(axis.caution_pct);
  const items: LensItem[] = (axis.items ?? []).map((it) => ({
    name: it.name,
    pct: num(it.pct),
    capPct: num(it.cap_pct) ?? cap,
    isResidual: RESIDUAL.some((k) => it.name.toLowerCase().includes(k)),
  }));
  const hhiRaw = num(axis.hhi);
  const coveragePct = num(axis.coverage_pct);
  const top3 = items.slice(0, 3).flatMap((it) => (it.pct != null ? [it.pct] : []));

  const reasons: string[] = [];
  let verdict: Verdict | null = null;
  // "sector cap", "AMC cap": the acronym keeps its capitals.
  const noun = meta.id === "amc" ? meta.label : meta.label.toLowerCase();
  if (cap != null) {
    verdict = "balanced";
    const judged = items.filter((it): it is LensItem & { pct: number } => !it.isResidual && it.pct != null);
    const over = judged.filter((it) => it.pct > cap);
    const approaching = judged.filter((it) => it.pct > cap - 3 && it.pct <= cap);
    if (over.length > 0) {
      verdict = "over-concentrated";
      over.forEach((it) => reasons.push(`${it.name} at ${it.pct.toFixed(1)}% exceeds the ${cap}% ${noun} cap (+${(it.pct - cap).toFixed(0)}pt)`));
    } else if (approaching.length > 0 || (coveragePct != null && coveragePct < 80)) {
      verdict = "elevated";
      approaching.forEach((it) => reasons.push(`${it.name} at ${it.pct.toFixed(1)}% is approaching the ${cap}% cap`));
      if (coveragePct != null && coveragePct < 80) reasons.push(`${meta.label} classification coverage ${coveragePct}% is below the 80% threshold — cannot certify Balanced`);
    }
  }

  return {
    ...meta,
    verdict,
    reasons,
    effectiveN: num(axis.effective_n),
    hhi: num(axis.hhi_x10000) ?? (hhiRaw != null ? Math.round(hhiRaw * 10000) : null),
    largestPct: num(axis.largest_pct) ?? items[0]?.pct ?? null,
    largestName: items[0]?.name ?? "",
    coveragePct,
    top3Pct: top3.length > 0 ? Number(top3.reduce((s, p) => s + p, 0).toFixed(2)) : null,
    capPct: cap,
    items,
  };
}

export type CapStatus = "residual" | "over" | "approaching" | "within" | "unknown";

/** Copy of the rule in ItemBar(): over the cap, within 3 points of it, or inside. */
export function capStatus(item: LensItem): CapStatus {
  if (item.isResidual) return "residual";
  if (item.pct == null || item.capPct == null) return "unknown";
  if (item.pct > item.capPct) return "over";
  return item.capPct - item.pct <= 3 ? "approaching" : "within";
}

export function capStatusText(item: LensItem): { text: string; tone: Tone } {
  const status = capStatus(item);
  if (status === "over" && item.pct != null && item.capPct != null) return { text: `+${(item.pct - item.capPct).toFixed(0)}pt over`, tone: "danger" };
  if (status === "approaching") return { text: "approaching", tone: "amber" };
  if (status === "within") return { text: "within cap", tone: "ink" };
  if (status === "residual") return { text: "unclassified", tone: "ink" };
  return { text: "—", tone: "ink" };
}

/** Bar scale for an "allocation vs cap" list: copy of the scale in LensPanel(). */
export function capScale(lens: Lens): number {
  const maxPct = Math.max(0, ...lens.items.map((i) => i.pct ?? 0));
  return Math.max(maxPct, lens.capPct ?? 0) * 1.18;
}

// ── the whole read ───────────────────────────────────────────────────────

export interface LadderRung {
  lens: Lens;
  effectiveN: number;
}

export interface ConcentrationRead {
  /** Sector, Company, AMC, Group — the axes the payload carries, in that order. */
  lenses: Lens[];
  /** Axes with an Effective N, most diversified first. */
  ladder: LadderRung[];
  /** The worst axis verdict; null when no axis could be judged. */
  verdict: Verdict | null;
  /** Axes that share that verdict, when it is not Balanced. */
  drivers: string[];
  /** "Well spread across 98 companies" / "concentrated in just 5.8 groups". */
  headline: { spread: string; concentrated: string } | null;
}

export function lensOf(read: ConcentrationRead, id: AxisId): Lens | null {
  return read.lenses.find((l) => l.id === id) ?? null;
}

/** Copy of buildAnalyticsData() and of the headline in ConcentrationAnalytics(). */
export function readConcentration(d: ConcentrationBreakdownC): ConcentrationRead {
  const lenses = AXES.flatMap((meta) => {
    const axis = d[meta.id];
    return axis ? [readLens(meta, axis)] : [];
  });

  // Portfolio verdict = the worst axis.
  const judged = lenses.filter((l): l is Lens & { verdict: Verdict } => l.verdict != null);
  const worstFirst = [...judged].sort((a, b) => SEVERITY[b.verdict] - SEVERITY[a.verdict]);
  const verdict = worstFirst[0]?.verdict ?? null;
  const drivers = verdict && verdict !== "balanced" ? worstFirst.filter((l) => l.verdict === verdict).map((l) => l.label) : [];

  const ladder: LadderRung[] = lenses
    .flatMap((lens) => (lens.effectiveN != null && lens.effectiveN > 0 ? [{ lens, effectiveN: lens.effectiveN }] : []))
    .sort((a, b) => b.effectiveN - a.effectiveN);

  const best = ladder[0];
  const worst = ladder[ladder.length - 1];
  const headline = best
    ? {
        spread: `Well spread across ${Math.round(best.effectiveN)} ${best.lens.countNoun}`,
        concentrated: worst && worst !== best
          ? `concentrated in just ${worst.effectiveN.toFixed(1)} ${worst.lens.countNoun}`
          : drivers.length > 0
            ? `review your ${drivers[0].toLowerCase()} exposure`
            : "all lenses look healthy",
      }
    : null;

  return { lenses, ladder, verdict, drivers, headline };
}

// ── fund overlap (GET /api/portfolio/exposure/fund-overlap/matrix) ───────

export type PairKind = "duplicate_plan" | "redundant" | "related" | "diversifying";

export const PAIR_META: Record<PairKind, { label: string; tone: Tone }> = {
  duplicate_plan: { label: "Near-duplicate", tone: "danger" },
  redundant: { label: "Redundant", tone: "danger" },
  related: { label: "Related", tone: "amber" },
  diversifying: { label: "Diversifying", tone: "mint" },
};

export interface SharedStock {
  name: string;
  /** Weight of the stock in each fund, percent. */
  weightA: number | null;
  weightB: number | null;
}

export interface FundPair {
  fundA: string;
  fundB: string;
  overlapPct: number;
  kind: PairKind;
  sharedCount: number | null;
  topShared: SharedStock[];
}

export interface OverlapRead {
  /** Highest overlap first, as the backend sends them (it sends its top 25). */
  pairs: FundPair[];
  /** Funds the matrix covers. */
  fundCount: number;
  /** Share of fund value whose portfolio is on record, percent. */
  coveragePct: number | null;
}

/** Copy of the thresholds in buildAnalyticsData(): 90 / 65 / 35. */
function pairKind(overlapPct: number): PairKind {
  if (overlapPct >= 90) return "duplicate_plan";
  if (overlapPct >= 65) return "redundant";
  return overlapPct >= 35 ? "related" : "diversifying";
}

/** null = not an overlap payload (for example `{}`, or the old hook's null after a failed request). */
export function readOverlap(raw: unknown): OverlapRead | null {
  const d = rec(raw);
  if (!d || !Array.isArray(d.pairs)) return null;
  const pairs = d.pairs.flatMap((p: unknown): FundPair[] => {
    const r = rec(p);
    const fundA = str(r?.a_name);
    const fundB = str(r?.b_name);
    const overlapPct = num(r?.overlap_pct);
    if (!r || !fundA || !fundB || overlapPct == null) return [];
    const topShared = (Array.isArray(r.top_shared) ? r.top_shared : []).flatMap((s: unknown): SharedStock[] => {
      const sr = rec(s);
      const name = str(sr?.name);
      return sr && name ? [{ name, weightA: num(sr.w_a), weightB: num(sr.w_b) }] : [];
    });
    return [{ fundA, fundB, overlapPct, kind: pairKind(overlapPct), sharedCount: num(r.shared_count), topShared }];
  });
  return { pairs, fundCount: Array.isArray(d.funds) ? d.funds.length : 0, coveragePct: num(d.coverage_pct) };
}

// ── remediation plan (GET /api/portfolio/exposure/remediation) ───────────

export interface RemContributor {
  name: string;
  /** Share of the exposure this holding accounts for, percent. */
  pct: number | null;
}

export interface RemBeforeAfter {
  lensId: string;
  lensLabel: string;
  beforeVerdict: Verdict | null;
  afterVerdict: Verdict | null;
  beforePct: number | null;
  afterPct: number | null;
  beforeHhi: number | null;
  afterHhi: number | null;
  beforeEffN: number | null;
  afterEffN: number | null;
}

export interface RemCaveat {
  /** "Tax", "Lock-in", "Exit load". */
  label: string;
  text: string;
}

export interface Remediation {
  id: string;
  kindLabel: string;
  kindTone: Tone;
  title: string;
  why: string;
  action: string;
  /** Rupees the action moves; null when it moves none (for example a SIP redirect). */
  amountRs: number | null;
  /** Fees saved per year; null when the action saves none. */
  annualSavingRs: number | null;
  /** 0–100. */
  leverageScore: number | null;
  contributors: RemContributor[];
  beforeAfter: RemBeforeAfter[];
  redeployTo: string;
  caveats: RemCaveat[];
}

export interface RemediationRead {
  /** Highest leverage first. */
  recs: Remediation[];
  /** Sum of each action's own yearly saving; null when none has one. */
  totalSavingRs: number | null;
  /** Sum of the rupees each action moves; null when none moves any. */
  totalAmountRs: number | null;
}

// The backend's action kinds, then the ones the old page's KIND_LABEL names.
const KIND_LABEL: Record<string, string> = {
  duplicate_plan: "Duplicate plan",
  consolidation: "Consolidate funds",
  category_overalloc: "Category over-allocation",
  trim_amc: "Trim AMC",
  trim_sector: "Trim sector",
  trim: "Trim",
  consolidate_duplicate: "Consolidate · Duplicate plan",
  consolidate_cluster: "Consolidate · Redundant cluster",
  rebalance: "Rebalance SIP",
};

const CAVEAT_LABEL: Record<string, string> = { tax: "Tax", lock: "Lock-in", exit: "Exit load" };

function kindTone(kind: string): Tone {
  if (kind.startsWith("consolid") || kind === "duplicate_plan") return "amber";
  return kind.startsWith("trim") ? "danger" : "indigo";
}

function positive(v: unknown): number | null {
  const n = num(v);
  return n != null && n > 0 ? n : null;
}

function sum(values: Array<number | null>): number | null {
  const present = values.flatMap((v) => (v != null ? [v] : []));
  return present.length > 0 ? present.reduce((s, v) => s + v, 0) : null;
}

/**
 * Copy of mapBackendRecs() and of the ranking in RemediationPanel().
 * null = not a remediation payload (for example `{}`).
 */
export function readRemediation(raw: unknown): RemediationRead | null {
  const d = rec(raw);
  if (!d || !Array.isArray(d.recommendations)) return null;
  const recs = d.recommendations.flatMap((item: unknown, i: number): Remediation[] => {
    const r = rec(item);
    const title = str(r?.title);
    if (!r || !title) return [];
    const kind = str(r.action_kind);
    return [{
      id: str(r.id) || `rec-${i}`,
      kindLabel: KIND_LABEL[kind] ?? humanise(kind),
      kindTone: kindTone(kind),
      title,
      why: str(r.why),
      action: str(r.action),
      amountRs: positive(r.amount_rs),
      annualSavingRs: positive(r.annual_saving_rs),
      leverageScore: num(r.leverage_score),
      contributors: (Array.isArray(r.contributors) ? r.contributors : []).flatMap((c: unknown): RemContributor[] => {
        const cr = rec(c);
        const name = str(cr?.name);
        return cr && name ? [{ name, pct: num(cr.pct_of_exposure) }] : [];
      }),
      beforeAfter: (Array.isArray(r.before_after) ? r.before_after : []).flatMap((b: unknown): RemBeforeAfter[] => {
        const br = rec(b);
        if (!br) return [];
        const lensId = str(br.lens_id);
        return [{
          lensId,
          lensLabel: str(br.lens_label) || humanise(lensId),
          beforeVerdict: readVerdict(br.before_verdict),
          afterVerdict: readVerdict(br.after_verdict),
          beforePct: num(br.before_pct),
          afterPct: num(br.after_pct),
          beforeHhi: num(br.before_hhi),
          afterHhi: num(br.after_hhi),
          beforeEffN: num(br.before_eff_n),
          afterEffN: num(br.after_eff_n),
        }];
      }),
      redeployTo: str(r.redeploy_to),
      caveats: (Array.isArray(r.caveats) ? r.caveats : []).flatMap((c: unknown): RemCaveat[] => {
        const cr = rec(c);
        const text = str(cr?.text);
        const icon = str(cr?.icon);
        return cr && text ? [{ label: CAVEAT_LABEL[icon] ?? (humanise(icon) || "Note"), text }] : [];
      }),
    }];
  });
  // Highest leverage first; an action with no score goes last.
  recs.sort((a, b) => (b.leverageScore ?? -1) - (a.leverageScore ?? -1));
  return {
    recs,
    totalSavingRs: sum(recs.map((r) => r.annualSavingRs)),
    totalAmountRs: sum(recs.map((r) => r.amountRs)),
  };
}
