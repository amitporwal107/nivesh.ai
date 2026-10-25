/**
 * F&O lab — pieces shared by the seven screens (design: docs/ai_research/designs/Nivesh F&O Desk (1).html).
 *
 * The product implements the design's "today" state only: every value comes from an endpoint, and a part that is not
 * built says so with its backlog tag (PRD v2.1 §24) instead of showing sample numbers. The design's "target" state is
 * not implemented, because illustrative numbers inside the product would read as real data.
 */
import type { CSSProperties, ReactNode } from "react";
import { TONE_COLOR, type Tone } from "../../components/ui";

export type LabScreenId = "mi" | "prog" | "replay" | "shadow" | "live" | "cert" | "audit";
export type LabMode = "research" | "governance" | "shadow" | "live-disabled";

export interface LabScreenMeta {
  id: LabScreenId;
  /** The screen's number in PRD §15.1. */
  n: string;
  label: string;
  /** Tab label at phone width. */
  short: string;
  sub: string;
  mode: LabMode;
}

export const LAB_SCREENS: LabScreenMeta[] = [
  { id: "mi", n: "01", label: "Market Intelligence", short: "Market", mode: "research",
    sub: "Regime, futures build-up per expiry, the options chain and quote quality, each with its source and time." },
  { id: "prog", n: "05", label: "Strategy Programs", short: "Programs", mode: "governance",
    sub: "The strategy templates the desk can price today, and a dry run that prices one without sending anything." },
  { id: "replay", n: "06", label: "Historical Replay Lab", short: "Replay", mode: "research",
    sub: "Options backtests on point-in-time data, judged against baselines and a sealed out-of-sample window." },
  { id: "shadow", n: "08", label: "Shadow Mode Monitor", short: "Shadow", mode: "shadow",
    sub: "Decisions on live market data that never reach a broker." },
  { id: "live", n: "09", label: "Live Trading Desk", short: "Live", mode: "live-disabled",
    sub: "The live readiness gate: what must be true before any live order, and where each condition stands." },
  { id: "cert", n: "11", label: "Agent Certification Center", short: "Certification", mode: "governance",
    sub: "Scoped, versioned authorisation for an exact agent, strategy, universe, broker and risk policy." },
  { id: "audit", n: "12", label: "Audit & Decision Replay", short: "Audit", mode: "research",
    sub: "Every recorded risk decision, what it is linked to, and the append-only record of control changes." },
];

export const isLabScreen = (v: string | null): v is LabScreenId => LAB_SCREENS.some((s) => s.id === v);

const MODE: Record<LabMode, { label: string; detail: string; bg: string; fg: string }> = {
  research: { label: "Research", detail: "Read-only analysis. No ledger and no orders.", bg: "var(--bg-3)", fg: "var(--cp-ink)" },
  governance: { label: "Governance", detail: "Read-only. Changes to programs and certifications need human approval.", bg: "var(--bg-3)", fg: "var(--cp-ink)" },
  shadow: { label: "Shadow mode", detail: "Live market data. Decisions are recorded and never sent to a broker.", bg: "var(--amber)", fg: "var(--bg-0)" },
  "live-disabled": { label: "Live · disabled", detail: "No order path exists in this build. Nivesh places no orders.", bg: "var(--bg-4)", fg: "var(--cp-ink-2)" },
};

/** The coloured strip at the top of every screen. */
export function ModeBand({ mode }: { mode: LabMode }) {
  const m = MODE[mode];
  return (
    <div data-testid="fnolab-mode" data-mode={mode} className="flex flex-wrap items-center" style={{ gap: "6px 14px", padding: "8px 16px", borderRadius: 10, background: m.bg, color: m.fg }}>
      <span style={{ fontFamily: "var(--mono)", fontSize: 11, fontWeight: 500, letterSpacing: "0.16em", textTransform: "uppercase" }}>{m.label}</span>
      <span style={{ fontSize: 12.5, flex: "1 1 220px" }}>{m.detail}</span>
    </div>
  );
}

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

/**
 * A part of the design that is not built yet. Unlike NotConnected, the backlog tag is shown to everyone: the design puts
 * it on the screen so a reader can see what closes the gap.
 */
export function GapNote({ tag, title, children, testId = "fnolab-gap" }: { tag: string; title: ReactNode; children?: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} data-tag={tag} className="flex flex-col items-start" style={{ gap: 8, padding: "16px 18px", borderRadius: 14, border: "1px dashed var(--line-3)", background: "var(--bg-1)" }}>
      <span className="cp-pill" data-tone="amber">Not built yet · {tag}</span>
      <span style={{ fontFamily: "var(--display)", fontSize: 21, lineHeight: 1.2 }}>{title}</span>
      {children && <div style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 680 }}>{children}</div>}
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
export const monoNote: CSSProperties = { fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.04em", color: "var(--cp-ink-3)" };
