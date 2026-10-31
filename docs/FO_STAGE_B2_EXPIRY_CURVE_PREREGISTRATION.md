# F&O Stage B2: expiry-curve study, pre-registration (written before any B2 data was exported or analysed)

Date: 2026-10-23 · Decision of record: the user's (expiry-specific signals; separate hypotheses; no pooling of expiries as independent opportunities; frozen selection rule; roll-window analysis).
Committed BEFORE the code runs. A change after a result is seen is a new experiment; this file stays as it is. Companion to `docs/FO_STAGE_B_PREREGISTRATION.md` (B1, near-month on Kite history), which is unchanged and still to be run.

## 0. Why B2 is a separate track, and what the data allows (verified 2026-10-23)
- Warehouse `nidp.fno_bhavcopy`: stock futures carry all three expiries on 98.7% of underlying-days (53,666 of 54,394), with each contract's own close, previous close, OI, change in OI and volume: 260 sessions, 1 Oct 2025 to 22 Oct 2026. This is the only source of next- and far-month history.
- Kite: only active contracts. INFY's current contracts hold 60 (near), 40 (next) and 16 (far) daily rows; the continuous series is near-month only. So next/far hypotheses cannot be tested on 2021-2025; they can be tested on this one year and, from now on, on the live series.
- Therefore the near-month hypothesis (A) gets two looks: B1 (four years, Kite) and B2 (one year, bhavcopy); B and C get B2 only. One year is thin and the verdict rules below say so.

## 1. Frozen inputs
- Thresholds: the baseline experiment `fo-bt-95f4e5df42dc` (hash `c5b125ba612073e0ce4e2c69b18c49c483c9bc813abcd7341a48a490ed287ea1`): per category its 5 frozen settings plus `no_threshold` and `production_floors`. Read from its report and checked against the hash. Nothing is added, dropped or changed. Weights stay `research_setting_not_validated`.
- A setting fires on an expiry's own values: |price change| >= p, |OI change| >= o, relative volume >= r (r null: none).

## 2. Per-expiry signals (pairing rules)
For each underlying and date, each of the first three available expiries is one bucket: **near** (first), **next** (second), **far** (third). For a bucket, the signal uses that same contract's own numbers only:
- price change = close / previous close - 1 (the contract's, from the bhavcopy);
- OI change = change in OI / (OI - change in OI) (the contract's; **no summing across expiries, no cross-expiry OI comparison, no cash price with futures OI**);
- relative volume = the contract's volume / mean of the previous 20 sessions' volume of the same bucket (null for the first 20 sessions; a setting with a volume floor cannot fire then).
- Category by signs: price up and OI up long build-up; down and up short build-up; up and down short covering; down and down long unwinding. Zero is neutral.
Per bucket also stored: expiry date, calendar days and weekdays to expiry (weekdays stand in for sessions), contract age in sessions since first seen in the data (censored at 1 Oct 2025), roll-window flag (weekdays to expiry 3 or fewer), expiry-day flag, post-expiry flag (the bucket's contract changed since the previous session), and whether it is the highest-OI contract that day (the liquid contract).

## 3. Configurations (one signal per underlying, session, setting and category: the shared outcome is never counted per expiry)
1. near_only, 2. next_only, 3. far_only: the bucket's own category and thresholds.
4. near_next_agree: near and next both fire the same category.
5. all_agree: near, next and far all fire the same category.
6. disagree_follow_near and 7. disagree_follow_next: near fires a category and next fires one of the opposite direction; traded in near's direction and in next's direction respectively (reported as two separate configurations, category = the driving bucket's).
Same entry, horizons, costs and windows for all.

## 4. Outcome (shared by the expiry signals)
Underlying's split/bonus-adjusted cash price: enter at the next session's open, exit at the close of D+h, h = 1, 3, 5, 10, 20 (**5 primary**); direction-adjusted. **Benchmark-relative** = direction x (stock return - benchmark return, same window): primary benchmark the equal-weighted average of all F&O underlyings' returns in that window; second, the same-sector equal-weighted average excluding the stock when at least 3 peers (current sector, static). Cost assumed 0.15% round trip (stress 0.30%, also standing in for the hedge leg).

## 5. Windows and the selection rule (fixed now; signal sessions, forward window inside the window)
- **U** 2025-10-01 to 2025-12-26 (never used to choose the thresholds: the features table did not exist then).
- **D** 2025-12-29 to 2026-06-25 (the baseline's discovery period). **V** 2026-06-29 to 2026-08-21. **T** 2026-08-24 to 2026-10-21 (the last window may run to the end of the data).
- **Expiry-selection rule**, learned on D only and then frozen: for each category, among near / next / far, choose the bucket with the highest D mean net benchmark-relative return at 5 sessions averaged over that category's 5 frozen settings, provided it has at least 100 signals in D; otherwise near. It is then evaluated, unchanged, on U, V and T.
- Acceptance uses **U, V and T only** (D is where the rule was learned).

## 6. Dependence
One observation per underlying-session per setting. The session is the unit: the per-session mean of benchmark-relative returns, with Newey-West standard errors (lag h-1) over sessions. No pooling of the three expiries as independent observations. Pairwise comparisons between configurations are descriptive (common sessions are not enforced).

## 7. Baselines and chance
Price-only (same price and volume floors on the near contract, no OI requirement, direction by the sign of the price change); `no_threshold`; permuted (OI changes shuffled across underlyings within each session on the near bucket, 200 permutations, seed 20261023; for the first frozen setting of each category and for `production_floors`; pooled U+V+T; one-sided p-value).

## 8. Roll and timing analysis (definitions fixed now)
For near_only with `production_floors`, pooled U+V+T: results by (a) outside the roll window (more than 3 weekdays to expiry), (b) roll window (1 to 3), (c) expiry day, (d) the first session after expiry; and by weekdays to expiry: 0-3, 4-10, 11-20, over 20. These are reported separately and are never used to select a setting.

## 9. Verdicts (fixed now)
Per configuration and category (primary horizon and benchmark, net of the base cost, pooled U+V+T): **supported** if the pooled mean is positive for at least 3 of the 5 frozen settings, the Newey-West t is at least 1.645 for at least 2 of them, the permutation p-value of the first setting is at most 0.05 (near_only only), and there are at least 30 signal sessions pooled; **not_supported** if fewer than 1 of 5 settings has a positive pooled mean; otherwise **inconclusive** (also when there are fewer than 30 pooled signal sessions).
- Hypothesis A: near_only supported in a category.
- Hypothesis B: next_only or far_only supported AND its pooled mean exceeds near_only's in that category.
- Hypothesis C: near_next_agree or all_agree supported AND its pooled mean exceeds near_only's. Disagreement configurations are reported, with no hypothesis attached.
- Nothing is validated by B2; `supported` still needs live shadow validation and, for A, B1's long-history result.

## 10. Declared limits
One year; U is 59 sessions; far-month contracts are thinly traded (little OI and volume), so far-only is expected to be noisy; cash returns proxy a futures trade; the cost is assumed; the sector map is the current one; the first 20 sessions have no volume ratio; clustering by underlying is not modelled; the three windows U, V, T are one regime sequence.
