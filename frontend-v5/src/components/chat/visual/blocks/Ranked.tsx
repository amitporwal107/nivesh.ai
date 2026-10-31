/**
 * `ranked`: a ranked table, each cell in its column's format. A row with `ask` has an "Ask ›" button that asks that
 * follow-up in the chat; a row with `plan_id` has "Plan ›", which opens the desk's own compact plan card for that id
 * (DecisionCardById) under the row. A wide box shows a table; a narrow one (a phone, the desk dock) shows one card per
 * row with the same cells, so nothing needs sideways scrolling.
 */
import { Fragment, useState } from "react";
import { DecisionCardById } from "@/pages/CopilotApp/screens/tradingdesk/decision/DecisionCard";
import { useBoxWidth } from "@/pages/CopilotApp/screens/tradingdesk/decision/PlanPayoff";
import type { RankedBlock } from "../schema";
import { fmtCell, toneColor } from "../format";
import type { BlockProps } from "./common";

type Row = RankedBlock["rows"][number];
type Col = RankedBlock["columns"][number];

/** Signed formats are coloured by sign; others stay in ink. */
function cellColor(v: unknown, col: Col): string {
  if (col.format === "pct" && typeof v === "number" && v !== 0) return v > 0 ? "var(--mint)" : "var(--cp-danger)";
  return "var(--cp-ink)";
}

function Actions({ row, open, setOpen, ask }: { row: Row; open: boolean; setOpen: (o: boolean) => void; ask?: (q: string) => void }) {
  const name = row.symbol ?? "this row";
  return (
    <span className="inline-flex flex-wrap items-center" style={{ gap: 6 }}>
      {row.plan_id && (
        <button type="button" data-testid="va-row-plan" className="cp-btn" data-variant="ghost" aria-expanded={open}
          aria-label={`${open ? "Hide" : "Open"} the plan for ${name}`} onClick={() => setOpen(!open)} style={{ padding: "3px 9px", fontSize: 12 }}>
          {open ? "Hide plan" : "Plan ›"}
        </button>
      )}
      {row.ask && (
        <button type="button" data-testid="va-row-ask" className="cp-btn" data-variant="ghost" disabled={!ask}
          aria-label={`Ask: ${row.ask}`} title={row.ask} onClick={() => ask?.(row.ask as string)} style={{ padding: "3px 9px", fontSize: 12 }}>
          Ask ›
        </button>
      )}
    </span>
  );
}

export function RankedView({ b, compact, ask }: BlockProps<RankedBlock>) {
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const measured = useBoxWidth(box);
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const narrow = compact || (measured != null && measured < 560);
  const hasActions = b.rows.some((r) => r.plan_id || r.ask);
  const toggle = (i: number) => (o: boolean) => setOpen((s) => ({ ...s, [i]: o }));
  if (!b.rows.length) return <div ref={setBox} data-testid="va-ranked-empty" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>Nothing to rank today.</div>;

  // The card's heading: the row's symbol, else the symbol column, else the first column.
  const titleKey = b.columns.find((c) => c.key === "symbol")?.key ?? null;
  return (
    <div ref={setBox} data-testid="va-ranked" data-layout={narrow ? "cards" : "table"} className="min-w-0">
      {narrow ? (
        <ol className="m-0 flex list-none flex-col p-0" style={{ gap: 8 }}>
          {b.rows.map((r, i) => {
            const head = r.symbol ?? (titleKey ? fmtCell(r.cells[titleKey]) : null);
            const rankCol = b.columns.find((c) => c.key === "rank") ?? null;
            const cols = b.columns.filter((c) => c.key !== titleKey && c !== rankCol);
            return (
              <li key={`${r.symbol ?? ""}-${i}`} data-testid="va-ranked-row" data-symbol={r.symbol ?? ""} className="flex min-w-0 flex-col"
                style={{ gap: 6, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--cp-line)", borderLeft: `3px solid ${r.tone ? toneColor(r.tone) : "var(--line-2)"}`, background: "var(--bg-2)" }}>
                <div className="flex min-w-0 flex-wrap items-center justify-between" style={{ gap: 6 }}>
                  <span className="flex min-w-0 items-baseline" style={{ gap: 6 }}>
                    {rankCol && <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>#<span data-testid={`va-cell-${rankCol.key}`}>{fmtCell(r.cells[rankCol.key], rankCol.format)}</span></span>}
                    {head && <strong style={{ fontSize: 13.5 }}>{head}</strong>}
                  </span>
                  <Actions row={r} open={!!open[i]} setOpen={toggle(i)} ask={ask} />
                </div>
                <dl className="m-0 grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(108px, 1fr))", gap: "2px 14px", fontSize: 12 }}>
                  {cols.map((c) => (
                    // Words (a setup, a buildup) take the card's full width; figures sit two to a line.
                    <div key={c.key} className="flex min-w-0 justify-between" style={{ gap: 8, gridColumn: !c.format || c.format === "text" ? "1 / -1" : undefined }}>
                      <dt style={{ flex: "none", color: "var(--cp-ink-3)" }}>{c.label}</dt>
                      <dd data-testid={`va-cell-${c.key}`} className="m-0 cp-num" style={{ color: cellColor(r.cells[c.key], c), textAlign: "right", overflowWrap: "anywhere" }}>{fmtCell(r.cells[c.key], c.format)}</dd>
                    </div>
                  ))}
                </dl>
                {open[i] && r.plan_id && <DecisionCardById planId={r.plan_id} testId="va-row-plan-card" variant="row" budgets />}
              </li>
            );
          })}
        </ol>
      ) : (
        <table className="cp-num" style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead>
            <tr style={{ color: "var(--cp-ink-3)" }}>
              {b.columns.map((c) => (
                <th key={c.key} scope="col" style={{ fontWeight: 400, padding: "4px 6px", textAlign: c.align ?? (c.format && c.format !== "text" ? "right" : "left"), whiteSpace: "nowrap" }}>{c.label}</th>
              ))}
              {hasActions && <th scope="col"><span className="sr-only">Actions</span></th>}
            </tr>
          </thead>
          <tbody>
            {b.rows.map((r, i) => (
              <Fragment key={`${r.symbol ?? ""}-${i}`}>
                <tr data-testid="va-ranked-row" data-symbol={r.symbol ?? ""} style={{ borderTop: "1px solid var(--cp-line)", boxShadow: r.tone ? `inset 3px 0 0 ${toneColor(r.tone)}` : undefined }}>
                  {b.columns.map((c) => (
                    <td key={c.key} data-testid={`va-cell-${c.key}`} style={{ padding: "5px 6px", textAlign: c.align ?? (c.format && c.format !== "text" ? "right" : "left"), color: cellColor(r.cells[c.key], c), fontFamily: c.format === "text" || !c.format ? "var(--sans)" : undefined }}>
                      {fmtCell(r.cells[c.key], c.format)}
                    </td>
                  ))}
                  {hasActions && <td style={{ padding: "3px 6px", textAlign: "right", whiteSpace: "nowrap" }}><Actions row={r} open={!!open[i]} setOpen={toggle(i)} ask={ask} /></td>}
                </tr>
                {open[i] && r.plan_id && (
                  <tr><td colSpan={b.columns.length + 1} style={{ padding: "4px 6px 10px" }}><DecisionCardById planId={r.plan_id} testId="va-row-plan-card" variant="row" budgets /></td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
