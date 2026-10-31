/**
 * `heatmap`: a grid of tiles coloured by value, with the label and the signed value printed on each tile. The colour
 * scale is the sector heatmap's own (screens/heatmap/heat.ts tintOf: mint up, danger down, flat and unknown neutral);
 * its saturation point is the day's 3%, the week's 6% or the month's 10%, whichever first covers the largest move
 * shown, so a quiet day is not painted as a crash. Cells with a `group` are shown under their group's name. A cell with
 * `members` is a button: selecting it shows those stocks (value, sub, an Ask ›) under the grid; the first such cell is open
 * to begin with, so the leading sector's stocks are on the screen without a click.
 */
import { useState } from "react";
import { legendSteps, tintOf } from "@/pages/CopilotApp/screens/heatmap/heat";
import type { PeriodKey } from "@/pages/CopilotApp/screens/heatmap/heatmap-data";
import type { HeatmapBlock } from "../schema";
import { fmtPct, fmtUnit } from "../format";
import type { BlockProps } from "./common";

function scaleFor(values: number[]): PeriodKey {
  const far = Math.max(0, ...values.map((v) => Math.abs(v)));
  return far <= 3 ? "d" : far <= 6 ? "w" : "m";
}

export function HeatmapView({ b, compact, ask }: BlockProps<HeatmapBlock>) {
  const firstWithMembers = b.cells.find((c) => c.members?.length)?.label ?? null;
  const [picked, setPicked] = useState<string | null | undefined>(undefined);       // undefined: the first one with members
  const open = picked === undefined ? firstWithMembers : picked;
  const openCell = open ? b.cells.find((c) => c.label === open && c.members?.length) : undefined;
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
              const has = !!c.members?.length;
              const selected = has && open === c.label;
              return (
                <li key={`${c.label}-${i}`} data-testid="va-heat-cell" data-label={c.label} data-value={c.value ?? ""} data-tone={t.tone}
                  data-selectable={has ? "1" : "0"} data-selected={selected ? "1" : "0"}
                  title={`${c.label} ${text}${c.sub ? ` · ${c.sub}` : ""}`}
                  role={has ? "button" : undefined} tabIndex={has ? 0 : undefined} aria-pressed={has ? selected : undefined}
                  aria-label={has ? `${c.label} ${text}: ${selected ? "hide" : "show"} its strongest stocks` : undefined}
                  onClick={has ? () => setPicked(selected ? null : c.label) : undefined}
                  onKeyDown={has ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPicked(selected ? null : c.label); } } : undefined}
                  className="flex min-w-0 flex-col justify-between"
                  style={{ gap: 2, minHeight: compact ? 48 : 54, padding: "6px 8px", borderRadius: 6, background: t.bg, color: t.fg, textShadow: t.shadow === "none" ? undefined : t.shadow,
                    cursor: has ? "pointer" : undefined, outline: selected ? "2px solid var(--cp-ink)" : undefined, outlineOffset: selected ? 1 : undefined }}>
                  <span data-testid="va-heat-label" style={{ fontSize: 11.5, lineHeight: 1.25, fontWeight: 500, overflowWrap: "anywhere" }}>{c.label}</span>
                  <span data-testid="va-heat-value" className="cp-num" style={{ fontSize: 12.5, lineHeight: 1.2 }}>{text}</span>
                  {c.sub && <span style={{ fontSize: 10, lineHeight: 1.25, opacity: 0.9, overflowWrap: "anywhere" }}>{c.sub}</span>}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
      {openCell && (
        <div data-testid="va-heat-members" data-sector={openCell.label} className="flex min-w-0 flex-col"
          style={{ gap: 4, padding: "8px 10px", borderRadius: 8, border: "1px solid var(--cp-line)", background: "var(--bg-2)" }}>
          <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>Top {openCell.members?.length} in {openCell.label} · by the day's move</span>
          <ul className="m-0 flex list-none flex-col p-0">
            {openCell.members?.map((m) => (
              <li key={m.label} data-testid="va-heat-member" data-symbol={m.label} className="flex min-w-0 items-center justify-between"
                style={{ gap: 8, padding: "4px 0", borderTop: "1px solid var(--cp-line)", fontSize: 12.5 }}>
                <span className="flex min-w-0 items-baseline" style={{ gap: 8 }}>
                  <strong data-testid="va-heat-member-label" style={{ fontSize: 13 }}>{m.label}</strong>
                  {m.sub && <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{m.sub}</span>}
                </span>
                <span className="inline-flex items-center" style={{ gap: 8 }}>
                  <span data-testid="va-heat-member-value" className="cp-num" style={{ color: (m.value ?? 0) > 0 ? "var(--mint)" : (m.value ?? 0) < 0 ? "var(--cp-danger)" : "var(--cp-ink)" }}>{fmtPct(m.value)}</span>
                  {m.ask && (
                    <button type="button" data-testid="va-heat-member-ask" className="cp-btn" data-variant="ghost" disabled={!ask}
                      aria-label={`Ask: ${m.ask}`} title={m.ask} onClick={() => ask?.(m.ask as string)} style={{ padding: "3px 9px", fontSize: 12 }}>Ask ›</button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
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
