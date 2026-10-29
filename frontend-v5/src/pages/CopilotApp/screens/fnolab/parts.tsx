/**
 * F&O lab — pieces shared by Audit.tsx and the Risk Desk (design: docs/ai_research/designs/Nivesh F&O Desk (1).html).
 * The lab's frame and its other screens (Programs, Live desk, Kite sessions, Replay, Certification, Shadow, Market
 * Intelligence) were removed in the desk redesign's step 6 (2026-10-27).
 *
 * The product implements the design's "today" state only: every value comes from an endpoint, and a part that is not
 * built says so with its backlog tag (PRD v2.1 §24) instead of showing sample numbers. The design's "target" state is
 * not implemented, because illustrative numbers inside the product would read as real data.
 */
import type { CSSProperties, ReactNode } from "react";
import { TONE_COLOR, type Tone } from "../../components/ui";

export type SourceTone = "mint" | "amber" | "danger" | "ink";

export interface SourceItem {
  /** What the figures are, e.g. "Option chain OI". */
  k: string;
  /** Where they come from and how fresh, or the backlog tag of what is missing. */
  sub: string;
  tone: SourceTone;
}

const DOT: Record<SourceTone, string> = { mint: "var(--mint)", amber: "var(--amber)", danger: "var(--cp-danger)", ink: "var(--cp-ink-3)" };

/** One card per data source: green = real and current, amber = partial or stale, red = not built. */
export function SourceCards({ items, testId = "fnolab-sources" }: { items: SourceItem[]; testId?: string }) {
  return (
    <div data-testid={testId} className="flex flex-wrap" style={{ gap: 8 }}>
      {items.map((f) => (
        <div key={f.k} data-testid="fnolab-source" data-tone={f.tone} className="cp-card flex flex-col" style={{ flex: "1 1 180px", minWidth: 0, gap: 4, padding: "10px 14px" }}>
          <span className="flex items-center" style={{ gap: 8, fontSize: 12.5 }}>
            <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", flex: "none", background: DOT[f.tone] }} />
            {f.k}
          </span>
          <span className="cp-mono-note" style={{ overflowWrap: "anywhere" }}>{f.sub}</span>
        </div>
      ))}
    </div>
  );
}

/** Label / value rows (two columns, wraps on phones). */
export function KvRows({ rows, testId }: { rows: Array<{ k: string; v: ReactNode }>; testId?: string }) {
  return (
    <div data-testid={testId} className="flex flex-col">
      {rows.map((r) => (
        <div key={r.k} className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1.6fr)", gap: 12, padding: "9px 0", borderBottom: "1px solid var(--cp-line)", fontSize: 13 }}>
          <span style={{ color: "var(--cp-ink-3)" }}>{r.k}</span>
          <span style={{ overflowWrap: "anywhere" }}>{r.v}</span>
        </div>
      ))}
    </div>
  );
}

/** A small status mark: ✓ recorded / passed, ✕ failed or missing, ○ not reached. */
export function Mark({ kind }: { kind: "ok" | "fail" | "pend" | "warn" }) {
  const m = { ok: ["✓", "mint"], fail: ["✕", "danger"], pend: ["○", "ink"], warn: ["!", "amber"] }[kind] as [string, Tone];
  const style: CSSProperties = {
    width: 22, height: 22, flex: "none", display: "grid", placeItems: "center", borderRadius: 5,
    border: `1px solid ${kind === "pend" ? "var(--cp-line)" : TONE_COLOR[m[1]]}`, color: kind === "pend" ? "var(--cp-ink-4)" : TONE_COLOR[m[1]],
    fontFamily: "var(--mono)", fontSize: 10.5,
  };
  return <span aria-label={kind} style={style}>{m[0]}</span>;
}

export const quiet: CSSProperties = { fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-3)" };
