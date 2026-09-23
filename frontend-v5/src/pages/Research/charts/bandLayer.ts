/**
 * Reference bands for an oscillator pane — §38.5: "Reference bands appear where the indicator
 * defines them (e.g. RSI 30/70 with shaded fill)."
 *
 * The levels are never chosen here. They come from the indicator catalogue the snapshot was built
 * with (`contract.ts` CatalogueIndicator.reference_bands / band_fill), so the line at 30 is the
 * catalogue's 30 and nothing in the browser decides what "oversold" means.
 *
 * A Lightweight Charts series primitive, the same extension point the drawing and pattern layers
 * use (`primitives.ts`, `patternLayer.ts`). It draws only within its own pane, because a primitive
 * is attached to a series and a series belongs to one pane.
 */
import type {
  IChartApi, ISeriesApi, SeriesType, Time,
  ISeriesPrimitiveBase, SeriesAttachedParameter, IPrimitivePaneView, IPrimitivePaneRenderer,
} from "lightweight-charts";

export interface ReferenceBand { value: number; label: string }
export interface BandFill { from: number; to: number }

class BandsPaneRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly _p: BandsPrimitive) {}

  draw(target: Parameters<IPrimitivePaneRenderer["draw"]>[0]): void {
    const p = this._p;
    if (!p.series || (!p.bands.length && !p.fill)) return;
    const y = (price: number): number | null => {
      const c = p.series!.priceToCoordinate(price);
      return c == null ? null : c;
    };

    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      ctx.save();
      ctx.scale(scope.horizontalPixelRatio, scope.verticalPixelRatio);
      const width = scope.mediaSize.width;

      // The shaded band first, so the dashed level lines sit on top of it.
      if (p.fill) {
        const a = y(p.fill.from);
        const b = y(p.fill.to);
        if (a != null && b != null) {
          ctx.fillStyle = p.fillColour;
          ctx.fillRect(0, Math.min(a, b), width, Math.abs(a - b));
        }
      }

      ctx.strokeStyle = p.lineColour;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      for (const band of p.bands) {
        const yy = y(band.value);
        if (yy == null) continue;
        ctx.beginPath();
        ctx.moveTo(0, yy);
        ctx.lineTo(width, yy);
        ctx.stroke();
      }

      ctx.restore();
    });
  }
}

class BandsPaneView implements IPrimitivePaneView {
  private readonly _renderer: BandsPaneRenderer;
  constructor(p: BandsPrimitive) { this._renderer = new BandsPaneRenderer(p); }
  renderer(): IPrimitivePaneRenderer { return this._renderer; }
}

/** Draws one indicator's reference levels, and the shaded region between them when the catalogue
 *  defines one. Holds no state of its own beyond what it was given. */
export class BandsPrimitive implements ISeriesPrimitiveBase<SeriesAttachedParameter<Time, SeriesType>> {
  chart: IChartApi | null = null;
  series: ISeriesApi<SeriesType, Time> | null = null;
  bands: ReferenceBand[] = [];
  fill: BandFill | null = null;
  lineColour = "rgba(140,140,140,0.55)";
  fillColour = "rgba(140,140,140,0.06)";

  private readonly _paneView: BandsPaneView;
  private _requestUpdate: (() => void) | null = null;

  constructor() { this._paneView = new BandsPaneView(this); }

  attached(param: SeriesAttachedParameter<Time, SeriesType>): void {
    this.chart = param.chart;
    this.series = param.series;
    this._requestUpdate = param.requestUpdate;
  }
  detached(): void { this.chart = null; this.series = null; this._requestUpdate = null; }

  updateAllViews(): void { /* the renderer reads live refs on each draw */ }
  paneViews(): readonly IPrimitivePaneView[] { return [this._paneView]; }

  set(bands: ReferenceBand[], fill: BandFill | null, lineColour: string, fillColour: string): void {
    this.bands = bands;
    this.fill = fill;
    this.lineColour = lineColour;
    this.fillColour = fillColour;
    this._requestUpdate?.();
  }
}
