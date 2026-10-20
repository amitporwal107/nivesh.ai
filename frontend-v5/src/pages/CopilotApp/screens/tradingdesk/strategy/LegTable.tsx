/**
 * Strategy Builder — the legs of the position (PRD §16.6 D: "allow inspecting each leg"), one card per
 * leg so it reads on a phone: side, instrument (the underlying's icon beside its name), expiry, strike,
 * option type, lots × lot size, the entry price with its source and date, the leg's gross P&L range
 * over the plotted prices (read from the answer's `per_leg` line, as "low to high"; an option leg that
 * is still rising at the edge says so rather than calling the edge its maximum) and, when the
 * pre-expiry estimate could not price the leg, the reason.
 */
import { StockIcon } from "../../../components/EntityIcon";
import { fmtDay } from "../../trading/parts";
import type { PayoffLeg, PayoffResponse } from "./strategy-contract";
import { DASH, rs } from "./strategy-format";

export interface LegTableProps {
  underlying: string;
  legs: PayoffLeg[];
  /** The answer's expiry block `per_leg` (null before the first answer). */
  perLeg?: NonNullable<PayoffResponse["expiry"]>["per_leg"] | null;
  /** The pre-expiry block's `unavailable` list. */
  unavailable?: Array<{ leg: number; reason: string }>;
  persona?: "trader" | "investor";
}

const KIND_WORD = { cash: "Shares", future: "Future", option: "Option" } as const;

/** The leg's gross P&L extremes on the plotted prices, with a note when the line is still running at an edge. */
function legRange(line: Array<number | null> | undefined): { low: number; high: number; openLow: boolean; openHigh: boolean } | null {
  const v = (line ?? []).filter((x): x is number => x != null);
  if (v.length < 2) return null;
  const low = Math.min(...v);
  const high = Math.max(...v);
  const first = v[0], second = v[1], last = v[v.length - 1], prev = v[v.length - 2];
  const edgeMoves = (a: number, b: number) => a !== b;
  return {
    low, high,
    openLow: (low === first && edgeMoves(first, second)) || (low === last && edgeMoves(last, prev)),
    openHigh: (high === first && edgeMoves(first, second)) || (high === last && edgeMoves(last, prev)),
  };
}

export function LegTable({ underlying, legs, perLeg, unavailable = [], persona = "trader" }: LegTableProps) {
  const investor = persona === "investor";
  return (
    <ul data-testid="leg-table" className="m-0 grid p-0" style={{ listStyle: "none", gap: 10, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))" }}>
      {legs.map((l, i) => {
        const why = unavailable.filter((u) => u.leg === i).map((u) => u.reason);
        const range = legRange(perLeg?.find((p) => p.index === i)?.gross);
        const lots = l.kind === "cash" ? `${l.quantity} ${l.quantity === 1 ? "share" : "shares"}` : `${l.quantity} ${l.quantity === 1 ? "lot" : "lots"} × ${l.lot_size}`;
        const instrument = l.kind === "option" ? `${underlying} ${l.strike ?? DASH} ${l.option_type === "put" ? "PUT" : "CALL"}` : l.kind === "future" ? `${underlying} FUT` : underlying;
        const buy = l.side === "buy";
        return (
          <li key={i} data-testid="leg-row" data-leg={i} data-side={l.side} className="cp-card flex min-w-0 flex-col" style={{ gap: 8, padding: "12px 14px" }}>
            <div className="flex min-w-0 items-center" style={{ gap: 8 }}>
              <StockIcon symbol={underlying} size={22} />
              <span data-testid="leg-side" className="cp-num" style={{ fontSize: 11, letterSpacing: "0.1em", padding: "2px 8px", borderRadius: 999, border: `1px solid ${buy ? "var(--mint-line)" : "var(--cp-danger)"}`, color: buy ? "var(--mint)" : "var(--cp-danger)" }}>
                {buy ? (investor ? "BUY" : "LONG · BUY") : (investor ? "SELL" : "SHORT · SELL")}
              </span>
              <span data-testid="leg-instrument" className="min-w-0" style={{ fontSize: 13, fontWeight: 500, overflowWrap: "anywhere" }}>{instrument}</span>
            </div>
            <dl className="m-0 grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(120px,1fr))", gap: "6px 12px", fontSize: 12 }}>
              <Cell k="Type" v={KIND_WORD[l.kind]} />
              <Cell k="Expiry" id="expiry" v={l.expiry ? fmtDay(l.expiry) : DASH} />
              <Cell k="Strike" id="strike" v={l.strike != null ? rs(l.strike) : DASH} />
              <Cell k="Call / put" id="optiontype" v={l.option_type ? l.option_type : DASH} />
              <Cell k={l.kind === "cash" ? "Quantity" : "Lots × lot size"} id="qty" v={lots} />
              <Cell k={l.kind === "option" ? "Premium per unit" : "Entry price"} id="entry" v={rs(l.entry_price)} sub={l.price_source || "source not given"} />
              <Cell
                k="Gross P&L range"
                id="range"
                v={range ? `${rs(range.low)} to ${rs(range.high, { signed: true })}` : DASH}
                sub={range ? `on the plotted prices${range.openHigh ? "; still rising at the edge" : ""}${range.openLow ? "; still falling at the edge" : ""}` : "no per-leg line in the answer"}
              />
              <Cell k="Pre-expiry estimate" id="unavailable" v={why.length ? "Unavailable" : DASH} sub={why.join(" ") || undefined} warn={why.length > 0} />
            </dl>
          </li>
        );
      })}
    </ul>
  );
}

function Cell({ k, v, sub, id, warn }: { k: string; v: string; sub?: string; id?: string; warn?: boolean }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 1 }}>
      <dt className="cp-eyebrow" style={{ margin: 0 }}>{k}</dt>
      <dd data-testid={id ? `leg-${id}` : undefined} className="cp-num m-0" style={{ color: warn ? "var(--amber)" : "var(--cp-ink)", overflowWrap: "anywhere" }}>{v}</dd>
      {sub && <dd data-testid={id ? `leg-${id}-note` : undefined} className="m-0" style={{ fontSize: 10.5, lineHeight: 1.4, color: warn ? "var(--amber)" : "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{sub}</dd>}
    </div>
  );
}
