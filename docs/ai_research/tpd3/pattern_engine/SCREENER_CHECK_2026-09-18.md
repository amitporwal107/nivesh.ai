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
