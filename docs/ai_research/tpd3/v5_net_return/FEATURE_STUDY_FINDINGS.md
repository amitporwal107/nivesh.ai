# Net-return feature study — 2026-09-18

Sample: 177,534 stock-days, 76 sessions (2026-06-01 .. 2026-09-16), NSE EQ, features from nidp.stock_features_daily
known BEFORE the outcome. Base rate: 3.05% of stock-days are followed by a +5% close; 8.29% touch +5% intraday.

## 1. Movement is predictable. Direction is not. Profit is not.

Lift on "next day closes +5% or more" (base 3.05%):

| feature (top quintile)            | hit % | lift |
|-----------------------------------|-------|------|
| locked near upper band yesterday  | 20.93 | 6.86 |
| volatile + momentum + volume       | 13.42 | 4.40 |
| 1-year volatility > 56%            |  4.56 | 1.62 |
| 20-day return > +7.6%              |  5.73 | 1.88 |
| ATR% > 5.0                         |  5.66 | 1.86 |
| 3-month return > +20.2%            |  5.51 | 1.81 |
| distance to 200-DMA > +13.4%       |  5.26 | 1.78 |
| RSI-14 > 60.2                      |  4.97 | 1.63 |
| 1-year return > +17.7%             |  4.63 | 1.64 |
| delivery % < 44 (INVERTED)         |  4.28 | 1.41 |
| above 20/50/200-DMA all three      |  4.26 | 1.40 |
| PAT growth YoY > 46%               |  4.10 | 1.49 |
| revenue growth YoY > 31%           |  4.24 | 1.48 |
| market cap < Rs 2,672 cr           |  4.33 | 1.42 |
| P/E (any quintile)                 |  ~3.0 | 0.95-1.09 (NO SIGNAL) |

## 2. None of it survives costs — and the reason is structural

Entering at the next open and exiting at that close, minus 0.25% round trip, EVERY quintile of EVERY
feature tested is negative. Best quintile: -0.278% (PAT growth). Worst: -0.739% (high delivery).
Best spread between extreme quintiles: 0.28pp (fii_pct) — smaller than the cost itself.

Cause, measured over the same 177,534 stock-days:

    average overnight gap (prev close -> open):   +0.307%
    average intraday     (open -> close):         -0.239%
    average close-to-close:                       +0.059%
    sessions where close > open:                   40.5%

The market rose over the period, but ALL of the gain accrued overnight. Intraday is negative on
average and on 59.5% of stock-days. Any strategy that buys at the open and sells at the close is
fighting a -0.24% headwind before costs. This is why the circuit-lock signal (6.86x lift, the
strongest predictor found) still loses 0.89% net: those stocks gap +3.64% overnight, so the move
is gone before the open.

Holding overnight (close -> next close) is less bad but still negative after costs in every quintile
tested (best: -0.061%, PAT growth top quintile).

## 3. Consequence for the model

A model trained to predict +5% moves can succeed at its stated task and still lose money — v4 does
exactly this (2025 replay: picks touch +5% 3.7x more often than average, net -0.43%/trade, edge vs
every eligible stock -0.03% [-0.40, +0.33]).

The redefined model must therefore be trained and judged on NET RETURN AFTER COSTS, at prices
actually obtainable. On this evidence the honest prior is that no tradeable edge exists in these
features at daily frequency; the model's job is to test that, not to assume otherwise.
