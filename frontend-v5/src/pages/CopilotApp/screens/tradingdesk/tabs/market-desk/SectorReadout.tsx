/**
 * Market Desk › Market Intelligence › the sector-rotation readout (the owner's design draws it beside the events
 * calendar): a few rows, with the full heatmap and rotation matrix one click away in Sector Rotation.
 *
 *   GET /api/markets/sector-heatmap?index=NIFTY50   (useSectorHeatmap; the same query and cache as Sector Rotation's
 *                                                   default index, so the two views never show different numbers)
 *
 * Per sector: the 1D return, the 1M return against the index's weighted 1M change ("vs Nifty 50, 1M"), the share of the
 * sector's priced stocks that rose on the day, and a state from a stated rule (rotationState): 1M vs the index is the
 * strength, 1W vs the index the momentum. Leading = both above; Weakening = 1M above, 1W below; Improving = 1M below,
 * 1W above; Lagging = both below. A figure the route did not send is "—" and the state is "—": never 0.
 *
 * The rows are the three strongest and the three weakest by 1M vs the index; Sector Rotation has every sector.
 */
import type { CSSProperties } from "react";
import { LoadingBlock, Pill, type Tone } from "../../../../components/ui";
import { indexLabel, useSectorHeatmap, type HeatSector, type Heatmap } from "../../../heatmap/heatmap-data";

export const READOUT_INDEX = "NIFTY50";
const EACH_END = 3;

export type RotationState = "leading" | "weakening" | "improving" | "lagging";
export const STATE_LABEL: Record<RotationState, string> = { leading: "Leading", weakening: "Weakening", improving: "Improving", lagging: "Lagging" };
const STATE_TONE: Record<RotationState, Tone> = { leading: "mint", weakening: "amber", improving: "indigo", lagging: "danger" };

/** The stated rule: strength = 1M vs the index, momentum = 1W vs the index; null when either is unknown. */
export function rotationState(rs1m: number | null, rs1w: number | null): RotationState | null {
  if (rs1m == null || rs1w == null) return null;
  if (rs1m >= 0) return rs1w >= 0 ? "leading" : "weakening";
  return rs1w >= 0 ? "improving" : "lagging";
}

export interface ReadoutRow {
  name: string;
  d: number | null;
  rs1m: number | null;
  rs1w: number | null;
  rosePct: number | null;
  priced: number;
  state: RotationState | null;
}

const diff = (a: number | null, b: number | null) => (a == null || b == null ? null : a - b);

export function readoutRows(h: Heatmap): ReadoutRow[] {
  const rows = h.sectors.map((s: HeatSector): ReadoutRow => {
    const stocks = h.stocks.filter((x) => x.sector === s.name && x.returns.d != null);
    const rose = stocks.filter((x) => (x.returns.d as number) > 0).length;
    const rs1m = diff(s.returns.m, h.weighted.m);
    const rs1w = diff(s.returns.w, h.weighted.w);
    return { name: s.name, d: s.returns.d, rs1m, rs1w, rosePct: stocks.length ? (rose / stocks.length) * 100 : null, priced: stocks.length, state: rotationState(rs1m, rs1w) };
  });
  const known = rows.filter((r) => r.rs1m != null).sort((a, b) => (b.rs1m as number) - (a.rs1m as number));
  if (known.length <= EACH_END * 2) return known;
  return [...known.slice(0, EACH_END), ...known.slice(-EACH_END)];
}

const th: CSSProperties = {
  padding: "7px 8px", textAlign: "left", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase",
  color: "var(--cp-ink-4)", fontWeight: 500, borderBottom: "1px solid var(--cp-line)", whiteSpace: "nowrap",
};
const td: CSSProperties = { padding: "8px 8px", fontSize: 13, color: "var(--cp-ink-2)", borderBottom: "1px solid var(--cp-line)", fontFamily: "var(--mono)", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" };
const tone = (v: number | null) => (v == null ? "var(--cp-ink-4)" : v > 0 ? "var(--mint)" : v < 0 ? "var(--cp-danger)" : "var(--cp-ink-2)");
/** Signed, two decimals, the true minus sign; "—" when unknown. */
const fmt = (v: number | null, unit = "%") => (v == null ? "—" : `${v < 0 ? "\u2212" : v > 0 ? "+" : ""}${Math.abs(v).toFixed(2)}${unit}`);
const linkBtn: CSSProperties = { padding: 0, border: 0, background: "none", cursor: "pointer", font: "inherit", color: "var(--mint)" };

export function SectorReadout({ onOpenRotation }: { onOpenRotation: () => void }) {
  const q = useSectorHeatmap(READOUT_INDEX);
  const open = (
    <button type="button" data-testid="md-readout-open" onClick={onOpenRotation} style={linkBtn}>All sectors, the heatmap and the rotation matrix · Sector Rotation ›</button>
  );
  let body;
  if (q.isPending) body = <LoadingBlock label="Loading the sector readout" rows={3} />;
  else if (q.isError) {
    body = <p data-testid="md-readout-error" role="alert" className="m-0" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>The sector readout didn’t load{q.error instanceof Error && q.error.message ? ` (${q.error.message})` : ""}.</p>;
  } else {
    const rows = readoutRows(q.data);
    body = rows.length ? (
      <div className="cp-scroll" style={{ overflowX: "auto", maxWidth: "100%" }}>
        <table className="w-full" style={{ borderCollapse: "collapse", minWidth: 480 }}>
          <thead>
            <tr>
              <th style={th} scope="col">Sector</th>
              <th style={th} scope="col">vs {indexLabel(q.data.index)} · 1M</th>
              <th style={th} scope="col">1 day</th>
              <th style={th} scope="col">Rose today</th>
              <th style={th} scope="col">State</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} data-testid="md-readout-row" data-sector={r.name} data-state={r.state ?? ""}>
                <td style={{ ...td, fontFamily: "var(--sans)", color: "var(--cp-ink)", whiteSpace: "normal" }}>{r.name}</td>
                <td style={{ ...td, color: tone(r.rs1m) }} data-testid="md-readout-rs">{fmt(r.rs1m, " pts")}</td>
                <td style={{ ...td, color: tone(r.d) }} data-testid="md-readout-d">{fmt(r.d)}</td>
                <td style={td} data-testid="md-readout-rose" title={`${r.priced} priced stocks`}>{r.rosePct == null ? "—" : `${Math.round(r.rosePct)}%`}</td>
                <td style={td} data-testid="md-readout-state">{r.state ? <Pill tone={STATE_TONE[r.state]}>{STATE_LABEL[r.state]}</Pill> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    ) : (
      <p data-testid="md-readout-empty" className="m-0" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>No sector has a 1M return against the index for the latest session yet.</p>
    );
  }
  return (
    <section data-testid="md-readout" aria-label="Sector rotation" className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: "14px 16px" }}>
      <header className="flex flex-wrap items-baseline" style={{ gap: "4px 12px" }}>
        <h3 className="cp-eyebrow m-0" style={{ flex: "1 1 auto" }}>Sector rotation · {indexLabel(READOUT_INDEX)}{q.data?.asOf ? ` · ${q.data.asOf}` : ""}</h3>
        {open}
      </header>
      {body}
      <p className="m-0" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
        The three strongest and three weakest sectors by their 1M return against the index’s weighted 1M change, in points.
        State: Leading when 1M and 1W are both above the index, Weakening when 1M is above and 1W below, Improving when 1M is
        below and 1W above, Lagging when both are below. A rule on returns, not a forecast.
      </p>
    </section>
  );
}
