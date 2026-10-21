/**
 * Strategy Builder — compare cash, futures and options (PRD §16.5 Alternatives, §17.3 step 7).
 *
 * One row per candidate from the plan's own `alternatives` comparison: max loss, capital at risk, breakeven,
 * reward : risk net and gross, liquidity flags, horizon, evidence quality and why a candidate is unsuitable.
 * A candidate that is wait / no trade / avoid / insufficient shows its reasons INSTEAD of numbers, never a
 * figure. Selecting a row (click, or Enter / Space on its button) selects the candidate shown below. The table
 * scrolls inside itself; the page never scrolls sideways. A max loss is shown as an amount (the route sends a
 * linear candidate's as a positive loss and an option's as a negative P&L).
 */
import { fmtNum } from "../../../components/ui";
import type { Alternative } from "./plan-contract";
import { CandidatePill, DASH, SEGMENT_WORD, noteStyle, ratio, rupees, rupeesAbs, sessions } from "./plan-format";
import type { CandidateStatus } from "./plan-contract";

const th = { textAlign: "left" as const, padding: "8px 10px", whiteSpace: "nowrap" as const, borderBottom: "1px solid var(--cp-line)" };
const td = { padding: "10px", verticalAlign: "top" as const, borderBottom: "1px solid var(--cp-line)", fontSize: 12.5 };

export function CompareTable({ rows, selected, preferred, onSelect }: { rows: Alternative[]; selected: string | null; preferred: string | null; onSelect: (id: string) => void }) {
  if (!rows.length) return <p data-testid="compare-empty" style={noteStyle}>No candidate was built, so there is nothing to compare. See the status reasons above.</p>;
  return (
    <div data-testid="compare" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <div tabIndex={0} role="region" aria-label="Candidates compared (scrolls sideways inside this box)" className="cp-scroll" style={{ overflowX: "auto", maxWidth: "100%" }}>
        <table data-testid="compare-table" style={{ borderCollapse: "collapse", width: "100%", minWidth: 980 }}>
          <caption className="cp-mono-note" style={{ textAlign: "left", paddingBottom: 6 }}>Max loss and capital at risk are in rupees for the sized position; reward : risk is net of the plan's costs where costs are known.</caption>
          <thead>
            <tr className="cp-mono-note">
              {["Candidate", "Status", "Max loss", "Capital at risk", "Breakeven", "Reward : risk (net / gross)", "Liquidity flags", "Horizon", "Evidence quality", "Why unsuitable"].map((h) => <th key={h} scope="col" style={th}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const viable = r.status === "candidate";
              const on = r.id === selected;
              const eq = r.evidence_quality;
              return (
                <tr
                  key={r.id} data-testid={`cmp-row-${r.id}`} data-selected={on} data-status={r.status} aria-selected={on} onClick={() => onSelect(r.id)}
                  style={{ cursor: "pointer", background: on ? "var(--bg-2)" : undefined }}
                >
                  <th scope="row" style={{ ...td, textAlign: "left", fontWeight: 400 }}>
                    <button
                      type="button" data-testid={`cmp-select-${r.id}`} aria-pressed={on} onClick={(e) => { e.stopPropagation(); onSelect(r.id); }}
                      style={{ display: "flex", flexDirection: "column", gap: 2, padding: 0, border: 0, background: "none", cursor: "pointer", color: "inherit", fontFamily: "var(--sans)", textAlign: "left" }}
                    >
                      <span style={{ fontSize: 13, fontWeight: 500 }}>{r.label}{on ? " (selected)" : ""}</span>
                      <span className="cp-mono-note">{SEGMENT_WORD[r.segment as keyof typeof SEGMENT_WORD] ?? r.segment}{r.id === preferred ? " · preferred" : ""}</span>
                    </button>
                  </th>
                  <td style={td}><CandidatePill status={r.status as CandidateStatus} /></td>
                  <td data-testid="cmp-maxloss" className="cp-num" style={td}>{viable ? <>{rupeesAbs(r.max_loss)}<br /><span style={noteStyle}>{r.max_loss_basis}</span></> : DASH}</td>
                  <td data-testid="cmp-capital" className="cp-num" style={td}>{viable ? rupees(r.capital_at_risk) : DASH}</td>
                  <td data-testid="cmp-breakeven" className="cp-num" style={td}>{viable && r.breakeven?.length ? r.breakeven.map((b) => fmtNum(b, 2)).join(", ") : DASH}</td>
                  <td data-testid="cmp-rr" className="cp-num" style={td}>{viable ? `${ratio(r.reward_risk_net)} / ${ratio(r.reward_risk_gross)}` : DASH}</td>
                  <td data-testid="cmp-flags" style={td}>{viable ? (r.liquidity_flags.length ? r.liquidity_flags.map((f) => (typeof f === "string" ? f : JSON.stringify(f))).join("; ") : "None flagged") : DASH}</td>
                  <td style={td}>{sessions(r.horizon_days)}</td>
                  <td data-testid="cmp-evidence" style={td}>{eq ? `${eq.label}: ${eq.supports} for, ${eq.conflicts} against, ${eq.unavailable} unavailable` : DASH}</td>
                  <td data-testid="cmp-why" style={{ ...td, minWidth: 200 }}>{r.why_unsuitable ?? "Viable"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
