/**
 * Smart trading desk — 06 Options & futures lab. Design: "Smart Trading Desk",
 * Options & futures lab. Analysis only: nothing here places an order or opens a
 * trade.
 *
 * Data (all end of day, one NSE F&O bhavcopy a day; screens/trading/fno.ts):
 *   expiry choice                  GET /api/fno/{symbol}/expiries              (useOptionChain)
 *   stats, option chain OI,        GET /api/fno/{symbol}/chain?expiry=         (useOptionChain)
 *   NIFTY & BANKNIFTY cards
 *   futures price, basis, OI chg   GET /api/fno/{symbol}/futures               (useFnoFutures)
 *
 * Implied volatility and the expected move are the chain route's model
 * estimates (Black-76 on end-of-day prices, backend/services/option_pricing.py),
 * labelled as such. An expiry is called "monthly" only when a futures contract
 * expires the same day (NSE lists futures for monthly expiries only); other
 * expiries show their date and days to expiry, with no weekly label guessed.
 *
 * Not connected:
 *   OI build-up across F&O stocks  futures rows carry no previous close (so no price change and no
 *                                  build-up label), and no route scans every F&O stock at once
 *   one-click paper strategies     no route generates rule-based strategies, and the paper engine
 *                                  records only its own selections; the Options lab's builder is linked
 */
import { useState, type FormEvent, type ReactNode } from "react";
import { StockIcon, StockName } from "../../components/EntityIcon";
import { Btn, LoadingBlock, NotConnected, Pill, fmtNum } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { TabBar } from "../markets/parts";
import { fmtIv, fmtMove, modelLabel } from "../trading/ModelViews";
import { fmtLevel } from "../trading/PayoffResult";
import { FNO_INDICES, cleanSymbol, isIndexUnderlying, useFnoFutures, useOptionChain, type ChainState, type FnoFutures, type FnoResult } from "../trading/fno";
import { Choices, INPUT_STYLE, QueryProblem, SEBI_FNO_NOTE, fmtDay, fmtQty, fmtSigned } from "../trading/parts";
import { CardRow, ChainOiTable, FnoGate, OiRangeBar, StatGrid, basisWords, chainTiles, nearFutureOf } from "./fno-parts";

type FnoView = "chain" | "indices" | "buildup" | "strategies";

const VIEWS: Array<{ key: FnoView; label: string }> = [
  { key: "chain", label: "Option chain OI" },
  { key: "indices", label: "NIFTY & BANKNIFTY" },
  { key: "buildup", label: "OI build-up · F&O stocks" },
  { key: "strategies", label: "Strategies" },
];

const BUILDUP_NEEDS = [
  "The day’s price change on futures rows: the data platform’s futures read (nidp/services/daas_api/routers/fno.py) sends the close and the change in OI but no previous close, so neither the price change nor a build-up label can be worked out.",
  "An all-stocks scan: the F&O routes (GET /api/fno/{symbol}/…) read one underlying at a time; nothing returns the ~180 F&O stocks with their nearest future in one call.",
  "The four build-up labels exist today only on option legs, one underlying at a time (oi_buildup on GET /api/fno/{symbol}/chain), and only once the previous close is sent.",
];

const STRATEGY_NEEDS = [
  "A rules engine that turns the chain (IV, OI walls, expected move) into candidate structures, served by a read route. None exists.",
  "A way to record a user-chosen paper options trade. The paper engine (GET /api/paper-trades/*) records only its own frozen equity selections; there is no create route, and this screen adds no write calls.",
];

// ── header ───────────────────────────────────────────────────────────────

function SpotBlock({ symbol, state, futures }: { symbol: string; state: ChainState; futures: FnoResult<FnoFutures> | undefined }) {
  const { mobile } = useCopilotShell();
  const summary = state.status === "ok" ? state.chain.summary : null;
  const fut = futures?.kind === "ok" ? futures.data : null;
  const spot = summary?.spot ?? fut?.spot ?? null;
  const asOf = summary?.as_of ?? fut?.as_of ?? null;
  if (state.status === "loading" && !fut) return <div style={{ flex: "0 1 220px", minWidth: 0 }}><LoadingBlock label={`Loading the ${symbol} spot`} rows={1} /></div>;
  if (spot == null) return null;
  return (
    <div className="flex flex-col" style={{ gap: 2, alignItems: mobile ? "flex-start" : "flex-end" }}>
      <span className="cp-num flex items-center" style={{ gap: 6, fontSize: 11, color: "var(--cp-ink-3)" }}>
        {!isIndexUnderlying(symbol) && <StockIcon symbol={symbol} size={18} />}
        {symbol} · SPOT
      </span>
      <span data-testid="desk-fno-spot" className="cp-metric">{fmtNum(spot, 2)}</span>
      {asOf && <span data-testid="desk-fno-asof" className="cp-mono-note">bhavcopy · {fmtDay(asOf)} · end of day</span>}
    </div>
  );
}

// ── underlying and expiry ────────────────────────────────────────────────

function UnderlyingChooser({ symbol, onPick }: { symbol: string; onPick: (s: string) => void }) {
  const [typed, setTyped] = useState("");
  const [bad, setBad] = useState(false);
  const options: Array<{ value: string; label: ReactNode }> = FNO_INDICES.map((i) => ({ value: i.symbol, label: i.symbol }));
  // A loaded underlying sits beside the two indices while it is the one shown; a company gets its icon.
  if (!options.some((o) => o.value === symbol)) {
    options.push({ value: symbol, label: isIndexUnderlying(symbol) ? symbol : <StockName symbol={symbol} size={18} testId="desk-fno-symbol-stock" /> });
  }
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const s = cleanSymbol(typed);
    setBad(s == null);
    if (s == null) return;
    setTyped("");
    onPick(s);
  };
  return (
    <div className="flex flex-wrap items-center" style={{ gap: "8px 10px", minWidth: 0 }}>
      <span className="cp-eyebrow">Underlying</span>
      <Choices label="Underlying" testId="desk-fno-symbol" value={symbol} onChange={onPick} options={options} />
      <form onSubmit={submit} className="flex items-center" style={{ gap: 6, flex: "0 1 280px", minWidth: 0 }}>
        <input
          data-testid="desk-fno-symbol-input"
          aria-label="F&O stock ticker"
          aria-invalid={bad}
          placeholder="F&O stock, e.g. RELIANCE"
          maxLength={20}
          autoCapitalize="characters"
          spellCheck={false}
          value={typed}
          onChange={(e) => { setTyped(e.target.value); setBad(false); }}
          style={INPUT_STYLE}
        />
        <Btn type="submit" data-testid="desk-fno-symbol-load" style={{ flex: "none" }}>Load</Btn>
      </form>
      {bad && (
        <span role="alert" data-testid="desk-fno-symbol-error" style={{ fontSize: 12, color: "var(--cp-danger)" }}>
          A ticker is letters, digits, &amp; or -, up to 20 characters.
        </span>
      )}
    </div>
  );
}

function ExpiryChooser({ oc, futures, onPick }: { oc: ReturnType<typeof useOptionChain>; futures: FnoResult<FnoFutures> | undefined; onPick: (e: string) => void }) {
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
  // NSE lists futures for monthly expiries only, so an option expiry a future shares is a monthly one.
  const futureDays = new Set(futures?.kind === "ok" ? futures.data.futures.map((f) => f.expiry) : []);
  return (
    <label className="flex items-center" style={{ gap: 8, minWidth: 0, maxWidth: "100%" }}>
      <span className="cp-eyebrow">Expiry</span>
      <select data-testid="desk-fno-expiry" value={expiry} onChange={(e) => onPick(e.target.value)} style={{ ...INPUT_STYLE, width: "auto", maxWidth: "100%" }}>
        {list.map((e) => (
          <option key={e.expiry} value={e.expiry}>
            {fmtDay(e.expiry)} · {e.days_to_expiry === 0 ? "expired at this close" : `${fmtNum(e.days_to_expiry)} ${e.days_to_expiry === 1 ? "day" : "days"}`}{futureDays.has(e.expiry) ? " · monthly" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

// ── NIFTY & BANKNIFTY ────────────────────────────────────────────────────

function IndexCard({ symbol, onOpen }: { symbol: string; onOpen: (s: string) => void }) {
  const { state } = useOptionChain(symbol, null);
  const fq = useFnoFutures(symbol);
  const near = nearFutureOf(fq.data);
  const id = `desk-fno-card-${symbol}`;
  const futuresLine = fq.isPending ? "Loading" : fq.isError ? "Didn’t load" : fq.data.kind === "none" ? "No futures rows" : "No contract listed";
  return (
    <section data-testid={id} className="cp-card flex flex-col min-w-0" style={{ flex: "1 1 300px", gap: 12, padding: 16 }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 12px" }}>
        <span className="cp-eyebrow">{symbol} · options and futures</span>
        {state.status === "ok" && <span className="cp-mono-note">{fmtDay(state.chain.summary.expiry)} expiry · as of {fmtDay(state.chain.summary.as_of)}</span>}
      </div>
      <FnoGate symbol={symbol} state={state} testId={id}>
        {(chain) => {
          const s = chain.summary;
          const words = basisWords(near?.future.basis ?? null);
          return (
            <>
              <div className="flex flex-col" style={{ gap: 2 }}>
                <span className="cp-mono-note">End-of-day spot</span>
                <span data-testid={`${id}-spot`} className="cp-metric">{s.spot == null ? "—" : fmtNum(s.spot, 2)}</span>
              </div>
              <OiRangeBar s={s} testId={id} />
              <div className="flex flex-col">
                <CardRow k="Futures · premium" testId={`${id}-futures`}>
                  {near?.future.settle != null
                    ? `${fmtNum(near.future.settle, 2)}${words === "level" ? " · level with spot" : words ? ` · ${fmtSigned(near.future.basis)} ${words}` : ""}`
                    : futuresLine}
                </CardRow>
                <CardRow k="Futures OI change" testId={`${id}-fut-oi-change`}>{near ? fmtQty(near.future.change_in_oi, { signed: true }) : futuresLine}</CardRow>
                <CardRow k="Put-call ratio · OI" testId={`${id}-pcr`}>{s.pcr == null ? "—" : fmtNum(s.pcr, 2)}</CardRow>
                <CardRow k="Max pain" testId={`${id}-max-pain`}>{s.max_pain == null ? "—" : fmtLevel(s.max_pain)}</CardRow>
                <CardRow k="ATM IV · expected move" testId={`${id}-move`}>
                  {fmtIv(s.atm_iv)} · {fmtMove(s.expected_move)}{s.expected_move_pct != null ? ` (${fmtNum(s.expected_move_pct, 2)}%)` : ""}
                </CardRow>
              </div>
              <div>
                <button type="button" data-testid={`${id}-open`} className="cp-chip" onClick={() => onOpen(symbol)}>
                  Open the {symbol} option chain ›
                </button>
              </div>
            </>
          );
        }}
      </FnoGate>
    </section>
  );
}

// ── strategies ───────────────────────────────────────────────────────────

function Strategies() {
  const { go } = useCopilotShell();
  return (
    <div className="flex flex-col" style={{ gap: 12 }}>
      <div data-testid="desk-fno-strategies" className="cp-card flex flex-col items-start" style={{ gap: 8, padding: "18px 18px" }}>
        <span className="cp-eyebrow">Strategy builder · Options lab</span>
        <span style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)", maxWidth: 620 }}>
          Put together calls and puts on any F&amp;O underlying and see the payoff at expiry, the model’s chance of profit and the net Greeks, priced from the end-of-day chain.
        </span>
        <button type="button" data-testid="desk-fno-open-optlab" className="cp-chip" onClick={() => go("tool/optlab")} style={{ borderColor: "var(--mint-line)", color: "var(--mint)", whiteSpace: "normal", textAlign: "left" }}>
          Build and test a strategy (payoff, Greeks, chance of profit) ›
        </button>
      </div>
      <NotConnected
        testId="desk-fno-strategies-not-connected"
        title="One-click paper strategies"
        body="The design lists strategies generated from rules, each with a paper-trade button. Nothing generates them yet, and paper trades are chosen by the model engine alone, so there is no way to open one from here."
        needs={STRATEGY_NEEDS}
      />
    </div>
  );
}

// ── tab ──────────────────────────────────────────────────────────────────

export default function FnoTab() {
  const { mobile } = useCopilotShell();
  const [symbol, setSymbol] = useState<string>(FNO_INDICES[0].symbol);
  /** The expiry chosen for `symbol`; null = the nearest still to come. */
  const [picked, setPicked] = useState<string | null>(null);
  const [view, setView] = useState<FnoView>("chain");
  const oc = useOptionChain(symbol, picked);
  const fq = useFnoFutures(symbol);
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

  return (
    <div data-testid="desk-fno" className="flex flex-col min-w-0" style={{ gap: 16 }}>
      <div className="flex flex-wrap items-end justify-between" style={{ gap: 12 }}>
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <span className="cp-eyebrow">Options &amp; futures lab · NSE F&amp;O</span>
          <Pill tone="indigo">Analysis only</Pill>
          <Pill>End of day</Pill>
        </span>
        <SpotBlock symbol={symbol} state={oc.state} futures={fq.data} />
      </div>

      <div className="flex flex-wrap items-center" style={{ gap: "10px 20px" }}>
        <UnderlyingChooser symbol={symbol} onPick={pick} />
        {oc.state.status !== "none" && <ExpiryChooser oc={oc} futures={fq.data} onPick={setPicked} />}
      </div>

      <FnoGate symbol={symbol} state={oc.state} testId="desk-fno-stats">
        {(c) => (
          <div className="flex flex-col" style={{ gap: 8 }}>
            <StatGrid testId="desk-fno-stats" columns={mobile ? 2 : 4} tiles={chainTiles(c.summary, near, futuresNote)} />
            {fq.isError && <QueryProblem what={`${symbol} futures`} error={fq.error} onRetry={() => fq.refetch()} />}
            <span data-testid="desk-fno-model-note" style={{ fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
              IV and the expected move: {modelLabel(c.summary)}. They are estimates, not quotes; the expected move is what the ATM straddle cost at the close, not a forecast.
            </span>
          </div>
        )}
      </FnoGate>

      <TabBar<FnoView> tabs={VIEWS} value={view} onChange={setView} label="Options and futures views" idPrefix="desk-fno-view" />

      <div className="flex flex-col min-w-0" style={{ gap: 12 }}>
        {view === "chain" && (chain
          ? <ChainOiTable chain={chain} />
          : oc.state.status === "loading" ? <LoadingBlock label={`Loading the ${symbol} chain`} rows={4} /> : null)}
        {view === "indices" && (
          <div data-testid="desk-fno-indices" className="flex flex-wrap items-start" style={{ gap: 12 }}>
            {FNO_INDICES.map((i) => <IndexCard key={i.symbol} symbol={i.symbol} onOpen={openChain} />)}
          </div>
        )}
        {view === "buildup" && (
          <NotConnected
            testId="desk-fno-buildup-not-connected"
            title="OI build-up across F&O stocks"
            body="The design plots every F&O stock by its price change and open-interest change, as long build-up, short build-up, short covering or long unwinding. That needs each stock’s futures price change for the day and a scan of all F&O stocks; neither reaches the app yet, so nothing is drawn."
            needs={BUILDUP_NEEDS}
          />
        )}
        {view === "strategies" && <Strategies />}
      </div>

      <span data-testid="desk-fno-sebi" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-danger)" }}>
        {SEBI_FNO_NOTE} Nivesh cannot place orders; everything here is analysis of end-of-day data.
      </span>
    </div>
  );
}
