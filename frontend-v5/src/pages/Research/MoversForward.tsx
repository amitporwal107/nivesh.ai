/**
 * Forward lists for the next session: the OFFICIAL frozen Move-odds run beside a labelled NEW-UNIVERSE PREVIEW.
 * The preview was scored with newer model code than the frozen nightly. It is never graded, never counts toward the verdict,
 * and is drawn in a dashed, differently-coloured frame so it cannot be mistaken for the official list.
 * Both lists are volatility odds ("either" = chance of a +5% move plus chance of a -5% move); direction is not predictable.
 */
import type { CSSProperties } from "react";
import type { MoverForward, MoverForwardRow } from "@/services/adapters/movers.adapter";

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (t: string) => { const d = new Date(`${t.slice(0, 10)}T00:00:00Z`); return `${String(d.getUTCDate()).padStart(2, "0")} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
const p0 = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(0)}%`);
const mono: CSSProperties = { fontFamily: "var(--mono)" };

function Rows({ rows, preview }: { rows: MoverForwardRow[]; preview: boolean }) {
  return (
    <div role="table" style={{ display: "flex", flexDirection: "column" }}>
      <div style={{ display: "grid", gridTemplateColumns: "22px minmax(0,1fr) 54px 44px 44px", gap: 8, padding: "0 0 6px", ...mono, fontSize: 9.5, letterSpacing: ".1em", color: "var(--ink-4)" }}>
        <span /><span>STOCK</span><span style={{ textAlign: "right" }}>EITHER ±5%</span><span style={{ textAlign: "right" }}>UP</span><span style={{ textAlign: "right" }}>DOWN</span>
      </div>
      {rows.map((r, i) => (
        <div key={r.symbol} role="row" data-testid={`mv-fwd-${preview ? "preview" : "official"}-row`}
             style={{ display: "grid", gridTemplateColumns: "22px minmax(0,1fr) 54px 44px 44px", gap: 8, alignItems: "center", padding: "7px 0", borderTop: "1px solid var(--line)" }}>
          <span style={{ ...mono, fontSize: 10.5, color: "var(--ink-4)" }}>{String(i + 1).padStart(2, "0")}</span>
          <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
            <span style={{ ...mono, fontSize: 12.5, fontWeight: 500, display: "flex", gap: 6, alignItems: "center" }}>
              {r.symbol}
              {preview && r.in_official_universe === false && (
                <span title="Not scored in the official run: outside its top-1,000 turnover cap" style={{ padding: "0 6px", borderRadius: 999, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", color: "var(--amber)", fontSize: 9, letterSpacing: ".08em" }}>NEWLY SCORED</span>
              )}
            </span>
            <span style={{ fontSize: 11.5, color: "var(--ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.name ?? ""}</span>
          </span>
          <span style={{ ...mono, fontSize: 13, fontWeight: 500, textAlign: "right" }}>{p0(r.either)}</span>
          <span style={{ ...mono, fontSize: 11.5, textAlign: "right", color: "var(--ink-2)" }}>{p0(r.up)}</span>
          <span style={{ ...mono, fontSize: 11.5, textAlign: "right", color: "var(--ink-2)" }}>{p0(r.down)}</span>
        </div>
      ))}
    </div>
  );
}

export function MoversForward({ data, error }: { data: MoverForward | null; error?: string | null }) {
  if (error) {
    return <p role="status" data-testid="mv-fwd-error" style={{ margin: 0, ...mono, fontSize: 10.5, letterSpacing: ".08em", color: "var(--ink-3)" }}>{`FORWARD LISTS UNAVAILABLE (${error.toUpperCase()})`}</p>;
  }
  if (!data || (!data.official.available && !data.preview.available)) return null;
  const o = data.official, pv = data.preview;
  const frame = (dashed: boolean): CSSProperties => ({
    flex: "1 1 420px", minWidth: 0, borderRadius: 12, padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10,
    background: dashed ? "var(--amber-soft)" : "var(--bg-0)", border: dashed ? "1px dashed var(--amber-line)" : "1px solid var(--line)",
  });
  return (
    <section data-testid="mv-forward" style={{ borderRadius: 14, background: "var(--bg-1)", border: "1px solid var(--line)", boxShadow: "var(--shadow-card)", padding: "18px 20px", display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ ...mono, fontSize: 11, letterSpacing: ".14em", color: "var(--ink-3)" }}>{`FORWARD LISTS · SESSION ${day(data.session).toUpperCase()}`}</span>
        <span style={{ flex: 1 }} />
        <span style={{ ...mono, fontSize: 10, letterSpacing: ".1em", color: "var(--ink-4)" }}>VOLATILITY ODDS · DIRECTION IS NOT PREDICTABLE</span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-start" }}>
        <div style={frame(false)} data-testid="mv-fwd-official">
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ padding: "3px 9px", borderRadius: 999, border: "1px solid var(--mint-line)", background: "var(--mint-soft)", color: "var(--mint)", ...mono, fontSize: 10.5, letterSpacing: ".1em" }}>OFFICIAL · FROZEN · COUNTS TOWARD THE VERDICT</span>
          </div>
          {o.available ? (
            <>
              <span style={{ ...mono, fontSize: 10, letterSpacing: ".08em", color: "var(--ink-3)" }}>{`RUN ${o.run_id} · DATA AS OF ${o.data_as_of ? day(o.data_as_of).toUpperCase() : "—"} · ${o.scored} SCORED · AVERAGE ${p0(o.avg_either)}`}</span>
              <Rows rows={o.rows} preview={false} />
            </>
          ) : <p style={{ margin: 0, fontSize: 13, color: "var(--ink-3)" }}>No official run is on record for this session.</p>}
        </div>
        <div style={frame(true)} data-testid="mv-fwd-preview">
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span data-testid="mv-fwd-preview-badge" style={{ padding: "3px 9px", borderRadius: 999, border: "1px dashed var(--amber)", background: "transparent", color: "var(--amber)", ...mono, fontSize: 10.5, letterSpacing: ".1em" }}>NEW-UNIVERSE PREVIEW · NOT GRADED</span>
          </div>
          {pv.available ? (
            <>
              <span style={{ ...mono, fontSize: 10, letterSpacing: ".08em", color: "var(--ink-3)" }}>{`DATA AS OF ${pv.data_as_of ? day(pv.data_as_of).toUpperCase() : "—"} · MODEL CODE ${pv.git_sha} · UNIVERSE ${pv.universe_size} · ${pv.scored} SCORED · AVERAGE ${p0(pv.avg_either)} · ${pv.top_overlap} OF THE TOP ${pv.rows.length} ALSO IN THE OFFICIAL TOP ${o.rows.length}`}</span>
              <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.5, color: "var(--ink-2)" }}>
                {pv.note} Newly scored names are the least liquid in this universe (median turnover as low as ₹1 cr), so a high figure there is harder to trade.
              </p>
              <Rows rows={pv.rows} preview />
            </>
          ) : <p style={{ margin: 0, fontSize: 13, color: "var(--ink-3)" }}>No preview is on record for this session.</p>}
        </div>
      </div>
    </section>
  );
}

export default MoversForward;
