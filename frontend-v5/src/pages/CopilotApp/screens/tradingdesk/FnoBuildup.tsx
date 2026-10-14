/**
 * Smart trading desk — Options & futures lab · OI build-up across F&O stocks.
 *
 *   GET /api/fno/scan/buildup   one row per F&O stock on the latest bhavcopy day: the nearest future's price change,
 *                               the change in open interest over every expiry, and the route's build-up label
 *                               (useBuildup, fno-buildup.ts). End of day.
 *
 * The four quadrant counts are the route's own, over every stock it scanned;
 * each also filters the table. The table sorts by stock, price change or OI
 * change, and a row opens that stock's option chain in the lab.
 */
import { useMemo, useState, type CSSProperties, type KeyboardEvent } from "react";
import { StockIcon } from "../../components/EntityIcon";
import { EmptyBlock, LoadingBlock, Pill, TONE_COLOR, fmtNum, fmtPct, signTone } from "../../components/ui";
import { SourceLine } from "../markets/parts";
import { QueryProblem, fmtDay, fmtQty } from "../trading/parts";
import { BUILDUP_LABELS, BUILDUP_META, useBuildup, type BuildupQuadrant, type BuildupRow } from "./fno-buildup";

type SortKey = "symbol" | "price" | "oi";
type SortDir = "asc" | "desc";
/** null = the route's own order: the largest OI change either way first. */
type Sort = { key: SortKey; dir: SortDir } | null;

/** Rows listed before "Show all". */
const PAGE = 30;

const TEMPLATE = "minmax(120px,1.4fr) 92px 92px minmax(120px,1fr)";
const cell: CSSProperties = { minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };

/** Missing values sort last in either direction. */
function compare(a: BuildupRow, b: BuildupRow, key: SortKey, dir: SortDir): number {
  if (key === "symbol") return dir === "asc" ? a.symbol.localeCompare(b.symbol) : b.symbol.localeCompare(a.symbol);
  const va = key === "price" ? a.priceChgPct : a.oiChgPct;
  const vb = key === "price" ? b.priceChgPct : b.oiChgPct;
  if (va == null && vb == null) return a.symbol.localeCompare(b.symbol);
  if (va == null) return 1;
  if (vb == null) return -1;
  return (dir === "asc" ? va - vb : vb - va) || a.symbol.localeCompare(b.symbol);
}

const SORT_LABEL: Record<SortKey, string> = { symbol: "Stock", price: "Price chg %", oi: "OI chg %" };

export function BuildupView({ onOpen }: { onOpen: (symbol: string) => void }) {
  const q = useBuildup(true);
  const [quadrant, setQuadrant] = useState<BuildupQuadrant | null>(null);
  const [sort, setSort] = useState<Sort>(null);
  const [all, setAll] = useState(false);

  const rows = useMemo(() => {
    const kept = (q.data?.rows ?? []).filter((r) => quadrant == null || r.label === quadrant);
    return sort ? kept.sort((a, b) => compare(a, b, sort.key, sort.dir)) : kept;
  }, [q.data, quadrant, sort]);

  if (q.isPending) return <LoadingBlock label="Scanning F&O stocks for OI build-up" rows={4} />;
  if (q.isError) return <div data-testid="desk-buildup-error"><QueryProblem what="OI build-up across F&O stocks" error={q.error} onRetry={() => q.refetch()} /></div>;
  const d = q.data;
  if (d.rows.length === 0) {
    return (
      <div data-testid="desk-buildup-empty">
        <EmptyBlock title="No stock futures on the latest day" body="The end-of-day F&O file the route read has no stock-futures rows to scan." />
      </div>
    );
  }

  const shown = all ? rows : rows.slice(0, PAGE);
  const pickSort = (key: SortKey) =>
    setSort((s) => (s?.key === key ? { key, dir: s.dir === "desc" ? "asc" : "desc" } : { key, dir: key === "symbol" ? "asc" : "desc" }));
  const open = (sym: string) => onOpen(sym);
  const onKey = (e: KeyboardEvent, sym: string) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      open(sym);
    }
  };

  return (
    <div data-testid="desk-buildup" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      <div role="group" aria-label="Build-up type" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 8 }}>
        {BUILDUP_LABELS.map((k) => {
          const m = BUILDUP_META[k];
          const on = quadrant === k;
          return (
            <button
              key={k}
              type="button"
              aria-pressed={on}
              data-testid={`desk-buildup-q-${k}`}
              title={on ? "Show every label" : `Show ${m.label.toLowerCase()} only`}
              onClick={() => { setQuadrant(on ? null : k); setAll(false); }}
              className="flex min-w-0 flex-col"
              style={{
                gap: 3, padding: "10px 12px", borderRadius: 12, textAlign: "left", cursor: "pointer", fontFamily: "var(--sans)", color: "var(--cp-ink)",
                border: `1px solid ${on ? "var(--mint-line)" : "var(--cp-line)"}`, background: on ? "var(--mint-soft)" : "var(--bg-1)",
              }}
            >
              <span className="cp-eyebrow" style={{ color: TONE_COLOR[m.tone] }}>{m.label}</span>
              <span data-testid={`desk-buildup-count-${k}`} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.1 }}>{fmtNum(d.counts[k])}</span>
              <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{m.rule}</span>
            </button>
          );
        })}
      </div>
      <span data-testid="desk-buildup-neutral" className="cp-mono-note">
        {d.counts.neutral != null ? `${fmtNum(d.counts.neutral)} neutral (price or OI unchanged)` : "Neutral count not sent"}
        {d.counts.noData ? ` · ${fmtNum(d.counts.noData)} without a label (a change is missing)` : ""}
        {d.universe != null ? ` · ${fmtNum(d.universe)} F&O stocks scanned` : ""}
        {quadrant ? ` · showing ${BUILDUP_META[quadrant].label.toLowerCase()} only` : ""}
      </span>

      <div className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden" }}>
        <div data-testid="desk-buildup-table" className="cp-scroll overflow-x-auto" role="table" aria-label="OI build-up by F&O stock" aria-rowcount={rows.length + 1}>
          <div style={{ minWidth: 440 }}>
            <div role="row" className="grid" style={{ gridTemplateColumns: TEMPLATE, gap: 12, padding: "10px 16px", borderBottom: "1px solid var(--cp-line)" }}>
              {(["symbol", "price", "oi"] as const).map((k) => {
                const on = sort?.key === k;
                return (
                  <span key={k} role="columnheader" aria-sort={on ? (sort?.dir === "asc" ? "ascending" : "descending") : "none"} style={{ ...cell, textAlign: k === "symbol" ? "left" : "right" }}>
                    <button
                      type="button"
                      data-testid={`desk-buildup-sort-${k}`}
                      onClick={() => pickSort(k)}
                      className="cp-mono-note"
                      style={{ padding: 0, border: 0, background: "none", cursor: "pointer", color: on ? "var(--cp-ink)" : undefined }}
                    >
                      {SORT_LABEL[k]}{on ? (sort?.dir === "asc" ? " ↑" : " ↓") : ""}
                    </button>
                  </span>
                );
              })}
              <span role="columnheader" className="cp-mono-note" style={cell}>Build-up</span>
            </div>
            {shown.length === 0 && (
              <div data-testid="desk-buildup-none" style={{ padding: 16, fontSize: 13, color: "var(--cp-ink-3)" }}>No stock has this label in the rows sent.</div>
            )}
            {shown.map((r) => {
              const m = r.label ? BUILDUP_META[r.label] : null;
              return (
                <div
                  key={r.symbol}
                  role="row"
                  tabIndex={0}
                  data-testid="desk-buildup-row"
                  data-symbol={r.symbol}
                  title={`Open the ${r.symbol} option chain`}
                  onClick={() => open(r.symbol)}
                  onKeyDown={(e) => onKey(e, r.symbol)}
                  className="cp-row-link grid items-center"
                  style={{ gridTemplateColumns: TEMPLATE, gap: 12, padding: "9px 16px", borderBottom: "1px solid var(--cp-line)", fontSize: 13, cursor: "pointer" }}
                >
                  <span role="cell" className="flex items-center" style={{ ...cell, gap: 8 }}>
                    <StockIcon symbol={r.symbol} size={20} />
                    <span className="flex min-w-0 flex-col" style={{ gap: 1 }}>
                      <span data-testid="desk-buildup-symbol" style={{ ...cell, color: "var(--cp-ink)", fontWeight: 500 }}>{r.symbol}</span>
                      <span style={{ ...cell, fontSize: 11, color: "var(--cp-ink-3)" }}>
                        OI {fmtQty(r.oi)}{r.expiries != null ? ` · ${fmtNum(r.expiries)} ${r.expiries === 1 ? "expiry" : "expiries"}` : ""}{r.nearExpiry ? ` · near ${fmtDay(r.nearExpiry)}` : ""}
                      </span>
                    </span>
                  </span>
                  <span role="cell" data-testid="desk-buildup-price" className="cp-num" style={{ ...cell, textAlign: "right", color: TONE_COLOR[signTone(r.priceChgPct)] }}>
                    {fmtPct(r.priceChgPct, { signed: true, digits: 2 })}
                  </span>
                  <span role="cell" data-testid="desk-buildup-oi" className="cp-num" style={{ ...cell, textAlign: "right", color: TONE_COLOR[signTone(r.oiChgPct)] }}>
                    {fmtPct(r.oiChgPct, { signed: true, digits: 2 })}
                  </span>
                  <span role="cell" data-testid="desk-buildup-label" data-label={r.label ?? ""} style={cell}>{m ? <Pill tone={m.tone}>{m.label}</Pill> : "—"}</span>
                </div>
              );
            })}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between" style={{ gap: 8, padding: "10px 16px" }}>
          <span data-testid="desk-buildup-shown" className="cp-mono-note">
            {fmtNum(shown.length)} of {fmtNum(rows.length)} shown · {sort ? `sorted by ${SORT_LABEL[sort.key].toLowerCase()}, ${sort.dir === "desc" ? "high to low" : "low to high"}` : "largest OI change either way first"} · open a row for its option chain
          </span>
          {rows.length > PAGE && (
            <button type="button" className="cp-chip" data-testid="desk-buildup-all" aria-expanded={all} onClick={() => setAll(!all)}>
              {all ? "Show fewer" : `Show all ${fmtNum(rows.length)}`}
            </button>
          )}
        </div>
      </div>

      <SourceLine
        testId="desk-buildup-source"
        source={d.source}
        asOf={d.asOf}
        asOfLabel="end of day"
        note="price change = the nearest future’s close vs its previous close · OI change = summed over every expiry, so a roll does not read as unwinding"
      />
    </div>
  );
}
