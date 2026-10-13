/**
 * Internal (admin) screens — the shared header, the tab strip between the four
 * operations pages, and the "this request failed" state with a plain 403.
 * Design: frontend-v5/design/nivesh-copilot/NVOps.dc.html (header + tabs).
 */
import type { ReactNode } from "react";
import { ApiError } from "@/services/api/errors";
import { ErrorBlock, Pill, ScreenHeader } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";

/** The server refused the request for this account (HTTP 403). */
export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && (error.kind === "forbidden" || error.status === 403);
}

const ADMIN_ONLY = "The server only returns this to admin accounts, and it refused this one (403). Nothing is wrong with the page — sign in with an admin account to see it.";

/**
 * A failed request. A 403 gets a plain explanation (retrying will not help);
 * anything else is an error with a retry.
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
  return <ErrorBlock title={`${what} didn’t load`} error={readable(error)} onRetry={onRetry} />;
}

/** A shared adapter reports a contract mismatch as a long JSON dump; show one line instead. */
function readable(error: unknown): unknown {
  if (error instanceof ApiError && error.kind === "contract_drift" && error.message.length > 160) {
    return "the server’s answer was not in the expected shape";
  }
  return error;
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

/** Moves between the four operations pages. */
export function OpsTabs({ current }: { current: string }) {
  const { go } = useCopilotShell();
  return (
    <nav aria-label="Operations pages" className="flex flex-wrap" style={{ gap: 6 }}>
      {OPS_TABS.map((t) => {
        const on = t.view === current;
        return (
          <button
            key={t.view}
            type="button"
            aria-current={on ? "page" : undefined}
            onClick={() => go(t.view)}
            style={{
              padding: "7px 14px",
              borderRadius: 999,
              fontFamily: "var(--sans)",
              fontSize: 13,
              cursor: "pointer",
              border: `1px solid ${on ? "var(--line-3)" : "var(--line-2)"}`,
              color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
              background: on ? "var(--bg-3)" : "transparent",
            }}
          >
            {t.label}
          </button>
        );
      })}
    </nav>
  );
}
