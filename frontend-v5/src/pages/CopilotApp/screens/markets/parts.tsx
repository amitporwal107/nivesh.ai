/**
 * Small presentational pieces shared by the Markets, Research, Screener,
 * Watchlist and Saved screens. Layout follows design/nivesh-copilot/NVTools and
 * NVPages; every value shown comes from the caller.
 */
import type { ReactNode } from "react";
import { ZodError } from "zod";
import { ApiError } from "@/services/api/errors";
import { ErrorBlock, Pill, TONE_COLOR, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";

/**
 * ErrorBlock for a failed read or write. A response that did not match its
 * contract is reported in plain words instead of a schema dump.
 */
export function LoadError({ title, error, onRetry }: { title: string; error: unknown; onRetry?: () => void }) {
  const drift = error instanceof ZodError || (error instanceof ApiError && error.kind === "contract_drift");
  return (
    <ErrorBlock
      title={title}
      error={drift ? "the server’s response was not in the expected format" : error}
      onRetry={onRetry}
    />
  );
}

/** The mint-outlined "Ask Copilot about this ›" pill that sits beside a headline. */
export function AskPill({ query, label = "Ask Copilot about this ›", testId }: { query: string; label?: string; testId?: string }) {
  const { ask } = useCopilotShell();
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={() => ask(query)}
      style={{ padding: "6px 12px", borderRadius: 999, border: "1px solid var(--mint-line)", background: "transparent", color: "var(--mint)", fontSize: 13, cursor: "pointer", fontFamily: "var(--sans)" }}
    >
      {label}
    </button>
  );
}

/** A quiet text link that hands a question to the Copilot. */
export function AskLink({ query, children, testId }: { query: string; children: ReactNode; testId?: string }) {
  const { ask } = useCopilotShell();
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={() => ask(query)}
      style={{ padding: 0, border: 0, background: "none", color: "var(--mint)", fontSize: 12, cursor: "pointer", fontFamily: "var(--sans)", textAlign: "left" }}
    >
      {children}
    </button>
  );
}

export interface TabItem<T extends string> {
  key: T;
  label: string;
}

/** Underlined tab strip; scrolls sideways when it does not fit. */
export function TabBar<T extends string>({ tabs, value, onChange, label, idPrefix }: {
  tabs: TabItem<T>[];
  value: T;
  onChange: (key: T) => void;
  /** Accessible name for the tab list. */
  label: string;
  /** Prefix for each tab's data-testid (`<prefix>-<key>`). */
  idPrefix: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="cp-scroll flex overflow-x-auto" style={{ gap: 24, borderBottom: "1px solid var(--cp-line)" }}>
      {tabs.map((t) => {
        const on = t.key === value;
        return (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={on}
            data-testid={`${idPrefix}-${t.key}`}
            onClick={() => onChange(t.key)}
            style={{
              padding: "10px 0 12px", fontSize: 14, whiteSpace: "nowrap", cursor: "pointer", background: "none", border: 0, flex: "none",
              borderBottom: `2px solid ${on ? "var(--cp-ink)" : "transparent"}`, color: on ? "var(--cp-ink)" : "var(--cp-ink-3)", fontFamily: "var(--sans)",
            }}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

export interface ChipItem<T extends string> {
  key: T;
  label: string;
}

/** A row of single-select filter chips. */
export function FilterChips<T extends string>({ items, value, onChange, label, idPrefix }: {
  items: ChipItem<T>[];
  value: T;
  onChange: (key: T) => void;
  label: string;
  idPrefix: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap" style={{ gap: 6 }}>
      {items.map((c) => {
        const on = c.key === value;
        return (
          <button
            key={c.key}
            type="button"
            aria-pressed={on}
            data-testid={`${idPrefix}-${c.key}`}
            onClick={() => onChange(c.key)}
            style={{
              padding: "6px 12px", borderRadius: 999, fontSize: 12, cursor: "pointer", fontFamily: "var(--sans)",
              border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`,
              color: on ? "var(--mint)" : "var(--cp-ink-2)",
              background: on ? "var(--mint-soft)" : "transparent",
            }}
          >
            {c.label}
          </button>
        );
      })}
    </div>
  );
}

/** The mint "read" card: an eyebrow, one serif sentence and optional bullet lines. */
export function ReadCard({ eyebrow, children, bullets, note, testId }: {
  eyebrow: ReactNode;
  children: ReactNode;
  bullets?: string[];
  note?: ReactNode;
  testId?: string;
}) {
  const { mobile } = useCopilotShell();
  return (
    <div data-testid={testId} className="flex" style={{ gap: 14, padding: mobile ? "16px" : "18px 20px", borderRadius: 14, border: "1px solid var(--mint-line)", background: "var(--mint-soft)" }}>
      <span className="nv-mark" style={{ flex: "none" }} aria-hidden>न</span>
      <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
        <span className="cp-eyebrow" style={{ color: "var(--mint)" }}>{eyebrow}</span>
        <span className="cp-pretty" style={{ fontFamily: "var(--display)", fontSize: mobile ? 20 : 23, lineHeight: 1.25 }}>{children}</span>
        {bullets?.map((b) => (
          <span key={b} style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>· {b}</span>
        ))}
        {note && <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{note}</span>}
      </div>
    </div>
  );
}

/** One announcement / article card with a tag, a title, a line of detail and an ask link. */
export function StoryCard({ tag, tone = "ink", title, meta, body, askQuery, href, testId }: {
  tag: string;
  tone?: Tone;
  title: ReactNode;
  meta?: ReactNode;
  body?: ReactNode;
  askQuery: string;
  /** Source document, opened in a new tab. */
  href?: string | null;
  testId?: string;
}) {
  return (
    <article data-testid={testId} className="cp-card flex flex-col" style={{ gap: 6, padding: "14px 18px" }}>
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Pill tone={tone}>{tag}</Pill>
        <span style={{ flex: "1 1 200px", minWidth: 0, fontSize: 14, fontWeight: 500 }}>{title}</span>
        {meta && <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>{meta}</span>}
      </div>
      {body && <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{body}</span>}
      <div className="flex flex-wrap items-center" style={{ gap: "4px 16px" }}>
        <AskLink query={askQuery}>Ask Copilot about this ›</AskLink>
        {href && (
          <a className="cp-link" href={href} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12 }}>Open the filing ↗</a>
        )}
      </div>
    </article>
  );
}

/** A figure coloured by its sign (mint up, danger down), for a table cell or a tile line. */
export function Signed({ value, children, testId }: { value: number | null | undefined; children: ReactNode; testId?: string }) {
  const tone: Tone = value == null || !Number.isFinite(value) || value === 0 ? "ink" : value > 0 ? "mint" : "danger";
  return (
    <span data-testid={testId} className="cp-num" style={{ color: tone === "ink" ? "var(--cp-ink-2)" : TONE_COLOR[tone] }}>
      {children}
    </span>
  );
}

/** The strong first cell of a table row: a name with an optional quiet suffix and badge. */
export function NameCell({ name, sub, held }: { name: ReactNode; sub?: ReactNode; held?: boolean }) {
  return (
    <span className="inline-flex items-center" style={{ gap: 8, maxWidth: "100%" }}>
      <span style={{ minWidth: 0, color: "var(--cp-ink)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis" }}>{name}</span>
      {sub && <span className="cp-mono-note" style={{ flex: "none" }}>{sub}</span>}
      {held && <Pill tone="mint" title="This company is in your holdings">You hold</Pill>}
    </span>
  );
}
