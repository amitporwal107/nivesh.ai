/**
 * Small presentational pieces shared by the Markets, Research, Screener,
 * Watchlist and Saved screens. Layout follows design/nivesh-copilot/NVTools and
 * NVPages; every value shown comes from the caller.
 */
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { ZodError } from "zod";
import { ApiError } from "@/services/api/errors";
import { StockName } from "../../components/EntityIcon";
import { ErrorBlock, Pill, TONE_COLOR, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { sourceLabel, stampLabel } from "./format";

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

/**
 * Where a block's figures came from and how fresh they are, using only what
 * the response said. A response that names no source gets no source claim;
 * admins are told the response did not state one.
 */
export function SourceLine({ source, asOf, asOfLabel = "as of", note, quiet, testId, style }: {
  /** Source name or code from the response (one or several). */
  source?: string | string[] | null;
  /** A date or date-time from the response. */
  asOf?: string | null;
  /** Words before the stamp ("as of", "updated", "generated"). */
  asOfLabel?: string;
  /** Anything else worth saying on the same line. */
  note?: ReactNode;
  /** A block that shares its response with a neighbour which already carries the source remark. */
  quiet?: boolean;
  testId?: string;
  style?: CSSProperties;
}) {
  const { isAdmin } = useCopilotShell();
  const names = (Array.isArray(source) ? source : [source]).map((x) => sourceLabel(x)).filter(Boolean);
  const stamp = stampLabel(asOf);
  const parts: ReactNode[] = [];
  if (names.length) parts.push(<span key="src" data-testid="source-name">Source: {names.join(" · ")}</span>);
  else if (isAdmin && !quiet) parts.push(<span key="src" data-testid="source-unstated" title="Shown to admins only">Source not stated in the response</span>);
  if (stamp) parts.push(<span key="asof" data-testid="source-asof">{asOfLabel} {stamp}</span>);
  if (note) parts.push(<span key="note">{note}</span>);
  if (!parts.length) return null;
  return (
    <div data-testid={testId} className="cp-mono-note flex flex-wrap" style={{ gap: "2px 10px", lineHeight: 1.6, ...style }}>
      {parts}
    </div>
  );
}

/**
 * The first cell of a row that names a listed company: its icon, its name, the
 * symbol on the second line, and a badge when the user holds it. A row with no
 * symbol keys its icon by the company name.
 */
export function CompanyCell({ symbol, name, sub, held, testId }: {
  symbol?: string | null;
  name?: string | null;
  /** Replaces the symbol on the second line. */
  sub?: ReactNode;
  held?: boolean;
  testId?: string;
}) {
  const key = (symbol ?? "").trim() || (name ?? "").trim();
  if (!key) return <span style={{ color: "var(--cp-ink-3)" }}>—</span>;
  return (
    <span className="inline-flex items-center" style={{ gap: 8, maxWidth: "100%", minWidth: 0 }}>
      <StockName symbol={key} name={name} sub={sub} testId={testId} />
      {held && <Pill tone="mint" title="This company is in your holdings">You hold</Pill>}
    </span>
  );
}

/** One announcement: who it is about, what it is, a line of detail, then where it came from. */
export function AnnouncementCard({ company, tag, tone = "ink", title, when, body, footer, askQuery, href, testId }: {
  /** The company the announcement names (a CompanyCell), when it names one. */
  company?: ReactNode;
  tag: string;
  tone?: Tone;
  title: ReactNode;
  when?: ReactNode;
  body?: ReactNode;
  /** Quiet facts under the body: source, reading time. */
  footer?: ReactNode;
  askQuery: string;
  /** Source document, opened in a new tab. */
  href?: string | null;
  testId?: string;
}) {
  return (
    <article data-testid={testId} className="cp-card flex min-w-0 flex-col" style={{ gap: 8, padding: "14px 18px" }}>
      {(company || when) && (
        <div className="flex flex-wrap items-center justify-between" style={{ gap: "6px 12px" }}>
          <span className="min-w-0" style={{ fontSize: 13 }}>{company}</span>
          {when && <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>{when}</span>}
        </div>
      )}
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Pill tone={tone}>{tag}</Pill>
        <span style={{ flex: "1 1 200px", minWidth: 0, fontSize: 14, fontWeight: 500, overflowWrap: "anywhere" }}>{title}</span>
      </div>
      {body && <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{body}</span>}
      <div className="flex flex-wrap items-center" style={{ gap: "4px 16px" }}>
        <AskLink query={askQuery}>Ask Copilot about this ›</AskLink>
        {href && (
          <a className="cp-link" href={href} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12 }}>Open the filing ↗</a>
        )}
        {footer && <span className="cp-mono-note" style={{ marginLeft: "auto" }}>{footer}</span>}
      </div>
    </article>
  );
}

/** A trend line for a short series of closes. Decorative: the figures sit beside it. */
export function Sparkline({ values, tone = "ink", height = 22, testId }: { values: number[]; tone?: Tone; height?: number; testId?: string }) {
  const pts = values.filter((v) => Number.isFinite(v));
  if (pts.length < 2) return null;
  const min = Math.min(...pts);
  const range = Math.max(...pts) - min || 1;
  const points = pts
    .map((v, i) => `${((i / (pts.length - 1)) * 100).toFixed(1)},${(height - 1 - ((v - min) / range) * (height - 2)).toFixed(1)}`)
    .join(" ");
  return (
    <svg data-testid={testId} aria-hidden viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ display: "block", width: "100%", height }}>
      <polyline fill="none" stroke={tone === "ink" ? "var(--cp-ink-3)" : TONE_COLOR[tone]} strokeWidth="1.5" points={points} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const fieldStyle: CSSProperties = {
  padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)",
  color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13, minWidth: 0,
};

/** A labelled text, search or date input. */
export function Field({ label, value, onChange, type = "text", placeholder, min, max, testId, grow }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "search" | "date";
  placeholder?: string;
  min?: string;
  max?: string;
  testId?: string;
  /** Take the remaining width of the row. */
  grow?: boolean;
}) {
  return (
    <label className="flex min-w-0 flex-col" style={{ gap: 4, flex: grow ? "1 1 220px" : "0 1 auto" }}>
      <span className="cp-mono-note">{label}</span>
      <input
        type={type}
        value={value}
        min={min}
        max={max}
        placeholder={placeholder}
        data-testid={testId}
        onChange={(e) => onChange(e.target.value)}
        style={fieldStyle}
      />
    </label>
  );
}

/** A labelled drop-down. */
export function SelectField({ label, value, onChange, children, testId }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <label className="flex min-w-0 flex-col" style={{ gap: 4 }}>
      <span className="cp-mono-note">{label}</span>
      <select value={value} data-testid={testId} onChange={(e) => onChange(e.target.value)} style={{ ...fieldStyle, maxWidth: "100%" }}>
        {children}
      </select>
    </label>
  );
}

/** A small figure with its label underneath, for a block that shows several side by side. */
export function Stat({ label, value, tone = "ink", testId }: { label: string; value: ReactNode; tone?: Tone; testId?: string }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <span data-testid={testId} className="cp-num" style={{ fontSize: 17, color: TONE_COLOR[tone] }}>{value}</span>
      <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{label}</span>
    </div>
  );
}

/** Brings a panel into view when it opens or its subject changes (a row opened far down a table). */
export function useReveal<T extends HTMLElement>(subject: string) {
  const ref = useRef<T>(null);
  useEffect(() => {
    ref.current?.scrollIntoView({ block: "nearest" });
  }, [subject]);
  return ref;
}

/** A value that settles after the user stops typing, so a search box does not refetch on every key. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}
