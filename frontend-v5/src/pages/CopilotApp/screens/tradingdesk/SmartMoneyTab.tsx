/**
 * Smart trading desk · 06 Smart Money Movement.
 *
 * Built to the v2 design (docs/design/SMART_MONEY_MOVEMENT_SCREEN.md §1–§2, source
 * frontend-v5/design/smart-money/Smart Money Movement v2.dc.html):
 *
 *   period toggle 1M|3M|6M|1Y  ·  five feed-status strips  ·  market-wide flows with a cumulative
 *   FII/DII chart  ·  sector rotation (diverging bars) beside evidence breadth  ·  scanner with
 *   lanes, filters and the A/B/C/D legend  ·  stock-evidence rail  ·  the §2.9 footer verbatim.
 *
 * Two deliberate departures from the drawing, both because the desk already owns the behaviour or
 * the warehouse cannot back it:
 *   * The design's rail carries its own Copilot. The desk already docks one from 1400px
 *     (TradingDesk.tsx), so the rail here holds only the Stock evidence panel and questions go to
 *     the desk's `askDesk`. One Copilot, not two.
 *   * The design offers a "Nifty 1000" universe. NSE publishes no such index and the warehouse
 *     holds no such list; Nifty Total Market (755 names) is offered under its own name.
 *
 * This screen shows EVIDENCE, never a verdict: no score, no ranking by one, no hit rate. The
 * reasons sit in smart-money-data.ts; `breadth.validatedStudy` is the live read that drives the
 * wording rather than a hardcoded string. Reads only — nothing here places an order.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Column, DataTable, EmptyBlock, ErrorBlock, Eyebrow, Footnote, LoadingBlock, Pill, Screen,
  ScreenHeader, Section, fmtDate, fmtNum, signTone,
} from "../../components/ui";
import { useDesk } from "./context";
import { TrustLine } from "./trust";
import {
  EVIDENCE_LABEL, EVIDENCE_LEGEND, EVIDENCE_NOTE, SECTOR_MEASURES, SM_DIRECTIONS, SM_FRESHNESS,
  SM_PERIODS, SM_UNIVERSES, type EvidenceClass, type FlowPoint, type ScannerFilters, type ScannerRow,
  type SectorMeasure, type SmDirection, type SmFreshness, type SmLane, type SmPeriod, type SmUniverse,
  FLOW_CAVEAT, amcConcentration, dataAgeDays, evidenceChain, flowRegime, ingestAheadOfData,
  mfWindowNote, rollingNet, rowDirection, sectorGrossCr, sectorTotals, sectorValue, useSmAmc,
  useSmartMoney, whatWouldWeaken,
} from "./smart-money-data";

/**
 * Whether THIS tab's own column is at least `px` wide — measured, not inferred from the viewport.
 * The desk docks its Copilot (384px) from 1400px, so at a 1600px viewport the tab has only ~490px
 * to work with and a 380px rail would leave the scanner clipped. Measuring means the rail appears
 * exactly when it fits, whether or not the dock is open.
 */
function useRoomFor(px: number): [boolean, (el: HTMLDivElement | null) => void] {
  const [on, setOn] = useState(false);
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!node || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setOn(e.contentRect.width >= px));
    ro.observe(node);
    setOn(node.getBoundingClientRect().width >= px);
    return () => ro.disconnect();
  }, [node, px]);
  return [on, setNode];
}

/**
 * A real colour for a tone name.
 *
 * `--danger` and `--indigo` hold "R G B" TRIPLETS in this app (so Tailwind's alpha modifiers work),
 * not colours — see the header of copilot-app.css. So `var(--danger)` is invalid CSS and paints
 * nothing, which is why negative sector bars and the indigo breadth tier rendered invisible while
 * the mint ones were fine (`--mint` is a real hex). The `--cp-*` aliases are the actual colours.
 */
const TONE_VAR: Record<string, string> = {
  mint: "var(--mint)",
  amber: "var(--amber)",
  indigo: "var(--cp-indigo)",
  danger: "var(--cp-danger)",
  ink: "var(--cp-ink-2)",
  "ink-3": "var(--cp-ink-3)",
  "ink-4": "var(--cp-ink-4)",
};
const toneColor = (t: string) => TONE_VAR[t] ?? "var(--cp-ink-2)";

const CLASS_TONE: Record<EvidenceClass, "mint" | "indigo" | "amber" | "ink"> = {
  D: "mint", A: "mint", B: "indigo", C: "amber", none: "ink",
};

const FRESH_TONE: Record<string, "mint" | "amber" | "danger"> = {
  fresh: "mint", ageing: "amber", stale: "danger",
};

/** ₹ crore, signed, with the direction also in words so colour is never the only cue. */
function Cr({ v, big }: { v: number | null; big?: boolean }) {
  if (v == null) return <span style={{ color: "var(--cp-ink-4)" }}>—</span>;
  const tone = signTone(v);
  return (
    <span className="cp-num" style={{ fontSize: big ? 20 : undefined, whiteSpace: "nowrap", color: toneColor(tone) }}>
      {v > 0 ? "+" : v < 0 ? "−" : ""}₹{fmtNum(Math.abs(v))} cr
      <span className="sr-only">{v > 0 ? " net bought" : v < 0 ? " net sold" : " flat"}</span>
    </span>
  );
}

/** A segmented control. One row of chips, each a real tab/button with its own label. */
function Chips<T extends string>({ items, value, onPick, idPrefix, label }: {
  items: ReadonlyArray<{ id: T; label: string; note?: string }>;
  value: T; onPick: (v: T) => void; idPrefix: string; label: string;
}) {
  return (
    <span role="tablist" aria-label={label} className="flex flex-wrap" style={{ gap: 4 }}>
      {items.map((it) => {
        const on = it.id === value;
        return (
          <button
            key={it.id} type="button" role="tab" aria-selected={on}
            data-testid={`${idPrefix}-${it.id}`} title={it.note}
            onClick={() => onPick(it.id)}
            className="cp-num"
            style={{
              padding: "3px 9px", borderRadius: 999, fontSize: 11, cursor: "pointer", whiteSpace: "nowrap",
              border: `1px solid ${on ? "var(--mint)" : "var(--cp-line)"}`,
              background: on ? "var(--mint-soft)" : "transparent",
              color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
            }}
          >{it.label}</button>
        );
      })}
    </span>
  );
}

// ── the cumulative FII / DII chart (spec 2.3) ────────────────────────────

/**
 * Cumulative FII and DII net cash over the window. Two series, one axis — both are ₹ crore, so a
 * second scale would be a lie. Crosshair + tooltip on hover, a legend and direct end-labels so
 * identity never rests on colour, and an equivalent table for anyone who cannot use the plot.
 * Colours are --sm-fii / --sm-dii, validated per mode against the card surface (see index.css).
 */
function CumulativeChart({ rows, grain }: { rows: FlowPoint[]; grain: string | null }) {
  const [hover, setHover] = useState<number | null>(null);
  const wrap = useRef<HTMLDivElement | null>(null);
  const W = 720, H = 190, PL = 56, PR = 16, PT = 14, PB = 26;

  const pts = rows.filter((r) => r.fiiCumCr != null || r.diiCumCr != null);
  if (pts.length < 2) {
    return <Footnote>Not enough points in this window to draw a series.</Footnote>;
  }
  const vals = pts.flatMap((r) => [r.fiiCumCr, r.diiCumCr]).filter((v): v is number => v != null);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const span = hi - lo || 1;
  const x = (i: number) => PL + (i * (W - PL - PR)) / (pts.length - 1);
  const y = (v: number) => PT + (H - PT - PB) * (1 - (v - lo) / span);
  const path = (k: "fiiCumCr" | "diiCumCr") => pts
    .map((r, i) => (r[k] == null ? null : `${i === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(r[k] as number).toFixed(1)}`))
    .filter(Boolean).join(" ");

  const zeroY = y(0);
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const rel = ((e.clientX - box.left) / box.width) * W;
    const i = Math.round(((rel - PL) / (W - PL - PR)) * (pts.length - 1));
    setHover(Math.max(0, Math.min(pts.length - 1, i)));
  };
  const h = hover == null ? null : pts[hover];
  const ticks = [lo, lo + span / 2, hi];

  return (
    <div ref={wrap} className="flex flex-col" style={{ gap: 8 }}>
      {/* Legend: always present for two series, so identity is never colour-alone. */}
      <div className="flex items-center" style={{ gap: 14, fontSize: 11.5, color: "var(--cp-ink-3)" }}>
        <span className="flex items-center" style={{ gap: 6 }}>
          <span aria-hidden style={{ width: 14, height: 2, borderRadius: 2, background: "var(--sm-fii)" }} />FII cumulative
        </span>
        <span className="flex items-center" style={{ gap: 6 }}>
          <span aria-hidden style={{ width: 14, height: 2, borderRadius: 2, background: "var(--sm-dii)" }} />DII cumulative
        </span>
        <span className="cp-mono-note">{grain === "monthly" ? "monthly" : "daily"} · ₹ crore</span>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img"
        data-testid="desk-smart-money-chart"
        aria-label={`Cumulative FII and DII net cash over the window. FII ends at ${pts[pts.length - 1].fiiCumCr ?? 0} crore, DII at ${pts[pts.length - 1].diiCumCr ?? 0} crore.`}
        style={{ overflow: "visible", cursor: "crosshair" }}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}
      >
        {/* Recessive grid: three value ticks and the zero line, nothing else. */}
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PL} x2={W - PR} y1={y(t)} y2={y(t)} stroke="var(--cp-line)" strokeWidth="1" />
            <text x={PL - 8} y={y(t) + 3.5} textAnchor="end" fontSize="9.5" fill="var(--cp-ink-4)" className="cp-num">
              {fmtNum(Math.round(t))}
            </text>
          </g>
        ))}
        {lo < 0 && hi > 0 && (
          <line x1={PL} x2={W - PR} y1={zeroY} y2={zeroY} stroke="var(--cp-ink-4)" strokeWidth="1" strokeDasharray="3 3" />
        )}
        <path d={path("fiiCumCr")} fill="none" stroke="var(--sm-fii)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        <path d={path("diiCumCr")} fill="none" stroke="var(--sm-dii)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

        {/* Direct end-labels: a second, non-colour cue for each series. */}
        {(["fiiCumCr", "diiCumCr"] as const).map((k, idx) => {
          const v = pts[pts.length - 1][k];
          if (v == null) return null;
          return (
            <text key={k} x={W - PR} y={y(v) + (idx === 0 ? -6 : 12)} textAnchor="end" fontSize="10"
                  fill={idx === 0 ? "var(--sm-fii)" : "var(--sm-dii)"} className="cp-num">
              {idx === 0 ? "FII" : "DII"}
            </text>
          );
        })}

        {h && (
          <g>
            <line x1={x(hover as number)} x2={x(hover as number)} y1={PT} y2={H - PB} stroke="var(--cp-ink-4)" strokeWidth="1" />
            {(["fiiCumCr", "diiCumCr"] as const).map((k, idx) => (h[k] == null ? null : (
              // A 2px surface ring keeps the two markers legible where the series cross.
              <circle key={k} cx={x(hover as number)} cy={y(h[k] as number)} r="4.5"
                      fill={idx === 0 ? "var(--sm-fii)" : "var(--sm-dii)"} stroke="var(--bg-1)" strokeWidth="2" />
            )))}
          </g>
        )}
        <text x={PL} y={H - 8} fontSize="9.5" fill="var(--cp-ink-4)" className="cp-num">{pts[0].date}</text>
        <text x={W - PR} y={H - 8} textAnchor="end" fontSize="9.5" fill="var(--cp-ink-4)" className="cp-num">{pts[pts.length - 1].date}</text>
      </svg>

      <div aria-live="polite" data-testid="desk-smart-money-chart-hover" style={{ minHeight: 18, fontSize: 12, color: "var(--cp-ink-2)" }}>
        {h ? (
          <span className="cp-num">
            {h.date} · FII <Cr v={h.fiiCumCr} /> · DII <Cr v={h.diiCumCr} />
          </span>
        ) : (
          <span style={{ color: "var(--cp-ink-4)" }}>Hover the chart for a date’s cumulative figures.</span>
        )}
      </div>

      <details>
        <summary style={{ fontSize: 11.5, color: "var(--cp-ink-3)", cursor: "pointer" }}>Show as a table</summary>
        <div className="cp-scroll" style={{ maxHeight: 220, overflow: "auto", marginTop: 8 }}>
          <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
            <thead>
              <tr>{["Date", "FII net", "DII net", "FII cum.", "DII cum."].map((h2) => (
                <th key={h2} className="cp-mono-note" style={{ textAlign: "right", padding: "4px 8px", borderBottom: "1px solid var(--cp-line)" }}>{h2}</th>
              ))}</tr>
            </thead>
            <tbody>
              {pts.map((r) => (
                <tr key={r.date}>
                  <td className="cp-num" style={{ padding: "3px 8px", color: "var(--cp-ink-3)" }}>{r.date}</td>
                  {[r.fiiNetCr, r.diiNetCr, r.fiiCumCr, r.diiCumCr].map((v, i) => (
                    <td key={i} className="cp-num" style={{ textAlign: "right", padding: "3px 8px" }}>{v == null ? "—" : fmtNum(v)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

// ── sector rotation: diverging bars (spec 2.4) ───────────────────────────

function SectorBars({ rows, measure }: { rows: Array<{ industry: string; stocks: number | null; stocksPriced: number | null; netValueCr: number | null; schemesUp: number | null; schemesDn: number | null }>; measure: SectorMeasure }) {
  const gross = sectorGrossCr(rows as never);
  const vals = rows.map((r) => sectorValue(r as never, measure, gross));
  const peak = Math.max(1, ...vals.map((v) => Math.abs(v ?? 0)));
  const unit = measure === "cr" ? "₹ cr" : measure === "pct" ? "%" : "stocks";
  // "# stocks" has no sign, so it draws from the left; the other two diverge around zero.
  const diverging = measure !== "stocks";

  return (
    <div className="flex flex-col" style={{ gap: 7 }} data-testid="desk-smart-money-sector-bars">
      {rows.map((r, i) => {
        const v = vals[i];
        const pct = v == null ? 0 : (Math.abs(v) / peak) * (diverging ? 50 : 100);
        const pos = (v ?? 0) >= 0;
        return (
          <div key={r.industry} className="grid items-center" style={{ gridTemplateColumns: "minmax(110px,0.9fr) minmax(0,1.6fr)", gap: 10 }}>
            <span style={{ fontSize: 12, color: "var(--cp-ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {r.industry}
            </span>
            <span className="flex items-center" style={{ gap: 8 }}>
              <span style={{ position: "relative", flex: "1 1 auto", minWidth: 90, height: 10, background: "var(--bg-2)", borderRadius: 3 }}>
                {diverging && <span aria-hidden style={{ position: "absolute", left: "50%", top: -1, bottom: -1, width: 1, background: "var(--cp-ink-4)" }} />}
                <span
                  style={{
                    position: "absolute", top: 0, height: 10, width: `${pct}%`,
                    // 4px rounded data-end, anchored to the baseline (zero), square at the origin.
                    ...(diverging
                      ? pos
                        ? { left: "50%", borderRadius: "0 4px 4px 0" }
                        : { right: "50%", borderRadius: "4px 0 0 4px" }
                      : { left: 0, borderRadius: "0 4px 4px 0" }),
                    background: toneColor(pos ? "mint" : "danger"),
                  }}
                />
              </span>
              <span className="cp-num" style={{ flex: "none", width: 66, textAlign: "right", fontSize: 11.5, color: "var(--cp-ink-2)" }}>
                {v == null ? "—" : `${diverging && v > 0 ? "+" : diverging && v < 0 ? "−" : ""}${fmtNum(Math.abs(v), measure === "pct" ? 1 : 0)}`}
                <span className="sr-only"> {unit}{diverging ? (v != null && v > 0 ? " net bought" : " net sold") : ""}</span>
              </span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── evidence breadth: three tiers with bars (spec 2.5) ───────────────────

function Tier({ label, n, of, tone, note }: { label: string; n: number | null; of: number | null; tone: "mint" | "indigo" | "amber"; note?: string }) {
  const pct = n != null && of ? (n / of) * 100 : 0;
  return (
    <div className="flex flex-col" style={{ gap: 4 }} title={note}>
      <span className="flex items-baseline" style={{ gap: 8, justifyContent: "space-between" }}>
        <span style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>{label}</span>
        <span className="cp-num" style={{ fontSize: 13, color: toneColor(tone) }}>{fmtNum(n)}</span>
      </span>
      <span style={{ height: 6, background: "var(--bg-2)", borderRadius: 3, overflow: "hidden" }}>
        <span style={{ display: "block", height: 6, width: `${pct}%`, background: toneColor(tone), borderRadius: "0 4px 4px 0" }} />
      </span>
    </div>
  );
}

// ── AMC contribution drill-down ──────────────────────────────────────────

/**
 * Which fund houses are behind a stock's disclosed change. "11 disclosing AMCs" is a coverage
 * statistic — it cannot say whether a month's move is broad-based or one house, and this can.
 *
 * Every scheme a house runs is aggregated and the stock is resolved by ISIN. Value is a LEVEL
 * (what is held now), never a month-on-month change, because differencing two months of market
 * value mixes price movement into what would read as buying. A house that disclosed no value at
 * all reads "—", never 0.
 */
function AmcContribution({ symbol }: { symbol: string }) {
  const q = useSmAmc(symbol);
  if (q.isPending) return <LoadingBlock label="Reading scheme disclosures" rows={2} />;
  if (q.isError) {
    return <Footnote>AMC contribution didn’t load. The rest of this panel is unaffected.</Footnote>;
  }
  const f = q.data ?? null;
  const t = f?.totals ?? null;
  const conc = amcConcentration(f);
  const rows = f?.rows ?? [];
  if (rows.length === 0) {
    return <Footnote>No scheme disclosed a holding in {symbol} for this month pair.</Footnote>;
  }
  const peak = Math.max(1, ...rows.map((r) => Math.abs(r.sharesDelta ?? 0)));

  return (
    <div className="flex flex-col" style={{ gap: 10 }} data-testid="desk-smart-money-amc">
      <Eyebrow>Which fund houses</Eyebrow>

      {conc && (
        <p data-testid="desk-smart-money-amc-concentration" style={{ margin: 0, fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          {conc.movers === 0
            ? `All ${fmtNum(t?.amcs)} disclosing houses held ${symbol} unchanged this month.`
            : <>
                {fmtNum(conc.buyers)} house{conc.buyers === 1 ? "" : "s"} raised and {fmtNum(conc.sellers)} cut,
                out of {fmtNum(t?.amcs)} holding {symbol}.
                {conc.topShare != null && <> The largest, {conc.topName}, holds {conc.topShare}% of the disclosed total.</>}
              </>}
        </p>
      )}

      <div className="flex flex-wrap" style={{ gap: "4px 14px", fontSize: 11.5, color: "var(--cp-ink-3)" }}>
        <span>Schemes <span className="cp-num">{fmtNum(t?.schemes)}</span> · {fmtNum(t?.schemesUp)}↑ {fmtNum(t?.schemesDn)}↓</span>
        <span>Held now{" "}
          <span className="cp-num">{t?.currentValueCr == null ? "—" : `₹${fmtNum(t.currentValueCr)} cr`}</span>
          {t?.valueDisclosedSchemes != null && t.valueDisclosedSchemes < (t.schemes ?? 0) && (
            <span style={{ color: "var(--cp-ink-4)" }} title="Only some schemes disclose a market value; the rest are absent, not zero">
              {" "}({fmtNum(t.valueDisclosedSchemes)} of {fmtNum(t.schemes)} priced)
            </span>
          )}
        </span>
        <span>Of equity{" "}
          <span className="cp-num">{t?.pctOfEquity == null
            ? <span style={{ color: "var(--cp-ink-4)" }} title="No quarter discloses a share count for this stock">n/d</span>
            : `${t.pctOfEquity}%`}</span>
        </span>
      </div>

      <div className="flex flex-col" style={{ gap: 6 }}>
        {rows.slice(0, 8).map((r) => {
          const d = r.sharesDelta ?? 0;
          const w = (Math.abs(d) / peak) * 100;
          return (
            <div key={r.amcId} className="grid items-center" style={{ gridTemplateColumns: "minmax(0,1.5fr) 54px minmax(0,1fr)", gap: 8, fontSize: 11.5 }}>
              <span style={{ color: "var(--cp-ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    title={`${r.schemesUp ?? 0} schemes raised, ${r.schemesDn ?? 0} cut, ${r.schemesFlat ?? 0} unchanged`}>
                {r.amcName ?? r.amcId}
              </span>
              <span className="cp-num" style={{ textAlign: "right", color: "var(--cp-ink-3)" }}>
                {r.shareOfDisclosedPct == null ? "—" : `${r.shareOfDisclosedPct}%`}
              </span>
              <span className="flex items-center" style={{ gap: 6 }}>
                <span style={{ position: "relative", flex: "1 1 auto", minWidth: 40, height: 7, background: "var(--bg-2)", borderRadius: 3 }}>
                  <span style={{ position: "absolute", top: 0, height: 7, width: `${w}%`, left: 0,
                                 borderRadius: "0 3px 3px 0", background: toneColor(d >= 0 ? "mint" : "danger") }} />
                </span>
                <span className="cp-num" style={{ flex: "none", width: 62, textAlign: "right", color: toneColor(d > 0 ? "mint" : d < 0 ? "danger" : "ink") }}>
                  {d === 0 ? "0" : `${d > 0 ? "+" : "−"}${fmtNum(Math.abs(d))}`}
                  <span className="sr-only"> shares {d > 0 ? "added" : d < 0 ? "reduced" : "unchanged"}</span>
                </span>
              </span>
            </div>
          );
        })}
        {rows.length > 8 && <span style={{ fontSize: 11, color: "var(--cp-ink-4)" }}>+{rows.length - 8} more houses</span>}
      </div>

      <Footnote>
        Share counts from each scheme’s own monthly disclosure, {fmtDate(f?.previousMonth)} → {fmtDate(f?.asOf)},
        aggregated per house and resolved by ISIN. The percentage is each house’s share of this stock’s
        disclosed mutual-fund holding — not of its equity, and not of that house’s own AUM, which is not
        ingested. “Held now” is a level, never a month-on-month value change.
      </Footnote>
    </div>
  );
}

// ── the stock-evidence rail (spec 2.7) ───────────────────────────────────

function StockEvidence({ row, mfWindow, onAsk }: { row: ScannerRow | null; mfWindow: Parameters<typeof whatWouldWeaken>[1]; onAsk: (q: string) => void }) {
  if (!row) {
    return (
      <div className="cp-card" data-testid="desk-smart-money-evidence-empty" style={{ padding: 16 }}>
        <Eyebrow>Stock evidence</Eyebrow>
        <p style={{ marginTop: 8, fontSize: 13, color: "var(--cp-ink-3)" }}>Select a stock in the scanner.</p>
      </div>
    );
  }
  const dir = rowDirection(row);
  const chain = evidenceChain(row);
  const weaken = whatWouldWeaken(row, mfWindow);
  const DIR_LABEL = { accumulation: "Accumulation", distribution: "Distribution", proxy: "Proxy signal" };

  return (
    <div className="cp-card flex flex-col" data-testid="desk-smart-money-evidence" style={{ padding: 16, gap: 14 }}>
      <div className="flex flex-col" style={{ gap: 6 }}>
        <Eyebrow>Stock evidence</Eyebrow>
        <span className="flex items-baseline flex-wrap" style={{ gap: 8 }}>
          <span style={{ fontFamily: "var(--display)", fontSize: 20 }}>{row.symbol}</span>
          <span className="cp-num" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
            {row.closePrice == null ? "—" : `₹${fmtNum(row.closePrice, 2)}`}
          </span>
          {row.changePct != null && (
            <span className="cp-num" style={{ fontSize: 12, color: toneColor(signTone(row.changePct) === "ink" ? "ink-3" : signTone(row.changePct)) }}>
              {row.changePct > 0 ? "+" : ""}{row.changePct}%
            </span>
          )}
        </span>
        <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
          {dir && <Pill tone={dir === "proxy" ? "amber" : dir === "accumulation" ? "mint" : "danger"}>{DIR_LABEL[dir]}</Pill>}
          <Pill tone={CLASS_TONE[row.evidence]} title={EVIDENCE_NOTE[row.evidence]}>{EVIDENCE_LABEL[row.evidence]}</Pill>
          {row.freshnessStatus && <Pill tone={FRESH_TONE[row.freshnessStatus] ?? "ink"}>{row.freshnessStatus}</Pill>}
          {row.singleAmcSignal && <Pill tone="amber" title="The whole disclosed signal rests on one fund house">One AMC only</Pill>}
        </span>
        <span style={{ fontSize: 11.5, color: "var(--cp-ink-4)" }}>{row.industry ?? "—"}</span>
      </div>

      {row.evidence === "C" && (
        <div role="note" data-testid="desk-smart-money-proxy-banner" style={{ padding: "9px 11px", borderRadius: 9, border: "1px solid var(--amber)", background: "var(--amber-soft)", fontSize: 12, color: "var(--cp-ink-2)" }}>
          Market-proxy evidence only. This is not labelled institutional accumulation.
        </div>
      )}

      <div className="flex flex-col" style={{ gap: 9 }}>
        <Eyebrow>Why it surfaced · evidence chain</Eyebrow>
        {chain.length === 0 ? (
          <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>Nothing is disclosed for this name in this window.</span>
        ) : chain.map((c) => (
          <div key={c.cls} className="flex" style={{ gap: 9 }}>
            <span className="cp-num" aria-hidden style={{
              flex: "none", width: 20, height: 20, borderRadius: 6, display: "grid", placeItems: "center",
              fontSize: 11, color: toneColor(CLASS_TONE[c.cls]), border: `1px solid ${toneColor(CLASS_TONE[c.cls])}`,
            }}>{c.cls}</span>
            <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
              <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>
                <span className="sr-only">Class {c.cls}: </span>{c.headline}
              </span>
              <span style={{ fontSize: 11, color: "var(--cp-ink-4)" }}>{c.source}</span>
            </span>
          </div>
        ))}
      </div>

      <AmcContribution symbol={row.symbol} />

      <div className="flex flex-col" style={{ gap: 7 }}>
        <Eyebrow>What would weaken this reading</Eyebrow>
        {weaken.length === 0 ? (
          <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>No specific weakness recorded for this row.</span>
        ) : (
          <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 5 }}>
            {weaken.map((w) => (
              <li key={w} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{w}</li>
            ))}
          </ul>
        )}
      </div>

      <button
        type="button" data-testid="desk-smart-money-ask"
        onClick={() => onAsk(`What is the disclosed institutional evidence behind ${row.symbol}, and what would weaken it?`)}
        style={{ alignSelf: "flex-start", padding: "6px 11px", borderRadius: 999, fontSize: 12, cursor: "pointer", border: "1px solid var(--cp-line)", background: "transparent", color: "var(--mint)" }}
      >Ask the Copilot about {row.symbol}</button>
    </div>
  );
}

// ── the screen ───────────────────────────────────────────────────────────

export default function SmartMoneyTab() {
  const { persona, askDesk } = useDesk();
  const [period, setPeriod] = useState<SmPeriod>("3M");
  const [universe, setUniverse] = useState<SmUniverse>("nifty500");
  const [sector, setSector] = useState<string | null>(null);
  const [direction, setDirection] = useState<SmDirection>("all");
  const [lane, setLane] = useState<SmLane>("all");
  const [freshness, setFreshness] = useState<SmFreshness>("any");
  const [measure, setMeasure] = useState<SectorMeasure>("cr");
  const [picked, setPicked] = useState<string | null>(null);

  const filters: ScannerFilters = { window: period, universe, sector, direction, lane, freshness };
  const feed = useSmartMoney(filters);
  const { feeds, flows, sectors, breadth, scanner } = feed;
  /**
   * The design's own minimum: 380px rail + 860px main. Measured on this tab's column, which the
   * desk shell caps — 888px at a 1600px viewport, 1076px at 2200px, both with the Copilot docked.
   * So inside the desk the panel stacks under the scanner rather than squeezing it; forcing the
   * split would leave the scanner (seven columns) scrolling sideways in ~670px, and the scanner is
   * the part of this screen that most needs the width.
   */
  const [railSide, measureRef] = useRoomFor(1240);
  const today = useMemo(() => new Date(), []);

  if (feed.status === "loading") return <Screen testId="screen-desk-smart-money"><LoadingBlock label="Reading disclosed holdings" rows={6} /></Screen>;
  if (feed.status === "error") {
    return (
      <Screen testId="screen-desk-smart-money">
        <ErrorBlock title="Smart Money didn’t load" error={feed.error} onRetry={feed.refetch} />
      </Screen>
    );
  }

  const m = breadth?.metrics ?? null;
  const disclosureAge = dataAgeDays(breadth?.disclosureAsOf ?? null, today);
  const rows = scanner?.rows ?? [];
  const pickedRow = rows.find((r) => r.symbol === picked) ?? null;
  const mfNote = mfWindowNote(scanner?.mfWindow ?? sectors?.mfWindow ?? null);
  const dirty = sector !== null || direction !== "all" || lane !== "all" || freshness !== "any";
  const clearAll = () => { setSector(null); setDirection("all"); setLane("all"); setFreshness("any"); };

  const sectorList = sectors?.rows ?? [];
  const flowRows = flows?.rows ?? [];
  const daily = flows?.grain !== "monthly";
  const regime = flowRegime(flows?.fiiNetCr ?? null, flows?.diiNetCr ?? null);

  const cols: Column<ScannerRow>[] = [
    {
      key: "symbol", header: "Stock · sector", width: "minmax(0,1.5fr)",
      render: (r) => (
        <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
          <span style={{ fontWeight: 600, color: r.symbol === picked ? "var(--mint)" : "var(--cp-ink)" }}>{r.symbol}</span>
          <span style={{ fontSize: 11, color: "var(--cp-ink-4)", overflow: "hidden", textOverflow: "ellipsis" }}>{r.industry ?? "—"}</span>
        </span>
      ),
    },
    {
      key: "mf", header: "MF holdings Δ", align: "right", num: true, width: "minmax(0,1.2fr)",
      render: (r) => (
        <span className="flex flex-col" style={{ gap: 2, alignItems: "flex-end" }}>
          <span>{r.mfSharesPctChg == null ? "—" : `${r.mfSharesPctChg > 0 ? "+" : ""}${r.mfSharesPctChg}%`}</span>
          <span style={{ fontSize: 10.5, color: "var(--cp-ink-4)" }}>
            {r.schemesUp == null ? "" : `${fmtNum(r.schemesUp)}↑ ${fmtNum(r.schemesDn)}↓ · ${fmtNum(r.amcsUp)} AMC`}
          </span>
        </span>
      ),
    },
    {
      key: "fii", header: "FII / DII Δ", align: "right", num: true, width: "minmax(0,1fr)",
      render: (r) => (r.fiiDeltaPp == null
        ? <span style={{ color: "var(--cp-ink-4)" }} title="Not disclosed for this stock in both quarters">n/d</span>
        : (
          <span className="flex flex-col" style={{ gap: 2, alignItems: "flex-end" }}>
            <span>{r.fiiDeltaPp > 0 ? "+" : ""}{r.fiiDeltaPp} pp</span>
            <span style={{ fontSize: 10.5, color: "var(--cp-ink-4)" }}>DII {r.diiDeltaPp == null ? "—" : `${r.diiDeltaPp > 0 ? "+" : ""}${r.diiDeltaPp}`}</span>
          </span>
        )),
    },
    {
      key: "deals", header: "Bulk / block net", align: "right", num: true, width: "minmax(0,1.1fr)",
      render: (r) => {
        if (!r.dealsChecked) return <span style={{ color: "var(--cp-ink-4)" }} title="This stock was never queried for deals — the ingest is deliberately partial">Not checked</span>;
        if (r.dealNetQty == null || r.dealNetQty === 0) {
          return r.transferDays && r.transferDays > 0
            ? <span title="Every leg matched an opposite leg: an ownership transfer, not net demand">Net 0 · transfer</span>
            : <span style={{ color: "var(--cp-ink-3)" }}>No deals</span>;
        }
        return (
          <span className="flex flex-col" style={{ gap: 2, alignItems: "flex-end" }}>
            <span>{r.dealNetQty > 0 ? "+" : "−"}{fmtNum(Math.abs(r.dealNetQty))}</span>
            <span style={{ fontSize: 10.5, color: "var(--cp-ink-4)" }}>{fmtNum(r.dealLegs)} legs · {fmtNum(r.matchedLegs)} matched</span>
          </span>
        );
      },
    },
    {
      key: "deliv", header: "Delivery vs base", align: "right", num: true, width: "minmax(0,0.95fr)",
      render: (r) => (r.delivVsBasePp == null ? "—" : (
        <span className="flex flex-col" style={{ gap: 2, alignItems: "flex-end" }}>
          <span>{r.delivVsBasePp > 0 ? "+" : ""}{r.delivVsBasePp} pp</span>
          <span style={{ fontSize: 10.5, color: "var(--cp-ink-4)" }}>{r.deliv10d ?? "—"}% vs {r.deliv60d ?? "—"}%</span>
        </span>
      )),
    },
    {
      key: "evidence", header: "Evidence", width: "minmax(0,0.7fr)",
      render: (r) => (
        <span className="flex flex-wrap items-center" style={{ gap: 4 }}>
          <Pill tone={CLASS_TONE[r.evidence]} title={`${EVIDENCE_LABEL[r.evidence]} — ${EVIDENCE_NOTE[r.evidence]}`}>
            {r.evidence === "none" ? "—" : r.evidence}
          </Pill>
          <span className="sr-only">{EVIDENCE_LABEL[r.evidence]}</span>
          {r.singleAmcSignal && <Pill tone="amber" title="The whole disclosed signal rests on one fund house">1 AMC</Pill>}
        </span>
      ),
    },
    {
      key: "fresh", header: "Freshness", align: "right", width: "minmax(0,0.75fr)",
      render: (r) => (r.freshnessStatus
        ? <Pill tone={FRESH_TONE[r.freshnessStatus] ?? "ink"}>{r.freshnessStatus}</Pill>
        : <span style={{ color: "var(--cp-ink-4)" }}>—</span>),
    },
  ];

  const main = (
    <>
      {/* ── feed-status strips (spec 2.2) ── */}
      <div
        data-testid="desk-smart-money-feed-strips"
        className="grid"
        style={{ gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))", gap: 10, marginBottom: 20 }}
      >
        {(feeds?.rows ?? []).map((s) => {
          const bad = s.status && s.status !== "OK";
          const tone = !s.statusRowPresent ? "ink-4" : bad ? (s.status === "STALE" ? "amber" : "danger") : "mint";
          return (
            <div key={s.feed} className="cp-card flex flex-col" style={{ padding: "11px 13px", gap: 5 }}>
              <span className="flex items-center" style={{ gap: 7 }}>
                <span aria-hidden style={{ flex: "none", width: 7, height: 7, borderRadius: 999, background: toneColor(tone) }} />
                <span style={{ fontSize: 12, color: "var(--cp-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.feed}</span>
              </span>
              <span className="cp-num" style={{ fontSize: 10.5, color: "var(--cp-ink-3)" }}>
                {s.expectedFreq ?? "—"} · {fmtDate(s.dataAsOf) || "no data"}
                <span className="sr-only">
                  {" "}status {s.statusRowPresent ? s.status ?? "unknown" : "no status row"}
                </span>
              </span>
              {ingestAheadOfData(s) && (
                <span style={{ fontSize: 10, color: "var(--cp-ink-4)" }} title="The loader ran later than the data it carries">
                  loader ran {fmtDate(s.ingestedFor)}
                </span>
              )}
              {!s.statusRowPresent && <span style={{ fontSize: 10, color: "var(--cp-ink-4)" }}>no status row</span>}
            </div>
          );
        })}
      </div>

      {/* ── market-wide flows (spec 2.3) ── */}
      <Section
        title="Market-wide flows"
        note={<Pill tone="ink" title="This panel is the whole cash market. It says nothing about any single stock.">Market-wide · not stock-specific</Pill>}
      >
        {flowRows.length === 0 ? (
          <EmptyBlock title="No flow rows in this window" body="The feed answered with an empty window rather than an older one." />
        ) : (
          <div className="flex flex-col" style={{ gap: 14 }}>
            {regime && (
              <div data-testid="desk-smart-money-regime" className="flex flex-col" style={{ gap: 5 }}>
                <p style={{ margin: 0, fontSize: 14, lineHeight: 1.55, color: "var(--cp-ink)" }}>{regime}</p>
                <p style={{ margin: 0, fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-4)" }}>{FLOW_CAVEAT}</p>
              </div>
            )}
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 12 }}>
              {([["FII", flows?.fiiNetCr ?? null, "fiiNetCr"], ["DII", flows?.diiNetCr ?? null, "diiNetCr"]] as const).map(([who, net, key]) => (
                <div key={who} className="cp-card flex flex-col" style={{ padding: "13px 15px", gap: 6 }}>
                  <span className="cp-eyebrow">{who} net · {period}</span>
                  <Cr v={net} big />
                  {daily && (
                    <span className="cp-num" style={{ fontSize: 10.5, color: "var(--cp-ink-4)" }}>
                      {[5, 20, 60].map((n) => {
                        const v = rollingNet(flowRows, n, key);
                        return `${n}D ${v == null ? "—" : fmtNum(Math.round(v))}`;
                      }).join(" · ")}
                    </span>
                  )}
                </div>
              ))}
            </div>
            <CumulativeChart rows={flowRows} grain={flows?.grain ?? null} />
            <Footnote>
              {flows?.grain === "monthly"
                ? "Monthly grain: the daily series begins 2026-04-01, so a one-year window is served from monthly rows. The two grains are never added together."
                : "Daily grain, cash segment only. 5D / 20D / 60D are rolling sums of the net, shown only where the window holds that many sessions."}
              {" "}<strong style={{ color: "var(--cp-ink-2)" }}>Historical market reaction: no validated study available.</strong>
            </Footnote>
          </div>
        )}
        <TrustLine source={flows?.source ?? "nidp.fii_dii_flows"} asOf={fmtDate(flows?.asOf)} mode="eod" maker="reported" method={regime ? "regime line is rules-based, not a model" : null} testId="desk-smart-money-flows-trust" />
      </Section>

      {/* ── sector rotation beside evidence breadth (spec 2.4 + 2.5) ── */}
      <div className="grid" style={{ gridTemplateColumns: railSide ? "1.6fr 1fr" : "minmax(0,1fr)", gap: 20 }}>
        <Section
          // "Rotation" and "buying" both overclaim: this is an estimated change in disclosed
          // holdings, not a measured capital flow, so the title says what it is.
          title="Estimated MF sector accumulation"
          note={
            <span className="flex flex-wrap items-center" style={{ gap: 10 }}>
              {sectors?.previousMonth && (
                <span className="cp-mono-note">{fmtDate(sectors.previousMonth)} → {fmtDate(sectors.asOf)}</span>
              )}
              <Chips items={SECTOR_MEASURES} value={measure} onPick={setMeasure} idPrefix="desk-smart-money-measure" label="Sector measure" />
            </span>
          }
        >
          {sectorList.length === 0 ? (
            <EmptyBlock title="No disclosed sector change" body="No month pair is disclosed for this universe." />
          ) : (
            <>
              {/* The arithmetic behind the ranking, so it can be checked by hand. */}
              {(() => {
                const t = sectorTotals(sectorList);
                return (
                  <div data-testid="desk-smart-money-sector-totals" className="flex flex-wrap items-baseline"
                       style={{ gap: "4px 16px", marginBottom: 12, fontSize: 12, color: "var(--cp-ink-3)" }}>
                    <span>Added <span className="cp-num" style={{ color: "var(--mint)" }}>+₹{fmtNum(t.added)} cr</span></span>
                    <span>Reduced <span className="cp-num" style={{ color: "var(--cp-danger)" }}>−₹{fmtNum(t.reduced)} cr</span></span>
                    <span>Net <span className="cp-num" style={{ color: "var(--cp-ink)" }}>{t.net >= 0 ? "+" : "−"}₹{fmtNum(Math.abs(t.net))} cr</span></span>
                    <span style={{ color: "var(--cp-ink-4)" }}>across {fmtNum(t.sectors)} sectors</span>
                  </div>
                );
              })()}
              <SectorBars rows={sectorList} measure={measure} />
            </>
          )}
          <Footnote>
            <strong style={{ color: "var(--cp-ink-2)" }}>Σ (share count this month − share count last month) × that month’s VWAP.</strong>{" "}
            A <em>share-count</em> delta, never a market-value delta, so a price move alone cannot read as buying.
            It is still an estimate: it assumes every change traded at the month’s VWAP, and it does not yet adjust
            for bonuses, splits or scheme mergers, any of which change a share count without a trade.{" "}
            {sectors?.previousMonth && <>Comparing {fmtDate(sectors.previousMonth)} with {fmtDate(sectors.asOf)}. </>}
            {sectorList.reduce((t, r) => t + (r.stocksPriced ?? 0), 0)} of {sectorList.reduce((t, r) => t + (r.stocks ?? 0), 0)} stocks priced.
            Disclosed portfolios of 11 reporting AMCs — not all mutual funds, and not all institutional flow.
            The FII/DII shareholding leg is absent on purpose: the prior quarter carries no share count, so a
            two-quarter value-weighted figure cannot be computed without inventing one.
          </Footnote>
        </Section>

        <Section title="Evidence breadth">
          {m == null ? (
            <EmptyBlock title="No scored names" body="Nothing was evaluated on the latest date." />
          ) : (
            <div className="flex flex-col" style={{ gap: 12 }}>
              <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
                <span className="cp-num" style={{ fontSize: 18, color: "var(--cp-ink)" }}>{fmtNum(m.disclosedRising)}</span>
                {" "}of {fmtNum(m.evaluated)} evaluated names have rising disclosed ownership.
              </span>
              <Tier label="Direct + proxy agree" n={m.risingDirectAndProxy} of={m.evaluated} tone="mint" note="A disclosed holdings change and a market proxy point the same way." />
              <Tier label="Direct evidence only" n={m.risingDirectOnly} of={m.evaluated} tone="indigo" note="A disclosed holdings change with no proxy confirmation." />
              <Tier label="Proxy only, not confirmed" n={m.proxyOnly} of={m.evaluated} tone="amber" note="Delivery or volume moved and the buyer is unknown. Never called accumulation." />
              <div className="flex flex-wrap items-center" style={{ gap: 6, paddingTop: 2 }}>
                {([["fresh", m.fresh], ["ageing", m.ageing], ["stale", m.stale]] as const).map(([k, v]) => (
                  <Pill key={k} tone={FRESH_TONE[k]}>{k} {fmtNum(v)}</Pill>
                ))}
                {m.singleAmc != null && <Pill tone="amber" title="Names whose whole signal rests on one fund house">one AMC {fmtNum(m.singleAmc)}</Pill>}
              </div>
              <Footnote>
                Disclosed portfolios of 11 reporting AMCs, as of {fmtDate(breadth?.disclosureAsOf)}. A proxy move on its
                own is never called accumulation: delivery and volume do not disclose who bought.
              </Footnote>
            </div>
          )}
        </Section>
      </div>

      {/* ── scanner (spec 2.6) ── */}
      <Section
        title="Stock-level smart money scanner"
        note={<span className="cp-mono-note">{scanner?.indexName ?? ""}</span>}
      >
        <div className="flex flex-col" style={{ gap: 12 }}>
          {/* Lanes as tabs, each with its real count so an empty lane reads as "none here". */}
          <Chips
            items={[
              { id: "all" as SmLane, label: `All (${scanner?.lanes.all ?? 0})` },
              { id: "disclosed" as SmLane, label: `Disclosed evidence · A/B (${scanner?.lanes.disclosed ?? 0})` },
              { id: "proxy" as SmLane, label: `Proxy only · C (${scanner?.lanes.proxy ?? 0})` },
            ]}
            value={lane} onPick={setLane} idPrefix="desk-smart-money-lane" label="Evidence lane"
          />

          {/* Filters in one row above the table. */}
          <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
            <Chips items={SM_UNIVERSES} value={universe} onPick={setUniverse} idPrefix="desk-smart-money-universe" label="Universe" />
            <Chips
              items={SM_DIRECTIONS.map((d) => ({ id: d, label: d === "all" ? "Any direction" : d === "accumulation" ? "Accumulation" : "Distribution" }))}
              value={direction} onPick={setDirection} idPrefix="desk-smart-money-direction" label="Direction"
            />
            <Chips
              items={SM_FRESHNESS.map((f) => ({ id: f, label: f === "any" ? "Any freshness" : f }))}
              value={freshness} onPick={setFreshness} idPrefix="desk-smart-money-freshness" label="Freshness"
            />
            <label className="flex items-center" style={{ gap: 6, fontSize: 12, color: "var(--cp-ink-3)" }}>
              Sector
              <select
                data-testid="desk-smart-money-sector"
                value={sector ?? ""}
                onChange={(e) => setSector(e.target.value || null)}
                style={{ padding: "3px 7px", borderRadius: 7, fontSize: 12, border: "1px solid var(--cp-line)", background: "var(--bg-1)", color: "var(--cp-ink-2)" }}
              >
                <option value="">All sectors</option>
                {sectorList.map((s) => <option key={s.industry} value={s.industry}>{s.industry}</option>)}
              </select>
            </label>
            {dirty && (
              <button
                type="button" data-testid="desk-smart-money-clear"
                onClick={clearAll}
                style={{ border: 0, background: "transparent", color: "var(--mint)", cursor: "pointer", font: "inherit", fontSize: 12, textDecoration: "underline" }}
              >Clear filters</button>
            )}
          </div>

          <span data-testid="desk-smart-money-coverage" className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-4)" }}>
            Showing {rows.length} of {scanner?.total ?? 0} in this lane · {scanner?.matched ?? 0} match the other filters
            {scanner?.lanes.proxy === 0 && lane === "proxy" && " · no name in this universe rests on a proxy alone"}
          </span>

          <DataTable
            rows={rows} rowKey={(r) => r.symbol} columns={cols} minWidth={760}
            onRowClick={(r) => setPicked(r.symbol === picked ? null : r.symbol)}
            empty="No stock matched these filters."
          />

          {/* The class legend, verbatim from the spec. */}
          <div data-testid="desk-smart-money-legend" className="flex flex-wrap" style={{ gap: 12, paddingTop: 2 }}>
            {EVIDENCE_LEGEND.map((l) => (
              <span key={l.cls} className="flex items-center" style={{ gap: 6, fontSize: 11.5, color: "var(--cp-ink-3)" }}>
                <span className="cp-num" aria-hidden style={{
                  width: 18, height: 18, borderRadius: 5, display: "grid", placeItems: "center", fontSize: 10,
                  color: toneColor(CLASS_TONE[l.cls]), border: `1px solid ${toneColor(CLASS_TONE[l.cls])}`,
                }}>{l.cls}</span>
                <span><strong style={{ color: "var(--cp-ink-2)" }}>{l.cls}</strong> {l.text}</span>
              </span>
            ))}
          </div>

          <Footnote>
            Ordered by evidence class, then by how many fund houses raised the holding — a count of disclosures,
            not a model score. “Not checked” means that stock was never queried for deals, which is different from
            having no deals. A deal leg carries no counterparty classification, so it may be a market maker rather
            than a long-term buyer, and matched same-day legs are already netted out as transfers.
            {scanner?.quarters?.current && <> FII columns compare {fmtDate(scanner.quarters.previous)} with {fmtDate(scanner.quarters.current)} and are disclosed for only a minority of names.</>}
          </Footnote>
        </div>
        <TrustLine source={scanner?.source ?? "nidp.mf_holdings_deltas"} asOf={fmtDate(scanner?.asOf)} mode="historical" maker="reported" confidence={`n ${scanner?.total ?? 0}`} testId="desk-smart-money-scanner-trust" />
      </Section>
    </>
  );

  return (
    <Screen testId="screen-desk-smart-money" width={1480}>
      <div ref={measureRef} />
      <ScreenHeader
        eyebrow={<Eyebrow>06 · Smart Money Movement</Eyebrow>}
        title={persona === "investor" ? "Who is buying and selling" : "Smart Money Movement"}
        pills={
          <>
            <Chips
              items={SM_PERIODS.map((p) => ({ id: p, label: p }))}
              value={period} onPick={setPeriod} idPrefix="desk-smart-money-period" label="Period"
            />
            <Pill tone="indigo" title="These are the disclosed holdings of the 11 AMCs that report, not all institutional activity">11 disclosing AMCs</Pill>
            {disclosureAge != null && (
              <Pill tone={disclosureAge > 45 ? "amber" : "ink"} title="Monthly portfolio disclosure is published in arrears, so this screen is weeks behind by construction">
                Disclosed {fmtDate(breadth?.disclosureAsOf)} · {disclosureAge}d ago
              </Pill>
            )}
            {!breadth?.validatedStudy && <Pill tone="amber" title="No promotion decision is on record, so nothing here is scored or ranked by a model">Evidence only · not scored</Pill>}
          </>
        }
        sub={persona === "investor"
          ? "What fund houses actually filed they bought or sold, plus the deals the exchanges published. It is a record of who moved, not advice to follow them."
          : "Disclosed holdings change, disclosed deal legs net of transfers, and market proxies — each labelled by what kind of evidence it is."}
      />

      {mfNote && (
        <div data-testid="desk-smart-money-mf-window" role="note" style={{ marginBottom: 16, padding: "9px 13px", borderRadius: 9, border: "1px solid var(--cp-line)", background: "var(--bg-2)", fontSize: 12, color: "var(--cp-ink-2)" }}>
          {mfNote} Flows, deals and delivery do follow the {period} period.
        </div>
      )}

      {feed.failed.length > 0 && (
        <div data-testid="desk-smart-money-partial" role="status" style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 10, border: "1px solid var(--amber)", background: "var(--amber-soft)", fontSize: 12.5, color: "var(--cp-ink-2)" }}>
          Partial: {feed.failed.join(", ")} didn’t answer. Everything else below is current.{" "}
          <button type="button" onClick={feed.refetch} style={{ border: 0, background: "transparent", color: "var(--mint)", cursor: "pointer", font: "inherit", textDecoration: "underline" }}>Retry</button>
        </div>
      )}

      <div className="grid" style={{ gridTemplateColumns: railSide ? "minmax(0,1fr) 380px" : "minmax(0,1fr)", gap: 20, alignItems: "start" }}>
        <div className="flex min-w-0 flex-col">{main}</div>
        <div data-testid="desk-smart-money-rail" className="flex flex-col" style={{ gap: 16, position: railSide ? "sticky" : undefined, top: railSide ? 12 : undefined }}>
          <StockEvidence row={pickedRow} mfWindow={scanner?.mfWindow ?? null} onAsk={askDesk} />
        </div>
      </div>

      {/* ── the footer, shipped verbatim (spec 2.9) ── */}
      <div data-testid="desk-smart-money-disclaimer" style={{ paddingTop: 14, borderTop: "1px solid var(--cp-line)" }}>
        <Footnote>
          <strong style={{ color: "var(--cp-ink-2)" }}>Smart money is evidence, not a buy signal.</strong>{" "}
          Ownership disclosures are periodic; deal disclosures may not identify beneficial intent; market proxies
          are indirect. Always validate with fundamentals, technicals and risk management. Educational market
          intelligence, not investment advice.
        </Footnote>
      </div>
    </Screen>
  );
}
