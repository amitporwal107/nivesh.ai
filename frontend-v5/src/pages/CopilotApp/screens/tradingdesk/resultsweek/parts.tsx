/**
 * Smart trading desk · Results week — small shared pieces: the verdict pill, signed percents, the "not available" word,
 * the build-up word and the type styles the Events calendar already uses (mono eyebrows, the desk's colour tokens).
 */
import type { CSSProperties, ReactNode } from "react";
import { INTENSITY_WORD, VERDICT_WORD, buildupHeadline, type Intensity, type RwBuildup, type Verdict } from "./results-week-data";

export const MINUS = "−";
export const mono: CSSProperties = { fontFamily: "var(--mono)" };
export const eyebrow: CSSProperties = { ...mono, fontSize: 9.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--cp-ink-3)" };
export const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
export const line = "1px solid var(--cp-line)";

/** "+1.2%" / "−3.4%" / "0.0%"; null is never formatted (callers show <NA/>). */
export const sg = (v: number, dp = 1) => `${v >= 0.05 ? "+" : v <= -0.05 ? MINUS : ""}${Math.abs(v).toFixed(dp)}%`;
export const toneOf = (v: number | null | undefined) => (v == null ? "var(--cp-ink-3)" : v >= 0.05 ? "var(--mint)" : v <= -0.05 ? "var(--cp-danger)" : "var(--cp-ink-2)");

/** Missing data: said in words, never a zero and never a neutral reading. */
export function NA({ text = "not available", testId }: { text?: string; testId?: string }) {
  return <span data-testid={testId} data-na="1" style={{ fontSize: 11.5, color: "var(--cp-ink-3)", fontStyle: "italic" }}>{text}</span>;
}

export function Pct({ v, dp = 1, na = "not available", testId, suffix }: { v: number | null | undefined; dp?: number; na?: string; testId?: string; suffix?: ReactNode }) {
  if (v == null) return <NA text={na} testId={testId} />;
  return <span data-testid={testId} className="cp-num" style={{ color: toneOf(v), whiteSpace: "nowrap" }}>{sg(v, dp)}{suffix}</span>;
}

const VERDICT_STYLE: Record<Verdict | "none", { c: string; bg: string; b: string }> = {
  above: { c: "var(--mint)", bg: "var(--mint-soft)", b: "var(--mint-line)" },
  in_line: { c: "var(--cp-ink-2)", bg: "transparent", b: "var(--line-2)" },
  below: { c: "var(--cp-danger)", bg: "var(--cp-danger-soft)", b: "var(--danger-line)" },
  none: { c: "var(--cp-ink-3)", bg: "transparent", b: "var(--line-2)" },
};

/** The headline verdict vs historical trend. "Outstanding" / "Well below" are the route's intensity, shown as a stronger pill. */
export function verdictText(label: Verdict | null, intensity: Intensity | null): string {
  if (!label) return "Not rated";
  if (intensity === "outstanding" && label === "above") return `${VERDICT_WORD.above} · ${INTENSITY_WORD.outstanding}`;
  if (intensity === "well_below" && label === "below") return INTENSITY_WORD.well_below;
  return VERDICT_WORD[label];
}

export function VerdictPill({ label, intensity, reason, testId, small }: { label: Verdict | null; intensity: Intensity | null; reason?: string | null; testId?: string; small?: boolean }) {
  const s = VERDICT_STYLE[label ?? "none"];
  const strong = (intensity === "outstanding" && label === "above") || (intensity === "well_below" && label === "below");
  const title = label
    ? `${verdictText(label, intensity)} vs historical trend (the company’s own past quarters), not analyst consensus`
    : reason ?? "Not rated: no reliable baseline";
  return (
    <span
      data-testid={testId}
      data-verdict={label ?? "none"}
      data-intensity={intensity ?? undefined}
      title={title}
      style={{
        display: "inline-flex", alignItems: "center", gap: 5, whiteSpace: "nowrap", ...mono, fontSize: small ? 9 : 9.5, letterSpacing: "0.1em", textTransform: "uppercase",
        padding: small ? "2px 7px" : "3px 9px", borderRadius: 999, color: s.c, background: strong ? s.bg : "transparent",
        border: `1px ${label ? "solid" : "dashed"} ${strong ? s.c : s.b}`, fontWeight: strong ? 600 : 400,
      }}
    >
      {verdictText(label, intensity)}
    </span>
  );
}

/** The row's OI chip: the F&O block's headline ("Fresh long build-up · OI +9.6%"); "not F&O" / "not available" otherwise. */
export function BuildupText({ b, fno, testId }: { b: RwBuildup | null; fno: boolean | null; testId?: string }) {
  if (fno === false) return <NA text="not F&O" testId={testId} />;
  if (!b || (b.state == null && b.oiChange == null && !b.text)) return <NA testId={testId} />;
  const h = buildupHeadline(b);
  const c = h.tone === "up" ? "var(--mint)" : h.tone === "down" ? "var(--cp-danger)" : "var(--cp-ink-2)";
  return <span data-testid={testId} title={b.why ?? undefined} style={{ fontSize: 12, color: c, whiteSpace: "nowrap" }}>{h.text}</span>;
}

export function Chip({ children, testId, title, tone = "ink" }: { children: ReactNode; testId?: string; title?: string; tone?: "ink" | "mint" | "amber" | "muted" }) {
  const c = tone === "mint" ? "var(--mint)" : tone === "amber" ? "var(--amber)" : tone === "muted" ? "var(--cp-ink-3)" : "var(--cp-ink-2)";
  const b = tone === "mint" ? "var(--mint-line)" : tone === "amber" ? "var(--amber-line)" : "var(--line-2)";
  return (
    <span data-testid={testId} title={title} style={{ display: "inline-flex", alignItems: "center", maxWidth: "100%", ...mono, fontSize: 9.5, letterSpacing: "0.06em", padding: "2px 7px", borderRadius: 6, border: `1px solid ${b}`, color: c, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
/** "Mon 27 Oct" from YYYY-MM-DD (calendar arithmetic in UTC, as the Events calendar does). */
export const fmtD = (iso: string | null) => {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isFinite(d.getTime()) ? `${DOW[d.getUTCDay()]} ${d.getUTCDate()} ${MON[d.getUTCMonth()]}` : "—";
};
export const addDays = (iso: string, n: number) => { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
export const mondayOf = (iso: string) => addDays(iso, -((new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7));
