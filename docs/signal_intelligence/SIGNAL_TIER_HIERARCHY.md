# Signal tier hierarchy and signal strength v2

Status: **design, points provisional** until the calibration study (§8) has run. Owner, 5 Nov 2026: "add extra points to the
signal strength based on what is the signal and how strong it is in terms of price volume action. Now we need to create this
tier hierarchy" (with the owner's pasted framework: Tier 1 / Tier 2 signals, setups A–E, the 100-point component model and
the rule "test each signal independently and in combinations … before assigning a high conviction score").

One hierarchy for every place that scores a chart signal: the desk's AI Trader (`backend/autodesk/agents/ai_trader.py`, today
`ait-rules-v1`) and the Scan dashboard (`backend/services/scan_builder/signal_strength.py`, today quality + trend + reason +
size + participation). Both keep their own detectors; both read their points from this table.

## 1. The score

```
signal strength (0–100) =  tier points          what fired                     max 30
                         + price-volume points  how strongly it fired          max 25
                         + confluence points    independent signals together   max 10
                         + context points       trend, structure, RS, sector   max 25
                         + quality & size       company quality, index size    max 10
                         − penalties            chasing, gap against, pump-and-dump, market against
                         clamped to 0–100
```

| Score | Class | What the desk does |
|---|---|---|
| 85–100 | Exceptional | first in the queue; full per-trade risk |
| 75–84 | Strong | proposal; full per-trade risk |
| 65–74 | Developing | watchlist; proposal only when slots are free, half risk |
| 50–64 | Weak | listed, no proposal |
| below 50 | Avoid | not shown as a signal |

Ties are broken by price-volume points, then relative strength, then traded value — never by name.

## 2. Tier points — what fired (the highest tier that fired counts)

| Tier | Points | Bullish signal | Bearish mirror | Detector today |
|---|---|---|---|---|
| **S — power** | 30 | **Multi-year breakout**: close above the highest high of ≥ 2 years, volume ≥ 2× | multi-year breakdown | Scan list `dt_multiyear` (history limit: adjusted daily data starts 1 Apr 2024) |
| S | 30 | **52-week-high breakout** on volume ≥ 2× and delivery ≥ 50 % | 52-week-low breakdown | `dt_52w_breakout` + `dt_delivery_volume` |
| S | 30 | **10× volume in the first 5 minutes** with price ≥ 2 % over the open (intraday) | 10× volume, price ≤ −2 % | `dt_vol_10x_5min`, `early_movers` (3 Nov study: ≥ 5× usual-by-now and ≥ 2 % over open) |
| S | 30 | **Setup A — institutional accumulation breakout**: above EMA20 and EMA50, 20-day breakout, volume > 1.5×, RSI 55–75, RS vs Nifty positive, sector index bullish | distribution breakdown | new (combination) |
| **1 — high value** | 22 | Resistance breakout with volume 1.5–2× | support breakdown with volume | `dt_vol_price_breakout`, desk `BREAKOUT` |
| 1 | 22 | Breakout + successful retest (broke within 3–15 sessions, low back within 1.5 % of the level, closes up) | breakdown + failed retest | new |
| 1 | 22 | Higher highs + higher lows (two of each on 5-bar swing points) | lower highs + lower lows | new |
| 1 | 22 | Bullish RSI divergence, confirmed by a close above EMA20 | bearish divergence, close below EMA20 | new |
| 1 | 22 | EMA20 crosses above EMA50, price above both | EMA20 below EMA50 | new |
| 1 | 22 | Setups B (pullback continuation), C (momentum reversal), D (volatility expansion), E (failed breakdown) | mirrors | new (combinations) |
| **2 — confirmation** | 12 | VWAP reclaim · volume expansion ≥ 2× without a breakout · MACD bullish crossover · cup and handle · inverse head and shoulders · bullish engulfing at support · Bollinger squeeze breakout · Supertrend flip · anchored-VWAP reclaim · relative-strength breakout (stock ÷ Nifty at a 52-week high) | mirrors | `cup_handle`, `triple_bottom`, `tight_consolidation`, `supertrend_rsi`; others new |
| **3 — context only** | 5 | Futures build-up label alone (long build-up, short covering) · trend continuation without a trigger | short build-up, long unwinding | desk v1 categories, `long_buildup` |

## 3. Price-volume points — how strongly it fired (max 25)

| Measure | Points |
|---|---|
| Relative volume (daily: vs 20-session average; intraday: vs the stock's usual volume by that time of day) | 1.5–2× **3** · 2–3× **6** · 3–5× **9** · 5–10× **12** · ≥ 10× **15** |
| Close location in the day's range (intraday: price now) | top 20 % **4** · 20–40 % **2** · lower half **0** (mirror for bearish) |
| Range expansion: day's range ≥ 1.5 × ATR14 | **3** |
| Delivery ≥ 60 % on volume ≥ 1.5× (end of day only) | **3** |
| F&O: price and open interest both up ≥ 5 % (supporting, not proof of institutional buying) | **2** |

## 4. Confluence (max 10)

+3 for each additional signal from a **different family** — structure (HH-HL, retest), breakout (levels), momentum (RSI, MACD,
divergence), volume (expansion, delivery), volatility (squeeze, ATR expansion), reversal (failed breakdown, divergence),
intraday (VWAP, opening range). Two signals from one family count once.

## 5. Context (max 25)

| Measure | Points |
|---|---|
| Market structure: above a rising EMA50 | 7 |
| Moving-average alignment: price > EMA20 > EMA50 > EMA200 | 6 |
| Momentum: RSI14 55–75 (above 80 scores 0) | 4 |
| Relative strength: 20-session return above the Nifty's | 4 |
| Sector index above its EMA20 and improving against the Nifty | 4 |

## 6. Quality and size (max 10)

The Scan dashboard's quality (30) and size (15) scaled to 10: earnings quality, debt, holdings, index membership (Nifty 50
highest). Keeps the owner's 4 Nov rule: blue chips weigh more, pump-and-dump traits weigh less.

## 7. Penalties

| Condition | Effect |
|---|---|
| Open gaps more than 1 % against the signal | −15 (and the plan is cancelled) |
| Bullish while the Nifty is below its 50-day average (bearish: above) | −10 |
| Chasing: close more than 3 × ATR above EMA20, or more than 25 % above the 50-day average | −8 |
| Pump-and-dump traits (existing Scan dashboard rules: tiny market cap, price band locks, exchange volume queries, unexplained spikes, losses, pledge) | as today |
| Negative filing or results reaction against the signal | −10 |
| 20-session average traded value below ₹5 crore | not scored |

## 8. Calibration — before any point is trusted

The points above are a starting hierarchy, not measured probabilities. Each is tested before it is used for proposals:

- Universe: Nifty Total Market (754 stocks; today's members, so a survivorship caveat) plus the F&O list; adjusted daily data
  1 Apr 2024 – 5 Nov 2026 (DaaS); intraday signals from Kite minute candles (about 6 months).
- Each signal alone and in setups A–E: forward 1, 3, 5, 10, 20-session returns from the next open, against the Nifty, maximum
  adverse and favourable excursion, win rate, expectancy after costs (shares ≈ 0.15 % round trip), by market regime.
- Fit points on Apr 2024 – Sep 2025; judge them only on Oct 2025 – Nov 2026. A tier whose signals do not beat the market out of
  sample is moved down; a measure that does not add is dropped.
- Then the desk compares v1 and v2 on the same sessions in the Simulation studio (Run history).

Evidence already in (desk v1 replay, 5 Nov; `test_reports/autodesk_staging_walkthrough_20261105.md`): over 5 sessions, steady
trend and a rising Nifty helped; generic 20-day highs, raw volume spikes and short-term outperformance did not. The hierarchy
therefore separates *major* levels (multi-year, 52-week) and *confirmed* volume (≥ 2× with delivery) from generic ones — the
calibration must show that the separation holds.

## 9. Open decisions (owner)

1. What the engine should mainly find: all strong bullish and bearish signals · early breakouts · reversals · accumulation and
   distribution.
2. Target move: 5–10 % positional · 2–5 % swing · large intraday · all horizons (assumed for now: all, scored per horizon).

## 10. Calibration results — daily signals (5 Nov 2026)

Data: DaaS adjusted daily bars, Nifty Total Market (739 stocks with enough history), 16 Apr 2024 – 4 Nov 2026; 163,656 signal
events (fit Apr 2024 – Sep 2025: 85,173; test Oct 2025 – Nov 2026: 78,483). Entry at the next open; excess return vs the Nifty
over the same window; t-statistic over per-day averages (signals on one day count once); costs 0.25 % round trip.

**Excess return vs the Nifty, 20 sessions (fit → test).** Bold = positive in both periods and significant (|t| ≥ 2) in at least one.

| Signal (tier in §2) | Fit | Test | Read |
|---|---|---|---|
| **Relative-strength breakout** (2) | +0.61 (t 2.1) | +1.22 (t 3.7) | strongest and most consistent bullish signal |
| **Higher highs + higher lows** (1) | +0.42 (t 1.5) | +0.78 (t 3.5) | consistent |
| **MACD bullish cross** (2) | +0.41 (t 1.4) | +0.86 (t 2.0) | consistent |
| **Setup B pullback continuation** (1) | +0.10 | +1.08 (t 2.4) | consistent sign |
| **Trend only, above EMA20 > EMA50** (3) | +0.35 | +1.10 (t 2.7) | consistent sign |
| Breakout + retest (1) | +0.51 | +0.94 | positive both, not significant |
| 52-week breakout, ≥ 2× volume, delivery ≥ 50 % (S) | +2.00 (n 51) | +0.88 (n 114) | positive both, small samples |
| 20-day breakout + volume 1.5× (1) | +0.32 | +0.81 | positive at 20 sessions, negative at 5 |
| Multi-year breakout ≥ 2× (S) | — (no 2-year history yet) | +0.78 (t 0.0) | unproven: one period, few days |
| Setup A accumulation breakout (S) | −0.05 | +0.21 | **not** a top signal on this data |
| RSI divergence, setups C and E, Supertrend flip, engulfing at support, Bollinger squeeze | mixed or negative in one period | | no reliable edge |
| Every bearish signal (breakdowns, LH-LL, bearish crosses, divergences) | negative | negative | shorting them lost against the Nifty |

- **Horizon matters:** at 5 sessions no daily signal beats the Nifty after costs (all within ±0.6 %, win rates 40–48 %); edges
  appear at 10–20 sessions and only for trend / relative-strength signals.
- **Price-volume strength on the signal day did not add consistently** (bullish breakouts, 10 sessions): relative volume ≥ 10×
  +0.46 → −0.33; closing in the top 20 % of the range +0.01 → +0.44 (no better than average); day's range vs ATR no pattern;
  delivery 50–60 % slightly positive in both (+0.27 → +0.60).
- **Context:** above a rising EMA50 (+0.23 and +0.56 better than below) and EMA20 > 50 > 200 alignment help in both periods;
  RSI 75–80 at the signal was the best band in both (+0.51, +1.28) — the 55–75 band is not better; "chasing" (> 3 ATR above
  EMA20) did *better*, not worse, at 10 sessions; sector index bullish made no difference; the Nifty-above-50-day rule flipped
  sign between periods.
- Multi-year breakdowns were followed by a strong rebound (−6.5 % short excess at 20 sessions), but 41 of 132 events are the
  March 2026 sell-off: one episode, not a rule.

**Proposed revision (needs the owner's OK; intraday results to follow):**
1. Promote the relative-strength breakout to Tier S; keep HH-HL, setup B, breakout + retest in Tier 1; add MACD bullish cross and
   trend alignment to Tier 1.
2. Move setup A, multi-year breakout (until more history), the 20-day breakout with volume and the EMA cross to Tier 2; RSI
   divergence, setups C and E, Supertrend, engulfing and the Bollinger squeeze to "context only".
3. No bearish tier for opening shorts; bearish signals become exit and risk warnings.
4. Price-volume points shrink from 25 to 10 (delivery 50–60 %, RSI 75–80, 20-session return vs Nifty > 10 %); relative-volume and
   close-location points are dropped for daily signals; drop the chasing penalty for positional plans (keep it for 2–5-day trades).
5. Score per horizon: positional (10–20 sessions) uses the table above; 2–5-day swing has no qualifying daily signal — it waits
   for the intraday study (10× first-5-minute volume, opening-range breakout, VWAP reclaim).

Caveats: 2.6 years only, one market history; today's index members (survivorship); edges are vs the Nifty — absolute returns were
negative in the test period's falling stretches; costs assumed 0.25 %.

## 11. v2-positional — as built (versioned, shadow only)

Owner, 5 Nov 2026 (pasted decision): build the revised hierarchy as a versioned, configurable framework; keep v1 for comparison
and rollback; bearish signals feed risk and exits only; signal-level attribution; intraday off until its study ends; walk-forward
validation before promotion; scoring is horizon-aware.

**Versions** (`backend/autodesk/scoring/registry.py`, `GET /api/v1/scoring/versions`):

| Version | Horizon | Status | Selects signals |
|---|---|---|---|
| v1 (ait-rules-v1) | positional | ACTIVE | yes — unchanged |
| v2-positional | positional, 10–20 sessions | SHADOW: score stored on each signal (`shadow_scores`) and in the scan report (`shadow`: candidates, bands, errors) | no |
| v3-intraday | intraday | DISABLED until the intraday study ends | no |

`AUTODESK_SCORING_SHADOW` ("" = off) switches shadow scoring; nothing switches the active version — promotion is a code change
after the validation report. v1 reads exactly the 60 bars it always read (sliced from the longer read v2 needs,
`AUTODESK_V2_BARS`, default 500); tests prove v1 scores, breakdowns and selection order are identical with shadow on and off.

**v2 score** (`backend/autodesk/scoring/v2_positional.py`) = signal quality 45 + trend confirmation 30 + relative strength 15 +
supporting evidence 10 − 10 per scan when a bearish warning is present; clamped 0–100; bands 85 / 75 / 65 / 50.

| Entry signal | Tier | Quality points | Family |
|---|---|---|---|
| Relative-strength breakout (stock ÷ Nifty above its prior 250-session high) | Tier 1 — highest priority | 45 | relative strength |
| Setup B pullback continuation | Tier 1 | 40 | pullback |
| Higher highs + higher lows, turned up within 5 sessions | Tier 1 | 38 | trend |
| MACD bullish cross | Tier 1 | 36 | trend |
| Breakout + retest | Tier 1* provisional | 32 | breakout |
| Setup A accumulation breakout (with the sector index) | Tier 2 — reduced | 24 | breakout |
| Multi-year breakout (> prior 480-session high, ≥ 2× volume) | Tier 2 — experimental | 22 | breakout |
| Plain volume breakout (20-session high, ≥ 1.5×) | Tier 2 — reduced | 20 | breakout |

- Quality = the primary (highest) entry signal + 3 per further entry signal from a **different family**, max 45 — correlated
  signals (HH-HL, MACD, trend) count once.
- Trend confirmation: above a rising EMA50 12 · price > EMA20 > EMA50 8 · EMA50 > EMA200 4 · HH-HL structure 6 (not when HH-HL
  is the primary signal).
- Relative strength: 20-session return vs the Nifty ≥ 10 % 15 · 5–10 % 11 · 0–5 % 7 · below 0 nothing; half when the
  relative-strength breakout is the primary signal (same evidence).
- Supporting evidence: RSI14 75–80 4 · 65–75 3 · 55–65 or > 80 2 · delivery ≥ 50 % 3 · volume ≥ 1.5× 1 (10× earns the same) ·
  context signals present 2.
- Context only (no quality points): RSI divergence, setups C and E, Supertrend flip, engulfing at support, Bollinger squeeze.
- Bearish warnings (never entries): breakdown on volume, lower highs + lower lows, EMA20/50 bearish cross, bearish RSI
  divergence, failed breakout, MACD bearish cross, Supertrend flip down, 52-week breakdown on 2× volume.
- No chasing penalty. Not scored: fewer than 60 sessions, or 20-session average traded value below ₹5 crore.
- Every point is a component with its weight and reason; the same code scores the live scan (last bar) and history (every bar).

## 12. Shadow check of the shipped v2 on history (AD-SC-15, 5 Nov 2026)

The shipped `v2_positional` scored every bar of 739 stocks (383,674 stock-days). 20-session excess vs the Nifty, entry next open:

| | Fit (Apr 2024 – Sep 2025) | Test (Oct 2025 – Nov 2026) |
|---|---|---|
| Universe baseline (all scored stock-days) | +0.07 | +0.91 |
| Exceptional / Strong / Developing / Weak / Avoid | +0.43 / +0.12 / −0.03 / +0.07 / +0.31 | +1.25 / +1.70 / +1.00 / +1.10 / +0.15 |
| Primary: RS breakout · setup B · HH-HL · setup A | +0.34 · −0.16 · +0.23 · +0.02 | +1.58 · +1.19 · +0.74 · +0.04 |
| Rank IC of the v2 score among candidates | −0.004 (t −0.6) | +0.055 (t 7.0) |

v2 ranks candidates in the test period and not in the fit period; the tier choices saw both periods. The relative-strength
breakout is the most consistent signal; setup A and the bearish-warning penalty add nothing (candidates for v2.1). Judge bands
against the universe baseline (which beats the Nifty in the test period: equal weighting, survivorship). **v2 stays in shadow
until live shadow scores confirm it.**

## 13. Intraday signals — study results (5 Nov 2026; v3-intraday stays DISABLED)

Data: Kite minute candles, 1 Apr – 5 Nov 2026, 743 stocks of the Nifty Total Market, 110,414 stock-days (149 sessions); split
Apr–Jul / Aug–Nov. Entry at the signal's own time (first-5-minute signals at the 09:20 price; opening-range breakout and VWAP
reclaim at their minute). Returns against the same day's average stock (market control); costs 0.06 % intraday, 0.25 % multi-day.
"10×" = first-5-minute volume against the stock's own first-5-minute volume over the previous 20 sessions.

| Signal (from its entry time) | Same day, Apr–Jul / Aug–Nov | Next day | 5 sessions |
|---|---|---|---|
| ≥ 10× first-5-minute volume, first 5 minutes up | −0.17 / −0.53 (t −2.8) | −0.01 / −0.36 | −1.13 / −0.13 |
| ≥ 10×, first 5 minutes down | −0.22 / −0.22 | −0.76 (t −2.3) / −0.44 | −0.92 / −0.82 |
| 5–10×, first 5 minutes down | −0.25 / −0.07 | −0.79 (t −3.0) / −0.46 (t −2.4) | −0.91 / −1.30 (t −2.6) |
| < 2×, first 5 minutes up (quiet open, rising) | −0.02 / +0.00 | +0.09 / +0.08 | +0.12 / +0.11 |
| Opening-range breakout up (15-min range) | about −0.05 to −0.10 in every band | | |
| VWAP reclaim after ≥ 30 min below (after 10:00) | about −0.05 to +0.05 | | |
| ≥ 10× and up, when the previous day's v2 band was Strong | −0.22 / — | −0.45 / — | −3.39 (t −4.7, n 52) / — |

- **No intraday entry signal tested beats the average stock after costs in either period.** By the time a 10× opening shows,
  the move is in the price; entering at 09:20 lagged the average stock.
- **10× opening volume with a falling first 5 minutes is a useful warning** (next day −0.4 to −0.8, 5 sessions −0.8 to −1.3): it
  belongs with the bearish warnings (risk / exits), not with entries.
- Short horizons revert: stocks the positional v2 rates Strong / Exceptional lag the next day (−0.3) — the positional and
  intraday problems are different, as the owner's plan said.
- The Scan dashboard's live "early movers" rule (≥ 5× usual-by-now and ≥ 2 % over the open, 3 Nov study) measured the rise *from
  the open*, which includes the move before the signal; it was not re-tested here from its detection time — next study.
- Caveats: 7 months; one entry time per signal; shares only (no option leverage); today's index members.

**Decision recorded:** v3-intraday stays DISABLED. Next: re-test the early-movers rule from its detection time (needs 15-minute
volume and price paths), and add "≥ 5× opening volume with a falling first 5 minutes" as a v2 risk warning in v2.1.
