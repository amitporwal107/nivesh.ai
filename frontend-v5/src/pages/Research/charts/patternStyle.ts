/**
 * §38.15 status styling for pattern overlays, built ONLY from the existing `ChartTheme` tokens (theme.ts is owned by
 * another agent building W1 — this module reads its exported type/helpers but adds no new colour, only line-style
 * and alpha choices layered on top of the existing tokens).
 *
 *   - confirmed: solid, full colour (theme.mint) — a pattern past price confirmation (contract.ts CONFIRMED_STATES).
 *   - forming: dashed, faded by stage (theme.amber at 0.4/0.65/0.9 alpha for S1/S2/no-stage) — never confused with
 *     "confirmed" even at a glance.
 *   - failed / invalidated: dotted, grey (theme.ink4) — both read as "over", label text tells them apart.
 *
 * Distinctness from manual drawings (primitives.ts): drawings are thin unfilled lines with a circular handle only;
 * patterns additionally carry a translucent fill (rectangles), a text label and event/pivot markers, so the two
 * layers never look alike even where a colour is shared.
 */
import { LineStyle } from "lightweight-charts";
import type { ChartTheme } from "./theme";
import { withAlpha } from "./theme";
import type { PatternVisualCategory } from "./contract";

export interface PatternStyle {
  stroke: string;
  fill: string;
  lineStyle: LineStyle;
  lineWidth: number;
  dash: number[]; // canvas ctx.setLineDash — mirrors `lineStyle` for the hand-drawn primitive (which does not use the library's native LineStyle enum)
}

const STAGE_ALPHA: Record<string, number> = { S1: 0.4, S2: 0.65, S3: 0.9 };

export function patternStyle(theme: ChartTheme, category: PatternVisualCategory, stage: string | null): PatternStyle {
  if (category === "confirmed") {
    return { stroke: theme.mint, fill: withAlpha(theme.mint, 0.12), lineStyle: LineStyle.Solid, lineWidth: 2, dash: [] };
  }
  if (category === "forming") {
    const alpha = stage != null ? (STAGE_ALPHA[stage] ?? 0.55) : 0.55;
    return { stroke: withAlpha(theme.amber, alpha), fill: withAlpha(theme.amber, alpha * 0.18), lineStyle: LineStyle.Dashed, lineWidth: 1.5, dash: [6, 4] };
  }
  // failed / invalidated
  return { stroke: withAlpha(theme.ink4, 0.85), fill: withAlpha(theme.ink4, 0.06), lineStyle: LineStyle.Dotted, lineWidth: 1.25, dash: [1.5, 3] };
}

export const KNOWN_MARKER_COLOUR = (theme: ChartTheme) => withAlpha(theme.ink3, 0.7);
export const SELECTED_GLOW = (theme: ChartTheme) => theme.ink; // ring drawn around the selected shape, dims everything else instead of re-colouring it
export const DIMMED_ALPHA = 0.28;
