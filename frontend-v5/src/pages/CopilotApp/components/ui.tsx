/**
 * Copilot app — shared building blocks for every screen in the shell.
 *
 * Colours: use the --cp-* aliases from copilot-app.css (var(--cp-line),
 * var(--cp-ink-2), var(--cp-danger), var(--cp-indigo)) or Tailwind's token
 * classes (text-ink-2, border-hairline). The bare --line / --ink-* / --danger /
 * --indigo variables hold "R G B" triplets in this app and are NOT colours.
 * --mint, --amber, --bg-0…--bg-4, --line-2, --line-3 and the *-soft / *-line
 * variables are real colours and can be used directly.
 *
 * Data: screens show real data from existing hooks, or one of the honest states
 * below (LoadingBlock / ErrorBlock / EmptyBlock / NotConnected). The design's
 * sample figures are never rendered.
 */
import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/utils";
import { ApiError } from "@/services/api/errors";
import { useCopilotShell } from "../lib/shell-context";

export type Tone = "mint" | "amber" | "indigo" | "danger" | "ink";

export const TONE_COLOR: Record<Tone, string> = {
  mint: "var(--mint)",
  amber: "var(--amber)",
  indigo: "var(--cp-indigo)",
  danger: "var(--cp-danger)",
  ink: "var(--cp-ink)",
};

// ── formatting ───────────────────────────────────────────────────────────

const DASH = "—";
const inFmt = new Intl.NumberFormat("en-IN");

/** ₹ value from RUPEES (not paise). null/undefined/NaN → "—". */
export function fmtINR(rupees: number | null | undefined, opts: { compact?: boolean; signed?: boolean } = {}): string {
  if (rupees == null || !Number.isFinite(rupees)) return DASH;
  const abs = Math.abs(rupees);
  const sign = rupees < 0 ? "−" : opts.signed && rupees > 0 ? "+" : "";
  if (opts.compact) {
    if (abs >= 1_00_00_000) return `${sign}₹${(abs / 1_00_00_000).toFixed(2)} Cr`;
    if (abs >= 1_00_000) return `${sign}₹${(abs / 1_00_000).toFixed(2)} L`;
    if (abs >= 1_000) return `${sign}₹${(abs / 1_000).toFixed(1)}k`;
  }
  return `${sign}₹${inFmt.format(Math.round(abs))}`;
}

/** Percent from a value already in percent units (12.4 → "12.4%"). */
export function fmtPct(pct: number | null | undefined, opts: { signed?: boolean; digits?: number } = {}): string {
  if (pct == null || !Number.isFinite(pct)) return DASH;
  const d = opts.digits ?? 1;
  const sign = pct < 0 ? "−" : opts.signed && pct > 0 ? "+" : "";
  return `${sign}${Math.abs(pct).toFixed(d)}%`;
}

export function fmtNum(n: number | null | undefined, digits = 0): string {
  if (n == null || !Number.isFinite(n)) return DASH;
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
}

/** Mint for gains, danger for losses, neutral otherwise. */
export function signTone(n: number | null | undefined): Tone {
  if (n == null || !Number.isFinite(n) || n === 0) return "ink";
  return n > 0 ? "mint" : "danger";
}

/** "2m ago", "3h ago", "4d ago", then a date. Empty string for a bad input. */
export function relTime(iso?: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const mins = Math.round((Date.now() - t) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(t).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function fmtDate(iso?: string | null): string {
  if (!iso) return DASH;
  // "2026-10-12" is a calendar day: parse it as local so it never shows the
  // previous day west of UTC.
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const t = day ? new Date(+day[1], +day[2] - 1, +day[3]) : new Date(iso);
  if (!Number.isFinite(t.getTime())) return DASH;
  return t.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** "risk_diversification" → "Risk diversification". Empty string for nothing. */
export function humaniseTag(id?: string | null): string {
  if (!id) return "";
  const s = String(id).replace(/[_-]+/g, " ").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : "";
}

// ── layout ───────────────────────────────────────────────────────────────

/** Page container for a tool / workspace screen. */
export function Screen({ children, width = 1040, testId }: { children: ReactNode; width?: number; testId?: string }) {
  const { mobile } = useCopilotShell();
  return (
    <div
      data-testid={testId}
      className="mx-auto flex flex-col"
      style={{ maxWidth: width, gap: mobile ? 22 : 28, padding: `${mobile ? 24 : 44}px 0 40px` }}
    >
      {children}
    </div>
  );
}

/** Eyebrow + pills, serif headline, one-paragraph sub. Wrap the accent word in <em>. */
export function ScreenHeader({ eyebrow, pills, title, sub }: { eyebrow?: ReactNode; pills?: ReactNode; title: ReactNode; sub?: ReactNode }) {
  const { mobile } = useCopilotShell();
  return (
    <header className="flex flex-col" style={{ gap: 12 }}>
      {(eyebrow || pills) && (
        <span className="flex flex-wrap items-center" style={{ gap: 10 }}>
          {eyebrow && <span className="cp-eyebrow">{eyebrow}</span>}
          {pills}
        </span>
      )}
      <h1 className="cp-display m-0" style={{ fontSize: mobile ? 34 : 46, lineHeight: 1.05 }}>{title}</h1>
      {sub && (
        <p className="m-0 cp-pretty" style={{ fontSize: 15, lineHeight: 1.6, color: "var(--cp-ink-2)", maxWidth: 680 }}>{sub}</p>
      )}
    </header>
  );
}

export function Eyebrow({ children, tone, className }: { children: ReactNode; tone?: Tone; className?: string }) {
  return <span className={cn("cp-eyebrow", className)} style={tone ? { color: TONE_COLOR[tone] } : undefined}>{children}</span>;
}

export function Pill({ children, tone = "ink", title }: { children: ReactNode; tone?: Tone; title?: string }) {
  return <span className="cp-pill" data-tone={tone} title={title}>{children}</span>;
}

export function Btn({ variant = "default", className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "primary" | "ghost" }) {
  return <button type="button" {...rest} data-variant={variant} className={cn("cp-btn", className)} />;
}

export interface TileItem {
  k: string;
  v: ReactNode;
  /** One line under the value. */
  s?: ReactNode;
  tone?: Tone;
}

/** A row of headline metrics. */
export function Tiles({ items, min = 150 }: { items: TileItem[]; min?: number }) {
  return (
    <div className="grid" style={{ gridTemplateColumns: `repeat(auto-fit,minmax(${min}px,1fr))`, gap: 12 }}>
      {items.map((m) => (
        <div key={m.k} className="cp-card flex flex-col" style={{ gap: 6, padding: "14px 16px" }}>
          <span className="cp-eyebrow">{m.k}</span>
          <span className="cp-num" style={{ fontSize: 22, color: TONE_COLOR[m.tone ?? "ink"] }}>{m.v}</span>
          {m.s != null && <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{m.s}</span>}
        </div>
      ))}
    </div>
  );
}

/** A titled card. `note` sits at the right of the header (mono, quiet). */
export function Section({ title, note, children, flush, className }: { title?: ReactNode; note?: ReactNode; children: ReactNode; flush?: boolean; className?: string }) {
  return (
    <section className={cn("cp-card flex flex-col min-w-0", className)}>
      {(title || note) && (
        <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "6px 12px", padding: "14px 16px", borderBottom: "1px solid var(--cp-line)" }}>
          {title && <span className="cp-eyebrow">{title}</span>}
          {note && <span className="cp-mono-note">{note}</span>}
        </div>
      )}
      <div className="min-w-0" style={flush ? undefined : { padding: 16 }}>{children}</div>
    </section>
  );
}

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Grid track, e.g. "minmax(0,1.6fr)". Defaults to "minmax(0,1fr)". */
  width?: string;
  align?: "left" | "right";
  /** Mono tabular figures for this column. */
  num?: boolean;
  render: (row: T) => ReactNode;
}

/** Grid table that scrolls sideways on narrow screens instead of squashing. */
export function DataTable<T>({ columns, rows, rowKey, onRowClick, minWidth, empty }: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, i: number) => string;
  onRowClick?: (row: T) => void;
  /** Minimum table width in px before it scrolls. Default: 110px per column. */
  minWidth?: number;
  empty?: ReactNode;
}) {
  const template = columns.map((c) => c.width ?? "minmax(0,1fr)").join(" ");
  const cell = (c: Column<T>): CSSProperties => ({ textAlign: c.align ?? "left", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" });
  if (!rows.length) {
    return <div style={{ padding: 16, fontSize: 13, color: "var(--cp-ink-3)" }}>{empty ?? "Nothing to show."}</div>;
  }
  return (
    <div className="cp-scroll overflow-x-auto" role="table">
      <div style={{ minWidth: minWidth ?? columns.length * 110 }}>
        <div role="row" className="grid" style={{ gridTemplateColumns: template, gap: 12, padding: "10px 16px", borderBottom: "1px solid var(--cp-line)" }}>
          {columns.map((c) => (
            <span key={c.key} role="columnheader" className="cp-mono-note" style={cell(c)}>{c.header}</span>
          ))}
        </div>
        {rows.map((r, i) => (
          <div
            key={rowKey(r, i)}
            role="row"
            tabIndex={onRowClick ? 0 : undefined}
            onClick={onRowClick ? () => onRowClick(r) : undefined}
            onKeyDown={onRowClick ? (e) => { if (e.key === "Enter") onRowClick(r); } : undefined}
            className={cn("grid items-center", onRowClick && "cp-row-link")}
            style={{ gridTemplateColumns: template, gap: 12, padding: "11px 16px", borderBottom: "1px solid var(--cp-line)", fontSize: 13 }}
          >
            {columns.map((c) => (
              <span key={c.key} role="cell" className={c.num ? "cp-num" : undefined} style={{ ...cell(c), whiteSpace: "nowrap", color: "var(--cp-ink-2)" }}>{c.render(r)}</span>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Prompt chips that hand a question to the Copilot. */
export function AskChips({ items, title }: { items: Array<string | { label: string; query: string }>; title?: ReactNode }) {
  const { ask } = useCopilotShell();
  if (!items.length) return null;
  return (
    <div className="flex flex-col" style={{ gap: 10 }}>
      {title && <span className="cp-eyebrow">{title}</span>}
      <div className="flex flex-wrap" style={{ gap: 8 }}>
        {items.map((it) => {
          const label = typeof it === "string" ? it : it.label;
          const query = typeof it === "string" ? it : it.query;
          return <button key={label} type="button" className="cp-chip" onClick={() => ask(query)}>{label}</button>;
        })}
      </div>
    </div>
  );
}

export function Footnote({ children }: { children: ReactNode }) {
  return <span className="cp-mono-note" style={{ lineHeight: 1.6 }}>{children}</span>;
}

// ── honest states ────────────────────────────────────────────────────────

export function LoadingBlock({ label = "Loading", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div role="status" aria-label={label} className="cp-card flex flex-col" style={{ gap: 10, padding: 16 }}>
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} className="cp-running" style={{ height: 14, borderRadius: 6, background: "var(--bg-2)", width: `${92 - i * 14}%` }} />
      ))}
    </div>
  );
}

/** One plain sentence for a failed request. A schema mismatch would otherwise
 *  print the validator's raw issue list. */
export function errorSentence(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof ApiError) {
    switch (error.kind) {
      case "contract_drift": return "the response was not in the expected shape";
      case "forbidden": return "this account does not have access";
      case "auth": return "you are signed out";
      case "not_found": return "nothing was found";
      case "network": return "the network request failed";
      case "timeout": return "the request took too long";
      case "rate_limit": return "too many requests, try again shortly";
      case "server": return "the server reported an error";
      default: return error.detail || error.message;
    }
  }
  return error instanceof Error ? error.message : "";
}

export function ErrorBlock({ title = "This didn’t load", error, onRetry }: { title?: string; error?: unknown; onRetry?: () => void }) {
  const msg = errorSentence(error);
  return (
    <div role="alert" className="flex flex-wrap items-start" style={{ gap: "8px 12px", padding: "12px 16px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--cp-danger-soft)" }}>
      <span className="cp-mono-note" style={{ color: "var(--cp-danger)", paddingTop: 2 }}>Error</span>
      <span style={{ flex: "1 1 240px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
        {title}{msg ? ` — ${msg}` : ""}
      </span>
      {onRetry && <button type="button" onClick={onRetry} style={{ fontSize: 13, color: "var(--cp-ink)", background: "none", border: 0, cursor: "pointer" }}>Retry ›</button>}
    </div>
  );
}

export function EmptyBlock({ title, body, action }: { title: ReactNode; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="cp-card flex flex-col items-start" style={{ gap: 8, padding: "20px 18px" }}>
      <span style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.2 }}>{title}</span>
      {body && <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 560 }}>{body}</span>}
      {action && <div style={{ paddingTop: 6 }}>{action}</div>}
    </div>
  );
}

/**
 * A part of the design that has no data source in the product yet. Says so
 * plainly and lists what it needs, instead of showing sample numbers.
 */
export function NotConnected({ title, body, needs, action, testId }: {
  title: ReactNode;
  body?: ReactNode;
  /** What has to exist before this can show real data (one line each).
   *  Rendered for admins only. */
  needs?: string[];
  action?: ReactNode;
  testId?: string;
}) {
  // The list names what engineering has to build; other users get the plain
  // explanation only.
  const { isAdmin } = useCopilotShell();
  return (
    <div data-testid={testId ?? "not-connected"} className="flex flex-col items-start" style={{ gap: 10, padding: "18px 18px", borderRadius: 14, border: "1px dashed var(--line-3)", background: "var(--bg-1)" }}>
      <span className="cp-pill" data-tone="amber">Not connected yet</span>
      <span style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.2 }}>{title}</span>
      {body && <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 600 }}>{body}</span>}
      {isAdmin && needs && needs.length > 0 && (
        <div data-testid="not-connected-needs" className="flex flex-col" style={{ gap: 6 }}>
          <span className="cp-mono-note">What this needs · shown to admins only</span>
          <ul className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 16, fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            {needs.map((n) => <li key={n}>{n}</li>)}
          </ul>
        </div>
      )}
      {action && <div style={{ paddingTop: 4 }}>{action}</div>}
    </div>
  );
}
