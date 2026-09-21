/**
 * The non-canvas alternative required by feasibility.md B7: the chart canvas is not screen-reader accessible, so
 * everything it draws also exists as a real, keyboard-reachable DOM table — bars and detected patterns.
 */
import { price, vol, txt, type Bar, type Pattern, patternVisualCategory } from "./contract";

export default function DataView({ symbol, bars, patterns }: { symbol: string; bars: Bar[]; patterns: Pattern[] }) {
  return (
    <div data-testid="chart-data-view" style={{ display: "grid", gap: 16 }}>
      <div>
        <p className="nv-eyebrow" style={{ margin: "0 0 8px" }}>Bars — {symbol} · {bars.length} sessions</p>
        <div
          tabIndex={0}
          role="region"
          aria-label={`${symbol} daily bars, table form`}
          style={{ maxHeight: 320, overflow: "auto", border: "1px solid var(--c-line)", borderRadius: 10 }}
        >
          <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
            <thead>
              <tr>
                {["Date", "Open", "High", "Low", "Close", "Volume"].map((h) => (
                  <th key={h} scope="col" style={{ textAlign: h === "Date" ? "left" : "right", padding: "7px 10px", position: "sticky", top: 0, background: "var(--bg-2)", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--c-ink-3)" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bars.map((b) => (
                <tr key={b[0]} data-testid="chart-dataview-bar">
                  <td style={{ padding: "5px 10px", borderTop: "1px solid var(--c-line)" }}>{b[0]}</td>
                  <td style={{ padding: "5px 10px", borderTop: "1px solid var(--c-line)", textAlign: "right" }}>{price(b[1])}</td>
                  <td style={{ padding: "5px 10px", borderTop: "1px solid var(--c-line)", textAlign: "right" }}>{price(b[2])}</td>
                  <td style={{ padding: "5px 10px", borderTop: "1px solid var(--c-line)", textAlign: "right" }}>{price(b[3])}</td>
                  <td style={{ padding: "5px 10px", borderTop: "1px solid var(--c-line)", textAlign: "right" }}>{price(b[4])}</td>
                  <td style={{ padding: "5px 10px", borderTop: "1px solid var(--c-line)", textAlign: "right" }}>{vol(b[5])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <p className="nv-eyebrow" style={{ margin: "0 0 8px" }}>Detected patterns · {patterns.length}</p>
        {patterns.length === 0 ? (
          <p data-testid="chart-dataview-patterns-empty" style={{ margin: 0, fontSize: 13, color: "var(--c-ink-3)" }}>
            No patterns in this snapshot for {symbol}.
          </p>
        ) : (
          <div tabIndex={0} role="region" aria-label={`${symbol} detected patterns, table form`} style={{ overflowX: "auto", border: "1px solid var(--c-line)", borderRadius: 10 }}>
            <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12, minWidth: 640 }}>
              <thead>
                <tr>
                  {["Type", "Direction", "Population", "Status", "Stage", "Start", "End"].map((h) => (
                    <th key={h} scope="col" style={{ textAlign: "left", padding: "7px 10px", background: "var(--bg-2)", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--c-ink-3)" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {patterns.map((p) => (
                  <tr key={p.pattern_id} data-testid="chart-dataview-pattern">
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{txt(p.pattern_type)}</td>
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{txt(p.direction)}</td>
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{txt(p.population)}</td>
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{txt(p.status)} ({patternVisualCategory(p)})</td>
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{txt(p.stage)}</td>
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{txt(p.formation_start)}</td>
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{txt(p.formation_end)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
