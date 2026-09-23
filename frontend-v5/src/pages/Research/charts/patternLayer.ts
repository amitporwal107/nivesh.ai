/**
 * §38.15 "Patterns on the chart" — a series primitive that draws every (filtered) chart pattern over ITS OWN dates
 * (AC19), with hit testing, mirroring primitives.ts's DrawingsPrimitive (attachPrimitive/ISeriesPrimitive* is the
 * documented extension point — the library ships no built-in pattern shapes). This primitive owns ONLY chart
 * patterns (RECTANGLE, HH_HL, …) — SUPPORT_RESISTANCE records are a separate, non-dated layer (still native
 * createPriceLine, grouped into bands by contract.ts `groupSrBands`) and are never passed in here.
 *
 * Shapes drawn (§38.15 "Shape, not lines"):
 *   - RECTANGLE (or any future family with both support+resistance): a box from formation_start/resistance to
 *     formation_end/support.
 *   - HH_HL (or any family with >=2 pivots and no support+resistance pair): a polyline through its pivots.
 *   - breakout_level / invalidation_level: a short segment from formation_end to the confirming/failing event date,
 *     at that level's price — never a line across the whole chart.
 *   - Markers at every pivot and at confirmation/failure/invalidation events.
 *   - A "Known" marker (contract.ts `knownMarkerDate`) — see patternStyle.ts's KNOWN_MARKER_COLOUR.
 *   - A small "<Type> · <status>" label.
 */
import type {
  IChartApi, ISeriesApi, SeriesType, Time,
  ISeriesPrimitiveBase, SeriesAttachedParameter, IPrimitivePaneView, IPrimitivePaneRenderer,
} from "lightweight-charts";
import type { ChartTheme } from "./theme";
import { patternStyle, KNOWN_MARKER_COLOUR, DIMMED_ALPHA } from "./patternStyle";
import { type Pattern, patternTypeLabel, statusLabel, patternVisualCategory, knownMarkerDate } from "./contract";

const HIT_PX = 8;

interface XY { x: number; y: number }

class PatternsPaneRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly _p: PatternsPrimitive) {}

  draw(target: Parameters<IPrimitivePaneRenderer["draw"]>[0]): void {
    const p = this._p;
    if (!p.chart || !p.series || !p.theme) return;
    const ts = p.chart.timeScale();
    const toXY = (date: string, price: number): XY | null => {
      const x = ts.timeToCoordinate(date as Time);
      const y = p.series!.priceToCoordinate(price);
      if (x == null || y == null) return null;
      return { x, y };
    };

    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      ctx.save();
      ctx.scale(scope.horizontalPixelRatio, scope.verticalPixelRatio);
      ctx.font = "10.5px var(--mono), monospace";
      ctx.textBaseline = "bottom";

      for (const p2 of p.patterns) {
        const dimmed = p.selectedId != null && p.selectedId !== p2.pattern_id;
        ctx.globalAlpha = dimmed ? DIMMED_ALPHA : 1;
        this._drawOne(ctx, p2, toXY, p.theme!);
      }
      ctx.globalAlpha = 1;
      ctx.restore();
    });
  }

  private _drawOne(ctx: CanvasRenderingContext2D, p: Pattern, toXY: (d: string, pr: number) => XY | null, theme: ChartTheme): void {
    const cat = patternVisualCategory(p);
    const style = patternStyle(theme, cat, p.stage);
    ctx.strokeStyle = style.stroke;
    ctx.fillStyle = style.fill;
    ctx.lineWidth = style.lineWidth;
    ctx.setLineDash(style.dash);

    const support = p.levels?.support, resistance = p.levels?.resistance;
    const hasBox = typeof support === "number" && typeof resistance === "number";
    let labelXY: XY | null = null;

    if (hasBox) {
      const a = toXY(p.formation_start, resistance!);
      const b = toXY(p.formation_end, support!);
      if (a && b) {
        const x1 = Math.min(a.x, b.x), x2 = Math.max(a.x, b.x);
        const y1 = Math.min(a.y, b.y), y2 = Math.max(a.y, b.y);
        ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
        labelXY = { x: x1 + 4, y: y1 };
      }
    } else if ((p.pivots ?? []).length >= 2) {
      const pts = p.pivots.map((piv) => toXY(piv.date, piv.price)).filter((xy): xy is XY => xy !== null);
      if (pts.length >= 2) {
        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        for (const pt of pts.slice(1)) ctx.lineTo(pt.x, pt.y);
        ctx.stroke();
        labelXY = { x: pts[0].x + 4, y: pts[0].y - 6 };
      }
    }

    // breakout / invalidation short segments: formation_end -> the confirming/failing event, at that level's price
    const seg = (levelPrice: number | null | undefined, matches: (t: string) => boolean) => {
      if (typeof levelPrice !== "number") return;
      const ev = (p.events ?? []).find((e) => matches((e.event_type || "").toUpperCase()));
      if (!ev) return;
      const a = toXY(p.formation_end, levelPrice);
      const b = toXY(ev.date, levelPrice);
      if (!a || !b) return;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    };
    seg(p.levels?.breakout_level, (t) => t.includes("CONFIRM"));
    seg(p.levels?.invalidation_level, (t) => t.includes("FAIL") || t.includes("INVALID"));

    // markers: pivots (small dot) + events (small square)
    ctx.setLineDash([]);
    for (const piv of p.pivots ?? []) {
      const xy = toXY(piv.date, piv.price);
      if (!xy) continue;
      ctx.beginPath();
      ctx.arc(xy.x, xy.y, 3, 0, Math.PI * 2);
      if (piv.kind === "HIGH") ctx.fill(); else ctx.stroke();
    }
    for (const ev of p.events ?? []) {
      const t = (ev.event_type || "").toUpperCase();
      const evPrice = t.includes("CONFIRM") ? p.levels?.breakout_level : t.includes("FAIL") || t.includes("INVALID") ? p.levels?.invalidation_level : null;
      if (typeof evPrice !== "number") continue;
      const xy = toXY(ev.date, evPrice);
      if (!xy) continue;
      ctx.fillRect(xy.x - 3, xy.y - 3, 6, 6);
    }

    // "Known" marker — dotted vertical line at the latest pivot confirmed_date (§38.15)
    const known = knownMarkerDate(p);
    if (known) {
      const x = toXY(known, support ?? resistance ?? p.pivots?.[0]?.price ?? 0)?.x;
      if (x != null) {
        const yTop = hasBox ? toXY(p.formation_start, resistance!)?.y : undefined;
        const yBot = hasBox ? toXY(p.formation_end, support!)?.y : undefined;
        ctx.save();
        ctx.strokeStyle = KNOWN_MARKER_COLOUR(theme);
        ctx.setLineDash([2, 2]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, yTop ?? 0);
        ctx.lineTo(x, yBot ?? (labelXY?.y ?? 0) + 40);
        ctx.stroke();
        ctx.fillStyle = KNOWN_MARKER_COLOUR(theme);
        ctx.fillText("pivots confirmed", x + 3, (yTop ?? 10) + 10);
        ctx.restore();
      }
    }

    // label
    if (labelXY) {
      ctx.fillStyle = style.stroke;
      ctx.fillText(`${patternTypeLabel(p.pattern_type)} · ${statusLabel(p)}`, labelXY.x, labelXY.y - 2);
    }
  }
}

class PatternsPaneView implements IPrimitivePaneView {
  private readonly _renderer: PatternsPaneRenderer;
  constructor(p: PatternsPrimitive) { this._renderer = new PatternsPaneRenderer(p); }
  renderer(): IPrimitivePaneRenderer { return this._renderer; }
}

export class PatternsPrimitive implements ISeriesPrimitiveBase<SeriesAttachedParameter<Time, SeriesType>> {
  chart: IChartApi | null = null;
  series: ISeriesApi<SeriesType, Time> | null = null;
  patterns: Pattern[] = [];
  selectedId: string | null = null;
  theme: ChartTheme | null = null;

  private readonly _paneView: PatternsPaneView;
  private _requestUpdate: (() => void) | null = null;

  constructor() { this._paneView = new PatternsPaneView(this); }

  attached(param: SeriesAttachedParameter<Time, SeriesType>): void {
    this.chart = param.chart;
    this.series = param.series;
    this._requestUpdate = param.requestUpdate;
  }
  detached(): void { this.chart = null; this.series = null; this._requestUpdate = null; }

  updateAllViews(): void { /* renderer reads live refs each draw() */ }
  paneViews(): readonly IPrimitivePaneView[] { return [this._paneView]; }

  setTheme(theme: ChartTheme): void { this.theme = theme; this.requestUpdate(); }
  setPatterns(patterns: Pattern[]): void { this.patterns = patterns; this.requestUpdate(); }
  setSelected(id: string | null): void { this.selectedId = id; this.requestUpdate(); }
  requestUpdate(): void { this._requestUpdate?.(); }

  /** Every pattern whose drawn shape contains/is near (x, y) in canvas/media coordinates, most-recent
   *  formation_end first (§38.15: "the most recent pattern is selected first, and Previous/Next step through the
   *  rest"). A filled box counts any interior click; a polyline uses a pixel hit tolerance like DrawingsPrimitive. */
  hitTestPatterns(x: number, y: number): string[] {
    if (!this.chart || !this.series) return [];
    const ts = this.chart.timeScale();
    const toXY = (date: string, price: number): XY | null => {
      const px = ts.timeToCoordinate(date as Time);
      const py = this.series!.priceToCoordinate(price);
      return px == null || py == null ? null : { x: px, y: py };
    };
    const hits: string[] = [];
    for (const p of this.patterns) {
      const support = p.levels?.support, resistance = p.levels?.resistance;
      if (typeof support === "number" && typeof resistance === "number") {
        const a = toXY(p.formation_start, resistance);
        const b = toXY(p.formation_end, support);
        if (a && b) {
          const x1 = Math.min(a.x, b.x), x2 = Math.max(a.x, b.x);
          const y1 = Math.min(a.y, b.y), y2 = Math.max(a.y, b.y);
          if (x >= x1 && x <= x2 && y >= y1 && y <= y2) { hits.push(p.pattern_id); continue; }
        }
      }
      const pivots = p.pivots ?? [];
      if (pivots.length >= 2) {
        const pts = pivots.map((piv) => toXY(piv.date, piv.price)).filter((xy): xy is XY => xy !== null);
        for (let i = 0; i < pts.length - 1; i++) {
          if (distToSegment(x, y, pts[i].x, pts[i].y, pts[i + 1].x, pts[i + 1].y) <= HIT_PX) { hits.push(p.pattern_id); break; }
        }
      }
    }
    return hits.sort((a, b) => {
      const pa = this.patterns.find((p) => p.pattern_id === a)!, pb = this.patterns.find((p) => p.pattern_id === b)!;
      return pb.formation_end.localeCompare(pa.formation_end);
    });
  }
}

function distToSegment(px: number, py: number, x1: number, y1: number, x2: number, y2: number): number {
  const dx = x2 - x1, dy = y2 - y1;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return Math.hypot(px - x1, py - y1);
  let t = ((px - x1) * dx + (py - y1) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  const cx = x1 + t * dx, cy = y1 + t * dy;
  return Math.hypot(px - cx, py - cy);
}
