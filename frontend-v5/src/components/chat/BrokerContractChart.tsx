/**
 * broker_contract_chart — the answer card of a question asked from a futures
 * or options position on the Trader desk. It charts the CONTRACT's own price
 * (an option's premium, a future's price), not the underlying share's.
 *
 * The widget carries only a reference: which broker account, which contract,
 * and the position's quantity and average as its row gave them
 * (backend/routes/chat.py :: _position_chart_widget). The card reads the
 * candles and the latest quote itself, from
 *   GET /api/broker/accounts/{account_id}/contract-chart
 * so it is a live read on a fresh answer and on one reloaded from history.
 * Nothing polls: it reads when it opens, when the candle size is changed, and
 * on "Read again".
 *
 * Read-only: nothing here can place, change or close a position.
 *
 * Every figure says where it is from. The average and the quantity are the
 * position's own and are on the card whatever the read does. The broker often
 * returns candles with no quote; the last price is then the last candle's
 * close and says so. The P&L is worked out here and is not the broker's own
 * figure. A field the broker did not send says "Not sent", never 0.
 *
 * Styling follows the other chat cards (Tailwind token classes), which hold in
 * the Copilot app and on the older chat page alike. The stock and broker icons
 * are the Copilot app's own.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  createChart, CandlestickSeries, HistogramSeries, CrosshairMode, LineStyle,
  type AutoscaleInfo, type UTCTimestamp,
} from "lightweight-charts";
import { BrokerIcon, StockIcon } from "@/pages/CopilotApp/components/EntityIcon";
import { fmtINR, fmtNum, humaniseTag } from "@/pages/CopilotApp/components/ui";
import { viewPath } from "@/pages/CopilotApp/lib/views";
import {
  CHART_INTERVALS, ContractChartError, fmtStamp, readContractWidget, useContractChart,
  type ChartFailure, type ChartInterval, type ContractCandle, type ContractChart, type ContractPosition,
} from "@/pages/CopilotApp/screens/desk/broker";
import { fmtDay, fmtPrice, fmtQty } from "@/pages/CopilotApp/screens/trading/parts";
import { useAppTheme, withAlpha } from "@/pages/Research/charts/theme";

const CHART_HEIGHT = 280;
/** India is UTC+05:30 all year. */
const IST_OFFSET_S = 5.5 * 3600;
const NOT_SENT = "Not sent";

const VIEW_WORDS: Record<ChartInterval, string> = { "5m": "5 min", "30m": "30 min" };

/** "COLPAL 1,760 put · 27 Oct 2026" · "COLPAL future · 27 Oct 2026" */
function contractWords(c: ContractPosition): string {
  const what = c.kind === "FUT"
    ? "future"
    : `${c.strike != null ? `${fmtNum(c.strike, Number.isInteger(c.strike) ? 0 : 2)} ` : ""}${c.kind === "CE" ? "call" : "put"}`;
  return `${c.symbol} ${what} · ${fmtDay(c.expiry)}`;
}

/** What the position's average is called: an option's is the premium paid or received. */
const averageLabel = (option: boolean) => (option ? "Average premium" : "Your average");

const joinWords = (parts: string[]) => (parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0] ?? "");

// ── the chart ───────────────────────────────────────────────────────────────

/** The app's colour tokens (index.css) as a canvas needs them. The same tokens colour the figures above the chart. */
const CHART_TOKENS = {
  surface: "rgb(var(--surface-1))",
  text: "rgb(var(--ink-3))",
  grid: "rgb(var(--line) / 0.06)",
  edge: "rgb(var(--line) / 0.10)",
  up: "rgb(var(--pos))",
  down: "rgb(var(--neg))",
  average: "rgb(var(--warm))",
} as const;
type ChartColours = Record<keyof typeof CHART_TOKENS, string>;

/** A canvas cannot read var(...); each token is read back through a hidden probe's computed `color`. */
function resolveColours(host: HTMLElement): ChartColours {
  const probe = document.createElement("span");
  probe.style.position = "absolute";
  probe.style.visibility = "hidden";
  probe.style.pointerEvents = "none";
  host.appendChild(probe);
  const out = {} as ChartColours;
  for (const key of Object.keys(CHART_TOKENS) as Array<keyof typeof CHART_TOKENS>) {
    probe.style.color = CHART_TOKENS[key];
    out[key] = getComputedStyle(probe).color;
  }
  host.removeChild(probe);
  return out;
}

interface Plotted {
  bars: Array<{ time: UTCTimestamp; open: number; high: number; low: number; close: number }>;
  volumes: Array<{ time: UTCTimestamp; value: number; up: boolean }>;
}

/**
 * Candles as the chart library takes them (they arrive oldest first, each
 * later than the one before). It draws time in UTC, so each bar is moved by
 * India's offset: the axis then reads India time for every viewer.
 */
function plot(candles: ContractCandle[]): Plotted {
  const out: Plotted = { bars: [], volumes: [] };
  for (const c of candles) {
    const time = (Math.floor(c.at / 1000) + IST_OFFSET_S) as UTCTimestamp;
    out.bars.push({ time, open: c.open, high: c.high, low: c.low, close: c.close });
    // 0 is a bar with no trades and is drawn as such; a bar with no volume field is left off the histogram.
    if (c.volume != null) out.volumes.push({ time, value: c.volume, up: c.close >= c.open });
  }
  return out;
}

/** The clock time the axis shows for a bar ("2026-10-13T15:25"), from the very number the chart is given. */
const axisClock = (time: UTCTimestamp | undefined) => (time == null ? "" : new Date(time * 1000).toISOString().slice(0, 16));

function Candles({ candles, skipped, interval, average, option, title }: {
  candles: ContractCandle[];
  /** Bars the broker sent out of time order, which are not among `candles`. */
  skipped: number;
  interval: ChartInterval;
  /** The position's average, drawn as a line; null draws none. */
  average: number | null;
  /** An option's average is a premium, and is called one. */
  option: boolean;
  title: string;
}) {
  const host = useRef<HTMLDivElement | null>(null);
  // Redraw in the new colours when the app's theme is switched.
  const { theme } = useAppTheme();
  const plotted = useMemo(() => plot(candles), [candles]);
  const { bars, volumes } = plotted;

  useEffect(() => {
    const el = host.current;
    if (!el || plotted.bars.length === 0) return;
    const colours = resolveColours(el);

    const chart = createChart(el, {
      height: CHART_HEIGHT,
      layout: { background: { color: colours.surface }, textColor: colours.text, attributionLogo: false },
      grid: { vertLines: { color: colours.grid }, horzLines: { color: colours.grid } },
      rightPriceScale: { borderColor: colours.edge },
      timeScale: { borderColor: colours.edge, timeVisible: true, secondsVisible: false, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { mode: CrosshairMode.Normal },
      // The card sits in a scrolling thread: the wheel and an up-down swipe scroll the page, never the chart.
      // Dragging sideways pans it; a pinch, or a drag on the time axis, zooms it.
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: true },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: colours.up, downColor: colours.down,
      wickUpColor: colours.up, wickDownColor: colours.down,
      borderVisible: false,
      priceLineVisible: false,
      // Keep the average in view: a price line alone does not widen the scale.
      autoscaleInfoProvider: (base: () => AutoscaleInfo | null) => {
        const info = base();
        if (!info || !info.priceRange || average == null) return info;
        return { ...info, priceRange: { minValue: Math.min(info.priceRange.minValue, average), maxValue: Math.max(info.priceRange.maxValue, average) } };
      },
    });
    series.setData(plotted.bars);

    if (average != null) {
      series.createPriceLine({ price: average, color: colours.average, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: averageLabel(option) });
    }

    if (plotted.volumes.length > 0) {
      // Volume shares the pane, in its bottom fifth, on a scale of its own.
      const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "", lastValueVisible: false, priceLineVisible: false });
      volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      series.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.24 } });
      volume.setData(plotted.volumes.map((v) => ({ time: v.time, value: v.value, color: withAlpha(v.up ? colours.up : colours.down, 0.45) })));
    }

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
    ro.observe(el);
    chart.applyOptions({ width: el.clientWidth });

    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [plotted, average, option, theme]);

  const count = `${fmtNum(bars.length)} ${bars.length === 1 ? "candle" : "candles"} · ${VIEW_WORDS[interval]} each`;
  const span = candles.length ? `${fmtStamp(candles[0].at)} to ${fmtStamp(candles[candles.length - 1].at)}` : "";
  const averageNote = average != null ? ` Dashed line: your average${option ? " premium" : ""} ${fmtPrice(average)}.` : "";

  return (
    <figure className="m-0 min-w-0">
      <div
        ref={host}
        data-testid="contract-chart-canvas"
        data-interval={interval}
        data-bars={bars.length}
        data-first-bar={axisClock(bars[0]?.time)}
        data-last-bar={axisClock(bars[bars.length - 1]?.time)}
        data-average={average ?? ""}
        data-volume={volumes.length > 0 ? "1" : "0"}
        role="img"
        aria-label={`Candlestick chart of ${title}: ${count}, ${span}, India time.${averageNote}`}
        className="w-full min-w-0 overflow-hidden rounded-lg"
        style={{ height: CHART_HEIGHT }}
      />
      <figcaption data-testid="contract-chart-caption" className="mt-2 text-[11.5px] leading-relaxed text-ink-3">
        {count} · {span} · India time (IST).{averageNote}
        {volumes.length > 0 ? " Bars along the bottom: volume." : ""}
        {skipped > 0 ? ` ${fmtNum(skipped)} ${skipped === 1 ? "candle was" : "candles were"} out of time order and ${skipped === 1 ? "is" : "are"} not drawn.` : ""}
      </figcaption>
    </figure>
  );
}

// ── figures ─────────────────────────────────────────────────────────────────

type Tone = "pos" | "neg" | "quiet";
const TONE_CLASS: Record<Tone, string> = { pos: "text-pos", neg: "text-neg", quiet: "text-ink-3" };

function Figure({ id, label, value, note, tone }: { id: string; label: string; value: ReactNode; note?: ReactNode; tone?: Tone }) {
  return (
    <div className="min-w-0 rounded-lg border border-hairline bg-surface-2/60 px-3.5 py-3">
      <div data-testid={`${id}-label`} className="text-[12px] leading-tight text-ink-3">{label}</div>
      <div data-testid={id} className={`mt-1 break-words font-display text-[20px] leading-tight tracking-tightish ${tone ? TONE_CLASS[tone] : "text-ink"}`}>{value}</div>
      {note != null && note !== "" && <div data-testid={`${id}-note`} className="mt-1 text-[11.5px] leading-snug text-ink-3">{note}</div>}
    </div>
  );
}

/** A price, or "Not sent" for a field the broker left out. */
function Price({ id, label, value, note }: { id: string; label: string; value: number | null; note?: ReactNode }) {
  return <Figure id={id} label={label} value={value != null ? fmtPrice(value) : NOT_SENT} tone={value != null ? undefined : "quiet"} note={note} />;
}

const lastCandle = (chart: ContractChart): ContractCandle | null => (chart.candles.length ? chart.candles[chart.candles.length - 1] : null);

/** The last price and the P&L worked out from it. */
function PriceFigures({ contract, chart, brokerSubject }: { contract: ContractPosition; chart: ContractChart; brokerSubject: string }) {
  const quote = chart.quote;
  const bar = lastCandle(chart);

  // The broker's last traded price when it sent one; else the close of the last candle, said as such.
  const fromQuote = quote?.last != null;
  const last = fromQuote ? quote.last : bar ? bar.close : null;
  const lastNote = fromQuote
    ? `${brokerSubject}’s last traded price · ${quote.lastTradedAt != null ? `traded ${fmtStamp(quote.lastTradedAt)}` : "trade time not sent"}`
    : bar
      ? `Close of the last candle (starts ${fmtStamp(bar.at)}). ${brokerSubject} sent no ${quote ? "last traded price" : "quote"} with this read.`
      : `${brokerSubject} sent no last price and no candles.`;

  const pnl = last != null && contract.avg != null && contract.qty != null ? (last - contract.avg) * contract.qty : null;
  const missing = [last == null ? "a last price" : "", contract.avg == null ? "your average" : "", contract.qty == null ? "the quantity" : ""].filter(Boolean);
  const pnlNote = pnl != null
    ? `(${fromQuote ? "last price" : "last candle’s close"} − average) × quantity. Worked out here, not the broker’s own P&L figure.`
    : `It needs ${joinWords(missing)}, which ${missing.length > 1 ? "were" : "was"} not sent.`;

  return (
    <>
      <Price id="contract-chart-last" label="Last price" value={last} note={lastNote} />
      <Figure
        id="contract-chart-pnl"
        label="P&L, worked out here"
        value={pnl != null ? fmtINR(pnl, { signed: true }) : "Not worked out"}
        tone={pnl == null ? "quiet" : pnl > 0 ? "pos" : pnl < 0 ? "neg" : undefined}
        note={pnlNote}
      />
    </>
  );
}

/** What the quote says about the day, and the open interest on the last candle. Each says "Not sent" when the broker left it out. */
function MarketFigures({ chart }: { chart: ContractChart }) {
  const quote = chart.quote;
  const bar = lastCandle(chart);
  const range = quote && (quote.high != null || quote.low != null)
    ? `${quote.high != null ? fmtPrice(quote.high) : NOT_SENT} / ${quote.low != null ? fmtPrice(quote.low) : NOT_SENT}`
    : null;

  return (
    <>
      <Figure id="contract-chart-range" label="Day high / low" value={range ?? NOT_SENT} tone={range ? undefined : "quiet"} />
      <Price id="contract-chart-prev-close" label="Previous close" value={quote?.previousClose ?? null} />
      <Price id="contract-chart-spot" label="Underlying price" value={quote?.spot ?? null} />
      <Figure
        id="contract-chart-oi"
        label="Open interest"
        value={bar?.openInterest != null ? fmtQty(bar.openInterest) : NOT_SENT}
        tone={bar?.openInterest != null ? undefined : "quiet"}
        // One bar's level. Open interest is never added up across bars.
        note={bar?.openInterest != null ? `On the last candle (starts ${fmtStamp(bar.at)}).` : undefined}
      />
    </>
  );
}

// ── states ──────────────────────────────────────────────────────────────────

interface Problem {
  testId: string;
  text: string;
  /** A read that failed is worth another try; a refusal is not. */
  retry?: boolean;
  /** The way to Broker connections, where the user signs in at the broker again. */
  signIn?: boolean;
  tone: "danger" | "amber" | "plain";
}

function problemOf(kind: ChartFailure, brokerName: string | null): Problem {
  const account = brokerName ?? "broker";
  switch (kind) {
    case "session_ended":
      return { testId: "contract-chart-session-ended", tone: "amber", signIn: true, text: `Your ${account} session has ended. Sign in again from Broker connections, then read this chart again.` };
    case "not_supported":
      return { testId: "contract-chart-not-supported", tone: "plain", text: `A contract’s own chart cannot be read from this kind of ${account} account.` };
    case "not_enabled":
      return { testId: "contract-chart-not-enabled", tone: "plain", text: "Reading from a broker is not switched on for this account." };
    case "no_account":
      return { testId: "contract-chart-no-account", tone: "plain", text: `This ${account} account is not among your connected broker accounts, so its contract cannot be read.` };
    case "wrong_shape":
      return { testId: "contract-chart-wrong-shape", tone: "danger", retry: true, text: "The chart came back in a form this card cannot read, so nothing is drawn." };
    case "broker_failed":
      return { testId: "contract-chart-failed", tone: "danger", retry: true, text: `${brokerName ?? "Your broker"} did not return this contract’s chart. Try again in a little while.` };
    case "unreachable":
      return { testId: "contract-chart-failed", tone: "danger", retry: true, text: "The request for this chart got no answer. Check your connection and try again." };
    default:
      return { testId: "contract-chart-failed", tone: "danger", retry: true, text: "This contract’s chart could not be read. Try again in a little while." };
  }
}

const PROBLEM_TINT: Record<Problem["tone"], { borderColor: string; background: string } | undefined> = {
  danger: { borderColor: "var(--danger-line)", background: "var(--danger-soft)" },
  amber: { borderColor: "var(--amber-line)", background: "var(--amber-soft)" },
  plain: undefined,
};

const TEXT_ACTION = "shrink-0 text-[13px] text-ink underline underline-offset-2 hover:no-underline";

function ProblemBlock({ problem, onRetry }: { problem: Problem; onRetry: () => void }) {
  return (
    <div
      data-testid={problem.testId}
      role={problem.tone === "plain" ? undefined : "alert"}
      className={`flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border px-4 py-3 text-[13px] leading-relaxed text-ink-2 ${problem.tone === "plain" ? "border-hairline bg-surface-2/60" : ""}`}
      style={PROBLEM_TINT[problem.tone]}
    >
      <span className="min-w-[200px] flex-1">{problem.text}</span>
      {problem.signIn && <Link to={viewPath("page/brokers")} className={TEXT_ACTION}>Broker connections ›</Link>}
      {problem.retry && <button type="button" data-testid="contract-chart-retry" onClick={onRetry} className={TEXT_ACTION}>Try again ›</button>}
    </div>
  );
}

// ── the card ────────────────────────────────────────────────────────────────

const VIEW_ON = "shrink-0 rounded-full border border-ink-3 bg-surface-2 px-3 py-1.5 text-[12.5px] font-medium text-ink";
const VIEW_OFF = "shrink-0 rounded-full border border-hairline bg-surface-1 px-3 py-1.5 text-[12.5px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink";

function ContractCard({ contract }: { contract: ContractPosition }) {
  const [view, setView] = useState<ChartInterval>("5m");
  const q = useContractChart(contract, view);

  const option = contract.kind !== "FUT";
  const title = contractWords(contract);
  const brokerName = contract.brokerName ?? (contract.broker ? humaniseTag(contract.broker) : null);
  /** Mid-sentence ("read from …") and at the start of one ("… sent no quote"). */
  const brokerObject = brokerName ?? "your broker";
  const brokerSubject = brokerName ?? "Your broker";

  // A read under way with nothing to show yet, including a new try after a failure.
  const reading = q.isPending || (q.isError && q.isFetching);
  const failure: ChartFailure | null = !reading && q.isError ? (q.error instanceof ContractChartError ? q.error.kind : "read_failed") : null;
  // While another view is being read this is still the previous view's chart, and the card says so.
  const chart = !reading && !failure ? q.data : undefined;
  const qtyDigits = contract.qty != null && Number.isInteger(contract.qty) ? 0 : 2;

  return (
    <section
      data-testid="contract-chart-card"
      data-instrument={contract.kind}
      aria-label={`${title}, read from ${brokerObject}`}
      className="mt-1 flex w-full min-w-0 flex-col gap-4 rounded-xl border border-hairline bg-surface-1 p-4 shadow-card sm:p-6"
    >
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="flex min-w-0 items-start gap-3">
          <StockIcon symbol={contract.symbol} size={32} />
          <div className="min-w-0">
            <h3 data-testid="contract-chart-title" className="m-0 break-words font-display text-[19px] leading-snug tracking-tightish text-ink">{title}</h3>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-ink-3">
              <span data-testid="contract-chart-broker" className="inline-flex items-center gap-1.5 text-ink-2">
                {brokerName && <BrokerIcon name={brokerName} size={18} />}
                {brokerSubject}
              </span>
              <span aria-hidden>·</span>
              <span data-testid="contract-chart-asof">{chart ? `Read ${fmtStamp(chart.asOf)}` : reading ? "Reading…" : "Not read"}</span>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Candle size" className="flex gap-2">
            {CHART_INTERVALS.map((iv) => (
              <button key={iv} type="button" data-testid={`contract-chart-interval-${iv}`} aria-pressed={iv === view} onClick={() => setView(iv)} className={iv === view ? VIEW_ON : VIEW_OFF}>
                {VIEW_WORDS[iv]}
              </button>
            ))}
          </div>
          <button
            type="button"
            data-testid="contract-chart-refresh"
            onClick={() => { void q.refetch(); }}
            disabled={q.isFetching}
            className="shrink-0 px-1 py-1.5 text-[12.5px] text-ink hover:underline disabled:opacity-60 disabled:hover:no-underline"
          >
            {q.isFetching ? "Reading…" : "Read again ›"}
          </button>
        </div>
      </header>

      <div data-testid="contract-chart-figures" className="grid gap-2.5" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(118px, 1fr))" }}>
        {chart && <PriceFigures contract={contract} chart={chart} brokerSubject={brokerSubject} />}
        <Price id="contract-chart-average" label={averageLabel(option)} value={contract.avg} />
        <Figure
          id="contract-chart-qty"
          label="Quantity"
          value={contract.qty == null ? NOT_SENT : contract.qty < 0 ? `Short ${fmtNum(-contract.qty, qtyDigits)}` : fmtNum(contract.qty, qtyDigits)}
          tone={contract.qty == null ? "quiet" : undefined}
        />
        {chart && <MarketFigures chart={chart} />}
      </div>

      {chart && q.isPlaceholderData && (
        <div data-testid="contract-chart-reading" role="status" className="text-[12.5px] leading-relaxed text-ink-3">
          Reading the {VIEW_WORDS[view]} view from {brokerObject}… What is shown is the {VIEW_WORDS[chart.interval]} view, read {fmtStamp(chart.asOf)}.
        </div>
      )}

      {reading && (
        <div data-testid="contract-chart-loading" role="status" className="flex items-center justify-center rounded-lg border border-hairline bg-surface-2/60 px-4 text-center text-[13px] text-ink-2" style={{ minHeight: CHART_HEIGHT }}>
          <span className="motion-safe:animate-pulse">Reading this contract’s price from {brokerObject}…</span>
        </div>
      )}
      {failure && <ProblemBlock problem={problemOf(failure, brokerName)} onRetry={() => { void q.refetch(); }} />}
      {chart && (chart.candles.length === 0 ? (
        <div data-testid="contract-chart-empty" className="rounded-lg border border-hairline bg-surface-2/60 px-4 py-3 text-[13px] leading-relaxed text-ink-2">
          {brokerSubject} returned no candles for the {VIEW_WORDS[chart.interval]} view of this contract, so there is no chart to draw. Try the other candle size, or read again later.
        </div>
      ) : (
        <Candles candles={chart.candles} skipped={chart.outOfOrder} interval={chart.interval} average={contract.avg} option={option} title={title} />
      ))}

      <p data-testid="contract-chart-source" className="m-0 text-[11.5px] leading-relaxed text-ink-3">
        Prices are this contract’s own, not the underlying’s, read from {brokerObject} when this card was opened or last refreshed. Nothing here updates by itself.
        {" "}Nivesh only reads from your broker: it cannot place, change or close a position.
      </p>
    </section>
  );
}

export function BrokerContractChart({ data }: { data: unknown }) {
  const contract = useMemo(() => readContractWidget(data), [data]);
  if (!contract) {
    return (
      <div data-testid="contract-chart-bad-reference" className="mt-1 w-full rounded-xl border border-hairline bg-surface-1 p-4 text-[13px] leading-relaxed text-ink-2">
        This card does not say which futures or options contract it is for, so no chart can be read.
      </div>
    );
  }
  return <ContractCard contract={contract} />;
}
