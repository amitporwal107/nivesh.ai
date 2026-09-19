# Were the owner's 2026-09-18 Screener +5% gainers selected by our models?

Owner's Screener list (shares > 1.5 cr, volume > 1 lakh, sales > 10, PAT > 1; ranks 16–104 shown). Matched to NSE symbols
by exact 18-Sep close and a ≥ 5% day return: **78 of 89** (11 unmatched, mostly SME-segment names absent from the
main-board table). Data: `/app/research/screener_20260918/`. **One day, winners only — descriptive, not evidence.**

## Answer: no — neither selection system picked them
| system | coverage | result |
|---|---|---|
| v4 movement model (forward paper run, P5 head) | **41 of 78** in its ~1,000-stock universe | **0 in its top 5 (the picks) or top 10**; 5 in top 50, 9 in top 100, 16 in top 200; median rank 242 of 997 (random ≈ 498). Its top 50 had 16.0% ≥ 5% movers vs 6.1% of its universe (2.6× lift) — ranks movement better than chance, but its picks missed every one |
| v4 picks' actual 18-Sep returns | — | P5: SHAREINDIA +4.5%, TRIVENI +2.7%, TEGA +1.2%, PNCINFRA −0.5%, RATNAVEER −1.5% |
| Track 1 (gap-down screen) | 53 of 78 in its liquid universe | **0 signals** — none gapped down; by design it cannot select up-movers |

## How the gainers moved
- **Intraday, not at the open:** median gap +0.56%; 55 of 78 opened within ±1%; only 6 gapped up ≥ 3%; median **92%** of
  the day's move came after the open (consistent with the earlier finding that 72% of +5% closers moved intraday).
- **Timing (28 liquid names with 5-minute bars):** first traded +5% above the previous close by 10:00 — 21%; by 12:30 —
  68%; by 14:00 — 75%; 3 only via the closing auction. At 09:45 the median gainer was already **+2.95%** (38% of its day);
  at 12:00 +4.29%. First-30-minute volume: 8% of the day (median).

## What it suggests (a NEW hypothesis — not a finding)
Early strength was visible for many of these names, but this list contains **only the winners**; stocks that were
+3% at 09:45 and then faded are invisible here. The hypothesis worth testing on the discovery 5-minute store (785 liquid
names, 2024-08 → 2026-09), including the faders: **"early intraday strength continuation"** — e.g. up ≥ 2–3% by
09:45–10:30 on above-normal volume → enter at that time, hold to the close; judged on net return after costs from the
later entry. Registry family #20 (candidate). A second gap it exposes: **37 of 78 gainers are outside the v4 model's
universe** — small caps, where +5% days concentrate.

---

## Follow-up (owner: "something earlier made them uptrend — momentum, results, news — and we should catch it intraday")

### Before the open (18 Sep, gainers vs 1,502-stock comparison universe with 20-day avg volume ≥ 1 lakh; base rate 3.9%)
| signal | gainers | others | lift | flagged | precision |
|---|---|---|---|---|---|
| 20-day return > +10% | 31.0% | 11.4% | 2.72× | 183 | 9.8% |
| 60-day return > +20% | 29.3% | 13.3% | 2.20× | 209 | 8.1% |
| above 50-DMA | 62.1% | 33.3% | 1.86× | 517 | 7.0% |
| ATR > 4% of price | 70.7% | 37.5% | 1.89× | — | — |
| material announcement, prior week or overnight | — | — | — | 148 | 6.8% |
| material announcement overnight only | 6.9% | 2.1% | 3.32× | — | 4 names: GMMPFAUDLR, SAMBHV, COASTCORP, ACMESOLAR |
Momentum and events raise the odds 2–3×, but ~90% of flagged stocks did not make +5%. Autos ran hottest (5 of 52).
Caveat: BSE-only announcements lack NSE tickers (15,578 of 26,817 rows usable).

### Intraday, same day (741 liquid names, faders included): up ≥ 3% at 09:45 → 59% closed ≥ +5%, +1.59% from 09:45 to close.

### The real test — every session, 2024-08 → 2026-09 (528 sessions, 370,376 stock-days, ETFs excluded, 0.30% cost)
| rule: enter 09:45, exit at the official close | trades | net per session | t | years |
|---|---|---|---|---|
| baseline, every stock | 370,376 | −0.348% | −11.68 | all negative |
| up ≥ +2% at 09:45 | 35,110 | −0.469% | −12.14 | all negative |
| up ≥ +3% at 09:45 | 16,593 | −0.469% | −10.05 | all negative |
| up ≥ +4% at 09:45 | 8,492 | −0.528% | −9.52 | all negative |
| up ≥ +3%, 5 strongest per session | 2,592 | −0.546% | −7.38 | all negative |
| up ≥ +3% and gap < +1% (intraday-driven) | 7,812 | −0.438% | −6.71 | all negative |
| up ≥ +3% and 20-day value ≥ Rs 25 cr | 10,700 | −0.491% | −10.23 | all negative |

**Family #20 FAILS in discovery.** Early strength identifies movers but, across sessions, fades more than the average stock
(even gross of costs: −0.17% vs −0.05%). 18 Sep was an exception day; the Screener list shows only the winners. With the
gap-down recovery result, the consistent picture is **intraday mean reversion**: early strength fades, gap-downs recover.
Code/data: `/app/research/family20/`.
