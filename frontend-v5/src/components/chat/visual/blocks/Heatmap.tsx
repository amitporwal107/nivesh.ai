/**
 * `heatmap`: a grid of tiles coloured by value, with the label and the signed value printed on each tile. The colour
 * scale is the sector heatmap's own (screens/heatmap/heat.ts tintOf: mint up, danger down, flat and unknown neutral);
 * its saturation point is the day's 3%, the week's 6% or the month's 10%, whichever first covers the largest move
 * shown, so a quiet day is not painted as a crash. Cells with a `group` are shown under their group's name.
 */
import { legendSteps, tintOf } from "@/pages/CopilotApp/screens/heatmap/heat";
import type { PeriodKey } from "@/pages/CopilotApp/screens/heatmap/heatmap-data";
import type { HeatmapBlock } from "../schema";
import { fmtUnit } from "../format";
import type { BlockProps } from "./common";

function scaleFor(values: number[]): PeriodKey {
  const far = Math.max(0, ...values.map((v) => Math.abs(v)));
  return far <= 3 ? "d" : far <= 6 ? "w" : "m";
}

export function HeatmapView({ b, compact }: BlockProps<HeatmapBlock>) {
  const vals = b.cells.map((c) => c.value).filter((v): v is number => v != null && Number.isFinite(v));
  const scale = scaleFor(vals);
  const groups: Array<{ name: string | null; cells: HeatmapBlock["cells"] }> = [];
  for (const c of b.cells) {
    const name = c.group ?? null;
    const g = groups.find((x) => x.name === name);
    if (g) g.cells.push(c);
    else groups.push({ name, cells: [c] });
  }
  const steps = legendSteps(scale);
  return (
    <div data-testid="va-heatmap" data-scale={scale} className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      {groups.map((g, gi) => (
        <div key={`${g.name ?? "all"}-${gi}`} className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          {g.name && groups.length > 1 && <span data-testid="va-heat-group" style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>{g.name}</span>}
          <ul className="m-0 grid list-none p-0" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${compact ? 88 : 104}px, 1fr))`, gap: 4 }}>
            {g.cells.map((c, i) => {
              const t = tintOf(c.value, scale);
              const text = fmtUnit(c.value, b.unit);
              return (
                <li key={`${c.label}-${i}`} data-testid="va-heat-cell" data-label={c.label} data-value={c.value ?? ""} data-tone={t.tone}
                  title={`${c.label} ${text}${c.sub ? ` · ${c.sub}` : ""}`}
                  className="flex min-w-0 flex-col justify-between"
                  style={{ gap: 2, minHeight: compact ? 48 : 54, padding: "6px 8px", borderRadius: 6, background: t.bg, color: t.fg, textShadow: t.shadow === "none" ? undefined : t.shadow }}>
                  <span data-testid="va-heat-label" style={{ fontSize: 11.5, lineHeight: 1.25, fontWeight: 500, overflowWrap: "anywhere" }}>{c.label}</span>
                  <span data-testid="va-heat-value" className="cp-num" style={{ fontSize: 12.5, lineHeight: 1.2 }}>{text}</span>
                  {c.sub && <span style={{ fontSize: 10, lineHeight: 1.25, opacity: 0.9, overflowWrap: "anywhere" }}>{c.sub}</span>}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
      <div data-testid="va-heat-legend" className="flex items-center" style={{ gap: 6, fontSize: 10.5, color: "var(--cp-ink-3)" }} aria-label={`Colour scale from ${fmtUnit(steps[0], b.unit)} to ${fmtUnit(steps[steps.length - 1], b.unit)}`}>
        <span className="cp-num">{fmtUnit(steps[0], b.unit)}</span>
        <span className="flex" aria-hidden style={{ gap: 2 }}>
          {steps.map((s) => <span key={s} style={{ width: 16, height: 8, borderRadius: 2, background: tintOf(s, scale).bg }} />)}
        </span>
        <span className="cp-num">{fmtUnit(steps[steps.length - 1], b.unit)}</span>
        <span>or more</span>
      </div>
    </div>
  );
}
