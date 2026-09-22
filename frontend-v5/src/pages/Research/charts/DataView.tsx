/**
 * The non-canvas alternative required by feasibility.md B7: the chart canvas is not screen-reader accessible, so
 * everything it draws also exists as a real, keyboard-reachable DOM table — bars, chart patterns and support/resistance levels.
 */
import { price, vol, txt, type Bar, type Pattern, statusLabel, patternTypeLabel, levelOf } from "./contract";

export default function DataView({ symbol, bars, patterns, levels = [] }: { symbol: string; bars: Bar[]; patterns: Pattern[]; levels?: Pattern[] }) {
  const levelRows = levels.map((p) => ({ p, lv: levelOf(p) })).filter((x) => x.lv !== null);
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
        <p className="nv-eyebrow" style={{ margin: "0 0 8px" }}>Chart patterns · {patterns.length}</p>
        {patterns.length === 0 ? (
          <p data-testid="chart-dataview-patterns-empty" style={{ margin: 0, fontSize: 13, color: "var(--c-ink-3)" }}>
            No chart patterns found.
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
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{patternTypeLabel(p.pattern_type)}</td>
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{txt(p.direction)}</td>
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{txt(p.population)}</td>
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{statusLabel(p)}</td>
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

      {levelRows.length > 0 && (
        <div>
          <p className="nv-eyebrow" style={{ margin: "0 0 8px" }}>Support &amp; resistance · {levelRows.length}</p>
          <div tabIndex={0} role="region" aria-label={`${symbol} support and resistance levels, table form`} style={{ overflowX: "auto", border: "1px solid var(--c-line)", borderRadius: 10 }}>
            <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12, minWidth: 420 }}>
              <thead>
                <tr>
                  {["Kind", "Level", "Status", "Since"].map((h) => (
                    <th key={h} scope="col" style={{ textAlign: "left", padding: "7px 10px", background: "var(--bg-2)", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--c-ink-3)" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {levelRows.map(({ p, lv }) => (
                  <tr key={p.pattern_id} data-testid="chart-dataview-level">
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{lv!.kind === "SUPPORT" ? "Support" : "Resistance"}</td>
                    <td className="nv-mono" style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{price(lv!.price)}</td>
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{lv!.failed ? "failed" : lv!.broken ? "broken" : "holding"}</td>
                    <td style={{ padding: "6px 10px", borderTop: "1px solid var(--c-line)" }}>{txt(p.formation_start)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
