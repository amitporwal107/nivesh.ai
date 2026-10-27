/**
 * Roll an open F&O strategy paper trade to the next listed expiry (owner option C; backend services/fno_roll.py).
 *
 *   GET  /api/desk/paper-trades/{id}/roll   the preview: both legs at the roll session's NSE bhavcopy close, the next
 *                                           expiry's strikes and prices, costs; or the reason it cannot roll
 *   POST /api/desk/paper-trades/{id}/roll   closes the old structure and opens the new one (same risk checks as any entry)
 *
 * The button opens a confirmation that shows BOTH legs and their prices; nothing is recorded until "Roll" is pressed,
 * and a second press records nothing new. Simulated; nothing is sent to a broker.
 */
import { useState } from "react";
import { Btn, fmtINR, fmtNum } from "../../components/ui";
import { fmtDay } from "../trading/parts";
import { useRollPreview, useRollTrade, writeProblem, type RollLegView, type StrategyPaperTrade } from "./desk-trading";

const quiet = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;

function LegTable({ title, legs, testId }: { title: string; legs: RollLegView[]; testId: string }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
      <span className="cp-eyebrow">{title}</span>
      <table data-testid={testId} style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
        <tbody>
          {legs.map((l, i) => (
            <tr key={i} data-testid={`${testId}-leg`} style={{ borderTop: "1px solid var(--cp-line)" }}>
              <td style={{ padding: "4px 8px" }}>{l.label}</td>
              <td data-testid={`${testId}-price`} className="cp-num" style={{ padding: "4px 8px", textAlign: "right" }}>{l.price != null ? fmtNum(l.price, 2) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RollAction({ t, testPrefix = "desk-roll" }: { t: StrategyPaperTrade; testPrefix?: string }) {
  const [open, setOpen] = useState(false);
  const preview = useRollPreview(open ? t.id : null);
  const roll = useRollTrade();
  if (t.status !== "open") return null;
  const p = preview.data;
  return (
    <span className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <button type="button" className="cp-chip" data-testid={`${testPrefix}-open`} aria-expanded={open}
        aria-label={`Roll the ${t.underlying} strategy paper trade to the next expiry`}
        onClick={() => { roll.reset(); setOpen((v) => !v); }} style={{ padding: "3px 10px", fontSize: 12 }}>
        {open ? "Cancel roll" : "Roll"}
      </button>
      {open && (
        <div data-testid={`${testPrefix}-confirm`} role="dialog" aria-label="Roll to the next expiry" className="flex min-w-0 flex-col"
          style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--cp-line)", background: "var(--bg-2)", minWidth: 280 }}>
          {preview.isLoading && <span style={quiet}>Reading the roll session’s bhavcopy…</span>}
          {preview.isError && <span role="alert" data-testid={`${testPrefix}-error`} style={{ fontSize: 12, color: "var(--cp-danger)" }}>The roll could not be priced — {writeProblem(preview.error)}</span>}
          {p && !p.eligible && (
            <span data-testid={`${testPrefix}-refused`} data-code={p.refusal?.code} role="note" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>
              Cannot roll: {p.refusal?.message}
            </span>
          )}
          {p && p.eligible && (
            <>
              <span style={{ ...quiet, color: "var(--cp-ink-2)" }}>
                Both sides at the {p.session ? fmtDay(p.session) : "—"} NSE bhavcopy close{p.newExpiry ? `; new expiry ${fmtDay(p.newExpiry)}` : ""}
                {p.strikeShift ? `; strikes moved by ${fmtNum(p.strikeShift)}` : "; same strikes"}.
              </span>
              <LegTable title="Close (old)" legs={p.oldLegs} testId={`${testPrefix}-old`} />
              <LegTable title="Open (new)" legs={p.newLegs} testId={`${testPrefix}-new`} />
              <span data-testid={`${testPrefix}-figures`} style={quiet}>
                Old structure {p.oldNetRs != null ? fmtINR(p.oldNetRs, { signed: true }) : "—"} after costs ·
                new premium {p.newNetPremiumRs != null ? fmtINR(p.newNetPremiumRs, { signed: true }) : "—"} ·
                new round-trip costs {p.newCostsRs != null ? fmtINR(p.newCostsRs) : "—"} (desk cost card)
              </span>
              {p.notes.map((n, i) => <span key={i} style={{ ...quiet, color: "var(--amber)" }}>{n}</span>)}
              <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
                <Btn variant="primary" data-testid={`${testPrefix}-submit`} disabled={roll.isPending || roll.isSuccess}
                  onClick={() => roll.mutate(t.id)} style={{ padding: "5px 12px", fontSize: 12 }}>
                  {roll.isSuccess ? "Rolled" : roll.isPending ? "Rolling…" : "Roll"}
                </Btn>
                <span style={quiet}>Simulated; nothing is sent to a broker.</span>
              </span>
              {roll.isSuccess && <span role="status" data-testid={`${testPrefix}-done`} style={{ fontSize: 12, color: "var(--mint)" }}>Rolled: new paper trade {roll.data?.newId ?? "—"}.</span>}
              {roll.isError && <span role="alert" data-testid={`${testPrefix}-failed`} style={{ fontSize: 12, color: "var(--cp-danger)" }}>Not rolled — {writeProblem(roll.error)}</span>}
            </>
          )}
        </div>
      )}
    </span>
  );
}
