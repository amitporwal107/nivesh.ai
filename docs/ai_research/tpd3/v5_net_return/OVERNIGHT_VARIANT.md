# Overnight-entry variant — tested and REJECTED before pre-registration
2026-09-18. Owner asked to test entering at the previous close instead of the next open, and to derive the
entry-price formula from the data. Result: the apparent edge is a bid-ask artefact. No pre-registration was
written because the candidate did not survive basic sanity checks — there was nothing worth registering.

## What looked promising
Decomposing 177,534 stock-days (2026-06-01..09-16):
    overnight gap (close -> next open):   +0.3069%
    intraday      (open -> next close):   -0.2390%
    close-to-close:                       +0.0588%
    sessions where close > open:            40.5%
All of the period's return accrued while the market was shut. Entering at the previous close and exiting at
the next OPEN (overnight only) looked strongly positive, and filtering on "high ATR + high delivery" gave:
    mean net +0.6177% per trade, t = 18.33, 98.7% of 76 sessions positive, ~148 stocks/session
A t-statistic of 18 in daily equity data is not a discovery; it is a bug or an artefact. It was the latter.

## Why it is not real
1. CONCENTRATED IN UNTRADEABLE STOCKS. Split by turnover on the signal day:
       under Rs 10 lakh/day : +0.630% net, t = 18.43, 112 of 148 names
       Rs 10 lakh - 1 cr    : +0.658% net, t =  9.66
       Rs 1 - 10 cr         : +0.344% net, t =  1.62
       above Rs 10 cr       : +0.313% net, t =  0.56   <- not distinguishable from zero
   The edge exists only where a Rs 20,000 order would move the price. In genuinely liquid stocks it vanishes.
   Selected names were penny stocks: A2ZINFRA Rs 14.70, AAKASH Rs 8.82, AGROPHOS Rs 23.18. Under Rs 20 gave
   the largest "edge" (+0.706%, t = 16.25) — the signature of tick size, not of a risk premium.

2. THE GAP IS GIVEN BACK WITHIN HOURS. On the illiquid subset (n = 8,164), net of 0.25%:
       hold to next OPEN   : +0.624%
       hold to next CLOSE  : -0.272%   <- the entire gain is gone the same day
       hold 2 days         : -0.259%
       hold 3 days         : -0.221%
   A genuine overnight premium persists. A gain that appears at the open and evaporates by the close is the
   bid-ask bounce: these stocks close at the bid and open at the ask. The "return" is the spread. You cannot
   sell at the ask you just bought at, so it is not capturable — and 0.25% round-trip costs do not model the
   spread on a stock trading Rs 8 lakh a day, which is far wider.

3. INTRADAY REVERSAL CONFIRMS IT. Illiquid names: gap +0.887%, then intraday -0.853% the same session.
   Liquid names (n = 39): gap +0.545%, intraday +0.949% — no reversal, and no significance either.

## Conclusion
The overnight variant is rejected. The previous close is NOT a usable entry price: the printed close is a
bid-side print in exactly the stocks where the apparent edge lives, so the entry price is unobtainable.

The paper engine's existing rule — enter at the next session's official open — remains correct. It is the one
price in the data that a real order can actually get, which is precisely why it shows no free money.

## What survives
No entry-price formula tested (previous close, next open, gap-capped entry) produces a positive expectancy in
liquid stocks. Combined with the v5 net-return model result (top decile still -0.393%, primary FAIL), the
finding stands: these features predict movement, not profit, at daily frequency.
