/**
 * The two v1 drawing tools (trendline, horizontal line) as a Lightweight Charts v5 series primitive
 * (`ISeriesPrimitiveBase` — the library ships no built-in drawing tools, `attachPrimitive`/`ISeriesPrimitive*` is
 * the documented extension point: node_modules/lightweight-charts/dist/typings.d.ts:2693,2785).
 *
 * System pattern overlays (levels, pivots, confirmation/failure markers) are rendered separately with the library's
 * native `createPriceLine` + `createSeriesMarkers` — this primitive owns ONLY manual drawings, so the two are
 * visually and structurally distinct, as required (B4: "manual drawing" is its own category; task item 7).
 */
import type {
  IChartApi, ISeriesApi, SeriesType, Time,
  ISeriesPrimitiveBase, SeriesAttachedParameter, IPrimitivePaneView, IPrimitivePaneRenderer,
} from "lightweight-charts";

export interface DrawingPoint { time: Time; price: number }
export interface DrawingSegment {
  id: string;
  type: "TRENDLINE" | "HORIZONTAL_LINE";
  points: DrawingPoint[];   // 2 for a trendline, 1 for a horizontal line
}

const HANDLE_R = 4.5;
const HIT_PX = 7;

class DrawingsPaneRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly _p: DrawingsPrimitive) {}

  draw(target: Parameters<IPrimitivePaneRenderer["draw"]>[0]): void {
    const p = this._p;
    if (!p.chart || !p.series) return;
    // §38.6 "hide all": the segments stay in `p.segments` (and on the server) — only the drawing is skipped.
    if (p.hidden) return;
    const ts = p.chart.timeScale();
    const toXY = (pt: DrawingPoint): { x: number; y: number } | null => {
      const x = ts.timeToCoordinate(pt.time);
      const y = p.series!.priceToCoordinate(pt.price);
      if (x == null || y == null) return null;
      return { x, y };
    };

    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      ctx.save();
      ctx.scale(scope.horizontalPixelRatio, scope.verticalPixelRatio);

      const draw1 = (seg: DrawingSegment, selected: boolean) => {
        const colour = p.theme.ink;
        ctx.strokeStyle = selected ? p.theme.mint : colour;
        ctx.fillStyle = selected ? p.theme.mint : colour;
        ctx.lineWidth = selected ? 2.5 : 1.75;
        ctx.setLineDash([]);

        if (seg.type === "HORIZONTAL_LINE") {
          const xy = toXY(seg.points[0]);
          if (!xy) return;
          const width = scope.mediaSize.width;
          ctx.beginPath();
          ctx.moveTo(0, xy.y);
          ctx.lineTo(width, xy.y);
          ctx.stroke();
          ctx.beginPath();
          ctx.arc(xy.x, xy.y, HANDLE_R, 0, Math.PI * 2);
          ctx.fill();
        } else {
          const a = toXY(seg.points[0]);
          const b = seg.points[1] ? toXY(seg.points[1]) : null;
          if (!a) return;
          if (b) {
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(b.x, b.y, HANDLE_R, 0, Math.PI * 2);
            ctx.fill();
          } else {
            // Pending first anchor of a trendline being placed — show the handle only.
            ctx.setLineDash([3, 3]);
          }
          ctx.beginPath();
          ctx.arc(a.x, a.y, HANDLE_R, 0, Math.PI * 2);
          ctx.fill();
        }
      };

      for (const seg of p.segments) draw1(seg, seg.id === p.selectedId);
      if (p.pending) draw1({ id: "__pending__", type: p.pending.type, points: p.pending.points }, true);

      ctx.restore();
    });
  }
}

class DrawingsPaneView implements IPrimitivePaneView {
  private readonly _renderer: DrawingsPaneRenderer;
  constructor(p: DrawingsPrimitive) { this._renderer = new DrawingsPaneRenderer(p); }
  renderer(): IPrimitivePaneRenderer { return this._renderer; }
}

/**
 * Owns the manual drawings for one series: holds the segment list + selection + in-progress placement, renders
 * them every frame, and answers hit-tests so the host component can implement "click near a line/handle → select".
 */
export class DrawingsPrimitive implements ISeriesPrimitiveBase<SeriesAttachedParameter<Time, SeriesType>> {
  chart: IChartApi | null = null;
  series: ISeriesApi<SeriesType, Time> | null = null;
  segments: DrawingSegment[] = [];
  selectedId: string | null = null;
  pending: { type: "TRENDLINE" | "HORIZONTAL_LINE"; points: DrawingPoint[] } | null = null;
  /** §38.6 "hide all" — drawn output is suppressed and nothing is hit-testable; nothing is deleted. */
  hidden = false;
  theme = { ink: "rgb(200,200,200)", mint: "rgb(110,240,168)" };

  private readonly _paneView: DrawingsPaneView;
  private _requestUpdate: (() => void) | null = null;

  constructor() { this._paneView = new DrawingsPaneView(this); }

  attached(param: SeriesAttachedParameter<Time, SeriesType>): void {
    this.chart = param.chart;
    this.series = param.series;
    this._requestUpdate = param.requestUpdate;
  }
  detached(): void { this.chart = null; this.series = null; this._requestUpdate = null; }

  updateAllViews(): void { /* renderer reads live refs each draw() — nothing to precompute */ }
  paneViews(): readonly IPrimitivePaneView[] { return [this._paneView]; }

  setTheme(ink: string, mint: string): void { this.theme = { ink, mint }; this.requestUpdate(); }
  setSegments(segs: DrawingSegment[]): void { this.segments = segs; this.requestUpdate(); }
  setSelected(id: string | null): void { this.selectedId = id; this.requestUpdate(); }
  setPending(pending: DrawingsPrimitive["pending"]): void { this.pending = pending; this.requestUpdate(); }
  setHidden(hidden: boolean): void { this.hidden = hidden; this.requestUpdate(); }
  requestUpdate(): void { this._requestUpdate?.(); }

  /** Nearest segment within HIT_PX of (x, y) in canvas/media coordinates, or null. */
  hitTestDrawing(x: number, y: number): string | null {
    if (!this.chart || !this.series || this.hidden) return null;
    const ts = this.chart.timeScale();
    const toXY = (pt: DrawingPoint) => {
      const px = ts.timeToCoordinate(pt.time);
      const py = this.series!.priceToCoordinate(pt.price);
      return px == null || py == null ? null : { x: px, y: py };
    };
    let best: { id: string; d: number } | null = null;
    for (const seg of this.segments) {
      if (seg.type === "HORIZONTAL_LINE") {
        const a = toXY(seg.points[0]);
        if (!a) continue;
        const d = Math.abs(y - a.y);
        if (d <= HIT_PX && (!best || d < best.d)) best = { id: seg.id, d };
      } else {
        const a = toXY(seg.points[0]);
        const b = seg.points[1] ? toXY(seg.points[1]) : null;
        if (!a || !b) continue;
        const d = distToSegment(x, y, a.x, a.y, b.x, b.y);
        if (d <= HIT_PX && (!best || d < best.d)) best = { id: seg.id, d };
      }
    }
    return best?.id ?? null;
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
