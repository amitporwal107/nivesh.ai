/**
 * "Import earlier statements" — the second line of the home statement bar.
 *
 *   POST /api/onboarding/gmail/auto-import   body {"all_statements": true}
 *   (backend/routes/onboarding_gmail.py :: _gmail_import_all_statements,
 *    rules in backend/services/cas_history_import.py)
 *
 * "Sync Gmail" beside it brings in the latest statement and replaces the
 * holdings. This brings in the older ones of the last 12 months as history:
 * each call reads at most six, stores each as its own record, and changes what
 * the portfolio shows only when it finds a consolidated statement newer than
 * the one on file. The answer says, per statement, what happened, which
 * statement the portfolio shows, and how many are left for the next call.
 *
 * Nothing here is worked out on the client: periods, outcomes and reasons are
 * shown as the backend sent them.
 */
import { useState } from "react";
import { apiFetch } from "@/services/api/authed-fetch";

type Status = "imported" | "already_stored" | "failed";

interface StatementRow {
  id: string;
  /** e.g. "Sep/2026"; null when the statement could not be read. */
  period: string | null;
  source: string | null;
  status: Status;
  /** The backend's own sentence for a failure or a statement not kept. */
  reason: string | null;
  filename: string | null;
  /** "YYYY-MM-DD" the email was sent. */
  emailDate: string | null;
  holdings: number | null;
  /** This statement is the one the portfolio now shows. */
  mounted: boolean;
}

interface ImportResult {
  rows: StatementRow[];
  /** Statements not yet read; another call picks them up. */
  remaining: number;
  /** Statements found in Gmail in the scanned months. */
  scanned: number;
  months: number;
  shownPeriod: string | null;
  /** One sentence on what the portfolio shows and why. */
  shownReason: string | null;
  /** The portfolio changed in this call. */
  changed: boolean;
  importedNow: number;
  message: string | null;
}

const SOURCE_LABEL: Record<string, string> = {
  nsdl: "NSDL",
  cdsl: "CDSL",
  cams: "CAMS",
  kfintech: "KFintech",
  cams_kfintech: "CAMS / KFintech",
};

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const rec = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);

/** Read the answer tolerantly; a body without `statements` is not this endpoint's answer. */
function parseResult(data: unknown): ImportResult | null {
  const d = rec(data);
  if (!d || !Array.isArray(d.statements)) return null;
  const rows = d.statements.flatMap((item: unknown, i: number): StatementRow[] => {
    const r = rec(item);
    const status = r?.status;
    if (!r || (status !== "imported" && status !== "already_stored" && status !== "failed")) return [];
    return [{
      id: str(r.message_id) ?? `row-${i}`,
      period: str(r.statement_period),
      source: str(r.source),
      status,
      reason: str(r.reason),
      filename: str(r.filename),
      emailDate: str(r.email_date),
      holdings: num(r.holdings_count),
      mounted: r.mounted === true,
    }];
  });
  const m = rec(d.mounted);
  return {
    rows,
    remaining: num(d.remaining) ?? 0,
    scanned: num(d.scanned) ?? rows.length,
    months: num(d.months) ?? 12,
    shownPeriod: str(m?.statement_period),
    shownReason: str(m?.reason),
    changed: m?.changed === true,
    importedNow: num(d.imported) ?? rows.filter((r) => r.status === "imported").length,
    message: str(d.message),
  };
}

/** A failed call in plain words. The two refusals the backend makes before it reads Gmail are named. */
async function failureSentence(res: Response): Promise<string> {
  const body = rec(await res.json().catch(() => null));
  const detail = str(body?.detail) ?? "";
  if (res.status === 401) return "Your Gmail connection has expired. Reconnect it with Sync Gmail, then try again.";
  if (res.status === 400 && /pan/i.test(detail)) return "Your PAN is needed to open the statements. Add it with Sync Gmail, then try again.";
  if (res.status === 400 && /gmail/i.test(detail)) return "Gmail is not connected. Connect it with Sync Gmail, then try again.";
  return `The import did not finish (the server answered ${res.status}). Nothing was changed by this attempt; try again.`;
}

function outcome(r: StatementRow, importedEarlier: boolean): { text: string; color: string } {
  if (r.status === "failed") return { text: "Not imported", color: "var(--cp-danger)" };
  if (r.status === "imported") return { text: r.mounted ? "Imported · now shown" : "Imported", color: "var(--mint)" };
  // Stored by an earlier click in this visit: it was imported here, a moment ago.
  if (importedEarlier) return { text: "Imported", color: "var(--mint)" };
  return { text: "Already stored", color: "var(--cp-ink-3)" };
}

function emailed(iso: string | null): string {
  if (!iso) return "";
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!d) return "";
  return new Date(+d[1], +d[2] - 1, +d[3]).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function StatementImport({ gmailConnected, onImported }: {
  /** The import reads Gmail; without a connection this line is not shown. */
  gmailConnected: boolean;
  /** Called after a call that stored or showed something, so the parent refreshes its reads. */
  onImported: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Statements imported by earlier clicks in this visit; the next answer lists them as already stored.
  const [imported, setImported] = useState<Set<string>>(new Set());

  if (!gmailConnected) return null;

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await apiFetch("/api/onboarding/gmail/auto-import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ all_statements: true }),
      });
      if (!res.ok) {
        setError(await failureSentence(res));
        return;
      }
      const parsed = parseResult(await res.json().catch(() => null));
      if (!parsed) {
        setError("The import answered in a form this screen does not understand. Nothing is shown rather than a guess.");
        return;
      }
      if (result) setImported((prev) => new Set([...prev, ...result.rows.filter((r) => r.status === "imported").map((r) => r.id)]));
      setResult(parsed);
      if (parsed.importedNow > 0 || parsed.changed) onImported();
    } catch {
      setError("The import could not reach the server. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  };

  const link = { background: "none", border: 0, padding: 0, cursor: busy ? "default" : "pointer", fontFamily: "var(--sans)", fontSize: 12 } as const;
  const failed = result ? result.rows.filter((r) => r.status === "failed").length : 0;

  return (
    <div data-testid="statement-import" className="flex flex-col min-w-0" style={{ flex: "1 1 100%", gap: 10, paddingTop: 8, borderTop: "1px solid var(--cp-line)" }}>
      <div className="flex flex-wrap items-center" style={{ gap: "4px 12px" }}>
        <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>Earlier statements</span>
        <span style={{ color: "var(--cp-ink-3)" }}>Keep the last 12 months from Gmail as history</span>
        {!result && (
          <button type="button" data-testid="statement-import-start" onClick={run} disabled={busy} style={{ ...link, marginLeft: "auto", color: "var(--cp-ink-2)", opacity: busy ? 0.6 : 1 }}>
            {busy ? "Reading your statements…" : "Import earlier statements"}
          </button>
        )}
      </div>

      {busy && (
        <span data-testid="statement-import-running" role="status" className="cp-running" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>
          Reading up to six statements. This can take a minute.
        </span>
      )}

      {error && (
        <div data-testid="statement-import-error" role="alert" className="flex flex-wrap items-start" style={{ gap: "6px 12px", padding: "10px 12px", borderRadius: 10, border: "1px solid var(--danger-line)", background: "var(--cp-danger-soft)" }}>
          <span style={{ flex: "1 1 220px", fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{error}</span>
          <button type="button" data-testid="statement-import-retry" onClick={run} disabled={busy} style={{ ...link, color: "var(--cp-ink)" }}>Try again ›</button>
        </div>
      )}

      {result && (
        <div className="flex flex-col" style={{ gap: 8 }}>
          <div className="flex flex-wrap items-baseline" style={{ gap: "4px 10px" }}>
            {result.shownPeriod && (
              <span data-testid="statement-import-shown" style={{ fontWeight: 500, color: "var(--cp-ink)" }}>Showing {result.shownPeriod}</span>
            )}
            {result.shownReason && (
              <span data-testid="statement-import-reason" style={{ color: "var(--cp-ink-3)", lineHeight: 1.5 }}>{result.shownReason}</span>
            )}
          </div>

          {result.rows.length === 0 ? (
            <span data-testid="statement-import-empty" style={{ color: "var(--cp-ink-3)" }}>
              {result.message ?? `No CAS statements were found in Gmail for the last ${result.months} months.`}
            </span>
          ) : (
            <ul data-testid="statement-import-list" className="m-0 flex flex-col cp-scroll" style={{ listStyle: "none", padding: 0, maxHeight: 300, overflowY: "auto" }}>
              {result.rows.map((r) => {
                const o = outcome(r, imported.has(r.id));
                const title = r.period ?? r.filename ?? "Statement";
                const about = [
                  r.source ? SOURCE_LABEL[r.source] ?? null : null,
                  r.status !== "failed" && r.holdings != null ? `${r.holdings} holdings` : null,
                  !r.period && emailed(r.emailDate) ? `emailed ${emailed(r.emailDate)}` : null,
                ].filter(Boolean).join(" · ");
                return (
                  <li key={r.id} data-testid="statement-import-row" data-status={r.status} className="flex flex-col" style={{ gap: 2, padding: "7px 0", borderTop: "1px solid var(--cp-line)" }}>
                    <span className="flex flex-wrap items-baseline" style={{ gap: "2px 10px" }}>
                      <span data-testid="statement-import-row-period" style={{ color: "var(--cp-ink)", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "100%" }}>{title}</span>
                      {about && <span style={{ color: "var(--cp-ink-3)", fontSize: 12 }}>{about}</span>}
                      <span data-testid="statement-import-row-outcome" style={{ marginLeft: "auto", color: o.color, whiteSpace: "nowrap" }}>{o.text}</span>
                    </span>
                    {r.reason && (
                      <span data-testid="statement-import-row-reason" style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{r.reason}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          <div className="flex flex-wrap items-center" style={{ gap: "6px 12px" }}>
            <span data-testid="statement-import-summary" style={{ color: "var(--cp-ink-3)" }}>
              {result.remaining > 0
                // The list scrolls, so a failure further down is counted here too.
                ? `${result.remaining} more ${result.remaining === 1 ? "statement" : "statements"} to import${failed > 0 ? ` · ${failed} could not be imported` : ""}`
                : result.rows.length > 0
                  ? failed > 0
                    ? `All ${result.scanned} statements were tried; ${failed} could not be imported`
                    : `All ${result.scanned} statements from the last ${result.months} months are stored`
                  : ""}
            </span>
            {result.remaining > 0 && (
              <button type="button" data-testid="statement-import-more" onClick={run} disabled={busy} className="cp-btn" style={{ marginLeft: "auto", padding: "6px 12px", fontSize: 12 }}>
                {busy ? "Reading…" : "Import more"}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
