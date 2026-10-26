/**
 * F&O lab · 01 Market Intelligence — the market reading for one underlying, each value with its source and time.
 *
 *   Regime            the desk regime (GET /api/macro/today): the rule, its version, the session it read, the inputs and
 *                     what would change the reading. It is a market-wide reading of the Nifty 50, the same for every
 *                     underlying. Realised-vs-implied, liquidity and events are not part of the rule yet.
 *   Futures build-up  one row per expiry (GET /api/fno/{sym}/futures), each with its own label: a sum over expiries
 *                     would hide expiries that disagree.
 *   Options           OI by strike, PCR, max pain and walls from the end-of-day chain; ATM IV per expiry (term
 *                     structure) and 25-delta skew from the chain's Black-76 estimates. IV rank needs IV history,
 *                     which does not exist.
 *   Quote quality     bid/ask spread, quote age and staleness from the live feed's option cache (NIFTY, BANKNIFTY).
 *
 * Data: market-intel.ts. Analysis only.
 */
import { useState, type ReactNode } from "react";
import { LoadingBlock, Pill, Section, Tiles, TONE_COLOR, fmtNum, fmtPct, type TileItem, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { QueryProblem, fmtDay } from "../trading/parts";
import { strikesAround, useFnoChain, useFnoFutures, useOptionChain, type FnoChain, type OiBuildup } from "../trading/fno";
import { DESK_REGIME_LABEL, useMacroToday, type DeskRegime, type RegimeFlip } from "../tradingdesk/overview-data";
import { TrustLine } from "../tradingdesk/trust";
import {
  MI_UNDERLYINGS, ON_LIVE_FEED, expiriesDisagree, expiryBuildups, quoteQuality, skew25, useLiveOptionChain,
  type ExpiryBuildup, type LiveChain, type MiUnderlying,
} from "./market-intel";
import { GapNote, KvRows, SourceCards, quiet, type SourceItem } from "./parts";
import { KiteSessions } from "./KiteSessions";

const BUILDUP_TONE: Record<OiBuildup, Tone> = {
  "long build-up": "mint", "short build-up": "danger", "short covering": "amber", "long unwinding": "amber",
};

const th = { textAlign: "left", padding: "6px 8px 10px", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--cp-ink-3)", fontWeight: 400, borderBottom: "1px solid var(--cp-line)", whiteSpace: "nowrap" } as const;
const td = { padding: "10px 8px", borderBottom: "1px solid var(--cp-line)", fontSize: 13, fontVariantNumeric: "tabular-nums" } as const;

const signedPct = (v: number | null | undefined, digits = 2) => fmtPct(v, { signed: true, digits });
const toneOf = (v: number | null | undefined): Tone => (v == null || v === 0 ? "ink" : v > 0 ? "mint" : "danger");

// ── underlying picker ────────────────────────────────────────────────────

function Picker({ value, onPick }: { value: MiUnderlying; onPick: (u: MiUnderlying) => void }) {
  return (
    <div role="radiogroup" aria-label="Underlying" className="flex flex-wrap" style={{ gap: 2, padding: 3, borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-1)", alignSelf: "flex-start", maxWidth: "100%" }}>
      {MI_UNDERLYINGS.map((u) => {
        const on = u === value;
        return (
          <button
            key={u}
            type="button"
            role="radio"
            aria-checked={on}
            data-testid={`fnolab-mi-u-${u}`}
            onClick={() => onPick(u)}
            style={{ height: 32, padding: "0 12px", borderRadius: 9, border: `1px solid ${on ? "var(--mint-line)" : "transparent"}`, background: on ? "var(--mint-soft)" : "transparent", color: on ? "var(--mint)" : "var(--cp-ink-2)", fontFamily: "var(--mono)", fontSize: 12.5, cursor: "pointer" }}
          >
            {u}
          </button>
        );
      })}
    </div>
  );
}

// ── regime ───────────────────────────────────────────────────────────────

const FLIP_INPUT: Record<RegimeFlip["input"], string> = { nifty_close: "Nifty 50 closes", india_vix: "India VIX", advancing_share_pct: "The advancing share" };
const FLIP_COND: Record<RegimeFlip["condition"], string> = { below: "below", above: "above", at_or_above: "at or above", at_or_below: "at or below" };

function StatePill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <Pill tone={tone}>{children}</Pill>;
}

function RegimePanel({ desk, unavailable, quality }: { desk: DeskRegime | null; unavailable: string | null; quality: ReactNode }) {
  if (!desk || desk.key == null) {
    return (
      <Section title="Market regime" note="desk regime">
        <div data-testid="fnolab-mi-regime-none" className="flex flex-col" style={{ gap: 6 }}>
          <span style={{ fontFamily: "var(--display)", fontSize: 22 }}>Regime not available</span>
          <span style={quiet}>{desk?.reason ?? unavailable ?? "The route sent no regime for the latest session. None is shown in its place."}</span>
        </div>
      </Section>
    );
  }
  const r = desk.rule;
  const factors: Array<{ k: string; v: ReactNode }> = [
    {
      k: "Trend",
      v: <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span>Nifty 50 {fmtNum(desk.niftyClose, 2)} vs its {r.averageSessions ?? "—"}-session average {fmtNum(desk.niftyAverage, 2)} ({signedPct(desk.gapPct)})</span>
        <StatePill tone={desk.trend === "up" ? "mint" : desk.trend === "down" ? "danger" : "ink"}>{desk.trend ?? "unknown"}</StatePill>
      </span>,
    },
    {
      k: "Volatility",
      v: <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span>India VIX {fmtNum(desk.vix, 2)} against the {fmtNum(r.vixHigh, 0)} threshold</span>
        <StatePill tone={desk.vixHigh ? "amber" : "ink"}>{desk.vixHigh == null ? "unknown" : desk.vixHigh ? "high" : "normal"}</StatePill>
      </span>,
    },
    {
      k: "Breadth",
      v: <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span>{fmtNum(desk.sharePct, 1)}% advancing ({fmtNum(desk.advances)} up, {fmtNum(desk.declines)} down{desk.breadthUniverse ? ` of ${fmtNum(desk.breadthUniverse)}` : ""})</span>
        <StatePill tone={desk.breadth === "up" ? "mint" : desk.breadth === "down" ? "danger" : "ink"}>{desk.breadth ?? "unknown"}</StatePill>
      </span>,
    },
    { k: "Realised vs implied", v: <span style={quiet}>Not computed: there is no IV history (P0.2).</span> },
    { k: "Liquidity / spread", v: quality },
    { k: "Events", v: <span style={quiet}>Not part of the rule yet.</span> },
  ];
  return (
    <Section title="Market regime · Nifty 50" note={`${r.version ?? "desk regime"} · ${fmtDay(desk.date)}`}>
      <div data-testid="fnolab-mi-regime" data-key={desk.key} className="flex flex-col" style={{ gap: 14 }}>
        <span className="flex flex-wrap items-baseline" style={{ gap: "4px 12px" }}>
          <span style={{ fontFamily: "var(--display)", fontSize: 32, lineHeight: 1.08, letterSpacing: "-0.02em" }}>{DESK_REGIME_LABEL[desk.key]}</span>
          <span style={quiet}>A market-wide reading of one end-of-day session: the same for every underlying.</span>
        </span>
        <span style={quiet}>
          The rule checks India VIX first, then whether trend and breadth disagree, then the Nifty close against its average.
          Regime labels are features, not forecasts.
        </span>
        <KvRows rows={factors} testId="fnolab-mi-factors" />
        {desk.skipped.length > 0 && (
          <div className="flex flex-col" style={{ gap: 4 }}>
            <span className="cp-eyebrow">Checks the rule could not make</span>
            {desk.skipped.map((s) => <span key={s.check} style={quiet}>{s.check}: {s.reason}</span>)}
          </div>
        )}
        {desk.invalidation.length > 0 && (
          <div data-testid="fnolab-mi-flips" className="flex flex-col" style={{ gap: 4 }}>
            <span className="cp-eyebrow">What would change the reading</span>
            {desk.invalidation.map((f) => (
              <span key={`${f.input}-${f.condition}-${f.level}`} style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
                {FLIP_INPUT[f.input]} {FLIP_COND[f.condition]} {fmtNum(f.level, f.input === "nifty_close" ? 2 : 1)}{f.input === "advancing_share_pct" ? "%" : ""} → {DESK_REGIME_LABEL[f.then]}
              </span>
            ))}
          </div>
        )}
        <span style={quiet}>Regime history is not stored yet, so transitions cannot be shown.</span>
        <TrustLine source="Desk regime" asOf={fmtDay(desk.date)} mode="eod" maker="rules" method={r.version ?? undefined} testId="fnolab-mi-regime-trust" />
      </div>
    </Section>
  );
}

// ── futures build-up ─────────────────────────────────────────────────────

function BuildupPanel({ rows, asOf, spot }: { rows: ExpiryBuildup[]; asOf: string; spot: number | null }) {
  return (
    <Section title="Futures build-up · per expiry" note={`EOD ${fmtDay(asOf)}`}>
      <div className="flex flex-col" style={{ gap: 12 }}>
        <div className="cp-scroll" style={{ overflowX: "auto" }}>
          <table data-testid="fnolab-mi-buildup" style={{ width: "100%", minWidth: 520, borderCollapse: "collapse" }}>
            <thead><tr><th style={th}>Expiry</th><th style={th}>Close</th><th style={th}>Price Δ</th><th style={th}>OI</th><th style={th}>OI Δ</th><th style={th}>Basis</th><th style={th}>Reading</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.expiry} data-testid="fnolab-mi-buildup-row" data-label={r.label ?? ""}>
                  <td style={{ ...td, fontWeight: 500 }}>{fmtDay(r.expiry)}</td>
                  <td style={td}>{fmtNum(r.close, 2)}</td>
                  <td style={{ ...td, color: TONE_COLOR[toneOf(r.changePct)] }}>{signedPct(r.changePct)}</td>
                  <td style={td}>{fmtNum(r.oi)}</td>
                  <td style={td}>{signedPct(r.oiChangePct, 1)}</td>
                  <td style={td}>{r.basis == null ? "—" : `${r.basis > 0 ? "+" : ""}${fmtNum(r.basis, 2)}`}</td>
                  <td style={{ ...td, color: r.label ? TONE_COLOR[BUILDUP_TONE[r.label]] : "var(--cp-ink-3)" }}>{r.label ?? "No reading"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {expiriesDisagree(rows)
            ? "The expiries disagree. Each is read on its own here; a total over expiries would show one label and hide the others."
            : "Each expiry is read on its own. The desk's build-up scan sums OI over all expiries; this screen does not."}
        </span>
        <span style={quiet}>The intraday price and OI series is not served yet (P0.1). Spot {fmtNum(spot, 2)} is the exchange file's underlying price.</span>
        <TrustLine source="NSE F&O bhavcopy" asOf={fmtDay(asOf)} mode="eod" maker="rules" method="price change × OI change, per contract" testId="fnolab-mi-buildup-trust" />
        <span className="cp-mono-note">Labels interpret price and OI together. They do not identify who traded or why.</span>
      </div>
    </Section>
  );
}

// ── options ──────────────────────────────────────────────────────────────

function TermRow({ symbol, expiry, dte }: { symbol: string; expiry: string; dte: number }) {
  const q = useFnoChain(symbol, expiry);
  const iv = q.data?.kind === "ok" ? q.data.data.summary.atm_iv ?? null : null;
  return (
    <div data-testid="fnolab-mi-term-row" className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 70px 80px", gap: 10, padding: "7px 0", borderBottom: "1px solid var(--cp-line)", fontSize: 13, fontVariantNumeric: "tabular-nums" }}>
      <span>{fmtDay(expiry)}</span>
      <span style={{ color: "var(--cp-ink-3)" }}>{dte} DTE</span>
      <span style={{ textAlign: "right" }}>{q.isPending ? "…" : iv == null ? "—" : `${fmtNum(iv, 1)}%`}</span>
    </div>
  );
}

function OptionsPanel({ symbol, chain, expiries }: { symbol: string; chain: FnoChain; expiries: Array<{ expiry: string; days_to_expiry: number }> }) {
  const s = chain.summary;
  const around = strikesAround(chain, 3);
  const maxOi = Math.max(1, ...around.flatMap((k) => [k.call?.oi ?? 0, k.put?.oi ?? 0]));
  const skew = skew25(chain);
  const nextThree = expiries.filter((e) => e.days_to_expiry > 0).slice(0, 3);
  const ivPrice = chain.strikes.find((k) => k.call?.iv_price || k.put?.iv_price);
  const priceUsed = ivPrice?.call?.iv_price ?? ivPrice?.put?.iv_price ?? null;
  return (
    <Section title={`Options · ${fmtDay(s.expiry)}`} note={`PCR ${fmtNum(s.pcr, 2)}`}>
      <div className="flex flex-col" style={{ gap: 14 }}>
        <div data-testid="fnolab-mi-strikes" className="flex flex-col" style={{ gap: 4 }}>
          {around.map((k) => {
            const atm = k.strike === s.atm_strike;
            const pw = ((k.put?.oi ?? 0) / maxOi) * 100;
            const cw = ((k.call?.oi ?? 0) / maxOi) * 100;
            return (
              <div key={k.strike} className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 72px minmax(0,1fr)", gap: 8, alignItems: "center", padding: "3px 0", borderRadius: 6, background: atm ? "var(--bg-2)" : "transparent" }}>
                <div style={{ height: 14, display: "flex", justifyContent: "flex-end", alignItems: "center" }} title={`Put OI ${fmtNum(k.put?.oi)}`}>
                  <div style={{ height: 10, width: `${pw}%`, borderRadius: "3px 0 0 3px", background: "var(--mint)" }} />
                </div>
                <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, textAlign: "center", color: atm ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>{fmtNum(k.strike)}</span>
                <div style={{ height: 14, display: "flex", alignItems: "center" }} title={`Call OI ${fmtNum(k.call?.oi)}`}>
                  <div style={{ height: 10, width: `${cw}%`, borderRadius: "0 3px 3px 0", background: "var(--cp-danger)" }} />
                </div>
              </div>
            );
          })}
          <div className="flex justify-between" style={{ gap: 8, fontSize: 12, color: "var(--cp-ink-2)" }}>
            <span>Put OI</span>
            <span className="cp-mono-note">Max pain {fmtNum(s.max_pain)}</span>
            <span>Call OI</span>
          </div>
        </div>
        <KvRows
          testId="fnolab-mi-vol"
          rows={[
            { k: "Put wall · call wall", v: `${fmtNum(s.put_wall?.strike)} · ${fmtNum(s.call_wall?.strike)}` },
            { k: "ATM IV · near (model estimate)", v: s.atm_iv == null ? "Not available" : `${fmtNum(s.atm_iv, 1)}%` },
            { k: "25Δ skew (model estimate)", v: skew ? `${skew.points > 0 ? "+" : ""}${fmtNum(skew.points, 1)} pts · put ${fmtNum(skew.putStrike)} vs call ${fmtNum(skew.callStrike)}` : "Not available: no strikes near ±0.25 delta" },
            { k: "IV rank", v: <span data-testid="fnolab-mi-ivrank" style={{ color: "var(--amber)" }}>Unavailable · no IV history (P0.2)</span> },
          ]}
        />
        {nextThree.length > 0 && (
          <div data-testid="fnolab-mi-term" className="flex flex-col">
            <span className="cp-eyebrow" style={{ paddingBottom: 4 }}>IV term structure · ATM, model estimate</span>
            {nextThree.map((e) => <TermRow key={e.expiry} symbol={symbol} expiry={e.expiry} dte={e.days_to_expiry} />)}
          </div>
        )}
        <span data-testid="fnolab-mi-greeks-src" style={quiet}>
          Greeks and IV: calculated with Black-76 from end-of-day {priceUsed ?? "settle or close"} prices, at {s.rate_pct == null ? "the model's" : `a ${fmtNum(s.rate_pct, 2)}%`} rate. No broker Greeks and no provenance flag yet (P0.2).
        </span>
        <TrustLine source="NSE F&O bhavcopy" asOf={fmtDay(s.as_of)} mode="eod" maker="model" method="Black-76" testId="fnolab-mi-chain-trust" />
      </div>
    </Section>
  );
}

// ── quote quality ────────────────────────────────────────────────────────

function QuotePanel({ symbol, live, isPending, error, onRetry, atm }: { symbol: string; live: LiveChain | undefined; isPending: boolean; error: unknown; onRetry: () => void; atm: number | null }) {
  if (!ON_LIVE_FEED.has(symbol)) {
    return (
      <GapNote tag="P0.1" title="Stock options are not on the live feed" testId="fnolab-mi-quotes-gap">
        The feed carries NIFTY and BANKNIFTY options only (two expiries, 15 strikes either side of the money). For {symbol} there is no bid/ask, so spread, quote age and fill quality cannot be shown.
      </GapNote>
    );
  }
  if (error) return <QueryProblem what="Live option quotes" error={error} onRetry={onRetry} />;
  if (isPending || !live) return <LoadingBlock label="Reading live option quotes" rows={2} />;
  if (live.cache !== "ok" || live.count === 0) {
    return (
      <Section title="Liquidity & quote quality" note="live feed cache">
        <div data-testid="fnolab-mi-quotes-empty" data-cache={live.cache} className="flex flex-col" style={{ gap: 6 }}>
          <span style={{ fontFamily: "var(--display)", fontSize: 21 }}>No live option quotes cached</span>
          <span style={quiet}>
            {live.cache === "unavailable"
              ? "The quote cache could not be read. Nothing is estimated in its place."
              : "The feed caches quotes during the market session (09:15–15:30 IST) and the cache empties soon after. Outside the session there is nothing to measure."}
          </span>
        </div>
      </Section>
    );
  }
  const q = quoteQuality(live, atm);
  const items: TileItem[] = [
    { k: "ATM ±5 median spread", v: q.medianSpreadPct == null ? "—" : `${fmtNum(q.medianSpreadPct, 2)}%`, s: `${q.spreadSample} fresh two-sided quotes`, tone: q.medianSpreadPct == null ? "ink" : q.medianSpreadPct <= 1 ? "mint" : "amber" },
    { k: "Quote age p95", v: q.p95AgeSeconds == null ? "—" : `${fmtNum(q.p95AgeSeconds, 1)} s`, s: "Exchange to cache", tone: "ink" },
    { k: "Stale quotes", v: `${q.stale} of ${q.cached}`, s: `Older than ${live.staleAfterSeconds ?? "—"} s`, tone: q.stale ? "amber" : "mint" },
    { k: "Crossed / malformed", v: String(q.crossed), s: "Bid above ask", tone: q.crossed ? "danger" : "ink" },
    { k: "Contracts cached", v: String(q.cached), s: "NIFTY and BANKNIFTY window", tone: "ink" },
  ];
  return (
    <Section title="Liquidity & quote quality" note={`live feed · ${live.session ?? "session"}`}>
      <div data-testid="fnolab-mi-quotes" className="flex flex-col" style={{ gap: 12 }}>
        <Tiles items={items} min={160} />
        <TrustLine source="Kite live feed cache" asOf={live.asOf ? new Date(live.asOf).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit" }) + " IST" : null} mode="live" maker="reported" testId="fnolab-mi-quotes-trust" />
      </div>
    </Section>
  );
}

// ── screen ───────────────────────────────────────────────────────────────

export function MarketIntel() {
  const { mobile } = useCopilotShell();
  const [symbol, setSymbol] = useState<MiUnderlying>("NIFTY");
  const macro = useMacroToday();
  const fut = useFnoFutures(symbol);
  const oc = useOptionChain(symbol, null);
  const chain = oc.state.status === "ok" ? oc.state.chain : null;
  const live = useLiveOptionChain(symbol, chain?.summary.expiry ?? null);

  const desk = macro.data?.kind === "ready" ? macro.data.desk : null;
  const futures = fut.data?.kind === "ok" ? fut.data.data : null;
  const rows = futures ? expiryBuildups(futures.futures) : [];
  const near = rows[0] ?? null;
  const onFeed = ON_LIVE_FEED.has(symbol);
  const liveData = live.data;

  const quoteSource: SourceItem = !onFeed
    ? { k: "Bid / ask quotes", sub: "Stock options not on the feed · P0.1", tone: "danger" }
    : live.isError ? { k: "Bid / ask quotes", sub: "Cache could not be read", tone: "danger" }
    : !liveData ? { k: "Bid / ask quotes", sub: "Reading the live cache", tone: "ink" }
    : liveData.cache === "ok" && liveData.count > 0
      ? { k: "Bid / ask quotes", sub: `Kite feed · ${liveData.count} contracts · ${liveData.staleCount} stale`, tone: liveData.staleCount ? "amber" : "mint" }
      : { k: "Bid / ask quotes", sub: liveData.cache === "unavailable" ? "Cache unavailable" : "Cache empty outside the session", tone: "amber" };

  const sources: SourceItem[] = [
    { k: "Index & futures", sub: futures ? `NSE F&O bhavcopy · EOD ${fmtDay(futures.as_of)}` : fut.isPending ? "Loading" : "Not available", tone: futures ? "mint" : fut.isPending ? "ink" : "danger" },
    { k: "Option chain OI", sub: chain ? `NSE F&O bhavcopy · EOD ${fmtDay(chain.summary.as_of)}` : oc.state.status === "loading" ? "Loading" : "Not available", tone: chain ? "mint" : oc.state.status === "loading" ? "ink" : "danger" },
    quoteSource,
    { k: "IV history", sub: "Not stored · P0.2", tone: "danger" },
    { k: "Regime", sub: desk?.key ? `${desk.rule.version ?? "desk regime"} · EOD ${fmtDay(desk.date)}` : macro.isPending ? "Loading" : "Not available", tone: desk?.key ? "mint" : macro.isPending ? "ink" : "danger" },
  ];

  const liveQuality = !onFeed
    ? <span style={quiet}>Not on the live feed (P0.1).</span>
    : liveData && liveData.cache === "ok" && liveData.count > 0
      ? (() => { const q = quoteQuality(liveData, chain?.summary.atm_strike ?? null); return <span>ATM ±5 median spread {q.medianSpreadPct == null ? "—" : `${fmtNum(q.medianSpreadPct, 2)}%`} ({q.spreadSample} quotes)</span>; })()
      : <span style={quiet}>No live quotes cached right now.</span>;

  const tiles: TileItem[] = [
    { k: "Spot", v: fmtNum(chain?.summary.spot ?? futures?.spot ?? null, 2), s: chain ? `EOD ${fmtDay(chain.summary.as_of)}` : futures ? `EOD ${fmtDay(futures.as_of)}` : "Not available" },
    { k: "Near future", v: fmtNum(near?.close ?? null, 2), s: near ? `${signedPct(near.changePct)} · ${fmtDay(near.expiry)}` : "Not available", tone: "ink" },
    { k: "ATM IV · near", v: chain?.summary.atm_iv == null ? "—" : `${fmtNum(chain.summary.atm_iv, 1)}%`, s: "Model estimate · Black-76", tone: "amber" },
    { k: "India VIX", v: fmtNum(desk?.vix ?? null, 2), s: desk?.date ? `EOD ${fmtDay(desk.date)}` : "Not available", tone: desk?.vixHigh ? "amber" : "ink" },
  ];

  return (
    <div data-testid="fnolab-mi" className="flex flex-col" style={{ gap: 14 }}>
      <Picker value={symbol} onPick={setSymbol} />
      <SourceCards items={sources} />
      <Tiles items={tiles} min={mobile ? 140 : 170} />

      {macro.isError
        ? <QueryProblem what="The market regime" error={macro.error} onRetry={() => void macro.refetch()} />
        : macro.isPending
          ? <LoadingBlock label="Reading the market regime" rows={3} />
          : <RegimePanel desk={desk} unavailable={macro.data?.kind === "unavailable" ? macro.data.reason : null} quality={liveQuality} />}

      <div className="flex flex-wrap" style={{ gap: 12, alignItems: "flex-start" }}>
        <div className="flex flex-col min-w-0" style={{ flex: "1.4 1 440px" }}>
          {fut.isError
            ? <QueryProblem what="Futures" error={fut.error} onRetry={() => void fut.refetch()} />
            : fut.isPending
              ? <LoadingBlock label="Reading futures" rows={3} />
              : !futures || rows.length === 0
                ? <Section title="Futures build-up · per expiry"><span data-testid="fnolab-mi-buildup-none" style={quiet}>{fut.data?.kind === "none" ? fut.data.message : `No futures contracts for ${symbol} in the latest session.`}</span></Section>
                : <BuildupPanel rows={rows} asOf={futures.as_of} spot={futures.spot} />}
        </div>
        <div className="flex flex-col min-w-0" style={{ flex: "1 1 320px" }}>
          {oc.state.status === "error"
            ? <QueryProblem what="The option chain" error={oc.state.error} onRetry={oc.state.retry} />
            : oc.state.status === "loading"
              ? <LoadingBlock label="Reading the option chain" rows={4} />
              : oc.state.status === "none"
                ? <Section title="Options"><span data-testid="fnolab-mi-chain-none" style={quiet}>{oc.state.message}</span></Section>
                : <OptionsPanel symbol={symbol} chain={oc.state.chain} expiries={oc.list} />}
        </div>
      </div>

      <KiteSessions own={false} />
      <QuotePanel symbol={symbol} live={liveData} isPending={live.isPending} error={live.isError ? live.error : null} onRetry={() => void live.refetch()} atm={chain?.summary.atm_strike ?? null} />
    </div>
  );
}
