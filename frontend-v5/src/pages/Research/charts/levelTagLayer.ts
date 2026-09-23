/**
 * Right-aligned S/R level tags — 1A change 08: "Tags are smaller, right-aligned in a fixed lane, and
 * carry only the label plus distance. Broken levels drop to a dashed hairline at 35% so live levels
 * read first."
 *
 * Why a primitive rather than the native price-line label: a `createPriceLine` gives you a `title`
 * drawn at the left of the line and an `axisLabelVisible` price badge on the axis. Turning both on
 * is what produced "R 2940.00" on the line beside "2940.00" on the axis — the same number twice —
 * and neither can be moved into a shared right-hand lane or nudged off a neighbour. This draws the
 * tags itself, so they sit in one lane and never overlap.
 *
 * The lines themselves stay native price lines (ChartCanvas): they are full-width, they already
 * carry selection/dim state, and the `renderedLevels` test hook counts them.
 *
 * Nothing here decides what a level is worth. Price, side, distance and broken-ness all arrive
 * computed from the snapshot (`contract.ts` groupSrBands / levelCards).
 */
import type {
  IChartApi, ISeriesApi, SeriesType, Time,
  ISeriesPrimitiveBase, SeriesAttachedParameter, IPrimitivePaneView, IPrimitivePaneRenderer,
} from "lightweight-charts";

export interface LevelTag {
  price: number;
  /** "S" | "R" | "S/R" */
  side: string;
  /** Distance from the last close in percent, already signed; null when there is no last close. */
  pct: number | null;
  colour: string;
  broken: boolean;
  dim: boolean;
}

/** Vertical room one tag needs before it counts as colliding with its neighbour. */
const ROW_H = 15;
/** Distance from the right-hand edge of the plot to the lane. */
const LANE_PAD = 6;

class TagsRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly _p: LevelTagsPrimitive) {}

  draw(target: Parameters<IPrimitivePaneRenderer["draw"]>[0]): void {
    const p = this._p;
    if (!p.series || !p.tags.length) return;

    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      ctx.save();
      ctx.scale(scope.horizontalPixelRatio, scope.verticalPixelRatio);
      const width = scope.mediaSize.width;
      const height = scope.mediaSize.height;

      // Place every tag at its own price first, then push apart any that would overlap. Sorting by y
      // and sweeping downwards keeps the order stable, so a tag never jumps past its neighbour.
      const placed: Array<{ t: LevelTag; y: number }> = [];
      for (const t of p.tags) {
        const c = p.series!.priceToCoordinate(t.price);
        if (c == null) continue;
        placed.push({ t, y: Number(c) });
      }
      placed.sort((a, b) => a.y - b.y);

      let lastY = -Infinity;
      for (const row of placed) {
        row.y = Math.max(row.y, lastY + ROW_H);
        lastY = row.y;
      }
      // A run pushed past the bottom is walked back up, so tags stay inside the pane.
      const overflow = lastY - (height - 4);
      if (overflow > 0) for (const row of placed) row.y -= overflow;

      ctx.font = "9px ui-monospace, SFMono-Regular, Menlo, monospace";
      ctx.textBaseline = "middle";
      ctx.textAlign = "right";

      for (const { t, y } of placed) {
        if (y < 2 || y > height - 2) continue;
        const label = t.pct != null ? `${t.side} · ${t.pct >= 0 ? "+" : ""}${t.pct.toFixed(1)}%` : t.side;
        const alpha = t.dim ? 0.25 : t.broken ? 0.35 : 0.95;
        const w = ctx.measureText(label).width + 10;
        const x = width - LANE_PAD;

        ctx.globalAlpha = alpha;
        ctx.fillStyle = "rgba(0,0,0,0.45)";
        roundRect(ctx, x - w, y - 7, w, 14, 3);
        ctx.fill();
        ctx.strokeStyle = t.colour;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.fillStyle = t.colour;
        ctx.fillText(label, x - 5, y);
        ctx.globalAlpha = 1;
      }

      ctx.restore();
    });
  }
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

class TagsPaneView implements IPrimitivePaneView {
  private readonly _renderer: TagsRenderer;
  constructor(p: LevelTagsPrimitive) { this._renderer = new TagsRenderer(p); }
  renderer(): IPrimitivePaneRenderer { return this._renderer; }
}

export class LevelTagsPrimitive implements ISeriesPrimitiveBase<SeriesAttachedParameter<Time, SeriesType>> {
  chart: IChartApi | null = null;
  series: ISeriesApi<SeriesType, Time> | null = null;
  tags: LevelTag[] = [];

  private readonly _paneView: TagsPaneView;
  private _requestUpdate: (() => void) | null = null;

  constructor() { this._paneView = new TagsPaneView(this); }

  attached(param: SeriesAttachedParameter<Time, SeriesType>): void {
    this.chart = param.chart;
    this.series = param.series;
    this._requestUpdate = param.requestUpdate;
  }
  detached(): void { this.chart = null; this.series = null; this._requestUpdate = null; }

  updateAllViews(): void { /* the renderer reads live refs on each draw */ }
  paneViews(): readonly IPrimitivePaneView[] { return [this._paneView]; }

  set(tags: LevelTag[]): void {
    this.tags = tags;
    this._requestUpdate?.();
  }
}
