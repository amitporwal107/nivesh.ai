# F&O Stage B3: options positioning, Greeks and strategy outcomes, pre-registration (written before any B3 code or data export)

Date: 2026-10-23 · Decision of record: the user's Greeks message of 2026-10-23. Companion to B1 (near-month futures, Kite 2021+) and B2 (expiry-curve futures signals); both unchanged. B3 is **sequenced after B2** and does not start until B2's report exists.

## 0. Principle
Greeks are not used to rescue a futures ranking that failed (Stage A). B3 asks three separate questions, in order: (1) does futures positioning carry information (A/B1/B2); (2) do options-derived features add **incremental** value over the frozen futures baseline; (3) can a signal be turned into a defined-risk strategy with positive risk-adjusted return after costs. A "no" at an earlier question stops the later claim, not the later report.

## 1. Data verified 2026-10-23 (read-only, warehouse `nidp.fno_bhavcopy`)
Options, 260 sessions (2025-10-01 to 2026-10-22): STO 8,759,395 rows (OI above zero on 4,869,033), IDO 1,333,049 (OI above zero on 565,078). Every row has close, settle, underlying price and lot size; OI and change in OI present. This supports **end-of-day** option research for one year. Not verified and not assumed: Kite option history for expired contracts (instrument list holds active contracts only), intraday option prices (none stored; the 5-minute option-OI job is not built), interest-rate and dividend history (no table seen). **Intraday Greek behaviour cannot be validated from daily snapshots**; it waits for the intraday snapshot job.

## 2. Greeks methodology (versioned: `greeks-v1`)
- Computed by us from that day's own inputs only: option settle price (close as a stated sensitivity), same-row underlying price, strike, expiry date, lot size. Never today's Greeks for a past signal.
- Model: Black-Scholes on the underlying's own price for index and stock options, with a documented fixed rate (RBI repo at the date, one table, versioned) and **zero dividend assumption** (stated limit: stock-dividend and early-exercise effects on American-style stock options are ignored; Indian stock options are physically settled, index options European).
- IV by bisection per contract; rejected (null, counted) when price is under intrinsic plus a tick, the price is zero, or time to expiry is under one session. Each stored row carries: date, underlying price, strike, expiry, IV, delta, gamma, theta (per calendar day), vega (per 1 vol point), rho, `greeks_version`, `rate`, `dividend`.
- The methodology and the count of rejected contracts are in the report. A change of any assumption is a new `greeks_version` and a new experiment.

## 3. Features per underlying, session and expiry bucket (near / next / far as in B2)
ATM (nearest strike to the same-row underlying price) call and put: IV, delta, gamma, theta, vega. IV by moneyness bucket (-10%, -5%, ATM, +5%, +10%); skew (25-delta-style put IV minus call IV approximated by the +-5% moneyness buckets, defined in code); term structure (far ATM IV - near ATM IV); ATM straddle premium and implied expected move (straddle / spot); put-call OI ratio; call and put OI and OI change by strike bucket; OI concentration (share of OI within +-5% of spot); delta-, gamma- and vega-weighted OI = OI x lot size x the per-unit Greek, **aggregated per underlying and expiry only, never summed across underlyings with different multipliers or prices**, and normalised by the underlying's value (stated formula in code).

## 4. Labelling (fixed now, also for the UI)
Three separate labels, never merged: **observed OI concentration** (contracts open at a strike); **estimated Greek-weighted OI exposure** (OI x multiplier x model Greek); **dealer positioning estimate**, which is **not produced** unless a documented defensible method exists (none does today). Public OI does not say who is long or short. No output may be named "dealer gamma", "gamma wall", or "support/resistance". Put-OI rise is described as put buying, writing, a spread or a hedge: undetermined.

## 5. Experiments (each a separate counted family; the denominator is reported)
- **A** futures-only baseline: the frozen B2 signal.
- **B** futures + options confirmation: the same signal and the same frozen thresholds, plus **one pre-registered confirmation rule per category, written before running**: long build-up needs ATM call-IV change >= 0 or call-OI change > put-OI change; short build-up the mirror; short covering and long unwinding need premium-fall evidence (ATM straddle change < 0). Evaluated as incremental: B minus A on the same sessions, benchmark-relative, net of cost. Every additional feature in section 3 is **reported as a diagnostic with its IC against the outcome, not used to select a rule**.
- **C** expiry-specific: B repeated independently for near, next and far.
- **D** strategy outcomes: for each category one defined-risk structure fixed now (long build-up: bull call spread, ATM / next strike at +5%; short build-up: bear put spread; short covering and long unwinding: no structure, reported "no strategy defined"), entered at the next session's settle price of each leg, held h = 1, 3, 5 sessions, exit at that session's settle, using **actual historical option prices from the bhavcopy**, never inferred from the underlying return. Costs: brokerage, STT (on sell side premium; exercise STT for expiry ITM noted), exchange, GST, stamp, plus a spread/slippage assumption stated in the report. Outcome: P&L per lot, return on max loss, with the long call's IV-decline and theta losses decomposed. Compared with the futures trade in the same sessions.

## 6. Windows, statistics and verdicts
Same U / D / V / T windows and session-level Newey-West statistics as B2; options-confirmation rules are fixed before any run so D is not used to pick them (D is reported as in-sample). Verdicts use B2's three states. For experiment B: **supported** only if B minus A is positive on pooled U+V+T for at least 3 of 5 frozen settings with Newey-West t >= 1.645 on at least 2 and at least 30 pooled signal sessions; D: supported only if mean return on max loss after costs is positive pooled with the same t rule. Nothing is `validated` by B3.

## 7. Strategy panel (product requirement recorded, not built by B3)
Net delta and underlying-equivalent exposure, gamma, theta per day, vega, P&L grid across spot, time and IV, max loss, max profit, breakeven, capital required, costs, liquidity. Strategy Greeks are signed-quantity sums with lot size included: sum of q_i x Greek_i, units stated. The probability-of-profit method is a documented release blocker (unchanged).

## 8. Declared limits
One year of option history; EOD only; model Greeks with a zero-dividend, fixed-rate assumption; settle prices of illiquid strikes are unreliable (liquidity floor: OI and volume above zero on the day for every leg, otherwise the trade is excluded and counted); chain data cannot identify who is long or short; strategy fills at settle are optimistic (spread/slippage assumption mitigates, does not remove); the confirmation rules are one pre-registered choice each, not a search.

## 9. Sequence and cost
B2 first (futures only, bhavcopy, no new data pulls). B3 then needs a one-off option export (a windowed subset: +-10 strikes around ATM, three expiries, to keep the export to a few million rows), a Greeks module with tests against known Black-Scholes values, and the runner. Intraday Greek research waits for the 5-minute option snapshot job and at least a few weeks of saved snapshots.
