# Paper Trade Simulation Engine v1 — pre-registration (rules_id paper-v1)

Written 2026-09-18 13:37:48 IST, before any paper-trade outcome was computed (forward or replay). The machine-readable rules are
`rules_v1.json` beside this file; its git commit time is the registration time stored in
`nidp.tpd_paper_rule_sets.registered_at`. Nothing below may be tuned after results are seen; a change is a new rules_id.

## What is tested
Whether v4's nightly EOD ranking picks stocks that do better than comparable stocks when bought at the next session's
official open — first as a prediction (does the probability rank the outcomes?), then economically (net of costs, versus
benchmarks A–D). The first milestone is not profitability.

## Portfolios
- **P5-NEXT**: top 5 eligible by P(+5% next session) (v4 head p_up5_1d).
- **P10-NEXT**: top 5 eligible by P(+10% next session) (v4 head p_up10_1d).
- P5-SWING / P10-SWING are not run: v4 has no 5-session head.

## Samples
- **Forward**: v4 snapshots frozen by run_v4.sh. A session counts only if its snapshot was generated after this rule set's
  registration commit. The sessions entered 2026-09-17 and 2026-09-18 are recorded but never counted: their predictions
  were frozen before registration, and Claude saw two 17 Sep OHLC rows (PNCINFRA, ALOKINDS) during a data check first.
  First counted entry: the session after the 2026-09-18 prediction (Mon 2026-09-21), if run_v4.sh freezes it tonight.
- **Historical replay**: the v4 early-window walk-forward (Jan–Aug 2025), labelled replay, never pooled with forward.
  Caveat: that window was already used for v4 decisions, so replay is descriptive, not a clean test.

## Rules (summary — the JSON is authoritative)
- Eligibility at EOD: scored; valid OHLC; fresh bar; close ≥ ₹5; 20-session median turnover ≥ ₹1 crore; no unexplained
  corporate action in 20 sessions; ATR14 defined. Excluded rows are stored with the failing filter.
- Rank by the head's probability (ties: symbol). Top 5 selected; the full ranked universe is stored.
- Entry: official open of the next session. Upper circuit at open → ENTRY_UNAVAILABLE. Lower circuit at open → entered,
  flagged. Gap ≥ 5% → entered, flagged. Missing open → ENTRY_UNAVAILABLE. No bar → SUSPENDED.
- ₹1,00,000 per portfolio, 20% per position, fractional quantity, no leverage/shorting/compounding.
- Costs 0.25% round trip (sensitivity 0.50%, 1.00%), recorded separately from gross.
- Sessions: s1 = entry day, s2–s6 = the five sessions after. Modes: EOD-1 (s1 close, **headline**), EOD-3 (s3 close),
  EOD-5 (s5 close), FIXED (s6 close), TARGET_STOP (first barrier in s1–s6, else s6 close).
- Target/stop (secondary experiment): target +5% / +10% from entry; stop = the lower of entry − k·ATR14 (k = 1.5 for
  P5, 2.0 for P10) and the prior 10-session low (if below entry), never more than 8% below entry. A session touching
  both counts the stop. Gaps through a level exit at the open.
- Benchmarks (defined now): A = all eligible entered stocks (and a seeded random five); B = seeded matched five (sector,
  size group, ATR%, price, turnover); C = top five by movement probability (up + down) without direction; D = Nifty 50.
- Statistics: 95% CIs on session-cohort means (EOD-1 session-clustered; multi-session modes Newey-West, lag h−1).
  An edge is called established only with ≥ 60 counted sessions and a CI excluding zero.
