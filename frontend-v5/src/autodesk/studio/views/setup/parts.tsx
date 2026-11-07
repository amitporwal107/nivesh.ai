/**
 * Building blocks of the New simulation view, copied from the design's markup (SimSetup.dc.html): a numbered section
 * card, a labelled row of option chips, the chip itself (the design's ch()), and a note for what Phase 1 does not do.
 */
import type { CSSProperties, KeyboardEvent, ReactNode } from "react";

export function SetupSection({ n, t, s, right, children, testId }: { n: string; t: string; s?: ReactNode; right?: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <section data-testid={testId} style={{ display: "flex", flexDirection: "column", gap: 12, padding: "16px 18px", borderRadius: 14, border: "1px solid var(--line)", background: "var(--bg-1)", minWidth: 0 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
        <span style={{ fontFamily: "var(--display)", fontSize: 20, color: "var(--ink-4)" }}>{n}</span>
        <span data-testid="setup-section-title" style={{ fontSize: 15, fontWeight: 500, flex: 1 }}>{t}</span>
        {s != null && <span style={{ fontSize: 12, color: "var(--ink-3)" }}>{s}</span>}
        {right}
      </div>
      {children}
    </section>
  );
}

export function SetupRow({ k, children, testId }: { k: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} style={{ display: "flex", flexWrap: "wrap", gap: "8px 12px", alignItems: "center" }}>
      <span style={{ fontSize: 12.5, color: "var(--ink-3)", minWidth: 150 }}>{k}</span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, flex: 1, minWidth: 0, alignItems: "center" }}>{children}</div>
    </div>
  );
}

/** One option chip: selected = indigo line + soft background, as the design's ch(). Disabled chips keep their place. */
export function Opt({ on, t, sub, onPick, rad = "999px", disabled, testId, title }: {
  on: boolean; t: ReactNode; sub?: ReactNode; onPick?: () => void; rad?: string; disabled?: boolean; testId?: string; title?: string;
}) {
  const act = () => { if (!disabled && onPick) onPick(); };
  const style: CSSProperties = {
    cursor: disabled ? "not-allowed" : onPick ? "pointer" : "default", padding: "7px 12px", borderRadius: rad,
    border: `1px solid ${on ? "var(--indigo-line)" : "var(--line-2)"}`, background: on ? "var(--indigo-soft)" : "transparent",
    color: on ? "var(--ink)" : "var(--ink-2)", fontSize: 12.5, display: "flex", flexDirection: "column", gap: 2, opacity: disabled ? 0.5 : 1,
  };
  return (
    <span role="button" tabIndex={disabled ? -1 : 0} aria-pressed={on} aria-disabled={disabled || undefined} data-testid={testId} title={title} style={style}
      onClick={act} onKeyDown={(e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(); } }}>
      <span>{t}</span>
      {sub != null && sub !== "" && <span style={{ fontSize: 11, color: "var(--ink-3)" }}>{sub}</span>}
    </span>
  );
}

/** For settings the design shows that Phase 1 does not have and no phase of the plan names (DESIGN.md §6.5). */
export function NotInPhase1({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId ?? "not-in-phase1"} style={{ display: "flex", gap: 10, alignItems: "baseline", padding: "10px 12px", borderRadius: 10, border: "1px dashed var(--line-3)", fontSize: 12.5, lineHeight: 1.5, color: "var(--ink-3)" }}>
      <span className="nv-pill" style={{ padding: "2px 8px", fontSize: 9.5, flex: "none" }}>Not in Phase 1</span>
      <span>{children}</span>
    </div>
  );
}

export const field: CSSProperties = { padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 13, minWidth: 0, fontFamily: "var(--sans)" };
