/**
 * Strategy Builder — small display helpers for the plan view. Nothing here changes a value: null is "—", a
 * status is a word as well as a shape (never colour alone), and a JSON evidence value is printed as it came.
 */
import type { CSSProperties, ReactNode } from "react";
import { fmtNum, Pill, type Tone } from "../../../components/ui";
import { fmtPrice } from "../../trading/parts";
import type { CandidateStatus, PlanStatus } from "./plan-contract";

export const DASH = "—";

export const noteStyle: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };

export const STATUS_WORDS: Record<PlanStatus, { trader: string; plain: string; tone: Tone; glyph: string }> = {
  plan: { trader: "Plan", plain: "A plan is ready", tone: "mint", glyph: "✓" },
  wait: { trader: "Wait for confirmation", plain: "Wait: not confirmed yet", tone: "amber", glyph: "◔" },
  no_trade: { trader: "No trade", plain: "Better to stay out", tone: "danger", glyph: "✕" },
  insufficient_data: { trader: "Insufficient data", plain: "Not enough data to plan", tone: "ink", glyph: "?" },
};

export const CANDIDATE_WORDS: Record<CandidateStatus, { label: string; tone: Tone; glyph: string }> = {
  candidate: { label: "Viable", tone: "mint", glyph: "✓" },
  wait: { label: "Wait", tone: "amber", glyph: "◔" },
  no_trade: { label: "No trade", tone: "danger", glyph: "✕" },
  avoid: { label: "Avoid", tone: "danger", glyph: "⊘" },
  insufficient_data: { label: "Insufficient data", tone: "ink", glyph: "?" },
};

export function StatusPill({ status, plain = false, testId }: { status: PlanStatus; plain?: boolean; testId?: string }) {
  const w = STATUS_WORDS[status];
  return <span data-testid={testId} data-status={status}><Pill tone={w.tone}><span aria-hidden>{w.glyph} </span>{plain ? w.plain : w.trader}</Pill></span>;
}

export function CandidatePill({ status, testId }: { status: CandidateStatus; testId?: string }) {
  const w = CANDIDATE_WORDS[status];
  return <span data-testid={testId} data-status={status}><Pill tone={w.tone}><span aria-hidden>{w.glyph} </span>{w.label}</Pill></span>;
}

export const SEGMENT_WORD = { cash: "Cash", futures: "Futures", options: "Options", combination: "Combination" } as const;

/** A rupee amount with paise ("₹1,234.50"); null is "—". */
export const rupees = fmtPrice;

/** A magnitude in rupees without a sign (a loss is a loss; the column says so). */
export const rupeesAbs = (n: number | null | undefined) => (n == null ? DASH : fmtPrice(Math.abs(n)));

export const ratio = (n: number | null | undefined) => (n == null ? DASH : `${fmtNum(n, 2)} : 1`);

const compactValue = (v: unknown): string => {
  if (v == null) return DASH;
  if (typeof v === "number") return fmtNum(v, Number.isInteger(v) ? 0 : 2);
  if (typeof v === "string") return v;
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return v.map(compactValue).join(", ");
  if (typeof v === "object") {
    return Object.entries(v as Record<string, unknown>)
      .filter(([, x]) => x != null && typeof x !== "object")
      .slice(0, 8)
      .map(([k, x]) => `${k.replace(/_/g, " ")} ${compactValue(x)}`)
      .join(" · ") || DASH;
  }
  return String(v);
};

/** An evidence item's value as one line of text, as the route sent it. */
export const valueText = compactValue;

export function Fact({ k, v, why, testId }: { k: ReactNode; v: ReactNode; why?: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{k}</span>
      <span className="cp-num" style={{ fontSize: 14, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{v}</span>
      {why && <span style={noteStyle}>{why}</span>}
    </div>
  );
}

/** The word for a number of sessions. */
export const sessions = (n: number | null | undefined) => (n == null ? DASH : `${n} session${n === 1 ? "" : "s"}`);

/** The cash candidate family built from a Chartink scan hit: its levels are rules, and the scan itself is not validated. */
export const CHARTINK_FAMILY = "chartink_screen_signal";
export const CHARTINK_CANDIDATE_NOTE = "Rule-based levels; Chartink scan, not validated.";
