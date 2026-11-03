/**
 * The matches of a screen, as one table with four lenses over the same rows:
 *
 *   Overview · Fundamentals · Technicals · Ownership & funds
 *
 * Every figure is a column of the run's own rows (POST /api/screeners/run): the feature store's
 * fundamentals, technicals and shareholding, and the mutual-fund evidence joined from the smart-money
 * scanner. Nothing is recomputed here. "LTP" and "Day" come from Kite's live feed while it is LIVE
 * (useLiveOverlays) and read "—" otherwise. A stock with no value for a metric shows "—", never 0,
 * and sorts after every stock that has one.
 *
 * A row opens the stock in a panel (StockPanel), which is Research's own stock view.
 *
 * With `select`, each row also carries a checkbox (not opening the panel) and the header one chooses the first `select.max`.
 */
import { useMemo, useState, type CSSProperties, type KeyboardEvent } from "react";
import type { StockHit } from "@/hooks/use-instrument-search";
import { StockIcon } from "../../components/EntityIcon";
import { fmtNum } from "../../components/ui";
import { closeLabel, type useLiveOverlays } from "../../lib/useLiveQuotes";
import { TabBar, type TabItem } from "../markets/parts";

type Row = Record<string, unknown>;
type Live = ReturnType<typeof useLiveOverlays>;

interface Col {
  key: string;
  header: string;
  /** Shown under the header on hover. */
  title?: string;
  digits?: number;
  /** Green above zero, red below. */
  signed?: boolean;
  /** Reads from the live feed rather than the row. */
  live?: "ltp" | "chg";
  /** Plain integer count. */
  count?: boolean;
}

const MF_NOTE = "Disclosed fund-house holdings, 3 months. Nifty 500 only: other stocks show —.";

const LTP: Col = { key: "live_ltp", header: "LTP ₹", live: "ltp", digits: 2, title: "Kite live price while the feed is live; otherwise the last close" };
const DAY: Col = { key: "live_chg", header: "Day %", live: "chg", digits: 2, signed: true, title: "Change on the day from Kite" };

export type Lens = "overview" | "fundamentals" | "technicals" | "ownership";

export const LENSES: TabItem<Lens>[] = [
  { key: "overview", label: "Overview" },
  { key: "fundamentals", label: "Fundamentals" },
  { key: "technicals", label: "Technicals" },
  { key: "ownership", label: "Ownership & funds" },
];

const COLUMNS: Record<Lens, Col[]> = {
  overview: [
    LTP, DAY,
    { key: "mcap", header: "Mkt cap ₹Cr" },
    { key: "pe", header: "P/E", digits: 1 },
    { key: "roe", header: "ROE %", digits: 1 },
    { key: "return1y", header: "1Y %", digits: 1, signed: true },
    { key: "rsi", header: "RSI", digits: 0 },
    { key: "amcsUp", header: "Houses ↑", count: true, title: MF_NOTE },
  ],
  fundamentals: [
    { key: "mcap", header: "Mkt cap ₹Cr" },
    { key: "pe", header: "P/E", digits: 1 },
    { key: "pb", header: "P/B", digits: 1 },
    { key: "evEbitda", header: "EV/EBITDA", digits: 1 },
    { key: "roe", header: "ROE %", digits: 1 },
    { key: "roce", header: "ROCE %", digits: 1 },
    { key: "de", header: "D/E", digits: 2 },
    { key: "profitMargin", header: "Net margin %", digits: 1 },
    { key: "salesG", header: "Sales 3Y %", digits: 1, signed: true },
    { key: "profitG", header: "Profit 3Y %", digits: 1, signed: true },
    { key: "divYield", header: "Div yield %", digits: 2 },
  ],
  technicals: [
    LTP, DAY,
    { key: "return1y", header: "1Y %", digits: 1, signed: true },
    { key: "rsi", header: "RSI", digits: 0 },
    { key: "momentum", header: "Momentum", digits: 0 },
    { key: "accumulation", header: "Accumulation", digits: 0 },
    { key: "beta", header: "Beta", digits: 2 },
    { key: "volatility", header: "Volatility %", digits: 1 },
    { key: "maxDrawdown", header: "Max DD %", digits: 1, signed: true },
  ],
  ownership: [
    { key: "promoter", header: "Promoter %", digits: 1 },
    { key: "promoterPledge", header: "Pledged %", digits: 1 },
    { key: "promoterChange", header: "Promoter Δ", digits: 2, signed: true, title: "Change vs last quarter, percentage points" },
    { key: "fii", header: "FII %", digits: 1 },
    { key: "fiiChange", header: "FII Δ", digits: 2, signed: true, title: "Change vs last quarter, percentage points" },
    { key: "dii", header: "DII %", digits: 1 },
    { key: "mfChange", header: "MF Δ %", digits: 1, signed: true, title: MF_NOTE },
    { key: "amcsUp", header: "Houses ↑", count: true, title: MF_NOTE },
    { key: "amcsDn", header: "Houses ↓", count: true, title: MF_NOTE },
    { key: "amcsHolding", header: "Houses", count: true, title: MF_NOTE },
  ],
};

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

const symbolOf = (r: Row) => String(r.ticker ?? r.symbol ?? "");

const th: CSSProperties = {
  padding: "10px 12px", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase",
  color: "var(--cp-ink-3)", fontWeight: 400, whiteSpace: "nowrap", borderBottom: "1px solid var(--cp-line)", background: "var(--bg-1)",
};

/** Row selection, for "Add to a list" (screener/AddToList.tsx). The table only draws the boxes; the page owns the choice. */
export interface RowSelect {
  selected: ReadonlySet<string>;
  onToggle: (symbol: string) => void;
  /** The header box: every selectable row, or none. */
  onToggleAll: () => void;
  /** All of the rows that can be chosen are chosen. */
  allSelected: boolean;
  /** How many rows can be chosen at most (a list holds 100). */
  max: number;
}

const box: CSSProperties = { width: 18, height: 18, margin: 0, accentColor: "var(--mint)", cursor: "pointer", flex: "none" };

export function ResultsTable({ rows, live, onOpen, select }: { rows: Row[]; live: Live; onOpen: (s: StockHit) => void; select?: RowSelect }) {
  const [lens, setLens] = useState<Lens>("overview");
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" } | null>(null);

  const liveOf = (r: Row) => live.get(symbolOf(r));
  // Kite's price and day change are columns only while the feed has a quote for some row of the run
  // (live, or the closing snapshot of a session the end-of-day data does not have yet).
  const firstQuote = rows.map(liveOf).find((q) => q) ?? null;
  const cols = COLUMNS[lens]
    .filter((c) => !c.live || firstQuote)
    .map((c) => (c.live === "ltp" && firstQuote?.kind === "close" ? { ...c, header: closeLabel(firstQuote) } : c));
  const valueOf = (r: Row, c: Col): number | null => {
    if (c.live) {
      const q = liveOf(r);
      return q ? (c.live === "ltp" ? q.ltp : q.changePct) : null;
    }
    return num(r[c.key]);
  };

  const sorted = useMemo(() => {
    const col = sort && cols.find((c) => c.key === sort.key);
    if (!sort || !col) return rows;
    const val = (r: Row) => valueOf(r, col);
    // A stock with no value goes last in either direction; ties keep the run's order.
    return rows
      .map((r, i) => ({ r, i, v: val(r) }))
      .sort((a, b) => {
        if (a.v === null && b.v === null) return a.i - b.i;
        if (a.v === null) return 1;
        if (b.v === null) return -1;
        return (sort.dir === "asc" ? a.v - b.v : b.v - a.v) || a.i - b.i;
      })
      .map((x) => x.r);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- valueOf reads `live`, listed through it
  }, [rows, sort, cols, live]);

  const toggle = (key: string) =>
    setSort((s) => (s?.key !== key ? { key, dir: "desc" } : s.dir === "desc" ? { key, dir: "asc" } : null));

  const open = (r: Row) =>
    onOpen({ symbol: symbolOf(r), name: String(r.name ?? symbolOf(r)), sector: (r.sector as string | null) ?? null });
  const onKey = (e: KeyboardEvent, r: Row) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(r); }
  };

  const cell = (r: Row, c: Col) => {
    const v = valueOf(r, c);
    if (v === null) return <span style={{ color: "var(--cp-ink-3)" }}>—</span>;
    const text = c.key === "mcap" ? fmtNum(v) : c.count ? fmtNum(v) : c.digits !== undefined
      ? `${c.signed && v > 0 ? "+" : ""}${new Intl.NumberFormat("en-IN", { minimumFractionDigits: c.digits, maximumFractionDigits: c.digits }).format(v)}`
      : fmtNum(v);
    const color = c.signed && v !== 0 ? (v > 0 ? "var(--mint)" : "var(--cp-danger)") : undefined;
    return <span style={{ color }}>{text}</span>;
  };

  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      <TabBar tabs={LENSES} value={lens} onChange={(l) => { setLens(l); setSort(null); }} label="Columns to show" idPrefix="screener-lens" />
      <div data-testid="screener-table-scroll" className="cp-card" style={{ overflowX: "auto" }}>
        <table data-testid="screener-table" data-lens={lens} style={{ borderCollapse: "separate", borderSpacing: 0, width: "100%", minWidth: 220 + cols.length * 84 }}>
          <thead>
            <tr>
              <th scope="col" style={{ ...th, textAlign: "left", position: "sticky", left: 0, zIndex: 1 }}>
                {select ? (
                  <label className="flex items-center" style={{ gap: 10, cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      data-testid="screener-select-all"
                      checked={select.allSelected}
                      onChange={select.onToggleAll}
                      aria-label={rows.length > select.max ? `Select the first ${select.max} stocks` : "Select all stocks"}
                      style={box}
                    />
                    Stock
                  </label>
                ) : "Stock"}
              </th>
              {cols.map((c) => {
                const on = sort?.key === c.key;
                return (
                  <th key={c.key} scope="col" title={c.title} aria-sort={on ? (sort.dir === "asc" ? "ascending" : "descending") : "none"} style={{ ...th, textAlign: "right", padding: 0 }}>
                    <button
                      type="button"
                      data-testid="screener-sort"
                      data-col={c.key}
                      onClick={() => toggle(c.key)}
                      style={{ all: "unset", cursor: "pointer", padding: "10px 12px", display: "inline-flex", gap: 4, alignItems: "center", color: on ? "var(--cp-ink)" : undefined }}
                    >
                      {c.header}<span aria-hidden>{on ? (sort.dir === "asc" ? "↑" : "↓") : ""}</span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr
                key={symbolOf(r)}
                data-testid="screener-row"
                data-symbol={symbolOf(r)}
                tabIndex={0}
                role="button"
                aria-label={`Open ${String(r.name ?? symbolOf(r))}`}
                onClick={() => open(r)}
                onKeyDown={(e) => onKey(e, r)}
                className="cp-row-link"
              >
                <td style={{ padding: "9px 12px", position: "sticky", left: 0, background: "var(--bg-1)", borderBottom: "1px solid var(--cp-line)", minWidth: select ? 222 : 190 }}>
                  <span className="flex items-center" style={{ gap: 10, minWidth: 0 }}>
                    {select && (
                      <input
                        type="checkbox"
                        data-testid="screener-select"
                        data-symbol={symbolOf(r)}
                        checked={select.selected.has(symbolOf(r))}
                        onChange={() => select.onToggle(symbolOf(r))}
                        onClick={(e) => e.stopPropagation()}
                        onKeyDown={(e) => e.stopPropagation()}
                        aria-label={`Select ${symbolOf(r)}`}
                        style={box}
                      />
                    )}
                    <StockIcon symbol={symbolOf(r)} name={String(r.name ?? "")} size={26} />
                    <span className="flex min-w-0 flex-col" style={{ gap: 1 }}>
                      <span style={{ fontSize: 13.5, fontWeight: 500, color: "var(--cp-ink)", whiteSpace: "nowrap" }}>{symbolOf(r)}</span>
                      <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 170 }}>
                        {String(r.sector ?? "") || "—"}
                      </span>
                    </span>
                  </span>
                </td>
                {cols.map((c) => (
                  <td key={c.key} data-col={c.key} className="cp-num" style={{ padding: "9px 12px", textAlign: "right", fontSize: 13, whiteSpace: "nowrap", borderBottom: "1px solid var(--cp-line)" }}>
                    {cell(r, c)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
