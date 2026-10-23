/**
 * Smart trading desk — 06 Options & futures lab. Design: "Smart Trading Desk",
 * Options & futures lab (design-spec §8): header with the underlying's spot,
 * the underlying row with the expiry switch, the stats card, then four
 * sub-tabs — OI build-up · F&O stocks, NIFTY & BANKNIFTY, Option chain OI and
 * Paper strategies. Analysis only: nothing here places an order.
 *
 * Data (all end of day, one NSE F&O bhavcopy a day):
 *   expiry switch                  GET /api/fno/{symbol}/expiries              (useOptionChain, trading/fno.ts)
 *   stats, option chain OI,        GET /api/fno/{symbol}/chain?expiry=         (useOptionChain)
 *   NIFTY & BANKNIFTY cards
 *   futures price, basis, OI chg   GET /api/fno/{symbol}/futures               (useFnoFutures)
 *   futures build-up tile, the     GET /api/fno/scan/buildup                   (useBuildup, fno-buildup.ts): every F&O
 *   ticker check, OI build-up,                                                 stock's futures price change × OI change
 *   paper strategy names
 *   India VIX, an index's change   GET /api/markets/home                       (useMarketOverview)
 *   paper strategies               worked out from the above (FnoStrategies.tsx); the Cash · delivery idea is
 *                                  recorded with POST /api/desk/paper-trades
 *
 * Implied volatility and the expected move are the chain route's model
 * estimates (Black-76 on end-of-day prices, backend/services/option_pricing.py),
 * labelled as such. An expiry is "monthly" when a futures contract expires the
 * same day (NSE lists futures for monthly expiries only); "weekly" is the
 * nearest other expiry before the farthest listed future (long-dated quarterly
 * options lie beyond it). Stocks have no weekly expiry, so that choice is off.
 *
 * Index futures build-up comes from the scan's `indices` rows (the near future's
 * price change × OI summed over every expiry, with the index close as the cash
 * side). F&O eligibility of a loaded stock is the NSE F&O master's (the scan row's
 * `fno_eligible`); a ticker not in the scan is refused before any read.
 *
 * Not available from the data (shown as "—" with the reason):
 *   an index card's day change     the bhavcopy has no previous spot; the markets tape's change is shown only when
 *                                  it is for the same session as the bhavcopy (the scan's index close and change is
 *                                  shown on the card as the cash side of the build-up)
 *   15-minute confirmation         no intraday OI is collected (FnoBuildup.tsx shows the route's reason)
 */
import { useState, type FormEvent, type ReactNode } from "react";
import { StockIcon } from "../../components/EntityIcon";
import { LoadingBlock, Pill, TONE_COLOR, fmtNum, signTone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { useLiveOverlay } from "../../lib/useLiveQuotes";
import { useMarketOverview } from "../markets/hooks";
import { modelLabel } from "../trading/ModelViews";
import { fmtLevel } from "../trading/PayoffResult";
import { FNO_INDICES, cleanSymbol, indexNameForSymbol, isIndexUnderlying, useFnoFutures, useOptionChain, type ChainState, type FnoFutures, type FnoResult, type FnoSummary } from "../trading/fno";
import { QueryProblem, SEBI_FNO_NOTE, fmtDay, fmtQty, fmtSigned } from "../trading/parts";
import { useDesk } from "./context";
import { BuildupView } from "./FnoBuildup";
import { StrategiesView } from "./FnoStrategies";
import { BUILDUP_META, buildupRowFor, matchFnoTickers, searchStocks, type StockHit, indexRowFor, useBuildup } from "./fno-buildup";
import { HEURISTIC_NOTE } from "./FnoBuildup";
import { SymbolSearch } from "./SymbolSearch";
import { TrustLine } from "./trust";
import {
  CardHead, CardRow, ChainOiTable, FnoGate, OiRangeBar, Segmented, StatGrid, TONE_LINE, TONE_SOFT, UnderlineTabs,
  basisWords, buildupWhy, chainTiles, istDay, nearFutureOf, shortDay, type SegOption, type UnderlyingBuildup,
} from "./fno-parts";

type FnoView = "buildup" | "indices" | "chain" | "strategies";

// ── header ───────────────────────────────────────────────────────────────

type MarketsHome = NonNullable<ReturnType<typeof useMarketOverview>["data"]>;

/** India VIX from the markets tape: its value and when it is for. */
function vixLine(home: MarketsHome | undefined): string | null {
  const v = home?.indices.find((i) => i.is_vix);
  if (!v || v.value == null) return null;
  const day = istDay(home?.as_of ?? null);
  return `India VIX ${fmtNum(v.value, 2)}${home?.is_live ? " live" : day ? ` · ${shortDay(day)}` : ""}`;
}

function SpotBlock({ symbol, state, futures }: { symbol: string; state: ChainState; futures: FnoResult<FnoFutures> | undefined }) {
  const { mobile } = useCopilotShell();
  const home = useMarketOverview();
  const summary = state.status === "ok" ? state.chain.summary : null;
  const fut = futures?.kind === "ok" ? futures.data : null;
  const spot = summary?.spot ?? fut?.spot ?? null;
  const asOf = summary?.as_of ?? fut?.as_of ?? null;
  const vix = vixLine(home.data);
  // Kite's live spot while the feed is LIVE (the index by its tape name, a stock by its symbol). Only the headline
  // number changes: the chain, walls and the model read below stay the bhavcopy's, and the label says so.
  const live = useLiveOverlay(indexNameForSymbol(symbol) ?? symbol, null);
  if (state.status === "loading" && !fut) return <div style={{ flex: "0 1 220px", minWidth: 0 }}><LoadingBlock label={`Loading the ${symbol} spot`} rows={1} /></div>;
  if (spot == null) return null;
  return (
    <div data-testid="desk-fno-spot-block" className="flex flex-col" style={{ flex: "none", gap: 4, alignItems: mobile ? "flex-start" : "flex-end", textAlign: mobile ? "left" : "right" }}>
      <span className="cp-eyebrow flex items-center" style={{ gap: 6 }}>
        {!isIndexUnderlying(symbol) && <StockIcon symbol={symbol} size={16} />}
        {symbol} · spot
      </span>
      <span data-testid="desk-fno-spot" data-live={live ? "true" : undefined} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: mobile ? 34 : 40, lineHeight: 1, letterSpacing: "-0.03em" }}>{fmtNum(live ? live.ltp : spot, 2)}</span>
      <span className="cp-num flex flex-col" style={{ gap: 2, fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--cp-ink-3)", alignItems: mobile ? "flex-start" : "flex-end" }}>
        {live && <span data-testid="desk-fno-live" style={{ color: "var(--mint)" }}>Live · Kite{live.changePct != null ? ` · ${live.changePct > 0 ? "+" : ""}${live.changePct.toFixed(2)}%` : ""}</span>}
        {asOf && <span data-testid="desk-fno-asof">{live ? `Chain figures: bhavcopy ${fmtDay(asOf)}` : `Bhavcopy ${fmtDay(asOf)} · end of day`}</span>}
        {vix && <span data-testid="desk-fno-vix" title="India VIX from the markets tape (GET /api/markets/home)">{vix}</span>}
      </span>
    </div>
  );
}

// ── underlying and expiry ────────────────────────────────────────────────

type Problem =
  | { kind: "format" }
  /** `name` is the company's name when the search found the stock. */
  | { kind: "unknown"; symbol: string; name: string | null; day: string | null; count: number }
  | { kind: "nomatch"; query: string }
  | { kind: "search_failed" }
  /** Several F&O stocks matched a name: the user picks one. */
  | { kind: "choose"; query: string; options: StockHit[] };

/** What a company name may contain; a ticker is stricter (cleanSymbol). */
const NAME_RE = /^[A-Za-z0-9&.' -]{2,40}$/;
const MAX_OFFERS = 8;

function UnderlyingRow({ symbol, onPick, expiry }: { symbol: string; onPick: (s: string) => void; expiry: ReactNode }) {
  const { mobile } = useCopilotShell();
  const { persona } = useDesk();
  const scan = useBuildup(true);
  const [typed, setTyped] = useState("");
  const [problem, setProblem] = useState<Problem | null>(null);
  const indexChip = FNO_INDICES.some((i) => i.symbol === symbol);
  const [busy, setBusy] = useState(false);
  const list = scan.data && scan.data.rows.length > 0 ? scan.data : null;
  // With the F&O list loaded, only its stocks (and the indices) can load; without it the chain route answers for itself.
  const inFno = (sym: string) => isIndexUnderlying(sym) || list == null || buildupRowFor(list, sym) != null;
  const unknown = (symbol: string, name: string | null): Problem => ({ kind: "unknown", symbol, name, day: list?.asOf ?? null, count: list ? (list.universe ?? list.rows.length) : 0 });
  const load = (sym: string) => {
    setProblem(null);
    setTyped("");
    onPick(sym);
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const query = typed.trim();
    const s = cleanSymbol(typed);
    if (s != null && inFno(s)) {
      load(s);
      return;
    }
    if (s == null && !NAME_RE.test(query)) {
      setProblem({ kind: "format" });
      return;
    }
    // Not a ticker in the F&O list: it may be a company name ("Tata Motors"), a name that is also a valid ticker
    // ("Reliance"), or a ticker that is not in F&O. The instrument search tells which.
    setBusy(true);
    let hits: StockHit[] | null = null;
    try {
      hits = await searchStocks(query);
    } catch {
      hits = null;
    } finally {
      setBusy(false);
    }
    // The F&O list's own tickers containing the text come first (the search knows only some companies), then the
    // search's hits; one entry per ticker, the search's company name kept when it has one.
    const names = new Map((hits ?? []).map((h) => [h.symbol, h.name]));
    const found: StockHit[] = [...matchFnoTickers(query, list ?? undefined).map((symbol) => ({ symbol, name: names.get(symbol) ?? symbol })), ...(hits ?? [])];
    const seen = new Set<string>();
    const fno = found.filter((h) => !seen.has(h.symbol) && seen.add(h.symbol) != null && cleanSymbol(h.symbol) != null && inFno(h.symbol));
    if (fno.length === 1) {
      load(fno[0].symbol);
    } else if (fno.length > 1) {
      setProblem({ kind: "choose", query, options: fno.slice(0, MAX_OFFERS) });
    } else if (hits == null) {
      setProblem(s != null ? unknown(s, null) : { kind: "search_failed" });
    } else if (s != null) {
      setProblem(unknown(s, hits.find((h) => h.symbol === s)?.name ?? null));
    } else if (hits.length > 0) {
      setProblem(unknown(hits[0].symbol, hits[0].name));
    } else {
      setProblem({ kind: "nomatch", query });
    }
  };
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <div className="flex flex-wrap items-center" style={{ gap: "10px 12px", minWidth: 0 }}>
        <span className="cp-eyebrow">Underlying</span>
        <div role="group" aria-label="Index underlying" className="flex" style={{ gap: 6 }}>
          {FNO_INDICES.map((i) => {
            const on = i.symbol === symbol;
            return (
              <button
                key={i.symbol}
                type="button"
                aria-pressed={on}
                data-testid={`desk-fno-symbol-${i.symbol.toLowerCase()}`}
                onClick={() => { setProblem(null); onPick(i.symbol); }}
                style={{
                  padding: "8px 16px", borderRadius: 999, fontSize: 14, fontFamily: "var(--sans)", cursor: "pointer", whiteSpace: "nowrap",
                  border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`, background: on ? "var(--mint-soft)" : "transparent", color: on ? "var(--mint)" : "var(--cp-ink-2)",
                }}
              >
                {i.symbol}
              </button>
            );
          })}
        </div>
        <form
          onSubmit={submit}
          className="flex items-center"
          style={{ position: "relative", gap: 6, width: mobile ? "100%" : 290, maxWidth: "100%", height: 40, padding: "0 4px 0 12px", borderRadius: 12, background: "var(--bg-2)", border: `1px solid ${problem && problem.kind !== "choose" ? "var(--danger-line)" : "var(--line-2)"}` }}
        >
          <SymbolSearch
            value={typed}
            onChange={(v) => { setTyped(v); setProblem(null); }}
            onSelect={(sym) => load(sym)}
            persona={persona}
            fnoOnly
            anchorToParent
            testIdPrefix="desk-fno-search"
            inputTestId="desk-fno-symbol-input"
            ariaLabel="Stock name or ticker"
            invalid={problem != null && problem.kind !== "choose"}
            placeholder="Name or ticker, e.g. TCS"
            maxLength={40}
            listMinWidth={mobile ? undefined : 340}
            inputStyle={{ flex: "1 1 auto", minWidth: 0, width: "100%", height: 38, border: 0, outline: "none", background: "transparent", color: "var(--cp-ink)", fontFamily: "var(--mono)", fontSize: 13 }}
          />
          <button
            type="submit"
            data-testid="desk-fno-symbol-load"
            disabled={busy}
            aria-busy={busy}
            style={{ flex: "none", height: 30, padding: "0 12px", borderRadius: 9, border: "1px solid var(--line-2)", background: "var(--bg-3)", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13, cursor: "pointer" }}
          >
            Load
          </button>
        </form>
        {!indexChip && (
          <span data-testid="desk-fno-loaded" className="cp-pill" data-tone="mint" style={{ gap: 6 }}>
            {!isIndexUnderlying(symbol) && <StockIcon symbol={symbol} size={14} />}
            <span data-testid="desk-fno-loaded-sym">{symbol} loaded</span>
          </span>
        )}
        {!isIndexUnderlying(symbol) && <Eligibility symbol={symbol} />}
        <div className="flex flex-wrap items-center" style={{ gap: 8, marginLeft: mobile ? 0 : "auto", minWidth: 0, maxWidth: "100%" }}>
          <span className="cp-eyebrow">Expiry</span>
          {expiry}
        </div>
      </div>
      {problem?.kind === "choose" && (
        <div id="desk-fno-symbol-problem" role="group" aria-label={`F&O stocks matching ${problem.query}`} className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>Several F&O stocks match “{problem.query}”. Pick one:</span>
          {problem.options.map((o) => (
            <button
              key={o.symbol}
              type="button"
              data-testid="desk-fno-symbol-suggest"
              onClick={() => load(o.symbol)}
              className="flex items-center"
              style={{ gap: 6, padding: "6px 12px", borderRadius: 999, fontSize: 13, cursor: "pointer", border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink-2)", fontFamily: "var(--sans)" }}
            >
              <StockIcon symbol={o.symbol} size={14} />
              <span style={{ fontFamily: "var(--mono)" }}>{o.symbol}</span>
              {o.name !== o.symbol && <span style={{ color: "var(--cp-ink-3)" }}>{o.name}</span>}
            </button>
          ))}
        </div>
      )}
      {problem && problem.kind !== "choose" && (
        <span
          id="desk-fno-symbol-problem"
          role="alert"
          data-testid={{ format: "desk-fno-symbol-error", unknown: "desk-fno-symbol-unknown", nomatch: "desk-fno-symbol-nomatch", search_failed: "desk-fno-symbol-search-error" }[problem.kind]}
          style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-danger)" }}
        >
          {problem.kind === "format"
            ? "Type an NSE ticker (letters, digits, & or -) or part of a company name."
            : problem.kind === "unknown"
              ? `${problem.name ? `${problem.name} (${problem.symbol})` : problem.symbol} is not in NSE’s F&O list${problem.day ? ` for ${fmtDay(problem.day)}` : ""} (${fmtNum(problem.count)} stocks have futures), so it has no option chain to load.`
              : problem.kind === "nomatch"
                ? `No stock matches “${problem.query}”. Try the NSE ticker, e.g. RELIANCE.`
                : "Stock search is unavailable. Type the NSE ticker instead."}
        </span>
      )}
    </div>
  );
}

/** PRD §10.2: whether the NSE F&O master lists the loaded stock (never assumed from a cash listing). */
function Eligibility({ symbol }: { symbol: string }) {
  const scan = useBuildup(true);
  const row = buildupRowFor(scan.data, symbol);
  if (scan.isPending || scan.isError) return null;
  const text = row?.fnoEligible === true
    ? `F&O eligible · NSE F&O master${row.masterDate ? ` ${shortDay(row.masterDate)}` : ""}`
    : row?.fnoEligible === false
      ? "Not on the NSE F&O master, though the bhavcopy has its futures"
      : row ? "In the bhavcopy's stock futures; the F&O master has no row for it" : "Not in the scan's F&O list";
  return (
    <span data-testid="desk-fno-eligible" data-eligible={row?.fnoEligible == null ? "" : String(row.fnoEligible)} className="cp-mono-note" title={scan.data.sources.master ?? undefined}>
      {text}
    </span>
  );
}

type ExpiryKey = "weekly" | "monthly" | "nearest";

function ExpiryChooser({ oc, futures, symbol, onPick }: { oc: ReturnType<typeof useOptionChain>; futures: FnoResult<FnoFutures> | undefined; symbol: string; onPick: (e: string) => void }) {
  const { expiries, list, expiry } = oc;
  if (expiries.isPending) return <span className="cp-mono-note">Loading expiries</span>;
  if (expiries.isError) {
    return (
      <span data-testid="desk-fno-expiry-error" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>
        The expiry list didn’t load, so only the nearest expiry is shown.{" "}
        <button type="button" onClick={() => expiries.refetch()} style={{ padding: 0, border: 0, background: "none", fontSize: 12, color: "var(--cp-ink)", cursor: "pointer" }}>Retry ›</button>
      </span>
    );
  }
  if (!list.length || expiry == null) return null;
  const upcoming = list.filter((e) => e.days_to_expiry > 0);
  const pool = upcoming.length ? upcoming : list;
  if (futures?.kind !== "ok") {
    // Without the futures list a monthly expiry cannot be told from a weekly one.
    const nearest = pool[0];
    return (
      <Segmented<string>
        label="Expiry"
        testId="desk-fno-expiry"
        value={expiry}
        onChange={onPick}
        options={[{ value: nearest.expiry, key: "nearest", label: `Nearest · ${shortDay(nearest.expiry)}`, title: "The futures did not load, so weekly and monthly cannot be told apart" }]}
      />
    );
  }
  // NSE lists futures for monthly expiries only, so an option expiry a future shares is a monthly one.
  const futDays = futures.data.futures.map((f) => f.expiry);
  const last = futDays.length ? futDays.reduce((a, b) => (a > b ? a : b)) : null;
  const monthly = pool.find((e) => futDays.includes(e.expiry)) ?? null;
  const weekly = pool.find((e) => !futDays.includes(e.expiry) && (last == null || e.expiry < last)) ?? null;
  const opts: Array<SegOption<string>> = [
    weekly
      ? { value: weekly.expiry, key: "weekly", label: `Weekly · ${shortDay(weekly.expiry)}`, title: `${fmtDay(weekly.expiry)} · ${fmtNum(weekly.days_to_expiry)} days` }
      : { value: "weekly-none", key: "weekly", label: "Weekly", disabled: true, title: `No weekly expiry is listed for ${symbol}` },
    monthly
      ? { value: monthly.expiry, key: "monthly", label: `Monthly · ${shortDay(monthly.expiry)}`, title: `${fmtDay(monthly.expiry)} · ${fmtNum(monthly.days_to_expiry)} days` }
      : { value: "monthly-none", key: "monthly", label: "Monthly", disabled: true, title: `No monthly expiry is listed for ${symbol}` },
  ];
  return <Segmented<string> label="Expiry" testId="desk-fno-expiry" value={expiry} onChange={onPick} options={opts} />;
}

// ── NIFTY & BANKNIFTY ────────────────────────────────────────────────────

/** The index's day change from the markets tape, only when the tape is the same closed session as the bhavcopy. */
function sameSessionChange(home: MarketsHome | undefined, symbol: string, asOf: string): { change: number; pct: number | null } | null {
  const name = indexNameForSymbol(symbol);
  if (!home || !name || home.is_live || istDay(home.as_of ?? null) !== asOf) return null;
  const idx = home.indices.find((i) => i.name.trim().toLowerCase() === name.toLowerCase());
  return idx?.change != null ? { change: idx.change, pct: idx.change_pct } : null;
}

function indexHeadline(s: FnoSummary, investor: boolean): string {
  const put = s.max_put_oi?.strike;
  const call = s.max_call_oi?.strike;
  if (put == null || call == null || s.spot == null) return "The chain has no open-interest walls to read.";
  if (investor) {
    return s.spot < put
      ? `Below the level where most put bets sit (${fmtLevel(put)}).`
      : s.spot > call ? `Above the level where most call bets sit (${fmtLevel(call)}).` : `Most open bets sit between ${fmtLevel(put)} and ${fmtLevel(call)}.`;
  }
  return s.spot < put
    ? `Spot is below the ${fmtLevel(put)} put wall.`
    : s.spot > call ? `Spot is above the ${fmtLevel(call)} call wall.` : `Spot sits between the ${fmtLevel(put)} put wall and the ${fmtLevel(call)} call wall.`;
}

function IndexCard({ symbol, onOpen }: { symbol: string; onOpen: (s: string) => void }) {
  const { mobile } = useCopilotShell();
  const { persona } = useDesk();
  const investor = persona === "investor";
  const home = useMarketOverview();
  const { state } = useOptionChain(symbol, null);
  const fq = useFnoFutures(symbol);
  const scan = useBuildup(true);
  const near = nearFutureOf(fq.data);
  const id = `desk-fno-card-${symbol}`;
  const futuresLine = fq.isPending ? "Loading" : fq.isError ? "Didn’t load" : fq.data.kind === "none" ? "No futures rows" : "No contract listed";
  const ix = indexRowFor(scan.data, symbol);
  const meta = ix?.label ? BUILDUP_META[ix.label] : null;
  const pill = meta
    ? <span data-testid={`${id}-buildup`} className="cp-pill" data-tone={meta.tone === "ink" ? undefined : meta.tone} title={`${meta.rule} · index futures, ${scan.data?.asOf ? shortDay(scan.data.asOf) : "end of day"}`}>{meta.label}</span>
    : <span data-testid={`${id}-buildup`} className="cp-pill" title={scan.isPending ? "Reading the build-up scan" : scan.isError ? "The build-up scan didn’t load" : ix ? "A price or OI change is missing" : "The scan has no index futures row for it"}>Build-up —</span>;
  return (
    <section data-testid={id} className="cp-card flex flex-col min-w-0" style={{ overflow: "hidden" }}>
      <CardHead testId={`${id}-head`} meta={pill}>
        {symbol}
        {state.status === "ok" && <span style={{ color: "var(--cp-ink-4)" }}>{fmtDay(state.chain.summary.expiry)} expiry</span>}
      </CardHead>
      <div className="flex flex-col" style={{ gap: 14, padding: mobile ? 14 : 18 }}>
        <FnoGate symbol={symbol} state={state} testId={id}>
          {(chain) => {
            const s = chain.summary;
            const words = basisWords(near?.future.basis ?? null);
            const chg = sameSessionChange(home.data, symbol, s.as_of);
            return (
              <>
                <div className="flex flex-wrap items-baseline" style={{ gap: "4px 12px" }}>
                  <span data-testid={`${id}-spot`} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 36, lineHeight: 1, letterSpacing: "-0.03em" }}>{s.spot == null ? "—" : fmtNum(s.spot, 2)}</span>
                  <span
                    data-testid={`${id}-change`}
                    className="cp-num"
                    title={chg ? `From the markets tape for ${fmtDay(s.as_of)}` : "The bhavcopy has no previous spot, and the markets tape is for another session"}
                    style={{ fontSize: 12, color: chg ? TONE_COLOR[signTone(chg.change)] : "var(--cp-ink-4)" }}
                  >
                    {chg ? `${fmtSigned(chg.change)}${chg.pct != null ? ` (${fmtSigned(chg.pct)}%)` : ""}` : "change —"}
                  </span>
                  <span className="cp-mono-note">end of day {fmtDay(s.as_of)}</span>
                </div>
                <span data-testid={`${id}-headline`} style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.2, letterSpacing: "-0.01em" }}>{indexHeadline(s, investor)}</span>
                <div className="flex flex-col" style={{ gap: 6 }}>
                  <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>OI range and expected move</span>
                  <OiRangeBar s={s} testId={id} />
                </div>
                <div className="flex flex-col">
                  <CardRow k="Futures · premium" testId={`${id}-futures`}>
                    {near?.future.settle != null
                      ? `${fmtNum(near.future.settle, 2)}${words === "level" ? " · level with spot" : words ? ` · ${fmtSigned(near.future.basis)} ${words}` : ""}`
                      : futuresLine}
                  </CardRow>
                  <CardRow k="Futures · day change" testId={`${id}-fut-day`}>
                    {near ? `${near.future.change == null ? "—" : `${fmtSigned(near.future.change)} (${fmtSigned(near.future.change_pct)}%)`}${near.future.prev_close != null ? ` · prev ${fmtNum(near.future.prev_close, 2)}` : " · no previous close"}` : futuresLine}
                  </CardRow>
                  <CardRow k={investor ? "Open bets (OI) change · futures" : "Futures OI change"} testId={`${id}-fut-oi-change`}>{near ? fmtQty(near.future.change_in_oi, { signed: true }) : futuresLine}</CardRow>
                  <CardRow k={investor ? "Futures price vs the index" : "Futures chg · cash check"} testId={`${id}-fut-chg`}>
                    {ix ? `${ix.priceChgPct == null ? "—" : `${fmtSigned(ix.priceChgPct)}%`} · ${ix.cashConfirmation === "confirms" ? "same way as the index" : ix.cashConfirmation === "diverges" ? "opposite to the index" : "no index move to compare"}` : "—"}
                  </CardRow>
                  <CardRow k="Put-call ratio · OI" testId={`${id}-pcr`}>{s.pcr == null ? "—" : fmtNum(s.pcr, 2)}</CardRow>
                  <CardRow k="Max pain" testId={`${id}-max-pain`}>{s.max_pain == null ? "—" : fmtLevel(s.max_pain)}</CardRow>
                  <CardRow k={investor ? "Expected volatility · swing" : "ATM IV · expected move"} testId={`${id}-move`}>
                    {s.atm_iv == null ? "—" : `${fmtNum(s.atm_iv, 2)}%`} · {s.expected_move == null ? "—" : `±${fmtNum(s.expected_move, 2)}`}{s.expected_move_pct != null ? ` (${fmtNum(s.expected_move_pct, 2)}%)` : ""}
                  </CardRow>
                </div>
                <div>
                  <button type="button" data-testid={`${id}-open`} onClick={() => onOpen(symbol)} style={{ padding: 0, border: 0, background: "none", fontFamily: "var(--sans)", fontSize: 13, color: "var(--mint)", cursor: "pointer" }}>
                    Open the {symbol} option chain ›
                  </button>
                </div>
              </>
            );
          }}
        </FnoGate>
      </div>
    </section>
  );
}

// ── tab ──────────────────────────────────────────────────────────────────

export default function FnoTab() {
  const { mobile } = useCopilotShell();
  const { persona } = useDesk();
  const investor = persona === "investor";
  const [symbol, setSymbol] = useState<string>(FNO_INDICES[0].symbol);
  /** The expiry chosen for `symbol`; null = the nearest still to come. */
  const [picked, setPicked] = useState<string | null>(null);
  const [view, setView] = useState<FnoView>("buildup");
  const oc = useOptionChain(symbol, picked);
  const fq = useFnoFutures(symbol);
  const scan = useBuildup(true);
  const near = nearFutureOf(fq.data);
  const futuresNote = fq.isPending ? "Loading the futures" : fq.isError ? "The futures didn’t load" : fq.data.kind === "none" ? "No futures rows" : "No futures contract listed";

  const pick = (s: string) => {
    setSymbol(s);
    setPicked(null);
  };
  const openChain = (s: string) => {
    pick(s);
    setView("chain");
  };
  const chain = oc.state.status === "ok" ? oc.state.chain : null;

  const row = isIndexUnderlying(symbol) ? indexRowFor(scan.data, symbol) : buildupRowFor(scan.data, symbol);
  const bu: UnderlyingBuildup = isIndexUnderlying(symbol) && !row && !scan.isPending && !scan.isError
    ? { status: "index" }
    : scan.isPending ? { status: "loading" }
      : scan.isError ? { status: "error" }
        : row ? { status: "ok", label: row.label, priceChgPct: row.priceChgPct, oiChgPct: row.oiChgPct, asOf: scan.data.asOf }
          : { status: "absent" };

  const views: Array<{ key: FnoView; label: string }> = [
    { key: "buildup", label: "OI build-up · F&O stocks" },
    { key: "indices", label: "NIFTY & BANKNIFTY" },
    { key: "chain", label: `Option chain OI · ${symbol}` },
    { key: "strategies", label: "Paper strategies" },
  ];

  return (
    <div data-testid="desk-fno" data-symbol={symbol} className="flex flex-col min-w-0" style={{ gap: mobile ? 16 : 20 }}>
      <div className="flex items-end justify-between" style={{ gap: 16, flexWrap: mobile ? "wrap" : "nowrap" }}>
        <div className="flex min-w-0 flex-col" style={{ gap: 12, flex: "1 1 auto" }}>
          <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <span className="cp-eyebrow">Options &amp; futures lab · NSE F&amp;O</span>
            <Pill tone="mint">{investor ? "Investor mode" : "Trader mode"}</Pill>
            <Pill tone="indigo">Analysis only</Pill>
            <Pill>End of day</Pill>
          </span>
          <h1 data-testid="desk-fno-title" className="cp-display m-0" style={{ fontSize: mobile ? 32 : 44, lineHeight: 1.05, letterSpacing: "-0.02em" }}>
            Build, test and understand <em>option trades</em>.
          </h1>
        </div>
        <SpotBlock symbol={symbol} state={oc.state} futures={fq.data} />
      </div>

      <UnderlyingRow
        symbol={symbol}
        onPick={pick}
        expiry={oc.state.status !== "none" ? <ExpiryChooser oc={oc} futures={fq.data} symbol={symbol} onPick={setPicked} /> : <span className="cp-mono-note">—</span>}
      />

      <FnoGate symbol={symbol} state={oc.state} testId="desk-fno-stats">
        {(c) => (
          <div className="flex flex-col" style={{ gap: 8 }}>
            <StatGrid
              testId="desk-fno-stats"
              columns={mobile ? 2 : 4}
              tiles={chainTiles(c.summary, near, futuresNote, bu, persona)}
              note={
                <>
                  {investor
                    ? "Expected volatility and the expected swing are worked out from option prices at the close (Black-76); they are estimates, not quotes or forecasts. "
                    : `IV and the expected move: ${modelLabel(c.summary)}. They are estimates, not quotes; the expected move is what the ATM straddle cost at the close, not a forecast. `}
                  PCR is put open interest ÷ call open interest over every strike; max pain is the strike where open options pay out least at expiry; build-up reads the stock future’s price change against the change in its open interest over every expiry.
                </>
              }
            />
            {fq.isError && <QueryProblem what={`${symbol} futures`} error={fq.error} onRetry={() => fq.refetch()} />}
            <span data-testid="desk-fno-heuristic" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{HEURISTIC_NOTE} Research and hypothetical scenarios only.</span>
            <TrustLine testId="desk-fno-trust" source="NSE F&O bhavcopy" asOf={c.summary.as_of ? shortDay(c.summary.as_of) : null} mode="eod" maker="model" method={`IV and expected move: ${modelLabel(c.summary)}`} />
          </div>
        )}
      </FnoGate>

      {investor && (
        <div data-testid="desk-fno-read-first" role="note" className="flex flex-wrap items-baseline" style={{ gap: "6px 12px", padding: "12px 16px", borderRadius: 12, border: `1px solid ${TONE_LINE.amber}`, background: TONE_SOFT.amber }}>
          <span className="cp-eyebrow" style={{ color: "var(--amber)" }}>Read first</span>
          <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)", flex: "1 1 300px", minWidth: 0 }}>
            {SEBI_FNO_NOTE} Options and futures can lose more than you put in, quickly. Everything here explains end-of-day data; Nivesh cannot place orders.
          </span>
        </div>
      )}

      <UnderlineTabs<FnoView> tabs={views} value={view} onChange={setView} label="Options and futures views" idPrefix="desk-fno-view" />

      <div role="tabpanel" aria-label={views.find((v) => v.key === view)?.label} className="flex flex-col min-w-0" style={{ gap: 12 }}>
        {view === "buildup" && (
          <BuildupView
            onOpen={openChain}
            selected={symbol}
            loaded={{ symbol, volume: near?.future.volume ?? null, pcr: chain?.summary.pcr ?? null, iv: chain?.summary.atm_iv ?? null }}
          />
        )}
        {view === "indices" && (
          <div data-testid="desk-fno-indices" className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "repeat(2,minmax(0,1fr))", gap: 16, alignItems: "start" }}>
            {FNO_INDICES.map((i) => <IndexCard key={i.symbol} symbol={i.symbol} onOpen={openChain} />)}
          </div>
        )}
        {view === "chain" && (chain
          ? <ChainOiTable chain={chain} />
          : oc.state.status === "loading" ? <LoadingBlock label={`Loading the ${symbol} chain`} rows={4} />
            : <span data-testid="desk-fno-chain-missing" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>No option chain for {symbol}; see the note above.</span>)}
        {view === "strategies" && <StrategiesView symbol={symbol} state={oc.state} near={near} futuresNote={futuresNote} onLoad={pick} />}
      </div>

    </div>
  );
}
