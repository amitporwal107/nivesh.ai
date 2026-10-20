/**
 * Strategy Builder — what-if controls for the payoff (PRD §16.6 D): the underlying price, the change in
 * implied volatility, the evaluation date, and the size. They only collect inputs; `buildScenarioRequest`
 * turns the inputs and the base request into the request the payoff route takes, and the chart updates
 * from the answer (usePayoff). An input the legs cannot use is disabled with the reason beside it:
 * cash and futures have no implied volatility and cash has no expiry date. The date is what asks the
 * route for the pre-expiry estimate (it is null unless requested).
 */
import { useId, type CSSProperties } from "react";
import type { PayoffLeg, PayoffRequest } from "./strategy-contract";
import { rs } from "./strategy-format";

export interface ScenarioInputs {
  /** The what-if underlying price; null keeps the reference price (no scenario point). */
  underlyingPrice: number | null;
  /** Change in implied volatility, in percentage points. */
  ivShiftPct: number;
  /** YYYY-MM-DD between the data date and the nearest expiry; null: no pre-expiry date chosen. */
  evalDate: string | null;
  /** One leg: its own quantity (shares or lots). Several legs: a whole-number multiple of the base position. */
  size: number | null;
}

export const DEFAULT_SCENARIO: ScenarioInputs = { underlyingPrice: null, ivShiftPct: 0, evalDate: null, size: null };

/** The request for the base position plus the what-if inputs: scaled size, a "what-if" scenario point, a pre-expiry block. */
export function buildScenarioRequest(base: PayoffRequest, s: ScenarioInputs, opts: { rate_pct?: number } = {}): PayoffRequest {
  const single = base.legs.length === 1;
  const legs: PayoffLeg[] = base.legs.map((l) => ({
    ...l,
    quantity: s.size == null ? l.quantity : single ? s.size : l.quantity * s.size,
  }));
  const req: PayoffRequest = { ...base, legs };
  if (s.underlyingPrice != null) req.scenarios = [...(base.scenarios ?? []), { name: "what-if", underlying_price: s.underlyingPrice }];
  if (s.evalDate) {
    req.pre_expiry = { ...(base.pre_expiry ?? { date: s.evalDate }), date: s.evalDate, iv_shift_pct: s.ivShiftPct, ...(opts.rate_pct != null ? { rate_pct: opts.rate_pct } : {}) };
  }
  return req;
}

export interface ScenarioControlsProps {
  /** The base position's legs (decides which inputs apply). */
  legs: PayoffLeg[];
  referencePrice: number;
  /** Slider range for the underlying price; defaults to the reference price ±25 %. */
  priceMin?: number;
  priceMax?: number;
  /** The date the end-of-day data is as of (the earliest evaluation date), YYYY-MM-DD. */
  dataDate: string | null;
  value: ScenarioInputs;
  onChange: (next: ScenarioInputs) => void;
  onReset: () => void;
  persona?: "trader" | "investor";
}

const field: CSSProperties = {
  width: "100%", minWidth: 0, padding: "7px 9px", borderRadius: 8, border: "1px solid var(--line-2)",
  background: "var(--bg-2)", color: "var(--cp-ink)", fontFamily: "var(--mono)", fontSize: 13,
};

export function ScenarioControls({ legs, referencePrice, priceMin, priceMax, dataDate, value, onChange, onReset, persona = "trader" }: ScenarioControlsProps) {
  const uid = useId();
  const investor = persona === "investor";
  const hasOption = legs.some((l) => l.kind === "option");
  const expiries = legs.map((l) => l.expiry).filter((e): e is string => !!e).sort();
  const nearest = expiries[0] ?? null;
  const lo0 = priceMin ?? referencePrice * 0.75;
  const hi0 = priceMax ?? referencePrice * 1.25;
  // A round step (at least 0.05), and bounds on that step, so a typed round price is also a slider position.
  const rough = (hi0 - lo0) / 400;
  const step = [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 25].find((s) => s >= rough) ?? 25;
  const lo = Math.floor(lo0 / step) * step;
  const hi = Math.ceil(hi0 / step) * step;
  const price = value.underlyingPrice ?? referencePrice;
  const single = legs.length === 1;

  const ivReason = !hasOption ? "Implied volatility applies to options only; this position has none." : null;
  const dateReason = !nearest ? "Cash has no expiry date to count down to." : !dataDate ? "The data date is not known." : null;
  const set = (patch: Partial<ScenarioInputs>) => onChange({ ...value, ...patch });
  const numOrNull = (v: string): number | null => (v.trim() === "" || !Number.isFinite(Number(v)) ? null : Number(v));

  return (
    <div data-testid="scenario-controls" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,230px),1fr))", gap: "12px 16px" }}>
        <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <label htmlFor={`${uid}-px`} className="cp-eyebrow">{investor ? "If the stock is at" : "Underlying price"}</label>
          <input
            data-testid="scenario-price-slider" type="range" aria-label="Underlying price slider" min={lo} max={hi} step={step} value={Math.min(hi, Math.max(lo, price))}
            onChange={(e) => set({ underlyingPrice: Number(e.target.value) })} style={{ width: "100%" }}
          />
          <input
            id={`${uid}-px`} data-testid="scenario-price" type="number" inputMode="decimal" step={step} value={value.underlyingPrice ?? ""} placeholder={`${referencePrice}`}
            onChange={(e) => set({ underlyingPrice: numOrNull(e.target.value) })} style={field}
          />
          <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>
            {value.underlyingPrice == null ? `Reference ${rs(referencePrice)} (last close); nothing marked.` : `Marked as a what-if point at ${rs(value.underlyingPrice)}.`}
          </span>
        </div>

        <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <label htmlFor={`${uid}-iv`} className="cp-eyebrow">{investor ? "Volatility change" : "IV shift (points)"}</label>
          <input
            data-testid="scenario-iv-slider" type="range" aria-label="IV shift slider" min={-20} max={20} step={0.5} value={value.ivShiftPct} disabled={!!ivReason}
            onChange={(e) => set({ ivShiftPct: Number(e.target.value) })} style={{ width: "100%" }}
          />
          <input
            id={`${uid}-iv`} data-testid="scenario-iv" type="number" inputMode="decimal" step={0.5} value={value.ivShiftPct} disabled={!!ivReason}
            onChange={(e) => set({ ivShiftPct: numOrNull(e.target.value) ?? 0 })} style={{ ...field, opacity: ivReason ? 0.55 : 1 }}
          />
          {ivReason
            ? <span data-testid="scenario-iv-reason" style={{ fontSize: 11, color: "var(--amber)" }}>{ivReason}</span>
            : <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>Applies to the pre-expiry estimate, which needs an evaluation date.</span>}
        </div>

        <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <label htmlFor={`${uid}-date`} className="cp-eyebrow">{investor ? "Evaluate on" : "Evaluation date"}</label>
          <input
            id={`${uid}-date`} data-testid="scenario-date" type="date" value={value.evalDate ?? ""} min={dataDate ?? undefined} max={nearest ?? undefined} disabled={!!dateReason}
            onChange={(e) => set({ evalDate: e.target.value || null })} style={{ ...field, opacity: dateReason ? 0.55 : 1 }}
          />
          {dateReason
            ? <span data-testid="scenario-date-reason" style={{ fontSize: 11, color: "var(--amber)" }}>{dateReason}</span>
            : <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>From the data date {dataDate} to the nearest expiry {nearest}; setting a date asks for the pre-expiry estimate.</span>}
        </div>

        <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <label htmlFor={`${uid}-size`} className="cp-eyebrow">{single ? (legs[0].kind === "cash" ? "Shares" : "Lots") : "Position size (× base)"}</label>
          <input
            id={`${uid}-size`} data-testid="scenario-size" type="number" inputMode="numeric" min={1} step={1} value={value.size ?? ""} placeholder={single ? `${legs[0].quantity}` : "1"}
            onChange={(e) => { const n = numOrNull(e.target.value); set({ size: n != null && n >= 1 ? Math.floor(n) : null }); }} style={field}
          />
          <span style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{single ? "The leg's own quantity." : "Every leg is scaled together, keeping the ratios."}</span>
        </div>
      </div>
      <div>
        <button type="button" data-testid="scenario-reset" onClick={onReset} className="cp-btn" data-variant="ghost">Reset to the base position</button>
      </div>
    </div>
  );
}
