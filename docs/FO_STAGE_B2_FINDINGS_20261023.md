# F&O Stage B2 findings: expiry-curve study (experiment `fo-b2-c4295fca6fbf`, 2026-10-23)

Pre-registered in `FO_STAGE_B2_EXPIRY_CURVE_PREREGISTRATION.md` + the amendment (incl. the transition addendum), all committed before the run. Code `025ae7fb`. Report: `test_reports/fno_expiry_study_fo-b2-c4295fca6fbf.json`. Data: warehouse `fno_bhavcopy` STF, 260 sessions, 231 underlyings; adjusted cash prices; frozen baseline hash `c5b125ba...`. 1,224 configurations counted. **Nothing is validated.** Results are net of an assumed 0.15% round trip and relative to the equal-weight F&O universe, primary horizon 5 sessions, pooled over U+V+T (D excluded: it is where the expiry rule was learned).

## 1. Hypotheses A, B, C
**None is supported.** No category/configuration met the rule (3 of 5 frozen settings positive with at least 30 pooled sessions, 2 with t >= 1.645, and, for near-month, permutation p <= 0.05 on the first setting).
- **A (near-month)**: long build-up `not_supported` (all 5 frozen settings negative, pooled -0.67%); short covering `not_supported`; long unwinding `inconclusive` (-0.22%); **short build-up `inconclusive`**: all 5 settings positive (+1.4 to +2.0%), 4 of 5 with t >= 1.645, but the permutation p of the first setting is **0.060** (just above the 0.05 gate) and the production floors give p = 0.020 at a smaller +0.37%.
- **B (next/far)**: next-month `not_supported` for three categories, `inconclusive` for short build-up (3 of 5 positive, none strong); far-month `inconclusive` for long build-up and short covering (all five positive but tiny, +0.12 to +0.19%, no t above the bar). Neither beats near-month where near-month is positive.
- **C (agreement)**: the agree configurations have too few signals (most have no setting with 30 pooled sessions) and are `not_supported` or `inconclusive`. Disagreement has almost no signals. Weak descriptive pattern: for short build-up under the production floors, agreement in 3 of 3 expiries +0.51% (t 1.98) vs 2 of 3 +0.41% vs 1 of 3 -1.19% (42 signals); not a verdict.

## 2. Expiry selection (learned on D, frozen)
The rule chose **near** for all four categories (next/far had either worse D means or too few D signals where better). So the frozen selection is near-month; nothing is gained from deferred expiries in this year.

## 3. Short build-up: the one candidate, with its caveats
Near-month short build-up with the frozen discovery settings is positive in U (+3.6%), D (+1.2%), T (+3.1%) and flat in V (-0.1%); the same under industry-relative returns (+1.96%, t 1.91), under the stress cost (+1.89%), and at 10 sessions (+3.0%). Against that: pooled sessions are 50 (thin), the first-setting permutation p is 0.06, the production floors give only +0.37% (t 1.86), the price-only baseline with the same floors is +0.14% (t 0.5, not significant), and long build-up shows the mirror image (-0.7%, negative in U and T), so part of this may be a shared reversal/continuation regime effect rather than OI information. It deserves live shadow tracking; it does **not** justify promoting the ranking or floors.

## 4. Roll and expiry timing (descriptive)
Under the production floors almost no build-up signals occur in the roll window (3 or fewer weekdays to expiry): long build-up 0, short build-up 1; near-contract OI collapses into expiry so the OI condition rarely holds. Short covering and long unwinding fire heavily in the roll window (772 and 1,283 signals) and are negative (-0.56% t -4.4; -0.22% t -3.9 over only 14 sessions). Far from expiry (11-20 weekdays) nothing is significant. Roll-window signals are largely rollover mechanics, which supports excluding them from any future live scanner claim.

## 5. Transitions (addendum)
24 transition tests (4 x 3 expiries x 2 settings counted; production floors shown): **none adds information** under the pre-registered rule. The nominal standout, near-month short covering -> long build-up, +2.21% (t 2.46), has only 17 pooled sessions and 36 signals, below the 30-session minimum; with 24 tests one such result is expected by chance. Long build-up -> long unwinding, short build-up -> short covering and long unwinding -> short build-up are not better than the static state. Persistence of the same state (two sessions) is not better than the single-session state either. Three consecutive sessions of short build-up near-month: +1.71% (18 sessions, t 1.18), too thin. Intraday transitions are untested (no historical intraday OI).

## 6. Conclusions and what changes
- The expiry decomposition does not rescue the ranking: near-month remains the only expiry with any signal, and only on the short build-up side.
- Keep candidates descriptive, with the research-status label. Do not rank "best trades".
- Use the short build-up result as the single pre-specified hypothesis for live shadow tracking (`kite_live_intraday` and the saved closes), evaluated going forward, never reconstructed.
- B3 (Greeks, strategy outcomes) should be run on near-month short build-up and long build-up only, as the hypothesis worth testing for incremental value; B1 (2021-2025 Kite near-month) is now the more valuable next test because it can settle whether the short build-up result survives a different regime. Next/far-month and agreement tests would need more history than exists.

## 7. Limits
One year, three windows that are one regime sequence (the market fell and rose within it, and short-side results here follow that tendency); cash returns proxy futures trades; cost assumed; weekdays ignore holidays; the industry benchmark is coarse (current NSE industry); thin counts in every cross-expiry cell; no clustering by underlying; 24 transition and 196 configuration tests mean a few nominal winners are expected by chance.
