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
