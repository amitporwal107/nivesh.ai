/**
 * `ranked`: a ranked table, each cell in its column's format. A row with `ask` has an "Ask ›" button that asks that
 * follow-up in the chat; a row with `plan_id` has "Plan ›", which opens the desk's own compact plan card for that id
 * (DecisionCardById) under the row. A row with `alternatives` has "+N more ›", which shows its other structures under it
 * in the same columns (the F&O board folds an underlying's alternatives under its lead). A `badge` sits by the symbol
 * ("Live", or the close the row was priced at) and `tips` are per-cell tooltips. A wide box shows a table; a narrow one (a
 * phone, the desk dock) shows one card per row with the same cells, so nothing needs sideways scrolling.
 */
import { Fragment, useState } from "react";
import { DecisionCardById } from "@/pages/CopilotApp/screens/tradingdesk/decision/DecisionCard";
import { useBoxWidth } from "@/pages/CopilotApp/screens/tradingdesk/decision/PlanPayoff";
import type { RankedBlock } from "../schema";
import { useOptionalCopilotShell } from "@/pages/CopilotApp/lib/shell-context";
import { fmtCell, toneColor } from "../format";
import { FnoSymbolDialog, type FnoDetailContext } from "../FnoSymbolDialog";
import type { BlockProps } from "./common";

type Row = RankedBlock["rows"][number];
type Col = RankedBlock["columns"][number];
type AltCtl = { shown: boolean; toggle: () => void };

/** Signed formats are coloured by sign; others stay in ink. */
function cellColor(v: unknown, col: Col): string {
  if (col.format === "pct" && typeof v === "number" && v !== 0) return v > 0 ? "var(--mint)" : "var(--cp-danger)";
  return "var(--cp-ink)";
}

const BADGE_STYLE = { fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", padding: "1px 6px", borderRadius: 999, border: "1px solid var(--line-2)", color: "var(--cp-ink-3)", whiteSpace: "nowrap" } as const;

function Badge({ row }: { row: Row }) {
  if (!row.badge) return null;
  const live = row.badge === "Live";
  return <span data-testid="va-row-badge" data-live={live ? "1" : "0"} style={{ ...BADGE_STYLE, ...(live ? { color: "var(--mint)", borderColor: "var(--mint)" } : {}) }}>{row.badge}</span>;
}

function Actions({ row, open, setOpen, ask, alts, onDetail }: { row: Row; open: boolean; setOpen: (o: boolean) => void; ask?: (q: string) => void; alts?: AltCtl; onDetail?: () => void }) {
  const name = row.symbol ?? "this row";
  const n = row.alternatives?.length ?? 0;
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
      {onDetail && (
        <button type="button" data-testid="va-row-detail" className="cp-btn" data-variant="ghost" aria-label={`Open the F&O detail of ${name}`}
          onClick={onDetail} style={{ padding: "3px 9px", fontSize: 12 }}>Details ›</button>
      )}
      {alts && n > 0 && (
        <button type="button" data-testid="va-row-alts" className="cp-btn" data-variant="ghost" aria-expanded={alts.shown}
          aria-label={`${alts.shown ? "Hide" : "Show"} ${n} other structure${n === 1 ? "" : "s"} for ${name}`} onClick={alts.toggle} style={{ padding: "3px 9px", fontSize: 12 }}>
          {alts.shown ? "Hide others" : `+${n} more ›`}
        </button>
      )}
    </span>
  );
}

export function RankedView({ b, compact, ask }: BlockProps<RankedBlock>) {
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const measured = useBoxWidth(box);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [altsOpen, setAltsOpen] = useState<Record<number, boolean>>({});
  const shell = useOptionalCopilotShell();
  const [detail, setDetail] = useState<FnoDetailContext | null>(null);
  // `detail: "fno"` and a symbol on the row: Details › opens that stock's option chain and futures build-up (inside the app shell).
  const detailOf = (r: Row): (() => void) | undefined => (b.detail === "fno" && shell && r.symbol
    ? () => setDetail({ symbol: r.symbol as string, label: typeof r.cells.buildup === "string" ? r.cells.buildup : null,
        sub: ["price", "oi"].map((k, i) => (typeof r.cells[k] === "number" ? `${i ? "OI" : "price"} ${fmtCell(r.cells[k] as number, "pct")}` : null)).filter(Boolean).join(", ") || null })
    : undefined);
  // A table needs room for its columns: 560 px up to seven (as before), then 110 px for each one more, so a ten-column board
  // is cards below 890 px instead of overflowing its box.
  const minTable = 560 + Math.max(0, b.columns.length - 7) * 110;
  // A card cell holds a label and a figure side by side: wider cells for a board of many figures, so no figure breaks in two.
  const cardMin = b.columns.length >= 8 ? 176 : 108;
  const narrow = compact || (measured != null && measured < minTable);
  const hasActions = b.rows.some((r) => r.plan_id || r.ask || r.alternatives?.length || r.alternatives?.some((a) => a.plan_id || a.ask)) || (b.detail === "fno" && !!shell);
  const toggle = (k: string) => (o: boolean) => setOpen((s) => ({ ...s, [k]: o }));
  if (!b.rows.length) return <div ref={setBox} data-testid="va-ranked-empty" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>Nothing to rank today.</div>;

  // The card's heading: the row's symbol, else the symbol column, else the first column.
  const titleKey = b.columns.find((c) => c.key === "symbol")?.key ?? null;
  const rankCol = b.columns.find((c) => c.key === "rank") ?? null;

  const card = (r: Row, k: string, alt: boolean, altCtl?: AltCtl) => {
    const head = r.symbol ?? (titleKey ? fmtCell(r.cells[titleKey]) : null);
    const cols = b.columns.filter((c) => c.key !== titleKey && c !== rankCol);
    return (
      <li key={k} data-testid={alt ? "va-ranked-alt" : "va-ranked-row"} data-symbol={r.symbol ?? ""} className="flex min-w-0 flex-col"
        style={{ gap: 6, padding: "8px 10px", marginLeft: alt ? 14 : 0, borderRadius: 10, border: "1px solid var(--cp-line)", borderLeft: `3px solid ${r.tone ? toneColor(r.tone) : "var(--line-2)"}`, background: "var(--bg-2)" }}>
        <div className="flex min-w-0 flex-wrap items-center justify-between" style={{ gap: 6 }}>
          <span className="flex min-w-0 items-baseline" style={{ gap: 6 }}>
            {rankCol && !alt && <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>#<span data-testid={`va-cell-${rankCol.key}`}>{fmtCell(r.cells[rankCol.key], rankCol.format)}</span></span>}
            {head && !alt && <strong style={{ fontSize: 13.5 }}>{head}</strong>}
            <Badge row={r} />
          </span>
          <Actions row={r} open={!!open[k]} setOpen={toggle(k)} ask={ask} alts={altCtl} onDetail={detailOf(r)} />
        </div>
        <dl className="m-0 grid" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${cardMin}px, 1fr))`, gap: "2px 14px", fontSize: 12 }}>
          {cols.map((c) => (
            // Words (a setup, a buildup) take the card's full width; figures sit two to a line.
            <div key={c.key} className="flex min-w-0 justify-between" style={{ gap: 8, gridColumn: !c.format || c.format === "text" ? "1 / -1" : undefined }}>
              <dt style={{ flex: "none", color: "var(--cp-ink-3)" }}>{c.label}</dt>
              <dd data-testid={`va-cell-${c.key}`} title={r.tips?.[c.key]} className="m-0 cp-num" style={{ color: cellColor(r.cells[c.key], c), textAlign: "right", ...(c.format && c.format !== "text" ? { whiteSpace: "nowrap" } : { overflowWrap: "anywhere" }) }}>{fmtCell(r.cells[c.key], c.format)}</dd>
            </div>
          ))}
        </dl>
        {open[k] && r.plan_id && <DecisionCardById planId={r.plan_id} testId="va-row-plan-card" variant="row" budgets />}
      </li>
    );
  };

  const tableRow = (r: Row, k: string, alt: boolean, altCtl?: AltCtl) => (
    <Fragment key={k}>
      <tr data-testid={alt ? "va-ranked-alt" : "va-ranked-row"} data-symbol={r.symbol ?? ""}
        style={{ borderTop: "1px solid var(--cp-line)", boxShadow: r.tone ? `inset 3px 0 0 ${toneColor(r.tone)}` : undefined, background: alt ? "var(--bg-2)" : undefined }}>
        {b.columns.map((c, ci) => (
          <td key={c.key} data-testid={`va-cell-${c.key}`} title={r.tips?.[c.key]}
            style={{ padding: "5px 6px", paddingLeft: alt && ci === 0 ? 18 : undefined, textAlign: c.align ?? (c.format && c.format !== "text" ? "right" : "left"), color: cellColor(r.cells[c.key], c), fontFamily: c.format === "text" || !c.format ? "var(--sans)" : undefined, whiteSpace: c.format && c.format !== "text" ? "nowrap" : undefined, textDecoration: r.tips?.[c.key] ? "underline dotted var(--line-2)" : undefined }}>
            {ci === 0 && r.badge
              ? <span className="inline-flex flex-wrap items-baseline" style={{ gap: 6 }}><span>{fmtCell(r.cells[c.key], c.format)}</span><Badge row={r} /></span>
              : fmtCell(r.cells[c.key], c.format)}
          </td>
        ))}
        {hasActions && <td style={{ padding: "3px 6px", textAlign: "right", whiteSpace: "nowrap" }}><Actions row={r} open={!!open[k]} setOpen={toggle(k)} ask={ask} alts={altCtl} onDetail={detailOf(r)} /></td>}
      </tr>
      {open[k] && r.plan_id && (
        <tr><td colSpan={b.columns.length + 1} style={{ padding: "4px 6px 10px" }}><DecisionCardById planId={r.plan_id} testId="va-row-plan-card" variant="row" budgets /></td></tr>
      )}
    </Fragment>
  );

  const ctl = (i: number): AltCtl => ({ shown: !!altsOpen[i], toggle: () => setAltsOpen((s) => ({ ...s, [i]: !s[i] })) });
  return (
    <div ref={setBox} data-testid="va-ranked" data-layout={narrow ? "cards" : "table"} className="min-w-0">
      {detail && <FnoSymbolDialog detail={detail} onClose={() => setDetail(null)} />}
      {narrow ? (
        <ol className="m-0 flex list-none flex-col p-0" style={{ gap: 8 }}>
          {b.rows.map((r, i) => (
            <Fragment key={`${r.symbol ?? ""}-${i}`}>
              {card(r, `${i}`, false, ctl(i))}
              {altsOpen[i] && r.alternatives?.map((a, j) => card(a, `${i}.${j}`, true))}
            </Fragment>
          ))}
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
                {tableRow(r, `${i}`, false, ctl(i))}
                {altsOpen[i] && r.alternatives?.map((a, j) => tableRow(a, `${i}.${j}`, true))}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
