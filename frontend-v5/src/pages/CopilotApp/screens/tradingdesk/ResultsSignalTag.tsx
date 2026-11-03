/**
 * Smart trading desk — the results chip on an AI scanner setup (owner requirement 2026-10-27: "show extra strength signal
 * for strong-results candidate stocks in the AI scanner").
 *
 * The scanner routes (GET /api/positional/watchlist, /picks) send `results_signal` {strength, points, basis, reasons,
 * filed_at, sessions_since} and `base_final_score`; `final_score` already includes the points (desk-data.ts
 * parseResultsSignal). The chip reads "Strong results +10" (mint) or "Weak results −10" (danger), with "· figures pending"
 * when the adjustment came from the filing analysis because the figures are not filed yet. It opens (a native
 * details/summary, keyboard reachable) to the reasons and "score X = technical Y + results Z"; its title carries the same
 * for hover. No signal (or an older route without the field) renders nothing.
 *
 * Wording (SEBI): a provisional results adjustment, not yet tested; never advice.
 */
import type { CSSProperties } from "react";
import { fmtNum } from "../../components/ui";
import type { ResultsSignal } from "./desk-data";

const MINUS = "−";
const pts = (n: number) => `${n > 0 ? "+" : n < 0 ? MINUS : ""}${fmtNum(Math.abs(n), Number.isInteger(n) ? 0 : 1)}`;

/** "Strong results +10" · "Weak results −10" · "… · figures pending". */
export function resultsSignalText(s: ResultsSignal): string {
  const head = `${s.strength === "strong" ? "Strong" : "Weak"} results${s.points != null ? ` ${pts(s.points)}` : ""}`;
  return s.basis === "filing_analysis" ? `${head} · figures pending` : head;
}

/** "score 82 = technical 72 + results +10"; null when the parts are not all known. */
export function resultsSignalSum(s: ResultsSignal, score: number | null | undefined, baseScore: number | null | undefined): string | null {
  if (s.points == null) return null;
  if (score == null || baseScore == null) return `results ${pts(s.points)} is inside the score`;
  return `score ${fmtNum(score, 0)} = technical ${fmtNum(baseScore, 0)} + results ${pts(s.points)}`;
}

export function ResultsSignalTag({ signal, score, baseScore, testId = "results-signal", style }: {
  signal: ResultsSignal | null | undefined; score?: number | null; baseScore?: number | null; testId?: string; style?: CSSProperties;
}) {
  if (!signal) return null;
  const strong = signal.strength === "strong";
  const c = strong ? "var(--mint)" : "var(--cp-danger)";
  const text = resultsSignalText(signal);
  const sum = resultsSignalSum(signal, score, baseScore);
  const when = [
    signal.basis === "filing_analysis" ? "From the filing analysis: the figures are not filed yet" : signal.basis === "figures" ? "From the filed figures" : null,
    signal.filedAt ? `filed ${signal.filedAt.slice(0, 16).replace("T", " ")}` : null,
    signal.sessionsSince != null ? `${fmtNum(signal.sessionsSince)} session${signal.sessionsSince === 1 ? "" : "s"} since` : null,
  ].filter(Boolean).join(" · ");
  const title = [text, ...signal.reasons, sum, "Provisional results adjustment, not yet tested."].filter(Boolean).join("\n");
  return (
    // The chip sits inside clickable rows: opening it must not open the row.
    <details data-testid={testId} data-strength={signal.strength} data-points={signal.points ?? undefined} onClick={(e) => e.stopPropagation()}
      style={{ display: "inline-block", maxWidth: "100%", verticalAlign: "middle", ...style }}>
      <summary data-testid={`${testId}-chip`} title={title} aria-label={`${text}. Show why`}
        style={{
          display: "inline-flex", alignItems: "center", gap: 5, maxWidth: "100%", cursor: "pointer", listStyle: "none", whiteSpace: "nowrap",
          fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.04em", padding: "2px 8px", borderRadius: 999,
          color: c, border: `1px solid ${strong ? "var(--mint-line)" : "var(--danger-line)"}`, background: strong ? "var(--mint-soft)" : "var(--cp-danger-soft)",
        }}>
        <span aria-hidden style={{ fontSize: 9 }}>{strong ? "▲" : "▼"}</span>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{text}</span>
      </summary>
      <div data-testid={`${testId}-detail`} style={{ marginTop: 6, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)", whiteSpace: "normal", maxWidth: 420 }}>
        {signal.reasons.length ? (
          <ul className="m-0" style={{ paddingLeft: 16 }}>{signal.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        ) : <span style={{ color: "var(--cp-ink-3)" }}>The route sent no reasons.</span>}
        {sum && <div data-testid={`${testId}-sum`} className="cp-num" style={{ marginTop: 4, color: "var(--cp-ink)" }}>{sum}</div>}
        {when && <div style={{ marginTop: 2, color: "var(--cp-ink-3)", fontSize: 11.5 }}>{when}</div>}
        <div style={{ marginTop: 2, color: "var(--cp-ink-3)", fontSize: 11.5 }}>Provisional results adjustment, not yet tested.</div>
      </div>
    </details>
  );
}
