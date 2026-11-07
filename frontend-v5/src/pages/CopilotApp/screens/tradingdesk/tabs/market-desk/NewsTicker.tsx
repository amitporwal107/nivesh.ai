/**
 * Market Desk › Market Intelligence — "Market Update", a Bloomberg-style ticker band over the event list. Owner, 5 Nov 2026:
 * results today and awaited tomorrow, fresh orders, M&A and the other important items; 6 Nov: "a summary of the everything,
 * need not to display every thing". So each item is one kind: a count and a few names (results with their change on the
 * year). Data and rules: news-ticker-data.ts. Test cases: test_reports/intel_news_ticker_TESTCASES.md (NT-*).
 *
 * The tape is two copies of the items on the app's seamless marquee (index.css `mkt-marquee`, moved by -50 %), at a speed
 * that scales with its length. It pauses on hover, while a keyboard focus is inside it, and on the Pause button. With
 * reduced motion it does not move: one copy, scrolled sideways. The second copy is hidden from assistive technology and
 * from the tab order.
 *
 * A name opens its event where it lives: a filing, deal, flow, circular or sector move in the event list below
 * (?in_chip=&in_ev=, IntelTab's own link), a company's results in the Events calendar (?ev_open=&ev_uni=, which the calendar
 * consumes once). "+n more" opens the whole list: that chip in the event list, or the results board.
 *
 * Wording: facts and counts; never buy / sell / target / stop loss / recommend / pick.
 */
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { useSearchParams } from "react-router-dom";
import { useCopilotShell } from "../../../../lib/shell-context";
import type { Universe } from "../../events-data";
import { useNow } from "../../overview-data";
import { eventWhen } from "../../intel-data";
import { useNewsTicker, type TickerEntry, type TickerFigure, type TickerItem, type TickerLink, type Tone } from "./news-ticker-data";

/** Tape speed, pixels a second. */
const SPEED = 60;
const MIN_SECONDS = 25;
const UNIVERSES: Array<[Universe, string]> = [["fno", "F&O"], ["n50", "Nifty 50"], ["all", "All NSE"]];
const EDGE_FADE = "linear-gradient(to right, transparent, #000 20px, #000 calc(100% - 28px), transparent)";

const mono: CSSProperties = { fontFamily: "var(--mono)" };
const line = "1px solid var(--cp-line)";
const plainBtn: CSSProperties = { padding: 0, border: 0, background: "none", font: "inherit", color: "inherit", cursor: "pointer", textAlign: "left" };
const TONE: Record<Tone, string> = { up: "var(--mint)", down: "var(--cp-danger)", flat: "var(--cp-ink-2)", note: "var(--cp-ink-3)" };

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

function Figure({ f }: { f: TickerFigure }) {
  return (
    <span data-testid={`md-ticker-fig-${f.key}`} style={{ display: "inline-flex", alignItems: "baseline", gap: 4 }}>
      {f.label && <span style={{ color: "var(--cp-ink-3)" }}>{f.label}</span>}
      <span className="cp-num" style={{ color: TONE[f.tone] }}>{f.text}</span>
    </span>
  );
}

/** What a screen reader hears for one name. */
const speak = (it: TickerItem, en: TickerEntry) =>
  [it.label, en.text, ...en.figures.map((f) => [f.label, f.text.replace("▲", "up ").replace("▼", "down ")].filter(Boolean).join(" "))].filter(Boolean).join(", ");

function Item({ it, copy, onOpen }: { it: TickerItem; copy: number; onOpen: (l: TickerLink) => void }) {
  const tab = copy === 0 ? undefined : -1;
  const tid = (s: string) => (copy === 0 ? s : undefined);
  return (
    <li
      data-testid={tid(`md-ticker-item-${it.key}`)}
      data-tag={it.tag}
      style={{ display: "inline-flex", alignItems: "center", gap: 9, padding: "0 20px", borderRight: line, whiteSpace: "nowrap", fontSize: 12.5, lineHeight: 1 }}
    >
      <span style={{ ...mono, flex: "none", fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase", color: it.color, border: `1px solid ${it.color}`, borderRadius: 4, padding: "2px 6px" }}>
        {it.label}
      </span>
      <span data-testid={tid(`md-ticker-count-${it.key}`)} style={{ color: "var(--cp-ink-3)" }}>{it.count}</span>
      {it.entries.map((en, i) => (
        <span key={en.key} style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
          {i > 0 && <span aria-hidden style={{ color: "var(--cp-ink-4)" }}>·</span>}
          {en.link ? (
            <button
              type="button"
              tabIndex={tab}
              data-testid={tid(`md-ticker-entry-${it.key}-${en.key}`)}
              aria-label={speak(it, en)}
              onClick={() => onOpen(en.link as TickerLink)}
              style={{ ...plainBtn, display: "inline-flex", alignItems: "baseline", gap: 6 }}
            >
              {en.text && <span className="cp-num" style={{ color: "var(--cp-ink)", fontWeight: 600 }}>{en.text}</span>}
              {en.figures.map((f) => <Figure key={f.key} f={f} />)}
            </button>
          ) : (
            <span className="cp-num" style={{ color: "var(--cp-ink)" }}>{en.text}</span>
          )}
        </span>
      ))}
      {it.more > 0 && it.moreLink && (
        <button
          type="button"
          tabIndex={tab}
          data-testid={tid(`md-ticker-more-${it.key}`)}
          aria-label={`${it.label}: the other ${it.more}, in the full list below`}
          onClick={() => onOpen(it.moreLink as TickerLink)}
          style={{ ...plainBtn, color: "var(--mint)" }}
        >
          +{it.more.toLocaleString("en-IN")} more ›
        </button>
      )}
    </li>
  );
}

export default function NewsTicker() {
  const { mobile } = useCopilotShell();
  const now = useNow(60_000);
  const [universe, setUniverse] = useState<Universe>("fno");
  const t = useNewsTicker(universe, now);
  const reduce = usePrefersReducedMotion();
  const [paused, setPaused] = useState(false);
  const [focused, setFocused] = useState(false);
  const tapeRef = useRef<HTMLUListElement>(null);
  const [seconds, setSeconds] = useState(60);
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
  }, [t.items.length, t.status]);

  const scrollToPanel = (id: string) =>
    window.requestAnimationFrame(() => document.querySelector(`[data-testid="desk-panel-${id}"]`)?.scrollIntoView({ block: "start" }));
  const open = (link: TickerLink) => {
    if (link.kind === "board") {
      scrollToPanel("events");
      return;
    }
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (link.kind === "intel") {
        p.set("in_chip", link.chip);
        if (link.event) p.set("in_ev", link.event);
        else p.delete("in_ev");
      } else {
        p.set("ev_open", link.event);
        p.set("ev_uni", link.universe);
      }
      return p;
    }, { replace: true });
    scrollToPanel(link.kind === "intel" ? "intel" : "events");
  };

  const stopped = paused || focused;
  const asOf = t.latestAt ? eventWhen(t.latestAt) : null;
  const label = (
    <div data-testid="md-ticker-label" className="flex items-center" style={{ flex: "none", gap: 8, padding: mobile ? "0 10px" : "0 14px", borderRight: line, background: "var(--bg-2, var(--bg-1))" }}>
      <span aria-hidden style={{ width: 7, height: 7, borderRadius: 999, background: t.status === "ready" ? "var(--amber)" : "var(--cp-ink-4)" }} />
      <span style={{ ...mono, fontSize: 10, letterSpacing: "0.16em", color: "var(--amber)", whiteSpace: "nowrap" }}>{mobile ? "UPDATE" : "MARKET UPDATE"}</span>
      {!mobile && asOf && <span data-testid="md-ticker-asof" className="cp-num" style={{ fontSize: 10.5, color: "var(--cp-ink-3)" }} title={`Newest filing read: ${asOf.full}`}>{asOf.short}</span>}
    </div>
  );

  let tape;
  if (t.status === "loading") {
    tape = <span data-testid="md-ticker-loading" style={{ padding: "0 14px", fontSize: 12.5, color: "var(--cp-ink-3)" }}>Loading results, filings and flows…</span>;
  } else if (t.status === "error") {
    tape = (
      <span data-testid="md-ticker-error" className="flex items-center" style={{ gap: 10, padding: "0 14px", fontSize: 12.5, color: "var(--cp-ink-2)" }}>
        The market update’s sources didn’t load.
        <button type="button" data-testid="md-ticker-retry" onClick={t.refetch} style={{ ...plainBtn, color: "var(--mint)" }}>Retry</button>
      </span>
    );
  } else if (t.items.length === 0) {
    tape = <span data-testid="md-ticker-empty" style={{ padding: "0 14px", fontSize: 12.5, color: "var(--cp-ink-3)" }}>Nothing new since {t.window.label}: no results today or tomorrow and no new filings{t.pending.length ? " so far" : ""}.</span>;
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
            aria-label={c === 0 ? "Market update" : undefined}
            className="m-0 flex items-stretch"
            style={{ listStyle: "none", padding: 0, flex: "none" }}
          >
            {t.items.map((it) => <Item key={it.key} it={it} copy={c} onOpen={open} />)}
          </ul>
        ))}
      </div>
    );
  }

  const seg = (on: boolean): CSSProperties => ({
    ...plainBtn, ...mono, fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase", padding: "4px 7px", borderRadius: 5, whiteSpace: "nowrap",
    color: on ? "var(--cp-ink)" : "var(--cp-ink-3)", background: on ? "var(--bg-3, var(--bg-2))" : "transparent",
  });
  const notLoaded = t.failed.length > 0 && t.status !== "error";
  return (
    <section data-testid="md-ticker" aria-label="Market update" className="cp-card flex min-w-0 flex-col" style={{ padding: 0, overflow: "hidden", borderRadius: 12 }}>
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
        <div className="flex flex-wrap items-center" style={{ gap: 8, minWidth: 0 }}>
          {!reduce && t.items.length > 0 && (
            <button
              type="button"
              data-testid="md-ticker-pause"
              aria-pressed={paused}
              aria-label={paused ? "Play the market update" : "Pause the market update"}
              onClick={() => setPaused((x) => !x)}
              style={{ ...plainBtn, ...mono, fontSize: 10, letterSpacing: "0.12em", color: "var(--cp-ink-2)", border: "1px solid var(--line-2)", borderRadius: 6, padding: "5px 8px" }}
            >
              {paused ? "▶ PLAY" : "❚❚ PAUSE"}
            </button>
          )}
          <div role="group" aria-label="Results from" className="flex" style={{ gap: 2, border: "1px solid var(--line-2)", borderRadius: 7, padding: 2 }}>
            {UNIVERSES.map(([u, name]) => (
              <button key={u} type="button" data-testid={`md-ticker-uni-${u}`} aria-pressed={universe === u} onClick={() => setUniverse(u)} style={seg(universe === u)}>
                {name}
              </button>
            ))}
          </div>
        </div>
        <span data-testid="md-ticker-note" style={{ minWidth: 0, flex: "1 1 300px" }}>
          A summary since {t.window.label}: results against the same quarter last year (figures load about 20:30 IST on the filing
          day), counts of NSE / BSE filings, the latest deals and flows. Select a name to open it, or “more” for the full list below.
        </span>
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
