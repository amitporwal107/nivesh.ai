# Pattern Discovery Engine — Phase 1: base rates (discovery period only)

**Computed:** 2026-09-19. **Data:** bhavcopy panel 2024-08-28..2026-09-17 — 767,241 stock-days, 2,382 symbols,
511 sessions. **This is the DISCOVERY period.** The 2021..mid-2024 Kite daily pull is reserved as the untouched
validation period and was NOT used here.

## Labels
| label | definition |
|---|---|
| P1d+5% / +10% | next session's HIGH ≥ +5% / +10% above next session's OPEN |
| P5d+5% / +10% | max HIGH over the 5 sessions from entry ≥ +5% / +10% above entry OPEN (window must span ≤ 9 calendar days) |
| net1d | next open → next close, minus 0.25% costs |
| net5d | next open → close of the 5th session, minus 0.25% |
Downside labels (−3/−5/−10% MAE) and path/direction labels need lows — not in this panel; they come next from
the Kite daily pull (discovery-period rows only).

## Headline
- **P1d+5% = 7.02%, P1d+10% = 1.14%, P5d+5% = 31.31%, P5d+10% = 10.65%.**
- **net1d = −0.445%, net5d = −0.480%** — the average trade from the open loses after costs, in every ATR,
  liquidity, breadth, year and sector bucket. Only gap-down buckets are net-positive on day 1.
- Touch rates are stable across years (6.74–7.45%), which makes them learnable; net improves 2024→2026 (−0.54→−0.40).

## ATR — where hits and false positives concentrate
| ATR | n | P1d+5% | P1d+10% | P5d+5% | P5d+10% | net1d | win1d | net5d |
|---|---|---|---|---|---|---|---|---|
| <2% | 67,632 | 0.60 | 0.10 | 7.74 | 1.12 | −0.436 | 27.1 | −0.578 |
| 2–3% | 187,576 | 2.62 | 0.35 | 20.04 | 4.35 | −0.455 | 35.1 | −0.706 |
| 3–5% | 375,588 | 7.21 | 1.06 | 34.92 | 11.51 | −0.435 | 38.1 | −0.429 |
| 5–8% | 127,823 | 15.21 | 2.82 | 48.59 | 21.58 | −0.447 | 39.8 | −0.209 |
| >8% | 8,611 | **23.78** | 5.56 | 54.51 | 27.53 | **−0.740** | 37.5 | **−0.966** |

A 40× rise in P1d+5% buys **no** improvement in net1d; the most volatile bucket has the highest hit rate AND the
worst outcome. **Any touch-only label will learn volatility.** This is the quantitative case for the direction and
net-outcome labels in the framework.

## Liquidity (20-day turnover; market-cap proxy — market cap is not in the panel)
| turnover | n | P1d+5% | P5d+10% | net1d | net5d |
|---|---|---|---|---|---|
| 1–5 cr | 218,833 | 8.24 | 12.25 | −0.511 | −0.529 |
| 5–25 cr | 253,483 | 7.62 | 11.65 | −0.452 | −0.488 |
| 25–100 cr | 166,141 | 6.73 | 10.17 | −0.406 | −0.442 |
| >100 cr | 128,783 | 4.16 | 6.71 | −0.371 | −0.434 |

## Opening gap (known only at 09:15 — an open-conditional base rate)
| gap | n | P1d+5% | P1d+10% | P5d+10% | net1d | win1d | net5d |
|---|---|---|---|---|---|---|---|
| < −3% | 8,736 | **36.14** | 8.85 | 34.47 | **+1.613** | 63.8 | +2.556 |
| −3..−1% | 48,712 | 12.86 | 1.80 | 16.74 | +0.254 | 54.3 | +0.605 |
| −1..+1% | 603,689 | 5.65 | 0.81 | 9.10 | −0.450 | 35.9 | −0.599 |
| +1..+3% | 91,913 | 8.84 | 1.81 | 13.64 | −0.862 | 30.9 | −0.676 |
| > +3% | 14,191 | 15.59 | 4.16 | 23.55 | **−1.207** | 32.3 | **+0.457** |

**Weighting warning.** The gap < −3% +1.613% is per stock-day. Per SESSION it is **+0.391%** (501 sessions) —
matching the earlier G1 close-only result. **Five sessions hold 36% of all gap-down rows**: the session after
2025-04-04 alone had 1,303 stocks gap ≤ −3% (mean net1d +4.96%), then 2026-02-27 (958, +2.32%),
2025-05-08 (422, +2.97%), 2025-06-12 (225, +2.79%), 2026-04-10 (211, +3.01%). Much of "gap recovery" is a
handful of **market-wide** gap-down-and-recover days, so its independent sample is far smaller than 8,736.
It must be tested with market-day clustering, and may be an index pattern rather than a stock pattern.

Gap-ups fade on the day (−1.207%) but are positive over 5 days (+0.457%) — a candidate continuation hypothesis,
not a finding.

## Market breadth (share of stocks above their 50-DMA, tertiles)
| regime | n | P1d+5% | P5d+5% | net1d | net5d |
|---|---|---|---|---|---|
| weak | 256,510 | 8.40 | 36.73 | −0.420 | −0.189 |
| mid | 255,883 | 6.28 | 27.25 | −0.443 | −0.882 |
| strong | 254,848 | 6.38 | 30.02 | −0.473 | −0.366 |
Non-monotonic in net5d — treat as noise until tested.

## Sector — coverage problem first
**Only 59.5% of stock-days have a real sector.** `nidp.sector_master` has 1,573 of 2,567 symbols as `UNKNOWN`,
and the gap is **not random**: UNKNOWN has the highest P1d+5% (9.93%) of any group — it is disproportionately the
small, volatile names. Sector-conditional results are unreliable until sector_master is filled.
Among classified sectors, P1d+5% ranges 2.27% (Construction Materials) to 8.08% (Capital Goods); net1d is negative
in all (−0.32 to −0.50).

## Data gaps found (block later phases)
1. **sector_master 61% UNKNOWN**, biased toward high-movers.
2. **No lows in the panel** → downside and direction labels need the Kite daily rows (discovery period).
3. **Market cap absent** → turnover used as a proxy.
4. **Event proximity not computed**: needs point-in-time publication timestamps (NIDP financials lack
   `broadcast_at`); fundamentals history may be overwritten with current values (memory, 2026-09-16) — must be
   re-verified before any fundamental feature is used.

## Next
Downside/direction labels from Kite daily (discovery rows), then Phase 2 univariate + interaction analysis with
market-day clustered errors. The pattern registry should be seeded with the hypotheses already tested and failed.
