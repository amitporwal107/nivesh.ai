/**
 * Smart trading desk — Options & futures lab: the pieces the tab draws from an
 * end-of-day chain, the futures list and the build-up scan:
 *
 *   GET /api/fno/{symbol}/chain?expiry=   one expiry by strike, plus a summary over every strike   (trading/fno.ts)
 *   GET /api/fno/{symbol}/futures         the latest day's futures, each with its basis to the spot (trading/fno.ts)
 *   GET /api/fno/scan/buildup             each F&O stock's futures price change × OI change         (fno-buildup.ts)
 *
 * Everything is one NSE F&O bhavcopy a day, after the close. Implied volatility
 * and the expected move are the chain route's model estimates (Black-76 on
 * end-of-day prices) and read "—" when the route sent none. The call wall (R)
 * and put wall (S) are the strikes with the most call and put open interest
 * over the whole expiry; max pain (MP) is the route's own. They describe
 * positions at the close; nothing here calls them targets.
 *
 * Design primitives (design-spec §1): the card header bar, the segmented
 * control, the underline sub-tabs and the stat tile. Calls are drawn in the
 * danger colour and puts in mint, as on the Options lab.
 */
import { useEffect, useLayoutEffect, useRef, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { EmptyBlock, LoadingBlock, TONE_COLOR, fmtNum, fmtPct, signTone, type Tone } from "../../components/ui";
import { fmtLevel } from "../trading/PayoffResult";
import { nearestFuture, strikesAround, type ChainState, type FnoChain, type FnoFuture, type FnoFutures, type FnoResult, type FnoSide, type FnoSummary } from "../trading/fno";
import { QueryProblem, fmtDay, fmtQty, fmtSigned } from "../trading/parts";
import type { DeskPersona } from "./context";
import { BUILDUP_META, type BuildupLabel } from "./fno-buildup";

export const CALL_COLOR = "var(--cp-danger)";
export const PUT_COLOR = "var(--mint)";
const DASH = "—";

/** The soft background and the line colour of a tone (design: a selected quadrant card, a warning row). */
export const TONE_SOFT: Record<Tone, string> = {
  mint: "var(--mint-soft)",
  danger: "var(--cp-danger-soft)",
  indigo: "var(--cp-indigo-soft)",
  amber: "var(--amber-soft)",
  ink: "var(--bg-2)",
};
export const TONE_LINE: Record<Tone, string> = {
  mint: "var(--mint-line)",
  danger: "var(--danger-line)",
  indigo: "var(--indigo-line)",
  amber: "var(--amber-line)",
  ink: "var(--line-2)",
};

/** "27 Oct" — a session date without the year, for tight labels. */
export function shortDay(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T12:00:00+05:30` : iso);
  return Number.isFinite(d.getTime()) ? d.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" }) : DASH;
}

/** The India date ("2026-10-13") of a timestamp. */
export function istDay(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isFinite(d.getTime()) ? d.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }) : null;
}

/** The sentence for an underlying with no F&O rows; the brief's wording, used by the tab and the spec. */
export const noRowsTitle = (symbol: string) => `No F&O rows for ${symbol} on the latest day`;

// ── design primitives ────────────────────────────────────────────────────

/** Card header bar: eyebrow left (`NN · Title`), an optional meta eyebrow pushed right. */
export function CardHead({ children, meta, testId, pad = "13px 18px" }: { children: ReactNode; meta?: ReactNode; testId?: string; pad?: string }) {
  return (
    <div className="flex flex-wrap items-center" style={{ gap: "6px 12px", padding: pad, borderBottom: "1px solid var(--cp-line)", background: "var(--bg-0)" }}>
      <span data-testid={testId} className="cp-eyebrow flex flex-wrap items-center" style={{ gap: 8, minWidth: 0 }}>{children}</span>
      {meta != null && <span className="cp-eyebrow" style={{ marginLeft: "auto", color: "var(--cp-ink-4)" }}>{meta}</span>}
    </div>
  );
}

export interface SegOption<T extends string> {
  value: T;
  /** testid suffix; the value when absent. */
  key?: string;
  label: ReactNode;
  disabled?: boolean;
  title?: string;
}

/** Segmented control (pill wrapper on bg-2; ON bg-4 + ink, OFF ink-3; a disabled item at 35%). */
export function Segmented<T extends string>({ label, value, options, onChange, testId, small }: {
  label: string;
  value: T | null;
  options: Array<SegOption<T>>;
  onChange: (v: T) => void;
  testId: string;
  small?: boolean;
}) {
  return (
    <div role="group" aria-label={label} data-testid={testId} className="inline-flex" style={{ gap: 2, padding: small ? 2 : 3, borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)", maxWidth: "100%" }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.key ?? o.value}
            type="button"
            aria-pressed={on}
            disabled={o.disabled}
            title={o.title}
            data-testid={`${testId}-${o.key ?? o.value}`}
            onClick={() => onChange(o.value)}
            className="cp-num"
            style={{
              padding: small ? "5px 10px" : "6px 12px", borderRadius: 999, border: 0, whiteSpace: "nowrap",
              fontSize: small ? 9.5 : 10.5, letterSpacing: "0.08em", textTransform: "uppercase",
              background: on ? "var(--bg-4)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
              opacity: o.disabled ? 0.35 : 1, cursor: o.disabled ? "not-allowed" : "pointer",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Underline sub-tabs (15px, gap 28; active ink with a 2px ink underline, inactive ink-3). */
export function UnderlineTabs<T extends string>({ tabs, value, onChange, label, idPrefix }: {
  tabs: Array<{ key: T; label: ReactNode }>;
  value: T;
  onChange: (v: T) => void;
  label: string;
  idPrefix: string;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  // On a phone the row scrolls sideways: keep the open tab fully in view.
  const at = tabs.findIndex((t) => t.key === value);
  useEffect(() => {
    const el = refs.current[at];
    const row = el?.parentElement;
    if (!el || !row || row.scrollWidth <= row.clientWidth) return;
    const left = el.offsetLeft - row.offsetLeft;
    if (left < row.scrollLeft || left + el.offsetWidth > row.scrollLeft + row.clientWidth) row.scrollLeft = Math.max(0, left - 16);
  }, [at]);
  const onKey = (e: KeyboardEvent, i: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = (i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
    onChange(tabs[next].key);
    refs.current[next]?.focus();
  };
  return (
    <div role="tablist" aria-label={label} className="cp-scroll flex overflow-x-auto" style={{ gap: 28, borderBottom: "1px solid var(--cp-line)" }}>
      {tabs.map((t, i) => {
        const on = t.key === value;
        return (
          <button
            key={t.key}
            ref={(el) => { refs.current[i] = el; }}
            type="button"
            role="tab"
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            data-testid={`${idPrefix}-${t.key}`}
            onClick={() => onChange(t.key)}
            onKeyDown={(e) => onKey(e, i)}
            style={{
              flex: "none", padding: "0 0 11px", marginBottom: -1, border: 0, borderBottom: `2px solid ${on ? "var(--cp-ink)" : "transparent"}`,
              background: "none", fontFamily: "var(--sans)", fontSize: 15, whiteSpace: "nowrap", cursor: "pointer",
              color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
            }}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

/** A coloured dot before a label (quadrant cards, legends). */
export function Dot({ color, size = 7 }: { color: string; size?: number }) {
  return <span aria-hidden="true" style={{ flex: "none", width: size, height: size, borderRadius: "50%", background: color }} />;
}

// ── loading / error / no rows ────────────────────────────────────────────

/** The chain's loading, error (with retry) and no-rows states; `children` once it has loaded. */
export function FnoGate({ symbol, state, testId, children }: { symbol: string; state: ChainState; testId: string; children: (chain: FnoChain) => ReactNode }) {
  if (state.status === "loading") return <div data-testid={`${testId}-loading`}><LoadingBlock label={`Loading the ${symbol} chain`} rows={3} /></div>;
  if (state.status === "error") return <div data-testid={`${testId}-error`}><QueryProblem what={`The ${symbol} option chain`} error={state.error} onRetry={state.retry} /></div>;
  if (state.status === "none") {
    return (
      <div data-testid={`${testId}-none`}>
        <EmptyBlock
          title={noRowsTitle(symbol)}
          body={`The server said: “${state.message}”. Only indices and stocks in NSE’s F&O segment have contracts in the end-of-day file, so check the ticker.`}
        />
      </div>
    );
  }
  return <>{children(state.chain)}</>;
}

// ── futures ──────────────────────────────────────────────────────────────

export interface NearFuture {
  future: FnoFuture;
  spot: number | null;
  asOf: string;
}

/** The nearest future from a loaded futures list; null while loading, on an error, for no rows or no contract. */
export function nearFutureOf(data: FnoResult<FnoFutures> | undefined): NearFuture | null {
  if (!data || data.kind !== "ok") return null;
  const f = nearestFuture(data.data);
  return f ? { future: f, spot: data.data.spot, asOf: data.data.as_of } : null;
}

/**
 * The contract's day change from the futures route (close − the exchange's previous close). Without a previous close
 * it says so: the change is never inferred and never shown as zero.
 */
export function futuresDayText(f: FnoFuture): string {
  if (f.change == null || f.change_pct == null) return "day change — (no previous close)";
  return `day ${fmtSigned(f.change)} (${fmtSigned(f.change_pct)}%)`;
}

/** "Premium to" / "Discount to" / "Level with" the spot, from the basis; null without one. */
export function basisWords(basis: number | null): string | null {
  if (basis == null) return null;
  return basis > 0 ? "premium" : basis < 0 ? "discount" : "level";
}

// ── the loaded underlying's build-up ─────────────────────────────────────

/**
 * The futures build-up of the loaded underlying: the scan's label for a stock;
 * for an index, none (the scan is stock futures, and the futures route sends no
 * previous close, so the index future's price change is unknown).
 */
export type UnderlyingBuildup =
  | { status: "ok"; label: BuildupLabel | null; priceChgPct: number | null; oiChgPct: number | null; asOf: string | null }
  | { status: "index" | "loading" | "error" | "absent" };

export function buildupWhy(b: UnderlyingBuildup, asOf: string | null): string {
  switch (b.status) {
    case "index": return "The build-up scan has no index futures row for this index";
    case "loading": return "Reading the build-up scan";
    case "error": return "The build-up scan didn’t load";
    case "absent": return `Not in the stock-futures scan${asOf ? ` for ${fmtDay(asOf)}` : ""}`;
    case "ok": return b.label == null ? "A price or OI change is missing in the scan" : "";
  }
}

// ── stats card ───────────────────────────────────────────────────────────

export interface StatTile {
  k: string;
  v: ReactNode;
  s: ReactNode;
  testId: string;
  tone?: Tone;
}

/** The stats card: eight tiles (4 × 2; 2 columns on a phone) and the method note under them. */
export function StatGrid({ tiles, testId, columns, note }: { tiles: StatTile[]; testId?: string; columns: number; note?: ReactNode }) {
  return (
    <section data-testid={testId} className="cp-card flex flex-col min-w-0" style={{ gap: 14, padding: columns > 2 ? 18 : 14 }}>
      <div className="grid" style={{ gridTemplateColumns: `repeat(${columns},minmax(0,1fr))`, gap: columns > 2 ? 10 : 8 }}>
        {tiles.map((t) => (
          <div key={t.testId} className="flex flex-col min-w-0" style={{ gap: 5, padding: columns > 2 ? "14px 16px" : "11px 12px", borderRadius: 12, background: "var(--bg-2)", border: "1px solid var(--cp-line)" }}>
            <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{t.k}</span>
            <span data-testid={t.testId} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: columns > 2 ? 26 : 22, lineHeight: 1.1, letterSpacing: "-0.02em", color: TONE_COLOR[t.tone ?? "ink"], overflowWrap: "anywhere" }}>{t.v}</span>
            <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{t.s}</span>
          </div>
        ))}
      </div>
      {note && <div data-testid="desk-fno-model-note" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>{note}</div>}
    </section>
  );
}

const ivText = (iv: number | null | undefined) => (iv == null ? DASH : `${fmtNum(iv, 2)}%`);
const moveText = (m: number | null | undefined) => (m == null ? DASH : `±${fmtNum(m, 2)}`);

/** The eight tiles of the design, from the chain summary, the nearest future and the build-up scan. */
export function chainTiles(s: FnoSummary, near: NearFuture | null, futuresNote: string, bu: UnderlyingBuildup, persona: DeskPersona): StatTile[] {
  const plain = persona === "investor";
  const basis = near?.future.basis ?? null;
  const words = basisWords(basis);
  const meta = bu.status === "ok" && bu.label ? BUILDUP_META[bu.label] : null;
  const oiLine = near ? `OI ${fmtQty(near.future.change_in_oi, { signed: true })}` : null;
  return [
    {
      k: plain ? "Expected volatility" : "ATM implied volatility",
      v: ivText(s.atm_iv),
      s: s.atm_iv == null
        ? "No model estimate at the ATM strike"
        : plain ? "A year, read from option prices at the close" : `A year · model estimate${s.atm_strike != null ? ` at the ${fmtLevel(s.atm_strike)} strike` : ""}`,
      testId: "desk-fno-atm-iv",
    },
    {
      k: plain ? "Expected swing" : "Expected move to expiry",
      v: moveText(s.expected_move),
      s: s.expected_move == null
        ? "Needs a call and a put close at the ATM strike"
        : `${s.expected_move_pct != null ? `${fmtNum(s.expected_move_pct, 2)}% of spot · ` : ""}${plain ? `either way by ${shortDay(s.expiry)}, priced by options` : "ATM straddle at the close"}`,
      testId: "desk-fno-expected-move",
    },
    {
      k: near ? `Futures · ${shortDay(near.future.expiry)}` : "Futures",
      v: near?.future.settle != null ? fmtNum(near.future.settle, 2) : DASH,
      s: near
        ? `${words == null ? "No basis to the spot" : words === "level" ? "Level with the spot" : `${fmtSigned(basis)} ${words} to spot`} · ${futuresDayText(near.future)}`
        : futuresNote,
      testId: "desk-fno-futures",
    },
    {
      k: "Days to expiry",
      v: s.days_to_expiry == null ? DASH : fmtNum(s.days_to_expiry),
      s: `Calendar days, ${fmtDay(s.as_of)} to ${fmtDay(s.expiry)}`,
      testId: "desk-fno-days",
    },
    {
      k: "Put-call ratio · OI",
      v: s.pcr == null ? DASH : fmtNum(s.pcr, 2),
      s: plain ? "Open puts for each open call, every strike" : "Put OI ÷ call OI, every strike",
      testId: "desk-fno-pcr",
    },
    {
      k: "Max pain",
      v: s.max_pain == null ? DASH : fmtLevel(s.max_pain),
      s: "Strike where open options pay out least at expiry",
      testId: "desk-fno-max-pain",
    },
    {
      k: "OI range",
      v: s.max_put_oi && s.max_call_oi ? `${fmtLevel(s.max_put_oi.strike)} – ${fmtLevel(s.max_call_oi.strike)}` : DASH,
      s: plain ? "Where most open bets sit: puts → calls" : "Most put OI → most call OI",
      testId: "desk-fno-oi-range",
    },
    {
      k: plain ? "Open bets (OI) change" : "Futures build-up",
      v: meta ? meta.label : DASH,
      s: bu.status === "ok" && meta
        ? `${plain ? meta.plain : `Price ${fmtPct(bu.priceChgPct, { signed: true, digits: 2 })} · OI ${fmtPct(bu.oiChgPct, { signed: true, digits: 2 })}`}${bu.asOf ? ` · ${shortDay(bu.asOf)}` : ""}`
        : `${buildupWhy(bu, null)}${oiLine ? ` · ${oiLine}` : ""}`,
      testId: "desk-fno-buildup-tile",
      tone: meta ? meta.tone : "ink",
    },
  ];
}

// ── option chain, open interest by strike ────────────────────────────────

/** Strikes either side of the ATM strike in the chain table. */
const CHAIN_EACH = 10;

function OiBar({ share, color, leftwards }: { share: number; color: string; leftwards?: boolean }) {
  const w = Math.max(0, Math.min(1, share)) * 100;
  return (
    <span aria-hidden="true" style={{ position: "relative", display: "block", flex: "1 1 0", minWidth: 24, height: 7, borderRadius: 2, background: "var(--bg-3)" }}>
      <span style={{ position: "absolute", top: 0, bottom: 0, [leftwards ? "right" : "left"]: 0, width: `${w}%`, borderRadius: 2, background: color }} />
    </span>
  );
}

const TAG_TITLE: Record<string, string> = {
  ATM: "Strike nearest the end-of-day spot",
  R: "Call wall: the strike with the most call open interest in the expiry",
  S: "Put wall: the strike with the most put open interest in the expiry",
  MP: "Max pain",
};

/** Which of ATM, R, S and MP a strike is. */
export function strikeTags(s: FnoSummary, strike: number): string[] {
  const tags: string[] = [];
  if (s.atm_strike === strike) tags.push("ATM");
  if (s.max_call_oi?.strike === strike) tags.push("R");
  if (s.max_put_oi?.strike === strike) tags.push("S");
  if (s.max_pain === strike) tags.push("MP");
  return tags;
}

/** One plain read of the summary: where the open interest sits, the PCR and max pain. Facts only. */
export function chainRead(s: FnoSummary): string {
  const parts: string[] = [];
  if (s.max_call_oi) parts.push(`the most call open interest is at ${fmtLevel(s.max_call_oi.strike)} (${fmtQty(s.max_call_oi.oi)})`);
  if (s.max_put_oi) parts.push(`the most put open interest at ${fmtLevel(s.max_put_oi.strike)} (${fmtQty(s.max_put_oi.oi)})`);
  if (s.pcr != null) parts.push(`the put-call ratio on open interest is ${fmtNum(s.pcr, 2)}`);
  if (s.max_pain != null) parts.push(`max pain is ${fmtLevel(s.max_pain)}`);
  if (!parts.length) return "This expiry has no open interest to read.";
  let out = `For the ${fmtDay(s.expiry)} expiry, ${parts.join(", ")}.`;
  out = out.charAt(0).toUpperCase() + out.slice(1);
  if (s.spot != null && s.max_call_oi && s.max_put_oi) {
    const lo = Math.min(s.max_put_oi.strike, s.max_call_oi.strike);
    const hi = Math.max(s.max_put_oi.strike, s.max_call_oi.strike);
    const where = s.spot < lo ? "below both" : s.spot > hi ? "above both" : "between the two";
    out += ` The end-of-day spot of ${fmtNum(s.spot, 2)} is ${where}.`;
  }
  return `${out} These are positions at the close, not price targets.`;
}

const signedQty = (n: number | null | undefined) => fmtQty(n, { signed: true });

function sideFigures(side: FnoSide | null) {
  return { oi: side?.oi ?? null, change: side?.change_in_oi ?? null, close: side?.close ?? null };
}

const CHAIN_TEMPLATE = "76px minmax(0,1fr) 76px 104px 76px minmax(0,1fr) 76px";

/** Design: "Option chain OI · SYM · expiry" — seven columns, OI bars, ATM / R / S / MP tags, a reading under it. */
export function ChainOiTable({ chain }: { chain: FnoChain }) {
  // On a narrow screen the table scrolls sideways; start it centred on the strike column, so calls sit to the left and puts to the right.
  const scroller = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && el.scrollWidth > el.clientWidth) el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2;
  }, [chain]);
  const s = chain.summary;
  const rows = strikesAround(chain, CHAIN_EACH);
  const max = Math.max(1, ...rows.flatMap((r) => [r.call?.oi ?? 0, r.put?.oi ?? 0]));
  const head = (key: string, label: string, align: CSSProperties["textAlign"]) => (
    <span key={key} role="columnheader" className="cp-num" style={{ textAlign: align, minWidth: 0, fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>{label}</span>
  );
  const quiet = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;
  return (
    <section data-testid="desk-fno-chain" className="cp-card flex flex-col min-w-0" style={{ overflow: "hidden" }}>
      <CardHead testId="desk-fno-chain-head" meta="R call wall · S put wall · MP max pain">
        Option chain OI · {chain.symbol} · {fmtDay(s.expiry)}
      </CardHead>
      <div ref={scroller} data-testid="desk-fno-chain-scroll" className="cp-scroll overflow-x-auto" role="table" aria-label={`${chain.symbol} open interest by strike, ${fmtDay(s.expiry)} expiry`}>
        <div style={{ minWidth: 700 }}>
          <div role="row" data-testid="desk-fno-chain-header" className="grid" style={{ gridTemplateColumns: CHAIN_TEMPLATE, gap: 10, padding: "10px 18px" }}>
            {head("call-chg", "Call OI chg", "left")}
            {head("call-oi", "Call OI", "right")}
            {head("call-close", "Call close", "right")}
            {head("strike", "Strike", "center")}
            {head("put-close", "Put close", "left")}
            {head("put-oi", "Put OI", "left")}
            {head("put-chg", "Put OI chg", "right")}
          </div>
          {rows.map((r) => {
            const c = sideFigures(r.call);
            const p = sideFigures(r.put);
            const tags = strikeTags(s, r.strike);
            const atm = tags.includes("ATM");
            return (
              <div
                key={r.strike}
                role="row"
                data-testid="desk-fno-chain-row"
                data-strike={r.strike}
                data-atm={atm ? "true" : undefined}
                className="grid items-center"
                style={{ gridTemplateColumns: CHAIN_TEMPLATE, gap: 10, padding: "7px 18px", borderTop: "1px solid var(--cp-line)", fontSize: 12, background: atm ? "var(--bg-2)" : undefined }}
              >
                <span role="cell" data-col="call-oi-change" className="cp-num" style={{ color: c.change ? TONE_COLOR[signTone(c.change)] : "var(--cp-ink-3)" }}>{signedQty(c.change)}</span>
                <span role="cell" className="flex items-center" style={{ gap: 6, minWidth: 0 }}>
                  <span data-col="call-oi" className="cp-num" style={{ flex: "none", fontSize: 11, color: "var(--cp-ink-2)" }}>{fmtQty(c.oi)}</span>
                  <OiBar share={(c.oi ?? 0) / max} color={CALL_COLOR} leftwards />
                </span>
                <span role="cell" data-col="call-close" className="cp-num" style={{ textAlign: "right", color: "var(--cp-ink)" }}>{c.close == null ? DASH : fmtNum(c.close, 2)}</span>
                <span role="cell" data-col="strike" className="flex flex-col items-center" style={{ gap: 3 }}>
                  <span style={{ fontFamily: "var(--display)", fontSize: 18, lineHeight: 1, color: atm ? "var(--mint)" : "var(--cp-ink)" }}>{fmtLevel(r.strike)}</span>
                  {tags.length > 0 && (
                    <span className="flex flex-wrap justify-center" style={{ gap: 3 }}>
                      {tags.map((t) => (
                        <span key={t} data-testid={`desk-fno-tag-${t.toLowerCase()}`} title={TAG_TITLE[t]} className="cp-pill" data-tone="amber" style={{ padding: "1px 5px", fontSize: 8.5 }}>{t}</span>
                      ))}
                    </span>
                  )}
                </span>
                <span role="cell" data-col="put-close" className="cp-num" style={{ color: "var(--cp-ink)" }}>{p.close == null ? DASH : fmtNum(p.close, 2)}</span>
                <span role="cell" className="flex items-center" style={{ gap: 6, minWidth: 0 }}>
                  <OiBar share={(p.oi ?? 0) / max} color={PUT_COLOR} />
                  <span data-col="put-oi" className="cp-num" style={{ flex: "none", fontSize: 11, color: "var(--cp-ink-2)" }}>{fmtQty(p.oi)}</span>
                </span>
                <span role="cell" data-col="put-oi-change" className="cp-num" style={{ textAlign: "right", color: p.change ? TONE_COLOR[signTone(p.change)] : "var(--cp-ink-3)" }}>{signedQty(p.change)}</span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="flex flex-col" style={{ gap: 6, padding: "12px 18px", borderTop: "1px solid var(--cp-line)" }}>
        <span data-testid="desk-fno-chain-read" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{chainRead(s)}</span>
        <span style={quiet}>
          ATM: the strike nearest the end-of-day spot. R (call wall) and S (put wall): the strikes with the most call and put open interest in the whole expiry. MP: max pain.
          {` Showing ${fmtNum(rows.length)} of the expiry’s ${fmtNum(chain.strike_count)} strikes; the tags and the totals cover all of them.`}
          {" Close is the end-of-day closing price, not a live quote."}
        </span>
        <span className="cp-mono-note" style={{ lineHeight: 1.6 }}>NSE F&amp;O bhavcopy · end of day · as of {fmtDay(s.as_of)}</span>
      </div>
    </section>
  );
}

// ── NIFTY & BANKNIFTY ────────────────────────────────────────────────────

/** Put wall, call wall, the spot and the expected-move band on one line, with their labels under it. */
export function OiRangeBar({ s, testId }: { s: FnoSummary; testId: string }) {
  const put = s.max_put_oi?.strike ?? null;
  const call = s.max_call_oi?.strike ?? null;
  const spot = s.spot;
  const em = s.expected_move ?? null;
  const pts = [put, call, spot, spot != null && em != null ? spot - em : null, spot != null && em != null ? spot + em : null].filter((x): x is number => x != null);
  if (pts.length < 2) return <span data-testid={`${testId}-bar-none`} style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>The chain has no walls or spot to draw.</span>;
  const lo0 = Math.min(...pts);
  const hi0 = Math.max(...pts);
  const pad = (hi0 - lo0) * 0.08 || Math.abs(hi0) * 0.01 || 1;
  const lo = lo0 - pad;
  const hi = hi0 + pad;
  const at = (x: number) => `${((x - lo) / (hi - lo)) * 100}%`;
  const mark = (x: number, color: string, label: string, key: string) => (
    <span key={key} title={label} aria-hidden="true" style={{ position: "absolute", top: -3, bottom: -3, left: at(x), width: 3, marginLeft: -1.5, borderRadius: 2, background: color }} />
  );
  const legend: Array<{ k: string; v: string; color: string; testId: string }> = [];
  if (put != null) legend.push({ k: "Put wall", v: fmtLevel(put), color: PUT_COLOR, testId: `${testId}-put-wall` });
  if (spot != null) legend.push({ k: "Spot", v: fmtNum(spot, 2), color: "var(--cp-ink)", testId: `${testId}-bar-spot` });
  if (call != null) legend.push({ k: "Call wall", v: fmtLevel(call), color: CALL_COLOR, testId: `${testId}-call-wall` });
  const label = [
    put != null ? `put wall ${fmtLevel(put)}` : null,
    spot != null ? `spot ${fmtNum(spot, 2)}` : null,
    call != null ? `call wall ${fmtLevel(call)}` : null,
    spot != null && em != null ? `expected move ${fmtNum(spot - em, 2)} to ${fmtNum(spot + em, 2)}` : null,
  ].filter(Boolean).join(", ");
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <div role="img" aria-label={`Open-interest range: ${label}`} style={{ position: "relative", height: 8, margin: "6px 2px", borderRadius: 999, background: "var(--bg-3)" }}>
        {spot != null && em != null && (
          <span title={`Expected move ${fmtNum(spot - em, 2)} – ${fmtNum(spot + em, 2)}`} aria-hidden="true" style={{ position: "absolute", top: 0, bottom: 0, left: at(spot - em), width: `${((2 * em) / (hi - lo)) * 100}%`, borderRadius: 999, background: "var(--cp-indigo-soft)", border: "1px solid var(--indigo-line)" }} />
        )}
        {put != null && mark(put, PUT_COLOR, `Put wall ${fmtLevel(put)}`, "put")}
        {call != null && mark(call, CALL_COLOR, `Call wall ${fmtLevel(call)}`, "call")}
        {spot != null && (
          <span title={`Spot ${fmtNum(spot, 2)}`} aria-hidden="true" style={{ position: "absolute", top: -6, bottom: -6, left: at(spot), width: 2, marginLeft: -1, background: "var(--cp-ink)" }} />
        )}
      </div>
      <div className="flex flex-wrap" style={{ gap: "4px 14px", fontSize: 11.5 }}>
        {legend.map((l) => (
          <span key={l.k} className="flex items-center" style={{ gap: 6, color: "var(--cp-ink-3)" }}>
            <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 2, background: l.color }} />
            {l.k} <span data-testid={l.testId} className="cp-num" style={{ color: "var(--cp-ink)" }}>{l.v}</span>
          </span>
        ))}
        {spot != null && em != null && (
          <span className="flex items-center" style={{ gap: 6, color: "var(--cp-ink-3)" }}>
            <span aria-hidden="true" style={{ width: 14, height: 8, borderRadius: 2, background: "var(--cp-indigo-soft)", border: "1px solid var(--indigo-line)" }} />
            Expected move <span data-testid={`${testId}-band`} className="cp-num" style={{ color: "var(--cp-ink)" }}>{fmtNum(spot - em, 2)}–{fmtNum(spot + em, 2)}</span>
          </span>
        )}
      </div>
    </div>
  );
}

/** A label and a figure on one line of an index card. */
export function CardRow({ k, children, testId }: { k: string; children: ReactNode; testId: string }) {
  return (
    <div className="flex justify-between" style={{ gap: 12, padding: "9px 0", borderTop: "1px solid var(--cp-line)", fontSize: 13 }}>
      <span style={{ color: "var(--cp-ink-3)" }}>{k}</span>
      <span data-testid={testId} className="cp-num" style={{ textAlign: "right", color: "var(--cp-ink)", minWidth: 0, overflowWrap: "anywhere" }}>{children}</span>
    </div>
  );
}
