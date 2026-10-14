/**
 * Smart trading desk — 03 Chart analysis, with the 05 Risk desk beside it.
 *
 *   daily candles, indicators   GET /api/research/chart-live/{symbol}/ohlcv?start=   (useDailyBars; flag `charting`;
 *                               end of day, split and bonus adjusted: nidp.prices_eod_adjusted)
 *   setup, levels, why          GET /api/positional/watchlist + /picks                (useDeskScanner, end of day)
 *   P(+5% next session), record GET /api/move-odds/latest?head=…                      (useDeskOdds; flag `move_odds`)
 *   four next-session estimates GET /api/move-odds/stocks/{symbol}                    (useStockOdds)
 *
 * EMA 20 / 50, RSI 14, ATR 14, RVOL and a 20-day VWAP are worked out here from
 * the daily bars (indicators.ts). The VWAP is a 20-day volume-weighted average
 * of daily prices, not the intraday VWAP. The stock shown is the desk's
 * `?sym=`, else the scanner's first setup.
 */
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { StockIcon } from "../../components/EntityIcon";
import { Btn, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, NotConnected, Pill, TONE_COLOR, fmtNum, fmtPct, humaniseTag, signTone, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { cleanSymbol } from "../trading/fno";
import { Choices, INPUT_STYLE, fmtDay, fmtPrice } from "../trading/parts";
import { CandleChart, CandleLegend } from "./CandleChart";
import { scanDateLabel, setupLabel, useDailyBars, useStockOdds, type DailyBars } from "./chart-data";
import { useDesk } from "./context";
import { headLabel, useDeskOdds, useDeskScanner, type DeskSetup } from "./desk-data";
import { ema, rsiZone, snapshot, vwapRolling, type DailyBar } from "./indicators";
import { RiskDesk } from "./RiskDesk";
import type { MoveHead } from "@/services/adapters/moveOdds.adapter";

type Timeframe = "1M" | "3M" | "6M";
const SESSIONS: Record<Timeframe, number> = { "1M": 22, "3M": 63, "6M": 126 };

// ── symbol bar ───────────────────────────────────────────────────────────

function SymbolBar({ symbol, quick, onPick }: { symbol: string | null; quick: string[]; onPick: (s: string) => void }) {
  const [typed, setTyped] = useState("");
  const [bad, setBad] = useState(false);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const s = cleanSymbol(typed);
    setBad(s == null);
    if (s == null) return;
    setTyped("");
    onPick(s);
  };
  return (
    <div className="flex flex-wrap items-center" style={{ gap: "8px 12px" }}>
      <form onSubmit={submit} className="flex items-center" style={{ gap: 6, flex: "0 1 300px", minWidth: 0 }}>
        <input
          data-testid="desk-chart-symbol-input"
          aria-label="NSE symbol"
          aria-invalid={bad}
          placeholder="Any NSE symbol, e.g. RELIANCE"
          maxLength={20}
          autoCapitalize="characters"
          spellCheck={false}
          value={typed}
          onChange={(e) => { setTyped(e.target.value); setBad(false); }}
          style={INPUT_STYLE}
        />
        <Btn type="submit" data-testid="desk-chart-symbol-load" style={{ flex: "none" }}>Chart</Btn>
      </form>
      {quick.length > 0 && (
        <Choices
          label="Scanner stocks"
          testId="desk-chart-quick"
          value={symbol ?? ""}
          onChange={onPick}
          options={quick.map((s) => ({ value: s, label: <span className="inline-flex items-center" style={{ gap: 6 }}><StockIcon symbol={s} size={16} />{s}</span> }))}
        />
      )}
      {bad && (
        <span role="alert" data-testid="desk-chart-symbol-error" style={{ fontSize: 12, color: "var(--cp-danger)", flexBasis: "100%" }}>
          A symbol is letters, digits, &amp; or -, up to 20 characters.
        </span>
      )}
    </div>
  );
}

// ── header ───────────────────────────────────────────────────────────────

function StockHeader({ symbol, setup, bars, company, sector }: { symbol: string; setup: DeskSetup | null; bars: DailyBar[] | null; company: string | null; sector: string | null }) {
  const { mobile } = useCopilotShell();
  const last = bars?.length ? bars[bars.length - 1] : null;
  const prev = bars && bars.length > 1 ? bars[bars.length - 2] : null;
  const close = last?.close ?? setup?.close ?? null;
  const change = last && prev && prev.close > 0 ? ((last.close - prev.close) / prev.close) * 100 : null;
  const vol = setup?.signals.volume_spike_3v20 ?? null;
  return (
    <div data-testid="desk-chart-header" className="flex flex-wrap items-center justify-between" style={{ gap: "10px 20px" }}>
      <div className="flex min-w-0 items-center" style={{ gap: 12 }}>
        <StockIcon symbol={symbol} name={company} size={mobile ? 36 : 42} />
        <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
          <span data-testid="desk-chart-symbol" style={{ fontSize: 18, fontWeight: 500, color: "var(--cp-ink)" }}>{symbol}</span>
          <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {[company, sector].filter(Boolean).join(" · ") || "NSE"}
          </span>
        </div>
      </div>
      <div className="flex flex-wrap items-baseline" style={{ gap: "4px 12px" }}>
        <span data-testid="desk-chart-close" style={{ fontFamily: "var(--display)", fontSize: mobile ? 30 : 36, lineHeight: 1 }}>{fmtPrice(close)}</span>
        <span data-testid="desk-chart-change" className="cp-num" style={{ fontSize: 13, color: TONE_COLOR[signTone(change)] }}>{fmtPct(change, { signed: true, digits: 2 })}</span>
        <span className="cp-mono-note">{last ? `Close ${fmtDay(last.day)} · end of day` : setup?.close != null ? "Scanner close · end of day" : ""}</span>
      </div>
      <div data-testid="desk-chart-pills" className="flex flex-wrap" style={{ gap: 6, flexBasis: "100%" }}>
        {setup ? (
          <>
            <Pill tone={setup.status === "confirmed" ? "mint" : setup.status === "awaiting" ? "amber" : "ink"}>{setupLabel(setup)}</Pill>
            {vol != null && <Pill tone={vol >= 1.5 ? "mint" : "ink"} title="Last 3 sessions' volume ÷ the 20-day average (scanner)">Volume {fmtNum(vol, 1)}×</Pill>}
            {setup.stage && <Pill tone="indigo">Stage · {humaniseTag(setup.stage.toLowerCase())}</Pill>}
          </>
        ) : (
          <Pill>Not on today’s scanner</Pill>
        )}
      </div>
    </div>
  );
}

// ── chart card ───────────────────────────────────────────────────────────

function Toggle({ on, onClick, disabled, title, testId, children }: { on: boolean; onClick: () => void; disabled?: boolean; title?: string; testId: string; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      disabled={disabled}
      title={title}
      data-testid={testId}
      onClick={onClick}
      className="cp-chip"
      style={{ padding: "5px 11px", fontSize: 12, ...(on ? { borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" } : null) }}
    >
      {children}
    </button>
  );
}

function ChartCard({ symbol, state, retry, setup }: {
  symbol: string;
  state: { isPending: boolean; isError: boolean; error: unknown; data: DailyBars | undefined };
  retry: () => void;
  setup: DeskSetup | null;
}) {
  const [tf, setTf] = useState<Timeframe>("3M");
  const [showEma, setShowEma] = useState(true);
  const [showVwap, setShowVwap] = useState(true);
  const [showLevels, setShowLevels] = useState(true);
  const bars = state.data?.kind === "ok" ? state.data.bars : null;
  const hasLevels = !!setup && (setup.entry != null || setup.stop != null || setup.target != null);

  const lines = useMemo(() => {
    if (!bars) return null;
    const closes = bars.map((b) => b.close);
    return { ema20: ema(closes, 20), ema50: ema(closes, 50), vwap20: vwapRolling(bars, 20) };
  }, [bars]);

  let body: ReactNode;
  if (state.isPending) body = <LoadingBlock label={`Loading ${symbol} daily bars`} rows={5} />;
  else if (state.isError) body = <div data-testid="desk-chart-error"><ErrorBlock title={`${symbol} prices didn’t load`} error={state.error} onRetry={retry} /></div>;
  else if (state.data?.kind === "locked") {
    body = (
      <NotConnected
        testId="desk-chart-locked"
        title="Charting is not enabled for this account"
        body="Daily candles and the indicators worked out from them need the charting feature. The scanner levels and the model’s estimates below still show."
        needs={["The `charting` feature allowlist for this account (GET /api/research/chart-live/{symbol}/ohlcv answers 403 without it)."]}
      />
    );
  } else if (state.data?.kind === "none" || !bars || !lines) {
    body = (
      <div data-testid="desk-chart-noprices">
        <EmptyBlock title={`No daily prices on record for ${symbol}`} body="The data platform has no adjusted end-of-day bars for this symbol. Check the symbol, or pick a stock from the scanner." />
      </div>
    );
  } else {
    const n = Math.min(SESSIONS[tf], bars.length);
    const from = bars.length - n;
    const slice = <T,>(xs: T[]) => xs.slice(from);
    const ok = state.data?.kind === "ok" ? state.data : null;
    body = (
      <div className="flex flex-col" style={{ gap: 10 }}>
        <CandleChart
          bars={slice(bars)}
          name={symbol}
          overlays={{
            ema20: showEma ? slice(lines.ema20) : undefined,
            ema50: showEma ? slice(lines.ema50) : undefined,
            vwap20: showVwap ? slice(lines.vwap20) : undefined,
            levels: showLevels && hasLevels && setup ? { target: setup.target, entry: setup.entry, stop: setup.stop } : null,
          }}
        />
        <CandleLegend ema={showEma} vwap={showVwap} levels={showLevels && hasLevels} />
        <Footnote>
          NSE daily bars, split and bonus adjusted{ok?.provider ? ` (${ok.provider})` : ""} · end of day · last session {fmtDay(bars[bars.length - 1].day)}
          {n < SESSIONS[tf] ? ` · only ${n} sessions on record, all shown` : ""}
          {ok?.partial ? " · the data platform dropped some incomplete sessions from this series" : ""}
        </Footnote>
      </div>
    );
  }

  return (
    <section data-testid="desk-chart-card" className="cp-card flex min-w-0 flex-col">
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px", padding: "14px 16px", borderBottom: "1px solid var(--cp-line)" }}>
        <span className="cp-eyebrow">03 · Chart intelligence</span>
        <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
          <div role="group" aria-label="Timeframe" className="flex" style={{ gap: 4 }}>
            {(Object.keys(SESSIONS) as Timeframe[]).map((t) => (
              <Toggle key={t} on={tf === t} onClick={() => setTf(t)} testId={`desk-chart-tf-${t}`} title={`${SESSIONS[t]} daily candles`}>{t}</Toggle>
            ))}
          </div>
          <span aria-hidden style={{ width: 1, height: 18, background: "var(--line-2)", margin: "0 4px" }} />
          <div role="group" aria-label="Overlays" className="flex flex-wrap" style={{ gap: 4 }}>
            <Toggle on={showEma} onClick={() => setShowEma((v) => !v)} testId="desk-chart-ov-ema">EMA (20 &amp; 50)</Toggle>
            <Toggle on={showVwap} onClick={() => setShowVwap((v) => !v)} testId="desk-chart-ov-vwap">VWAP</Toggle>
            <Toggle
              on={showLevels && hasLevels}
              disabled={!hasLevels}
              title={hasLevels ? undefined : "No scanner levels for this stock"}
              onClick={() => setShowLevels((v) => !v)}
              testId="desk-chart-ov-levels"
            >
              Levels
            </Toggle>
          </div>
        </div>
      </div>
      <div style={{ padding: 16 }}>{body}</div>
    </section>
  );
}

// ── indicator tiles ──────────────────────────────────────────────────────

function where(close: number | null, v: number | null): string {
  if (close == null || v == null) return "—";
  if (close > v) return "Price above";
  if (close < v) return "Price below";
  return "Price at";
}

function IndicatorTile({ k, v, s, tone = "ink", id }: { k: string; v: string; s: ReactNode; tone?: Tone; id: string }) {
  return (
    <div className="cp-card flex min-w-0 flex-col" style={{ gap: 6, padding: "12px 14px" }}>
      <span className="cp-eyebrow">{k}</span>
      <span data-testid={`desk-ind-${id}`} className="cp-num" style={{ fontSize: 19, color: TONE_COLOR[tone] }}>{v}</span>
      <span data-testid={`desk-ind-${id}-sub`} style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{s}</span>
    </div>
  );
}

function IndicatorTiles({ bars }: { bars: DailyBar[] }) {
  const snap = useMemo(() => snapshot(bars), [bars]);
  const zone = rsiZone(snap.rsi14);
  const expansion = snap.rvol20 != null && snap.rvol20 >= 1.5;
  return (
    <div data-testid="desk-indicators" className="flex flex-col" style={{ gap: 8 }}>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
        <IndicatorTile id="ema20" k="EMA 20" v={fmtPrice(snap.ema20)} s={<>{where(snap.close, snap.ema20)} · EMA 50 <span data-testid="desk-ind-ema50">{fmtPrice(snap.ema50)}</span></>} />
        <IndicatorTile id="rsi" k="RSI 14" v={fmtNum(snap.rsi14, 1)} s={zone ?? "—"} tone={zone === "Overbought" ? "amber" : zone === "Healthy" ? "mint" : "ink"} />
        <IndicatorTile id="atr" k="ATR 14" v={fmtPrice(snap.atr14)} s={snap.atrPct != null ? `${fmtPct(snap.atrPct, { digits: 2 })} of price` : "—"} />
        <IndicatorTile id="vwap" k="VWAP 20D" v={fmtPrice(snap.vwap20)} s={where(snap.close, snap.vwap20)} />
        <IndicatorTile id="rvol" k="RVOL" v={snap.rvol20 != null ? `${fmtNum(snap.rvol20, 2)}×` : "—"} s={snap.rvol20 == null ? "—" : expansion ? "Volume expansion" : "No volume expansion"} tone={expansion ? "mint" : "ink"} />
      </div>
      <Footnote>
        Worked out here from the end-of-day daily bars above. EMA seeded with the simple average of its first 20 or 50 closes; RSI and ATR with Wilder’s smoothing over 14 sessions; RVOL is the last session’s volume ÷ the average of the 20 sessions before it. VWAP here is a 20-day volume-weighted average of daily prices ((high + low + close) ÷ 3), not the intraday VWAP.
      </Footnote>
    </div>
  );
}

// ── setup check and why ──────────────────────────────────────────────────

interface CheckLine { key: string; label: string; value: string; tone: Tone }

function setupLines(s: DeskSetup): CheckLine[] {
  const sig = s.signals;
  const out: CheckLine[] = [];
  const add = (key: string, label: string, value: string, tone: Tone = "ink") => out.push({ key, label, value, tone });
  if (s.trigger != null) {
    const d = sig.dist_breakout_pct;
    add("trigger", "Breakout level (trigger)", `${fmtPrice(s.trigger)}${d != null ? ` · close ${fmtPct(d, { signed: true, digits: 1 })} from it` : ""}`, d != null && d >= 0 ? "mint" : "ink");
  }
  if (sig.volume_spike_3v20 != null) add("volume", "Volume, 3 sessions vs 20-day average", `${fmtNum(sig.volume_spike_3v20, 1)}×`, sig.volume_spike_3v20 >= 1.5 ? "mint" : "ink");
  if (s.rsi14 != null) add("rsi", "RSI 14", fmtNum(s.rsi14, 1), s.rsi14 >= 70 ? "amber" : s.rsi14 >= 55 ? "mint" : "ink");
  if (sig.dist_ema20_pct != null) add("ema20", "Distance to EMA 20", fmtPct(sig.dist_ema20_pct, { signed: true, digits: 1 }), sig.dist_ema20_pct >= 0 && sig.dist_ema20_pct <= 4 ? "mint" : "ink");
  if (s.atrPct != null) add("atr", "ATR 14, % of close", fmtPct(s.atrPct, { digits: 2 }));
  if (sig.range_pct_15d != null) add("range", "15-day range", fmtPct(sig.range_pct_15d, { digits: 1 }), sig.range_pct_15d < 8 ? "mint" : "ink");
  if (sig.higher_lows_count != null) add("higher-lows", "Higher lows, last 20 sessions", fmtNum(sig.higher_lows_count), sig.higher_lows_count >= 1 ? "mint" : "ink");
  if (sig.volume_slope_10d_pct != null) add("vol-slope", "Volume trend, 10 sessions", `${fmtPct(sig.volume_slope_10d_pct, { signed: true, digits: 1 })} a day`);
  if (sig.delivery_trend_pct != null) add("delivery", "Delivery trend, 10 sessions", fmtPct(sig.delivery_trend_pct, { signed: true, digits: 0 }));
  if (s.daysMin != null || s.daysMax != null) add("window", "Scanner holding window", `${s.daysMin != null ? fmtNum(s.daysMin) : "—"}–${s.daysMax != null ? fmtNum(s.daysMax) : "—"} days`);
  if (s.confidence) add("confidence", "Scanner confidence", humaniseTag(s.confidence.toLowerCase()));
  return out;
}

function SetupCheck({ setup, date }: { setup: DeskSetup; date: string | null }) {
  const lines = setupLines(setup);
  return (
    <section data-testid="desk-setup-check" className="cp-card flex min-w-0 flex-col">
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "6px 12px", padding: "14px 16px", borderBottom: "1px solid var(--cp-line)" }}>
        <span className="cp-eyebrow">Setup check</span>
        <span className="cp-mono-note">Scanner · {date ?? "end of day"}</span>
      </div>
      <ul className="m-0 flex flex-col" style={{ gap: 8, padding: 16, listStyle: "none" }}>
        {lines.length === 0 && <li style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>The scanner sent no structure figures for this setup.</li>}
        {lines.map((l) => (
          <li key={l.key} data-testid={`desk-check-${l.key}`} className="flex items-center" style={{ gap: 10, fontSize: 13 }}>
            <span aria-hidden style={{ flex: "none", width: 7, height: 7, borderRadius: 999, background: l.tone === "ink" ? "var(--cp-ink-4)" : TONE_COLOR[l.tone] }} />
            <span style={{ flex: "1 1 auto", minWidth: 0, color: "var(--cp-ink-2)" }}>{l.label}</span>
            <span className="cp-num" style={{ flex: "none", color: "var(--cp-ink)", textAlign: "right" }}>{l.value}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function WhyItRanks({ setup }: { setup: DeskSetup }) {
  const { askDesk } = useDesk();
  const lines = [setup.why, ...setup.reasons].filter((x): x is string => !!x);
  return (
    <section data-testid="desk-why" className="cp-card flex min-w-0 flex-col">
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "6px 12px", padding: "14px 16px", borderBottom: "1px solid var(--cp-line)" }}>
        <span className="cp-eyebrow">Why it ranks</span>
        <span className="cp-mono-note">Score {setup.score != null ? fmtNum(setup.score, 0) : "—"} · rules-based</span>
      </div>
      <div className="flex flex-col" style={{ gap: 12, padding: 16 }}>
        {lines.length ? (
          <ul className="m-0 flex flex-col" style={{ gap: 8, paddingLeft: 18, fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
            {lines.map((l, i) => <li key={`${i}-${l}`} data-testid="desk-why-line">{l}</li>)}
          </ul>
        ) : (
          <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>The scanner stored no reason text for this setup.</span>
        )}
        {setup.scans.length > 0 && (
          <div className="flex flex-wrap" style={{ gap: 6 }}>
            {setup.scans.map((s) => <Pill key={s}>{humaniseTag(s.replace(/\./g, " "))}</Pill>)}
          </div>
        )}
        <div>
          <button
            type="button"
            data-testid="desk-why-ask"
            onClick={() => askDesk(`Explain the ${setup.symbol} setup and what would invalidate it`)}
            style={{ padding: "6px 12px", borderRadius: 999, border: "1px solid var(--mint-line)", background: "transparent", color: "var(--mint)", fontSize: 13, cursor: "pointer", fontFamily: "var(--sans)" }}
          >
            Ask Copilot ›
          </button>
        </div>
      </div>
    </section>
  );
}

// ── the model's four estimates ───────────────────────────────────────────

const HEADS: MoveHead[] = ["p_up5_1d", "p_down5_1d", "p_up10_1d", "p_down10_1d"];
const pct1 = (p: number | null | undefined) => (p == null ? "—" : fmtPct(p * 100, { digits: 1 }));

function Estimates({ estimates, events, run }: { estimates: Record<string, number>; events: number; run: { target_session: string; data_as_of: string; model: string } }) {
  // Each head's base rate comes with its published list (cached; the scanner already holds p_up5_1d).
  const up5 = useDeskOdds("p_up5_1d");
  const down5 = useDeskOdds("p_down5_1d");
  const up10 = useDeskOdds("p_up10_1d");
  const down10 = useDeskOdds("p_down10_1d");
  const base: Record<MoveHead, number | null> = {
    p_up5_1d: up5.data?.kind === "final" ? up5.data.data.base_rate : null,
    p_down5_1d: down5.data?.kind === "final" ? down5.data.data.base_rate : null,
    p_up10_1d: up10.data?.kind === "final" ? up10.data.data.base_rate : null,
    p_down10_1d: down10.data?.kind === "final" ? down10.data.data.base_rate : null,
  };
  return (
    <div className="flex flex-col" style={{ gap: 10 }}>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
        {HEADS.map((h) => {
          const p = estimates[h];
          return (
            <div key={h} data-testid={`desk-model-${h}`} className="flex min-w-0 flex-col" style={{ gap: 4, padding: "12px 14px", borderRadius: 12, border: "1px solid var(--cp-line)", background: "var(--bg-0)" }}>
              <span className="cp-eyebrow">{headLabel(h)}</span>
              <span data-testid={`desk-model-${h}-p`} className="cp-num" style={{ fontSize: 20, color: "var(--cp-ink)" }}>{pct1(typeof p === "number" ? p : null)}</span>
              <span data-testid={`desk-model-${h}-base`} style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>Base rate {pct1(base[h])}</span>
            </div>
          );
        })}
      </div>
      <Footnote>
        Next-session estimates for {fmtDay(run.target_session)}, on data of {fmtDay(run.data_as_of)} · model {run.model} · {fmtNum(events)} events on record for this stock. Each base rate is the one the model publishes with that estimate’s run, for comparison. Up: the session’s high reaches the previous close plus the move; down: the low reaches the previous close minus it.
      </Footnote>
    </div>
  );
}

function ModelBlock({ symbol }: { symbol: string }) {
  const q = useStockOdds(symbol);
  const odds = useDeskOdds("p_up5_1d");
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading the model’s estimates" rows={2} />;
  else if (q.isError) body = <ErrorBlock title="The model’s estimates didn’t load" error={q.error} onRetry={() => q.refetch()} />;
  else if (q.data.kind === "locked") {
    body = <div data-testid="desk-model-locked" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>Move probabilities are not enabled for this account.</div>;
  } else if (q.data.kind === "withheld") {
    body = <div data-testid="desk-model-withheld" style={{ fontSize: 13, color: "var(--amber)" }}>The model’s run for the next session was withheld: {q.data.reason}.</div>;
  } else if (q.data.kind === "none") {
    const pending = odds.data?.kind === "not_published" ? odds.data.expectedSession : null;
    body = (
      <div data-testid="desk-model-none" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
        {pending ? `The model has not published for ${fmtDay(pending)} yet.` : `No estimate for ${symbol}: it is not in the model’s published run for the next session.`}
      </div>
    );
  } else {
    body = <Estimates estimates={q.data.data.estimates} events={q.data.data.events.length} run={q.data.data.run} />;
  }
  return (
    <section data-testid="desk-model" className="cp-card flex min-w-0 flex-col">
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "6px 12px", padding: "14px 16px", borderBottom: "1px solid var(--cp-line)" }}>
        <span className="cp-eyebrow">Move-odds model · next session</span>
        <span className="cp-mono-note">One session ahead only</span>
      </div>
      <div style={{ padding: 16 }}>{body}</div>
    </section>
  );
}

// ── the tab ──────────────────────────────────────────────────────────────

export default function ChartTab() {
  const { symbol: chosen, setSymbol } = useDesk();
  const scan = useDeskScanner();
  const odds = useDeskOdds("p_up5_1d");
  const setups = scan.data?.setups ?? [];
  const symbol = chosen ?? setups[0]?.symbol ?? null;
  const setup = symbol ? setups.find((s) => s.symbol === symbol) ?? null : null;
  const barsQ = useDailyBars(symbol);
  const stockQ = useStockOdds(symbol);
  const quick = setups.slice(0, 6).map((s) => s.symbol);
  const date = scan.data ? scanDateLabel(scan.data.watchAsOf, scan.data.signalDate) : null;

  if (!symbol) {
    if (scan.isPending) return <LoadingBlock label="Loading the scanner" rows={4} />;
    return (
      <div data-testid="desk-chart-tab" className="flex flex-col" style={{ gap: 16 }}>
        <SymbolBar symbol={null} quick={quick} onPick={setSymbol} />
        <div data-testid="desk-chart-nosymbol">
          <EmptyBlock
            title="Pick a stock to chart"
            body={scan.isError ? "The scanner didn’t load, so there is no first setup to show. Type any NSE symbol above." : "The scanner has no setups on its latest scan. Type any NSE symbol above."}
          />
        </div>
      </div>
    );
  }

  const bars = barsQ.data?.kind === "ok" ? barsQ.data.bars : null;
  const row = odds.data?.kind === "final" ? odds.data.data.rows.find((r) => r.symbol.toUpperCase() === symbol) ?? null : null;
  const stock = stockQ.data?.kind === "ok" ? stockQ.data.data : null;
  const company = row?.company_name ?? stock?.company_name ?? null;
  const sector = setup?.sector ?? row?.sector ?? stock?.sector ?? null;

  return (
    <div data-testid="desk-chart-tab" data-symbol={symbol} className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <SymbolBar symbol={symbol} quick={quick} onPick={setSymbol} />
      <StockHeader symbol={symbol} setup={setup} bars={bars} company={company} sector={sector} />

      <div className="flex flex-wrap items-start" style={{ gap: 16 }}>
        <div className="flex min-w-0 flex-col" style={{ flex: "2 1 520px", gap: 12 }}>
          <ChartCard key={symbol} symbol={symbol} state={barsQ} retry={() => barsQ.refetch()} setup={setup} />
          {bars && <IndicatorTiles bars={bars} />}
        </div>
        <div className="min-w-0" style={{ flex: "1 1 300px" }}>
          <RiskDesk symbol={symbol} setup={setup} lastClose={bars ? bars[bars.length - 1].close : setup?.close ?? null} />
        </div>
      </div>

      {setup ? (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 300px), 1fr))", gap: 16 }}>
          <SetupCheck setup={setup} date={date} />
          <WhyItRanks setup={setup} />
        </div>
      ) : (
        <div data-testid="desk-not-on-scanner">
          <EmptyBlock
            title="Not on today’s scanner — no levels"
            body={scan.isError
              ? `The scanner didn’t load, so there is no trigger, stop or target for ${symbol}. The chart and indicators are still worked out from its daily bars.`
              : `${symbol} did not pass the end-of-day scanner’s rules${date ? ` on the ${date} scan` : ""}, so it has no trigger, stop or target. The chart and indicators are still worked out from its daily bars.`}
          />
        </div>
      )}

      <ModelBlock symbol={symbol} />
    </div>
  );
}
