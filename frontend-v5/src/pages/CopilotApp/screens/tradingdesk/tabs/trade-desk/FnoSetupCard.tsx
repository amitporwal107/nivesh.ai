/**
 * Trade Desk › Chart Analysis › Live chart — the F&O SETUP card (the owner's design of 28 Oct).
 *
 *   tagged lines        the futures build-up (GET /api/fno/{symbol}/futures/oi-buildup: the current month's and the
 *                       consolidated latest window) and the call / put walls of the chain
 *   OI by strike        GET /api/fno/{symbol}/chain?expiry=  (useOptionChain) — the nearest expiry with days left (an expiry on
 *                       its own day has no IV or expected move), strikes around the ATM: put OI to the left (support),
 *                       call OI to the right (resistance). Walls = summary.call_wall / put_wall, the chain route's own rule
 *                       (the heaviest call at or above the spot, the heaviest put at or below it)
 *   PCR · ATM IV · EXP. MOVE   the chain summary (end of day, Black-76 on the bhavcopy close)
 *   IV PCTILE           GET /api/fno/{symbol}/iv-history: null with the route's reason until 252 sessions are recorded; "stale"
 *                       when the last recorded session is older than the chain's day
 *   CANDIDATE STRUCTURE the symbol's idea on today's F&O ideas board (useTop10Fno, POST /api/desk/strategy/top, the board Market
 *                       Overview reads): legs, net premium, max loss / profit, breakevens. Wording rule (SEBI): a candidate,
 *                       never "suggested". The link goes to Trade Desk › Strategy Lab.
 *
 * OI shows positioning, not who initiated it. Nothing here is computed in the browser beyond picking and drawing.
 */
import type { ReactNode } from "react";
import { LoadingBlock, TONE_COLOR, fmtNum, fmtPct } from "../../../../components/ui";
import { fmtDay, fmtPrice } from "../../../trading/parts";
import { strikesAround, useFnoExpiries, useOptionChain, type FnoChain } from "../../../trading/fno";
import { BUILDUP_META } from "../../fno-buildup";
import { useTop10Fno } from "../../top10-data";
import { SLOT_LABEL, useIvHistory, type OiBuildup, type OiWindow } from "./live-chart-data";
import { linkBtn, quiet } from "./parts";

const mono = { fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase" as const };

function Tag({ text, color, testId }: { text: string; color: string; testId?: string }) {
  return (
    <span data-testid={testId} style={{ ...mono, display: "inline-block", padding: "2px 7px", borderRadius: 5, whiteSpace: "nowrap", color, border: `1px solid color-mix(in srgb, ${color} 45%, transparent)`, background: `color-mix(in srgb, ${color} 12%, transparent)` }}>
      {text}
    </span>
  );
}

function Line({ tag, children, testId }: { tag: ReactNode; children: ReactNode; testId: string }) {
  return (
    <div data-testid={testId} className="flex min-w-0 items-start" style={{ gap: 10, fontSize: 12.5, lineHeight: 1.5 }}>
      <span style={{ flexShrink: 0, minWidth: 118 }}>{tag}</span>
      <span style={{ color: "var(--cp-ink-2)", minWidth: 0 }}>{children}</span>
    </div>
  );
}

const lakh = (n: number | null | undefined) => (n == null ? "—" : Math.abs(n) >= 1e5 ? `${fmtNum(n / 1e5, 1)} L` : fmtNum(n));
const signed = (n: number | null | undefined, f: (x: number) => string) => (n == null ? "—" : `${n > 0 ? "+" : n < 0 ? "−" : ""}${f(Math.abs(n))}`);

function windowWhen(w: OiWindow, mode: string): string {
  return mode === "end_of_day" ? `${fmtDay(w.day)} (end of day)` : `${w.start.slice(11, 16)}–${w.end.slice(11, 16)} ${fmtDay(w.day)}`;
}

function BuildupLines({ oi }: { oi: OiBuildup }) {
  const pick = [oi.contracts[0], oi.consolidated].filter(Boolean);
  const out: ReactNode[] = [];
  const seen = new Set<string>();
  for (const s of pick) {
    const w = [...s.windows].reverse().find((x) => x.label != null);
    if (!w || !w.label) continue;
    const key = `${s.slot}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const meta = BUILDUP_META[w.label];
    out.push(
      <Line key={key} testId={`lc-fno-line-${s.slot}`} tag={<Tag text={meta.label} color={TONE_COLOR[meta.tone]} />}>
        {SLOT_LABEL[s.slot] ?? s.slot}{s.expiry ? ` (${fmtDay(s.expiry)})` : ""}: price {signed(w.price_change, (x) => fmtNum(x, 2))}, OI {signed(w.oi_change, lakh)} in {windowWhen(w, oi.mode)}. {meta.rule}.
      </Line>,
    );
  }
  return <>{out}</>;
}

/** Horizontal bars per strike: put OI to the left of the strike, call OI to the right. */
function OiByStrike({ chain }: { chain: FnoChain }) {
  const rows = strikesAround(chain, 6);
  const max = Math.max(1, ...rows.flatMap((r) => [r.call?.oi ?? 0, r.put?.oi ?? 0]));
  const cw = chain.summary.call_wall?.strike ?? null;
  const pw = chain.summary.put_wall?.strike ?? null;
  return (
    <div data-testid="lc-fno-oi-strike" className="flex min-w-0 flex-col" style={{ gap: 3 }}>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 64px minmax(0,1fr)", gap: 6, ...mono, fontSize: 8.5, color: "var(--cp-ink-3)" }}>
        <span style={{ textAlign: "right" }}>Put OI · support</span><span style={{ textAlign: "center" }}>Strike</span><span>Call OI · resistance</span>
      </div>
      {rows.map((r) => {
        const put = r.put?.oi ?? 0;
        const call = r.call?.oi ?? 0;
        const atm = r.strike === chain.summary.atm_strike;
        return (
          <div key={r.strike} data-testid="lc-fno-strike" data-strike={r.strike} data-put-oi={put} data-call-oi={call}
            className="grid items-center" style={{ gridTemplateColumns: "minmax(0,1fr) 64px minmax(0,1fr)", gap: 6, height: 14 }}
            title={`${fmtNum(r.strike, 0)}: put OI ${fmtNum(put)}, call OI ${fmtNum(call)}`}>
            <div className="flex justify-end"><div style={{ width: `${(put / max) * 100}%`, height: 8, borderRadius: 2, background: r.strike === pw ? "var(--mint)" : "color-mix(in srgb, var(--mint) 45%, transparent)" }} /></div>
            <span className="cp-num" style={{ textAlign: "center", fontSize: 11, fontWeight: atm ? 700 : 400, color: atm ? "var(--cp-ink)" : "var(--cp-ink-2)" }}>
              {fmtNum(r.strike, r.strike % 1 ? 1 : 0)}{r.strike === cw ? " C" : r.strike === pw ? " P" : ""}
            </span>
            <div><div style={{ width: `${(call / max) * 100}%`, height: 8, borderRadius: 2, background: r.strike === cw ? "var(--cp-danger)" : "color-mix(in srgb, var(--cp-danger) 45%, transparent)" }} /></div>
          </div>
        );
      })}
      <span style={{ ...quiet, fontSize: 11 }}>{fmtDay(chain.summary.expiry)} expiry, {rows.length} strikes around the ATM {fmtNum(chain.summary.atm_strike, 0)}. C = call wall, P = put wall.</span>
    </div>
  );
}

function Stat({ k, v, sub, testId }: { k: string; v: ReactNode; sub?: ReactNode; testId: string }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <span style={{ ...mono, fontSize: 8.5, color: "var(--cp-ink-3)" }}>{k}</span>
      <span data-testid={testId} className="cp-num" style={{ fontSize: 15, color: "var(--cp-ink)" }}>{v}</span>
      {sub && <span style={{ ...quiet, fontSize: 10.5 }}>{sub}</span>}
    </div>
  );
}

function CandidateStructure({ symbol, onStrategyLab }: { symbol: string; onStrategyLab: () => void }) {
  const board = useTop10Fno();
  const all = [...(board.data?.classes.index_options?.ideas ?? []), ...(board.data?.classes.stock_fno?.ideas ?? [])];
  const idea = all.find((i) => i.underlying.toUpperCase() === symbol.toUpperCase()) ?? null;
  let body: ReactNode;
  if (board.isPending) body = <LoadingBlock label="Reading today's F&O ideas" rows={2} />;
  else if (board.isError) body = <span data-testid="lc-structure-error" style={quiet}>Today&apos;s F&amp;O ideas could not be read, so no candidate structure is shown.</span>;
  else if (!idea) body = <span data-testid="lc-structure-none" style={quiet}>No candidate structure for {symbol} on today&apos;s F&amp;O ideas board.</span>;
  else {
    const bounded = idea.profit_unbounded !== true && idea.loss_unbounded !== true;
    const net = idea.net_premium ?? null;
    body = (
      <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span data-testid="lc-structure-name" style={{ fontSize: 13, fontWeight: 600 }}>{idea.name}{idea.expiry ? ` · ${fmtDay(idea.expiry)}` : ""}</span>
        <ul className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 0, listStyle: "none", fontSize: 12.5 }}>
          {idea.legs.map((l, i) => (
            <li key={i} data-testid="lc-structure-leg" className="cp-num">
              {l.side === "sell" ? "Sell" : "Buy"} {l.quantity ?? 1} × {l.strike != null ? fmtNum(l.strike, 0) : ""} {l.option_type ?? l.kind}{l.entry_price != null ? ` @ ${fmtPrice(l.entry_price)}` : ""}
            </li>
          ))}
        </ul>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,110px),1fr))", gap: "6px 10px" }}>
          <Stat k={net != null && net < 0 ? "Net credit" : "Net debit"} v={net != null ? fmtPrice(Math.abs(net)) : "—"} testId="lc-structure-net" />
          <Stat k="Max loss" v={idea.loss_unbounded ? "unbounded" : fmtPrice(idea.max_loss ?? null)} testId="lc-structure-maxloss" />
          <Stat k="Max profit" v={idea.profit_unbounded ? "unbounded" : fmtPrice(idea.max_profit ?? null)} testId="lc-structure-maxprofit" />
          <Stat k="Breakeven" v={idea.breakevens.length ? idea.breakevens.map((b) => fmtNum(b, 2)).join(" / ") : "—"} testId="lc-structure-be" />
        </div>
        <span data-testid="lc-structure-note" style={{ ...quiet, fontSize: 11.5 }}>
          {bounded ? "Both legs bounded." : "Not bounded on every side."} Margin is an estimate{idea.margin != null ? ` (${fmtPrice(idea.margin)})` : idea.margin_reason ? ` (${idea.margin_reason})` : ""}. OI shows positioning, not who initiated it.
        </span>
      </div>
    );
  }
  return (
    <div data-testid="lc-structure" className="flex min-w-0 flex-col" style={{ gap: 8, padding: "10px 12px", borderRadius: 12, border: "1px dashed var(--line-3)", background: "var(--bg-2)" }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: 6 }}>
        <span data-testid="lc-structure-title" style={{ ...mono, color: "var(--cp-ink-2)" }}>Candidate structure</span>
        <button type="button" data-testid="lc-structure-lab" style={{ ...linkBtn, fontSize: 12 }} onClick={onStrategyLab}>Trade Desk › Strategy Lab ›</button>
      </div>
      {body}
    </div>
  );
}

export function FnoSetupCard({ symbol, oi, oiNote, onStrategyLab }: { symbol: string; oi: OiBuildup | null; oiNote: string | null; onStrategyLab: () => void }) {
  const exp = useFnoExpiries(symbol);
  const listed = exp.data?.kind === "ok" ? exp.data.data.expiries : [];
  const picked = listed.find((e) => e.days_to_expiry > 0)?.expiry ?? null;      // an expiry on its own day has no IV or expected move
  const { state } = useOptionChain(symbol, picked);
  const iv = useIvHistory(symbol);
  const chain = state.status === "ok" ? state.chain : null;
  const s = chain?.summary ?? null;
  const ivp = iv.data?.iv_percentile ?? null;
  const ivStale = !!(iv.data?.last_session && s?.as_of && iv.data.last_session < s.as_of);
  const age = s ? `Chain end of day · ${fmtDay(s.as_of)}` : state.status === "loading" ? "Chain: reading" : "Chain unavailable";

  let chainBody: ReactNode;
  if (state.status === "loading") chainBody = <LoadingBlock label="Reading the option chain" rows={3} />;
  else if (state.status === "none") chainBody = <span data-testid="lc-fno-none" style={quiet}>{state.message}.</span>;
  else if (state.status === "error") chainBody = <span data-testid="lc-fno-error" role="alert" style={{ ...quiet, color: "var(--amber)" }}>The option chain did not load.</span>;
  else if (chain && s) {
    chainBody = (
      <>
        {s.call_wall && (
          <Line testId="lc-fno-line-callwall" tag={<Tag text={`Call wall ${fmtNum(s.call_wall.strike, 0)}`} color="var(--cp-danger)" />}>
            The most call OI at or above the spot ({lakh(s.call_wall.oi)}): resistance as positioning, not a level the price must respect.
          </Line>
        )}
        {s.put_wall && (
          <Line testId="lc-fno-line-putwall" tag={<Tag text={`Put wall ${fmtNum(s.put_wall.strike, 0)}`} color="var(--mint)" />}>
            The most put OI at or below the spot ({lakh(s.put_wall.oi)}): support as positioning.
          </Line>
        )}
        <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <span style={{ ...mono, color: "var(--cp-ink-3)" }}>OI by strike · call wall and put wall</span>
          <OiByStrike chain={chain} />
        </div>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,96px),1fr))", gap: "8px 12px" }}>
          <Stat k="PCR" v={s.pcr != null ? fmtNum(s.pcr, 2) : "—"} testId="lc-fno-pcr" />
          <Stat k="ATM IV" v={s.atm_iv != null ? fmtPct(s.atm_iv, { digits: 1 }) : "—"} sub="model, end of day" testId="lc-fno-atmiv" />
          <Stat k="IV pctile" v={ivp != null ? `${fmtNum(ivp, 0)}${ivStale ? " · stale" : ""}` : iv.isPending ? "…" : "not recorded"}
            sub={ivp == null ? (iv.data?.reason ? "needs 252 recorded sessions" : iv.isError ? "unavailable" : undefined) : ivStale ? `last ${fmtDay(iv.data?.last_session)}` : undefined} testId="lc-fno-ivp" />
          <Stat k="Exp. move" v={s.expected_move != null ? `±${fmtNum(s.expected_move, 2)}` : "—"} sub={s.expected_move_pct != null ? fmtPct(s.expected_move_pct, { digits: 2 }) : undefined} testId="lc-fno-em" />
        </div>
      </>
    );
  }
  return (
    <section data-testid="lc-fno" className="flex min-w-0 flex-col" style={{ gap: 12, padding: "14px 16px", borderRadius: 16, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: 6 }}>
        <h3 className="cp-eyebrow m-0" style={{ color: "var(--cp-ink-2)" }}>F&amp;O setup</h3>
        <span data-testid="lc-fno-age" style={{ ...mono, color: "var(--cp-ink-3)" }}>{age}</span>
      </div>
      {oi ? <BuildupLines oi={oi} /> : oiNote ? <span data-testid="lc-fno-oi-note" style={quiet}>{oiNote}</span> : null}
      {chainBody}
      <CandidateStructure symbol={symbol} onStrategyLab={onStrategyLab} />
    </section>
  );
}
