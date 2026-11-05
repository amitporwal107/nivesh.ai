/**
 * Market Desk › Market Intelligence — the news ticker (owner, 5 Nov 2026): a Bloomberg-style band over the event list with
 * today's results, tomorrow's results meetings, fresh orders, M&A and the day's other corporate actions, the largest deals,
 * FII / DII flows, SEBI circulars and sector moves. Data and rules: news-ticker-data.ts. Test cases:
 * test_reports/intel_news_ticker_TESTCASES.md (NT-*).
 *
 * The tape is two copies of the items on the app's seamless marquee (index.css `mkt-marquee`, moved by -50 %), at a speed
 * that scales with its length. It pauses on hover, while a key-board focus is inside it, and on the Pause button. With
 * reduced motion it does not move: one copy, scrolled sideways. The second copy is hidden from assistive technology and
 * from the tab order.
 *
 * A click opens the item where it lives: a filing, deal, flow, circular or sector move in the event list below
 * (?in_chip=&in_ev=, IntelTab's own link), a company's results in the Events calendar (?ev_open=&ev_uni=, which the
 * calendar consumes once).
 *
 * Wording: facts and the exchange's own subject lines; never buy / sell / target / stop loss / recommend / pick.
 */
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useCopilotShell } from "../../../../lib/shell-context";
import type { Universe } from "../../events-data";
import { useNow } from "../../overview-data";
import { LIMIT_GROUPED, LIMIT_SINGLE, eventWhen } from "../../intel-data";
import { FOCUS, focusCount, focusItems, useNewsTicker, type TickerFigure, type TickerFocus, type TickerItem, type TickerLink } from "./news-ticker-data";

/** Tape speed, pixels a second. */
const SPEED = 70;
const MIN_SECONDS = 20;
const UNIVERSES: Array<[Universe, string]> = [["fno", "F&O"], ["n50", "Nifty 50"], ["all", "All NSE"]];
const MINUS = "−";
const EDGE_FADE = "linear-gradient(to right, transparent, #000 20px, #000 calc(100% - 28px), transparent)";

const mono: CSSProperties = { fontFamily: "var(--mono)" };
const line = "1px solid var(--cp-line)";
const plainBtn: CSSProperties = { padding: 0, border: 0, background: "none", font: "inherit", color: "inherit", cursor: "pointer", textAlign: "left" };

function usePrefersReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduce, setReduce] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(query).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return undefined;
    const on = () => setReduce(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduce;
}

const pct = (n: number) => `${n > 0 ? "▲" : n < 0 ? "▼" : ""}${Math.abs(n).toFixed(1)}%`;
const toneOf = (n: number | null) => (n == null || n === 0 ? "var(--cp-ink-2)" : n > 0 ? "var(--mint)" : "var(--cp-danger)");

function Figure({ f }: { f: TickerFigure }) {
  return (
    <span data-testid={`md-ticker-fig-${f.key}`} style={{ display: "inline-flex", alignItems: "baseline", gap: 5 }}>
      <span style={{ color: "var(--cp-ink-3)" }}>{f.label}</span>
      <span className="cp-num" style={{ color: f.kind === "sign" ? toneOf(f.change) : "var(--cp-ink)" }}>{f.value.replace(/^-/, MINUS)}</span>
      {f.kind === "yoy" && f.change != null && (
        <span className="cp-num" style={{ color: toneOf(f.change) }}>{pct(f.change)} YoY</span>
      )}
      {f.note && <span style={{ color: "var(--cp-ink-3)" }}>{f.note}</span>}
    </span>
  );
}

/** What a screen reader hears for an item (the band itself is a list of buttons). */
function speak(it: TickerItem): string {
  const figs = it.figures.map((f) => `${f.label} ${f.value}${f.kind === "yoy" && f.change != null ? ` ${f.change >= 0 ? "up" : "down"} ${Math.abs(f.change).toFixed(1)}% on the year` : ""}${f.note ? ` ${f.note}` : ""}`);
  return [it.label, it.symbol, it.text, ...figs, it.when].filter(Boolean).join(", ");
}

function Item({ it, copy, onOpen, onMore }: { it: TickerItem; copy: number; onOpen: (l: TickerLink) => void; onMore: () => void }) {
  const tab = copy === 0 ? undefined : -1;
  const tid = (s: string) => (copy === 0 ? s : undefined);
  const tag = (
    <span style={{ ...mono, flex: "none", fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase", color: it.color, border: `1px solid ${it.color}`, borderRadius: 4, padding: "2px 6px" }}>
      {it.label}
    </span>
  );
  const body: ReactNode = (
    <>
      {it.symbol && <span className="cp-num" style={{ color: "var(--cp-ink)", fontWeight: 600 }}>{it.symbol}</span>}
      <span style={{ color: "var(--cp-ink-2)" }}>{it.text}</span>
      {it.figures.map((f) => <Figure key={f.key} f={f} />)}
      {it.when && <span className="cp-num" style={{ color: "var(--cp-ink-4)", fontSize: 11 }}>{it.when}</span>}
    </>
  );
  const wrap: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 8, padding: "0 18px", borderRight: line, whiteSpace: "nowrap", fontSize: 12.5, lineHeight: 1 };
  if (it.group) {
    const g = it.group;
    return (
      <li data-testid={tid(`md-ticker-item-${it.key}`)} data-tag={it.tag} style={wrap}>
        {tag}
        <span style={{ color: "var(--cp-ink-2)" }}>{it.text}</span>
        {g.symbols.map((s, i) => (
          <span key={s.symbol} style={{ display: "inline-flex", gap: 6 }}>
            {i > 0 && <span aria-hidden style={{ color: "var(--cp-ink-4)" }}>·</span>}
            <button type="button" tabIndex={tab} data-testid={tid(`md-ticker-sym-${it.tag}-${s.symbol}`)} aria-label={`${it.label}: ${s.symbol}, open its results`} onClick={() => onOpen(s.link)} className="cp-num" style={{ ...plainBtn, color: "var(--cp-ink)" }}>
              {s.symbol}
            </button>
          </span>
        ))}
        {g.more > 0 && (
          <button type="button" tabIndex={tab} data-testid={tid(`md-ticker-more-${it.tag}`)} onClick={onMore} style={{ ...plainBtn, color: "var(--mint)" }}>
            +{g.more} more ›
          </button>
        )}
      </li>
    );
  }
  return (
    <li data-testid={tid(`md-ticker-item-${it.key}`)} data-tag={it.tag} style={wrap}>
      {it.link ? (
        <button type="button" tabIndex={tab} aria-label={speak(it)} onClick={() => onOpen(it.link as TickerLink)} style={{ ...plainBtn, display: "inline-flex", alignItems: "center", gap: 8 }}>
          {tag}{body}
        </button>
      ) : (
        <>{tag}{body}</>
      )}
    </li>
  );
}

export default function NewsTicker() {
  const { mobile } = useCopilotShell();
  const now = useNow(60_000);
  const [universe, setUniverse] = useState<Universe>("fno");
  const [focus, setFocus] = useState<TickerFocus>("all");
  const t = useNewsTicker(universe, now);
  const shown = focusItems(t.items, focus);
  const reduce = usePrefersReducedMotion();
  const [paused, setPaused] = useState(false);
  const [focused, setFocused] = useState(false);
  const tapeRef = useRef<HTMLUListElement>(null);
  const [seconds, setSeconds] = useState(90);
  const [, setParams] = useSearchParams();

  useLayoutEffect(() => {
    const el = tapeRef.current;
    if (!el) return undefined;
    const measure = () => setSeconds(Math.max(MIN_SECONDS, Math.round(el.scrollWidth / SPEED)));
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [shown.length, t.status, focus]);

  const scrollToPanel = (id: string) =>
    window.requestAnimationFrame(() => document.querySelector(`[data-testid="desk-panel-${id}"]`)?.scrollIntoView({ block: "start" }));
  const open = (link: TickerLink) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (link.kind === "intel") {
        p.set("in_chip", link.chip);
        p.set("in_ev", link.event);
      } else {
        p.set("ev_open", link.event);
        p.set("ev_uni", link.universe);
      }
      return p;
    }, { replace: true });
    scrollToPanel(link.kind === "intel" ? "intel" : "events");
  };
  const toEvents = () => scrollToPanel("events");

  const stopped = paused || focused;
  const asOf = t.latestAt ? eventWhen(t.latestAt) : null;
  const label = (
    <div data-testid="md-ticker-label" className="flex items-center" style={{ flex: "none", gap: 8, padding: mobile ? "0 10px" : "0 14px", borderRight: line, background: "var(--bg-2, var(--bg-1))" }}>
      <span aria-hidden style={{ width: 7, height: 7, borderRadius: 999, background: t.status === "ready" ? "var(--amber)" : "var(--cp-ink-4)" }} />
      <span style={{ ...mono, fontSize: 10, letterSpacing: "0.16em", color: "var(--amber)" }}>{mobile ? "WIRE" : "MARKET WIRE"}</span>
      {!mobile && asOf && <span data-testid="md-ticker-asof" className="cp-num" style={{ fontSize: 10.5, color: "var(--cp-ink-3)" }} title={`Newest filing on the tape: ${asOf.full}`}>{asOf.short}</span>}
    </div>
  );

  let tape: ReactNode;
  if (t.status === "loading") {
    tape = <span data-testid="md-ticker-loading" style={{ padding: "0 14px", fontSize: 12.5, color: "var(--cp-ink-3)" }}>Loading results, filings and flows…</span>;
  } else if (t.status === "error") {
    tape = (
      <span data-testid="md-ticker-error" className="flex items-center" style={{ gap: 10, padding: "0 14px", fontSize: 12.5, color: "var(--cp-ink-2)" }}>
        The ticker’s sources didn’t load.
        <button type="button" data-testid="md-ticker-retry" onClick={t.refetch} style={{ ...plainBtn, color: "var(--mint)" }}>Retry</button>
      </span>
    );
  } else if (t.items.length === 0) {
    tape = <span data-testid="md-ticker-empty" style={{ padding: "0 14px", fontSize: 12.5, color: "var(--cp-ink-3)" }}>Nothing on the wire since {t.window.label}: no results today or tomorrow and no new filings{t.pending.length ? " so far" : ""}.</span>;
  } else if (shown.length === 0) {
    tape = <span data-testid="md-ticker-empty-focus" style={{ padding: "0 14px", fontSize: 12.5, color: "var(--cp-ink-3)" }}>Nothing of this kind since {t.window.label}{t.pending.length ? " so far" : ""}.</span>;
  } else {
    const copies = reduce ? [0] : [0, 1];
    tape = (
      <div
        data-testid="md-ticker-track"
        data-paused={stopped ? "true" : "false"}
        className={reduce ? "flex w-max items-stretch" : "mkt-marquee flex w-max items-stretch"}
        // Paused inline only: a "running" here would override index.css's hover pause.
        style={reduce ? undefined : { animationDuration: `${seconds}s`, ...(stopped ? { animationPlayState: "paused" } : {}) }}
      >
        {copies.map((c) => (
          <ul
            key={c}
            ref={c === 0 ? tapeRef : undefined}
            data-testid={c === 0 ? "md-ticker-tape" : "md-ticker-tape-copy"}
            aria-hidden={c === 0 ? undefined : true}
            aria-label={c === 0 ? "Latest items" : undefined}
            className="m-0 flex items-stretch"
            style={{ listStyle: "none", padding: 0, flex: "none" }}
          >
            {shown.map((it) => <Item key={it.key} it={it} copy={c} onOpen={open} onMore={toEvents} />)}
          </ul>
        ))}
      </div>
    );
  }

  const seg = (on: boolean): CSSProperties => ({
    ...plainBtn, ...mono, fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase", padding: "4px 7px", borderRadius: 5, whiteSpace: "nowrap",
    color: on ? "var(--cp-ink)" : "var(--cp-ink-3)", background: on ? "var(--bg-3, var(--bg-2))" : "transparent",
  });
  const segBox: CSSProperties = { gap: 2, border: "1px solid var(--line-2)", borderRadius: 7, padding: 2 };
  const controls = (
    <div className="flex flex-wrap items-center" style={{ gap: 8, minWidth: 0 }}>
      {!reduce && shown.length > 0 && (
        <button
          type="button"
          data-testid="md-ticker-pause"
          aria-pressed={paused}
          aria-label={paused ? "Play the ticker" : "Pause the ticker"}
          onClick={() => setPaused((x) => !x)}
          style={{ ...plainBtn, ...mono, fontSize: 10, letterSpacing: "0.12em", color: "var(--cp-ink-2)", border: "1px solid var(--line-2)", borderRadius: 6, padding: "5px 8px" }}
        >
          {paused ? "▶ PLAY" : "❚❚ PAUSE"}
        </button>
      )}
      <div role="group" aria-label="Results from" className="flex" style={segBox}>
        {UNIVERSES.map(([u, name]) => (
          <button key={u} type="button" data-testid={`md-ticker-uni-${u}`} aria-pressed={universe === u} onClick={() => setUniverse(u)} style={seg(universe === u)}>
            {name}
          </button>
        ))}
      </div>
      <div role="group" aria-label="Show on the tape" className="flex flex-wrap" style={segBox}>
        {FOCUS.map((f) => {
          const n = f.key === "all" ? null : focusCount(t.items, f.key);
          return (
            <button key={f.key} type="button" data-testid={`md-ticker-focus-${f.key}`} aria-pressed={focus === f.key} onClick={() => setFocus(f.key)} style={seg(focus === f.key)}>
              {f.label}{n != null && t.status === "ready" ? <span className="cp-num" style={{ marginLeft: 5, color: "var(--cp-ink-4)" }}>{n}</span> : null}
            </button>
          );
        })}
      </div>
    </div>
  );

  const notLoaded = t.failed.length > 0 && t.status !== "error";
  return (
    <section data-testid="md-ticker" aria-label="Market news ticker" className="cp-card flex min-w-0 flex-col" style={{ padding: 0, overflow: "hidden", borderRadius: 12 }}>
      <div className="flex min-w-0 items-stretch" style={{ height: 44 }}>
        {label}
        <div
          data-testid="md-ticker-view"
          className="mkt-ticker-view relative flex min-w-0 flex-1 items-center"
          style={{
            overflowX: reduce ? "auto" : "hidden", overflowY: "hidden",
            // the tape fades in and out at the edges while it moves
            ...(reduce ? {} : { maskImage: EDGE_FADE, WebkitMaskImage: EDGE_FADE }),
          }}
          onFocus={() => setFocused(true)}
          onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false); }}
        >
          {tape}
        </div>
      </div>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "6px 14px", padding: "7px 14px", borderTop: line, fontSize: 11, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>
        {controls}
        <span data-testid="md-ticker-note" style={{ minWidth: 0, flex: "1 1 300px" }}>
          Results declared since {t.window.label} vs the same quarter last year (figures load about 20:30 IST on the filing day),
          today’s and tomorrow’s meetings · NSE / BSE filings since {t.window.label} · the latest deal day · FII / DII (provisional)
          · SEBI · sector moves of 1% or more. Everything shows the newest few of each kind; choose a kind to see all of those.
          Hover or focus pauses the tape; select an item to open it below.
        </span>
        {t.reach.length > 0 && (
          <span data-testid="md-ticker-reach" style={{ minWidth: 0, flex: "1 1 100%", color: "var(--cp-ink-3)" }}>
            Each kind reads the newest {LIMIT_GROUPED} filings ({LIMIT_SINGLE} for orders), so these start after {t.window.label}:{" "}
            {t.reach.map((r) => `${r.label} from ${eventWhen(r.since).full.replace(/^(\d+ \w+) \d{4},/, "$1,")}`).join(" · ")}.
          </span>
        )}
        {notLoaded && (
          <span data-testid="md-ticker-partial" style={{ color: "var(--amber)" }}>
            Not loaded: {t.failed.join(", ")}.{" "}
            <button type="button" data-testid="md-ticker-partial-retry" onClick={t.refetch} style={{ ...plainBtn, color: "var(--mint)" }}>Retry</button>
          </span>
        )}
      </div>
    </section>
  );
}
