/**
 * Trader screens — small pieces shared by Trader desk, Options lab and Paper trades.
 */
import type { CSSProperties, ReactNode } from "react";
import { ApiError } from "@/services/api/errors";
import { EmptyBlock, ErrorBlock, fmtNum } from "../../components/ui";
import { isForbidden } from "./queries";

/** SEBI's F&O risk disclosure, as worded in the design. */
export const SEBI_FNO_NOTE = "9 out of 10 individual traders in equity F&O incurred net losses (SEBI study).";

/** A price in rupees with paise ("₹1,234.50"). fmtINR rounds to whole rupees, which is wrong for a quote. */
export function fmtPrice(n: number | null | undefined): string {
  return n == null || !Number.isFinite(n) ? "—" : `₹${fmtNum(n, 2)}`;
}

/** "+12.50" / "−3.00" / "0.00". */
export function fmtSigned(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${fmtNum(Math.abs(n), digits)}`;
}

/**
 * A trading-session date ("2026-10-12") as "12 Oct 2026". fmtDate parses a
 * date-only string as UTC midnight, which lands on the previous day for a
 * viewer west of UTC; a session date is an India date wherever it is read.
 */
export function fmtDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T12:00:00+05:30` : iso);
  if (!Number.isFinite(d.getTime())) return "—";
  return d.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" });
}

export const INPUT_STYLE: CSSProperties = {
  width: "100%",
  minWidth: 0,
  padding: "8px 10px",
  borderRadius: 8,
  border: "1px solid var(--line-2)",
  background: "var(--bg-2)",
  color: "var(--cp-ink)",
  fontFamily: "var(--mono)",
  fontSize: 13,
};

/** A titled slot for a block that is loading, failed, empty or not connected (Section is for the loaded table). */
export function Labeled({ title, note, children, testId }: { title: ReactNode; note?: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} className="flex flex-col min-w-0" style={{ gap: 10 }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "6px 12px" }}>
        <span className="cp-eyebrow">{title}</span>
        {note && <span className="cp-mono-note">{note}</span>}
      </div>
      {children}
    </div>
  );
}

/**
 * A failed query. No access (403) gets a plain explanation; anything else gets
 * the error with a retry. A body in the wrong shape is reported in words: the
 * adapters put the whole zod issue list in the error message, which is not
 * something to show a user.
 */
export function QueryProblem({ what, error, onRetry }: { what: string; error: unknown; onRetry: () => void }) {
  if (isForbidden(error)) {
    return <EmptyBlock title={`${what} is not enabled for this account`} body="This account does not have access to this data. An admin can enable it." />;
  }
  const shown = error instanceof ApiError && error.kind === "contract_drift" ? "unexpected response shape" : error;
  return <ErrorBlock title={`${what} didn’t load`} error={shown} onRetry={onRetry} />;
}

/**
 * One-of-many buttons (index picker, market view, sample). With `testId`, each
 * button gets `${testId}-${value as a slug}`, e.g. "fno-index-nifty-50".
 */
export function Choices<T extends string>({ label, value, options, onChange, testId }: {
  label: string;
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (v: T) => void;
  testId?: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap" style={{ gap: 6 }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            className="cp-chip"
            aria-pressed={on}
            data-testid={testId ? `${testId}-${o.value.toLowerCase().replace(/[^a-z0-9]+/g, "-")}` : undefined}
            onClick={() => onChange(o.value)}
            style={on ? { borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" } : undefined}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
