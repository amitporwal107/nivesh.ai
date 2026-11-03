/**
 * What every block of the visual answer shares: its frame (title, note), a guard so one block that fails to draw
 * never takes the answer down, and the notes shown instead of a block that cannot be drawn.
 */
import { Component, type CSSProperties, type ReactNode } from "react";

export const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
export const axisText: CSSProperties = { fontFamily: "var(--mono)", fontSize: 10, fill: "var(--cp-ink-3)" };

/** One action a block can ask for: a follow-up question in words (the chat's own ask path). */
export type Ask = (query: string) => void;

export interface BlockProps<B> {
  b: B;
  /** The desk dock's narrow, tighter layout. */
  compact: boolean;
  /** Ask the Copilot a follow-up question; absent when the host cannot ask (then buttons are disabled). */
  ask?: Ask;
}

export function BlockFrame({ type, id, title, note, children }: { type: string; id?: string; title?: string | null; note?: string | null; children: ReactNode }) {
  return (
    <section data-testid="va-block" data-type={type} data-block-id={id ?? ""} className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      {title && <h4 data-testid="va-block-title" className="cp-eyebrow m-0" style={{ fontWeight: 400, fontSize: 9.5, color: "var(--cp-ink-3)" }}>{title}</h4>}
      {children}
      {note && <span data-testid="va-block-note" style={quiet}>{note}</span>}
    </section>
  );
}

/** A block this build cannot draw: said in one short line, never a crash. */
export function BlockNote({ testId, children }: { testId: string; children: ReactNode }) {
  return (
    <span data-testid={testId} role="note" style={{ ...quiet, padding: "6px 10px", borderRadius: 8, border: "1px dashed var(--line-2)" }}>
      {children}
    </span>
  );
}

/** Catches a block that throws while drawing; the rest of the answer still shows. */
export class BlockGuard extends Component<{ type: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    // Not swallowed: the console keeps the reason; the reader sees which part could not be drawn.
    console.error(`visual answer: the ${this.props.type} block failed to draw`, error);
  }
  render() {
    if (this.state.failed) return <BlockNote testId="va-block-failed">This part of the answer ({this.props.type}) could not be drawn.</BlockNote>;
    return this.props.children;
  }
}
