/**
 * Model estimates on the Options lab: the header strip for the loaded chain
 * (ATM implied volatility, the ATM straddle, the forward, days to expiry) and
 * the strategy builder's figures for the typed legs (chance of profit, net
 * Greeks; trading/odds.ts).
 *
 * Every figure here is worked out by the chain route with Black-76 from the
 * exchange's end-of-day prices (backend/services/option_pricing.py). Each
 * block says so with MODEL_LABEL, and a figure the route sent as null, or did
 * not send, is shown as "Not available", never as a number.
 */
import type { ReactNode } from "react";
import { fmtINR, fmtNum } from "../../components/ui";
import { fmtLevel } from "./PayoffResult";
import type { FnoChain, FnoSummary } from "./fno";
import { chanceOfProfit, netGreeks } from "./odds";
import { fmtDay, fmtSigned } from "./parts";
import type { Leg } from "./payoff";

export const MODEL_LABEL = "Model estimate from end-of-day prices (Black-76)";
export const NOT_AVAILABLE = "Not available";

/** "13.07%", or "Not available". */
export function fmtIv(iv: number | null | undefined): string {
  return iv == null ? NOT_AVAILABLE : `${fmtNum(iv, 2)}%`;
}

/** "±476.45", or "Not available". */
export function fmtMove(points: number | null | undefined): string {
  return points == null ? NOT_AVAILABLE : `±${fmtNum(points, 2)}`;
}

/** The model label with the interest rate the model used, when the route sent it. */
export function modelLabel(s: FnoSummary): string {
  return s.rate_pct == null ? MODEL_LABEL : `${MODEL_LABEL}, at an interest rate of ${fmtNum(s.rate_pct, 2)}% a year`;
}

/** How the forward was found, in a few plain words; null when there is none. */
export function forwardBasisWords(s: FnoSummary): string | null {
  switch (s.forward_basis) {
    case "future": return "Same-expiry future’s settle price";
    case "put-call parity": return "Implied from call and put prices";
    case "carried spot": return "Spot carried to expiry";
    default: return null;
  }
}

/** One sentence naming the forward and how it was found, for the reader who wants to check the model. */
export function forwardNote(s: FnoSummary): string {
  if (s.forward == null || s.forward_basis == null) return "No forward could be set for this expiry, so nothing was priced.";
  const forward = `Forward ${fmtNum(s.forward, 2)}`;
  const expiry = fmtDay(s.expiry);
  if (s.forward_basis === "future") return `${forward} · the ${expiry} future’s settle price.`;
  if (s.forward_basis === "put-call parity") {
    return `${forward} · implied from call and put prices, at the strike where the two are closest, because no future expires on ${expiry}.`;
  }
  return `${forward} · the spot carried to expiry${s.rate_pct == null ? "" : ` at ${fmtNum(s.rate_pct, 2)}% a year`}, because no future expires on ${expiry} and no strike had both its call and its put traded. If the day’s spot and option prices were not struck at the same moment, calls and puts at one strike show different IV.`;
}

/** Why the chain carries no model estimate at all, or null when it does. */
export function noModelReason(s: FnoSummary): string | null {
  if (s.days_to_expiry === undefined && s.forward === undefined) return "The server did not send model estimates for this chain.";
  if (s.days_to_expiry != null && s.days_to_expiry <= 0) return "These contracts expired at this close, so there is nothing left to estimate.";
  if (s.forward == null) return "No forward could be set for this expiry (the futures could not be read, or no future expires that day, no strike had both sides traded and there is no spot to carry), so nothing was priced.";
  return null;
}

function Figure({ k, testId, value, sub }: { k: string; testId: string; value: ReactNode; sub: ReactNode }) {
  return (
    <div className="flex flex-col min-w-0" style={{ gap: 3, padding: "10px 12px", borderRadius: 10, background: "var(--bg-2)" }}>
      <span className="cp-eyebrow">{k}</span>
      <span data-testid={testId} className="cp-num" style={{ fontSize: 18, color: "var(--cp-ink)" }}>{value}</span>
      <span style={{ fontSize: 11, lineHeight: 1.4, color: "var(--cp-ink-3)" }}>{sub}</span>
    </div>
  );
}

const GRID = { gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,150px),1fr))", gap: 8 } as const;
const LABEL_STYLE = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;

// ── header strip ─────────────────────────────────────────────────────────

export function ModelStrip({ chain }: { chain: FnoChain }) {
  const s = chain.summary;
  const none = noModelReason(s);
  const days = s.days_to_expiry;
  return (
    <div data-testid="optlab-model" className="cp-card flex flex-col min-w-0" style={{ gap: 10, padding: 14 }}>
      <div className="grid" style={GRID}>
        <Figure
          k="ATM implied volatility"
          testId="optlab-atm-iv"
          value={fmtIv(s.atm_iv)}
          sub={s.atm_iv != null && s.atm_strike != null ? `A year · mean of the ${fmtLevel(s.atm_strike)} call and put` : "No figure for the ATM strike"}
        />
        <Figure
          k="Expected move to expiry"
          testId="optlab-expected-move"
          value={fmtMove(s.expected_move)}
          sub={s.expected_move != null && s.atm_strike != null
            ? <>ATM straddle: {fmtLevel(s.atm_strike)} call + put close{s.expected_move_pct != null && <> · <span data-testid="optlab-expected-move-pct">{fmtNum(s.expected_move_pct, 2)}%</span> of the spot</>}</>
            : "Needs a call and a put close at the ATM strike"}
        />
        <Figure
          k="Forward"
          testId="optlab-forward"
          value={s.forward == null ? NOT_AVAILABLE : fmtNum(s.forward, 2)}
          sub={<span data-testid="optlab-forward-basis">{forwardBasisWords(s) ?? "No forward set"}</span>}
        />
        <Figure
          k="Days to expiry"
          testId="optlab-days"
          value={days == null ? NOT_AVAILABLE : fmtNum(days)}
          sub={`Calendar days from ${fmtDay(s.as_of)} to ${fmtDay(s.expiry)}`}
        />
      </div>
      <span data-testid="optlab-model-label" style={LABEL_STYLE}>
        {modelLabel(s)}. {none ?? forwardNote(s)} The expected move is what the ATM straddle cost at the close: a market price for movement either way, not a forecast.
      </span>
    </div>
  );
}

// ── the builder's legs ───────────────────────────────────────────────────

const legName = (l: Leg) => `${fmtLevel(l.strike)} ${l.type}`;

/** Chance of profit and net Greeks for complete legs, against the loaded chain. */
export function LegModel({ chain, legs, lotSize }: { chain: FnoChain | null; legs: Leg[]; lotSize: number }) {
  if (!chain) {
    return (
      <div data-testid="optlab-leg-model" className="cp-card flex flex-col" style={{ gap: 6, padding: 16 }}>
        <span className="cp-eyebrow">Chance of profit and net Greeks</span>
        <span data-testid="optlab-leg-model-unavailable" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {NOT_AVAILABLE}. No end-of-day chain is loaded, so there is no implied volatility to work them from.
        </span>
      </div>
    );
  }
  const s = chain.summary;
  const chance = chanceOfProfit(legs, lotSize, s.forward, s.atm_iv, s.days_to_expiry);
  const { net, missing } = netGreeks(chain, legs, lotSize);
  const rupees = (n: number) => fmtINR(n, { signed: true });
  return (
    <div data-testid="optlab-leg-model" className="cp-card flex flex-col min-w-0" style={{ gap: 10, padding: 16 }}>
      <span className="cp-eyebrow">Model estimates for these legs · {chain.symbol} {fmtDay(s.expiry)}</span>
      <div className="grid" style={GRID}>
        <Figure
          k="Chance of profit"
          testId="optlab-chance"
          value={chance == null ? NOT_AVAILABLE : `${fmtNum(chance * 100, 1)}%`}
          sub={chance == null ? "Needs the chain’s forward and ATM IV" : `Model probability at expiry, at the ATM IV of ${fmtIv(s.atm_iv)}. Not a forecast`}
        />
        <Figure k="Net delta" testId="optlab-net-delta" value={net ? fmtSigned(net.delta, 2) : NOT_AVAILABLE} sub="₹ per one-point rise in the forward" />
        <Figure k="Net gamma" testId="optlab-net-gamma" value={net ? fmtSigned(net.gamma, 4) : NOT_AVAILABLE} sub="Change in delta per point" />
        <Figure k="Net theta" testId="optlab-net-theta" value={net ? rupees(net.theta) : NOT_AVAILABLE} sub="Per calendar day, all else unchanged" />
        <Figure k="Net vega" testId="optlab-net-vega" value={net ? rupees(net.vega) : NOT_AVAILABLE} sub="Per one-point rise in IV" />
      </div>
      {missing.length > 0 && (
        <span data-testid="optlab-net-greeks-missing" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          No net Greeks: the chain has no model estimate for {missing.map(legName).join(", ")} (the strike is outside the strikes sent, or that contract has no implied volatility).
        </span>
      )}
      <span data-testid="optlab-leg-model-label" style={LABEL_STYLE}>
        {modelLabel(s)}, as of {fmtDay(s.as_of)}. Each Greek is the contract’s end-of-day figure at the leg’s strike and side × lots × lot size of {fmtNum(lotSize)}; it does not follow a premium you type. Chance of profit is the risk-neutral probability that this P&L is above zero at expiry, with one volatility for every strike. It is how the options were priced, not how often such a trade has worked.
      </span>
    </div>
  );
}
