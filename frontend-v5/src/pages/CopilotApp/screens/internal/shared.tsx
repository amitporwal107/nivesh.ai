/**
 * Internal (admin) screens — the shared header, the tab strip between the four
 * operations pages, the "this request failed" states (a plain 403, a plain
 * 429), and the small pieces every operations page repeats: a query's
 * loading / failed / empty / loaded switch, in-page tabs, status pills and
 * timestamps.
 * Design: frontend-v5/design/nivesh-copilot/NVOps.dc.html (header + tabs).
 */
import { Fragment, type CSSProperties, type ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "@/services/api/errors";
import { EmptyBlock, ErrorBlock, LoadingBlock, Pill, ScreenHeader, type Column, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";

/** The server refused the request for this account (HTTP 403). */
export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && (error.kind === "forbidden" || error.status === 403);
}

/** The server's per-minute request budget was used up (HTTP 429). */
export function isRateLimited(error: unknown): boolean {
  return error instanceof ApiError && (error.kind === "rate_limit" || error.status === 429);
}

const ADMIN_ONLY = "The server only returns this to admin accounts, and it refused this one (403). Nothing is wrong with the page — sign in with an admin account to see it.";

/**
 * A failed request. A 403 gets a plain explanation (retrying will not help), a
 * 429 says to wait; anything else is an error with a retry.
 */
export function LoadFailed({ what, error, onRetry, forbidden = ADMIN_ONLY }: {
  /** What was being loaded, e.g. "Feed status". */
  what: string;
  error: unknown;
  onRetry: () => void;
  /** The 403 explanation, when the default admin wording does not fit. */
  forbidden?: string;
}) {
  if (isForbidden(error)) {
    return (
      <div data-testid="forbidden" className="cp-card flex flex-col items-start" style={{ gap: 8, padding: "20px 18px" }}>
        <span className="cp-eyebrow">{what}</span>
        <span style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.2 }}>Not available to this account</span>
        <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 560 }}>{forbidden}</span>
      </div>
    );
  }
  if (isRateLimited(error)) {
    return (
      <div data-testid="rate-limited" className="cp-card flex flex-col items-start" style={{ gap: 8, padding: "16px 18px" }}>
        <span className="cp-eyebrow">{what}</span>
        <span style={{ fontSize: 14, lineHeight: 1.5 }}>Too many admin requests in the last minute</span>
        <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 560 }}>
          The server answers ten admin requests a minute for each signed-in session, and these pages went over that. Nothing is broken — wait a minute, then load this again.
        </span>
        <button type="button" className="cp-chip" onClick={onRetry}>Load again ›</button>
      </div>
    );
  }
  return <ErrorBlock title={`${what} didn’t load`} error={readable(error)} onRetry={onRetry} />;
}

/** A shared adapter reports a contract mismatch as a long JSON dump; show one line instead. */
function readable(error: unknown): unknown {
  if (error instanceof ApiError && error.kind === "contract_drift" && error.message.length > 160) {
    return "the server’s answer was not in the expected shape";
  }
  return error;
}

/**
 * One query, one block: skeleton while it loads, LoadFailed when it fails, the
 * empty state when `isEmpty` says so, otherwise the content.
 */
export function QueryBlock<T>({ query, what, rows = 3, forbidden, isEmpty, empty, emptyTestId, children }: {
  query: UseQueryResult<T>;
  /** Names the block in its loading label and its error, e.g. "The prompt list". */
  what: string;
  /** Skeleton lines while loading. */
  rows?: number;
  forbidden?: string;
  isEmpty?: (data: T) => boolean;
  /** Shown when `isEmpty` is true. */
  empty?: { title: ReactNode; body?: ReactNode };
  emptyTestId?: string;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <LoadingBlock label={`Loading ${what.charAt(0).toLowerCase()}${what.slice(1)}`} rows={rows} />;
  if (query.isError) return <LoadFailed what={what} error={query.error} onRetry={() => query.refetch()} forbidden={forbidden} />;
  if (isEmpty?.(query.data) && empty) {
    return <div data-testid={emptyTestId}><EmptyBlock title={empty.title} body={empty.body} /></div>;
  }
  return <>{children(query.data)}</>;
}

/** Eyebrow + "Admins only" pill + headline, as on every internal page. */
export function OpsHeader({ area = "Operations", title, sub }: { area?: string; title: ReactNode; sub?: ReactNode }) {
  return (
    <ScreenHeader
      eyebrow={`Internal · ${area}`}
      pills={<Pill tone="danger">Admins only</Pill>}
      title={title}
      sub={sub}
    />
  );
}

const OPS_TABS: Array<{ view: string; label: string }> = [
  { view: "ops/tools", label: "Tools" },
  { view: "ops/feeds", label: "Feed health" },
  { view: "ops/audit", label: "Audit log" },
  { view: "ops/kpis", label: "KPIs" },
];

function tabStyle(on: boolean) {
  return {
    padding: "7px 14px",
    borderRadius: 999,
    fontFamily: "var(--sans)",
    fontSize: 13,
    cursor: "pointer",
    border: `1px solid ${on ? "var(--line-3)" : "var(--line-2)"}`,
    color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
    background: on ? "var(--bg-3)" : "transparent",
  } as const;
}

/** Moves between the four operations pages. */
export function OpsTabs({ current }: { current: string }) {
  const { go } = useCopilotShell();
  return (
    <nav aria-label="Operations pages" className="flex flex-wrap" style={{ gap: 6 }}>
      {OPS_TABS.map((t) => {
        const on = t.view === current;
        return (
          <button key={t.view} type="button" aria-current={on ? "page" : undefined} onClick={() => go(t.view)} style={tabStyle(on)}>
            {t.label}
          </button>
        );
      })}
    </nav>
  );
}

/**
 * Tabs inside one page. Used where a section has its own request, so that
 * request is made when the section is opened and not on page load (the admin
 * API allows ten requests a minute).
 */
export function SectionTabs<Id extends string>({ label, tabs, current, onChange, testId }: {
  /** Names the group for screen readers. */
  label: string;
  tabs: Array<{ id: Id; label: string }>;
  current: Id;
  onChange: (id: Id) => void;
  testId?: string;
}) {
  return (
    <div role="tablist" aria-label={label} data-testid={testId} className="flex flex-wrap" style={{ gap: 6 }}>
      {tabs.map((t) => {
        const on = t.id === current;
        return (
          <button key={t.id} type="button" role="tab" aria-selected={on} data-tab={t.id} onClick={() => onChange(t.id)} style={{ ...tabStyle(on), borderRadius: 10 }}>
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * DataTable's layout with one difference: a row can be opened, and its detail
 * is drawn directly under it. The detail stays as wide as the visible part of
 * the table (not the scrolled width), so it reads on a phone without scrolling
 * sideways.
 */
export function ExpandableTable<T>({ columns, rows, rowKey, minWidth, openKey, onToggle, renderOpen, openLabel }: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  minWidth: number;
  /** Key of the open row, or null. */
  openKey: string | null;
  onToggle: (row: T) => void;
  renderOpen: (row: T) => ReactNode;
  /** Screen-reader name for a row, e.g. (f) => `Run history of ${f.ingester}`. */
  openLabel: (row: T) => string;
}) {
  const template = columns.map((c) => c.width ?? "minmax(0,1fr)").join(" ");
  const cell = (c: Column<T>): CSSProperties => ({ textAlign: c.align ?? "left", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" });
  return (
    <div className="cp-scroll overflow-x-auto" role="table" style={{ containerType: "inline-size" }}>
      <div style={{ minWidth }}>
        <div role="row" className="grid" style={{ gridTemplateColumns: template, gap: 12, padding: "10px 16px", borderBottom: "1px solid var(--cp-line)" }}>
          {columns.map((c) => (
            <span key={c.key} role="columnheader" className="cp-mono-note" style={cell(c)}>{c.header}</span>
          ))}
        </div>
        {rows.map((r) => {
          const key = rowKey(r);
          const open = key === openKey;
          return (
            <Fragment key={key}>
              <div
                role="row"
                tabIndex={0}
                aria-expanded={open}
                aria-label={openLabel(r)}
                onClick={() => onToggle(r)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(r); } }}
                className="grid items-center cp-row-link"
                style={{ gridTemplateColumns: template, gap: 12, padding: "11px 16px", borderBottom: "1px solid var(--cp-line)", fontSize: 13, background: open ? "var(--bg-2)" : undefined }}
              >
                {columns.map((c) => (
                  <span key={c.key} role="cell" className={c.num ? "cp-num" : undefined} style={{ ...cell(c), whiteSpace: "nowrap", color: "var(--cp-ink-2)" }}>{c.render(r)}</span>
                ))}
              </div>
              {open && (
                <div role="row" style={{ borderBottom: "1px solid var(--cp-line)", background: "var(--bg-2)" }}>
                  <div role="cell" style={{ position: "sticky", left: 0, width: "100cqw", maxWidth: "100%", boxSizing: "border-box", padding: "14px 16px 18px" }}>
                    {renderOpen(r)}
                  </div>
                </div>
              )}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

// ── status and time ──────────────────────────────────────────────────────

/** Tone for the status words the job log and the checks use. */
const STATUS_TONE: Record<string, Tone> = {
  ok: "mint", passed: "mint", pass: "mint", healthy: "mint", success: "mint", gold: "mint", auto_publish: "mint",
  partial: "amber", review: "amber", warn: "amber", backlog: "amber", lagging: "amber", stale: "amber", silver: "amber", denied: "amber", skipped: "ink",
  failed: "danger", error: "danger", block: "danger", reject: "danger",
  running: "indigo",
};

export function statusTone(status?: string | null): Tone {
  return STATUS_TONE[(status ?? "").toLowerCase()] ?? "ink";
}

/** A status word from the backend as a pill; "—" when there is none. */
export function StatusPill({ status, label }: { status?: string | null; label?: string }) {
  if (!status) return <span style={{ color: "var(--cp-ink-4)" }}>—</span>;
  return <Pill tone={statusTone(status)}>{label ?? status.replace(/_/g, " ")}</Pill>;
}

/**
 * Some backend tables store UTC without a zone suffix (Postgres `timestamp`).
 * A bare "2026-10-13T10:11:25" would be read as local time, so mark it UTC.
 */
export function asUtc(iso?: string | null): string | null {
  if (!iso) return null;
  return /T\d{2}:\d{2}/.test(iso) && !/(Z|[+-]\d{2}:?\d{2})$/.test(iso) ? `${iso}Z` : iso;
}

/**
 * "13 Oct, 14:33:08" in the viewer's time zone; "—" for a bad timestamp.
 * Pass `year` where a row can be more than a year old.
 */
export function stamp(iso?: string | null, opts: { year?: boolean } = {}): string {
  if (!iso) return "—";
  const t = new Date(iso);
  if (!Number.isFinite(t.getTime())) return "—";
  const day = t.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: opts.year ? "numeric" : undefined });
  const time = t.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
  return `${day}, ${time}`;
}

/** 850 → "850 ms", 2132 → "2.1 s", 95_000 → "1m 35s". "—" for nothing. */
export function fmtDuration(ms?: number | null): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}
