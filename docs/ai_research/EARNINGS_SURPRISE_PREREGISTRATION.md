# Pre-registration: does the Earnings Surprise & Guidance Tracker ("Results week") explain post-results returns?

**Registered:** 2026-10-27 (IST), before any verdict, score or return was computed for any season. The git commit of this
file is the registration timestamp (log at the end). Nothing in it may change after results are seen; any later change is a
new, separately labelled analysis, and the results document lists every deviation.
**What is tested:** the scoring in `docs/EARNINGS_SURPRISE_TRACKER.md` §4 (P1). Owner decision (27 Oct, 17:50 IST): the
ranked list is shown now, labelled **not yet tested**; this test runs alongside, and weights change **only** by §9.
**Status of the code under test:** the P1 service (`feat/earnings-surprise-tracker`) has no scoring code yet. Where §4 of the
spec leaves a formula open, §4 below pins it. The study tests the formulas written here; the live implementation should
adopt them, or the difference is a deviation the results document must name.
**Wording:** "vs historical trend", "ordered for review". No consensus is held; nothing here is a recommendation.

## 1. Questions (from the spec §7)
- **H1** Results the tracker rates **above** its historical-trend baseline have a higher mean excess return vs the Nifty 50
  than results rated **below**, on the first reaction session (R1) and over 5 sessions (R5).
- **H2** The Earnings Intelligence Score (the §4b composite) has a positive Spearman rank IC with R5.
- **H3** The pre-results early-signal order (§4c "Upcoming") of F&O names has a positive Spearman rank IC with the
  post-results R5.
- **H4** (added here because the live list also orders *declared* names) The §4c "Declared" order of F&O names, computed at
  the close of the first reaction session, has a positive Spearman rank IC with the **following** 5-session excess return
  (D5, the drift a reader could still act on after seeing the list).

## 2. Data (staging warehouse, read-only; checked 2026-10-27)
| Need | Source | Coverage checked |
|---|---|---|
| Quarterly figures | `nidp.nse_financials_quarterly` (period_type quarterly) | period ends 2024-09-30 → 2026-09-30 (≈1,700–2,140 symbols per quarter). `broadcast_at` stamped from the Jun 2025 quarter on (95–99 %); null for Sep 2024–Mar 2025 |
| Results meetings | `nidp.event_calendar` (quarterly_results) | Jun 2024 → Nov 2026. `broadcast_at` (IST date) is within ±1 day of a meeting for 98–100 % of stamped filings |
| Prices | `nidp.prices_eod_adjusted` (split/bonus-adjusted), with `deliv_pct` from `nidp.prices_eod` | 2024-04-01 → 2026-10-26, 634 sessions, one row per symbol and date |
| Benchmark | `nidp.index_eod` "Nifty 50" | 634 sessions, none missing against the price calendar |
| Scanner sector term | NIFTYBEES raw close, `nidp.prices_eod` series EQ (as in `P4_ADX_RS_PREREGISTRATION.md` §2) | complete |
| Futures OI | `nidp.fno_bhavcopy` instrument_type STF | 2025-10-01 → 2026-10-26, 262 sessions |
| Filing analysis (outlook proxy) | Mongo `event_ai_analysis`, event_type RESULTS | 664 docs; 522 cover Jul–Aug 2026 filings, **all generated in Oct 2026** (model claude-sonnet-5-5, tools off and isolated); none before Jul 2026 |
| Technical score | the AI scanner's own functions replayed on prices (below) | `stock_technical_features` exists only for 2026-10-23/26, so it is not used |

No new external source is fetched. Exports go to `/home/deploy/earnings-study-data/` (not in git); the results document
records the per-table watermark (`max(ingested_at)` where the table has one), row counts and file hashes.

## 3. Seasons, samples and the baselines each can support (counts are data availability only, no scores)
A season is defined by the **target quarter**, not the calendar month.

| Season | Target quarter | Stamped filings | Full live method (needs t−1, t−2, t−4, t−5, t−6) | "Last year unchanged" (needs t−4) | F&O names | Role |
|---|---|---|---|---|---|---|
| Oct–Nov 2025 | 2025-09-30 | 1,829 | 0 | 1,645 | 183 | H3; secondary S1 |
| Jan–Feb 2026 | 2025-12-31 | 1,867 | 0 | 1,698 | 183 | H3; secondary S1 |
| Apr–May 2026 | 2026-03-31 | 1,892 | 1,654 | 1,755 | 187 | **H1, H2, H4 primary**; H3; S1 |
| Jul–Aug 2026 | 2026-06-30 | 2,090 | 1,708 | 1,894 | 203 | **H1, H2, H4 primary**; H3; S1 |
| Oct–Nov 2026 | 2026-09-30 | in progress | — | — | — | **untouched holdout** (§8) |

**Design choice, and why.** The quarterly history starts at Sep 2024, so the live method (7 published quarters) can be
replayed for exactly two seasons. H1, H2 and H4 test the **live method** on those two seasons (primary). Because two seasons
cannot give a cross-season t-statistic, a **secondary** test (S1) runs the same §4a pipeline with the simplest baseline
the data supports in every season, "same quarter last year unchanged" (the router's own benchmark, `naive_flat`), over all
four seasons. It is labelled secondary everywhere and no decision rests on it. H3 does not need a baseline (its inputs are
prices, OI, past reactions and reported quarters), so it runs on all four seasons. The Oct–Nov 2026 season is not touched.

Sample-size consequences, stated now: if ~50 % of PAT baselines are reliable (the spec's figure) about 850 results per
primary season are rated, of which the tails (above / below) hold roughly 80–130 each; with a 5-session excess-return
standard deviation near 8 %, a difference of about 2.5 percentage points is detectable at 80 % power, smaller ones are not.
H2: ~900 per season, minimum detectable IC ≈ 0.07. H3: ~180 F&O names per season over 4 seasons, minimum detectable IC
≈ 0.10. H4: ~150 per season over 2 seasons, ≈ 0.14. A non-significant result is "no measurable skill", **not** "no effect".

## 4. Scores (pinned; computed point-in-time)
### 4.1 Baseline and band (full live method)
- Expectation, reliability rules and band: the router's own pure functions in
  `backend/nidp/services/daas_api/routers/desk_expectation.py` (`build_store`, `forecast_metric`, `run_backtest`,
  `Calibration`, `answer`), imported, not re-written (code SHA recorded). `answer()` is called with the meeting's
  `event_calendar` row, `today = 2026-10-27`; the expectation cutoff is the target filing's own `broadcast_at`, exactly as
  the endpoint does for a declared meeting.
- **Band calibration (deviation from the live endpoint, chosen in advance):** the endpoint calibrates the band on the
  method's errors for *every* tested quarter, including the target's own and later ones. The study freezes the calibration
  on tested quarters ≤ 2026-06-30 (the two primary seasons). This is a look-ahead in the band's *scale* only (errors of other
  stocks in the same and the next season), never in returns. It keeps the holdout's band strictly point-in-time.
  Secondary S3 re-rates the Jul–Aug 2026 season with a band calibrated only on errors known before each filing.
- "Last year unchanged" (S1): expected = value(t−4); same reliability rules where they apply (value(t−4) > 0; for PAT,
  last year's PAT ≥ 0.5 % of its revenue); band = `Calibration` on that method's own errors (instability set to 0, so the
  cells are size quartiles), frozen on target quarters ≤ 2026-06-30.

### 4.2 Surprise verdict (§4a)
Per metric m ∈ {pat, revenue} with `reliable = true`: z = (filed − mid)/(high − mid) if filed ≥ mid, else
(filed − mid)/(mid − low); S_m = clamp(50 + 25·z, 0, 100). Surprise score = 0.6·S_pat + 0.4·S_revenue; S_pat alone when
revenue is not reliable or null; S_revenue alone when PAT is not reliable. **Headline verdict (pinned):** surprise score
> 75 **above**, < 25 **below**, otherwise **in line**; null when neither metric is reliable. (Secondary S2: the PAT metric
verdict alone, z > 1 / z < −1.)

### 4.3 Operating trend (§4b, 25)
For quarter Q on the basis the expectation used (else consolidated, else standalone), values as stored:
- growth items, each when both values are > 0: revenue, EBITDA and PAT, each YoY (Q vs Q−4) and QoQ (Q vs Q−1); item
  score = clamp(50 + 100·g, 0, 100), g a fraction;
- margin item: EBITDA margin(Q) − EBITDA margin(Q−4), in percentage points, when both revenues > 0 and both EBITDA present;
  score = clamp(50 + 10·Δ, 0, 100).
Trend = mean of the items present; null with fewer than 2 items. For a declared result Q is the target quarter; for an
upcoming one (H3) Q is the latest quarter known before the signal (§5).

### 4.4 Earnings quality (§4b, 15)
On the target quarter: F1 |exceptional items| > 20 % of PBT (PBT > 0); F2 other income > 30 % of PBT (PBT > 0); F3 tax ÷ PBT
< 10 % or > 40 % (PBT > 0); F4 PAT YoY > 0, PAT YoY > 2 × revenue YoY, and other income higher than a year earlier. A flag
whose inputs are missing is "not checked", never fired. Quality = 100 − 25 × flags fired; null when no flag could be
checked. Cash flow is not checked (empty on staging).

### 4.5 Outlook (§4b, 25)
Filing analysis `(net_impact_score + 100)/2`. It exists only for part of Jul–Aug 2026 and was generated in Oct 2026, so it
is **not point-in-time** and is excluded from H2. Exploratory E2 reports it separately (§7).

### 4.6 Earnings Intelligence Score (H2)
Weighted mean over the components present: surprise 35, trend 25, quality 15 (outlook excluded, see 4.5). Null when
surprise and trend are both null (spec §4b).

### 4.7 Technical score (§4c) — the AI scanner's own score, replayed
The scanner's base score B0 exactly as `P4_ADX_RS_PREREGISTRATION.md` §4 defines it (`feature_calculator.compute_features`
on the last 260 adjusted bars with delivery %, the scanner's `score_*` functions, `DEFAULT_WEIGHTS`, sector term = stock
20-session return − NIFTYBEES 20-session return, macro multiplier omitted), × 100. Needs ≥ 60 bars, else null.

### 4.8 OI build-up (§4c)
The DaaS `/desk/fno-buildup` rule (`desk_market.buildup_label`) on one session: price change of the nearest-expiry stock
future (close vs prev_close), OI change summed over all expiries (null if any expiry lacks it). long_buildup and
short_covering → 100; neutral → 50; short_buildup and long_unwinding → 0; no STF rows → null.

### 4.9 Past results reactions (§4c, upcoming)
The stock's earlier results meetings (`event_calendar`, one per calendar quarter: the earliest date in it) whose window ends
before the signal session; reaction = adj_close(t+5) ÷ adj_close(t−1) − 1, t the first session on or after the meeting
(the DaaS history's event_day and w1 combined, on adjusted prices). Mean of the latest 4 (≥ 2 needed, else null); score =
clamp(50 + 2.5 × mean %, 0, 100).

### 4.10 Early-signal orders (§4c)
- **Upcoming (H3):** technical 40 · OI 30 · past reactions 15 · operating trend 15, weights renormalised over the parts
  present; the technical part must be present. Computed at the close of session S−1 (§5).
- **Declared (H4):** earnings score (4.6) 40 · reaction 20 · OI 20 · technical 20, renormalised over parts present;
  computed at the close of session S. Reaction = clamp(50 + 5 × R1 %, 0, 100). The spec also names "volume ×" but gives no
  direction or mapping; it is **not scored** here (an open spec point the results document repeats).
- F&O list only: a name is F&O when it has STF rows in `fno_bhavcopy` on the signal session.

## 5. Point-in-time and returns
- A quarter is known at its `broadcast_at`; one without (Sep 2024–Mar 2025) at period_end + 60 days (the router's rule).
- **Event:** the target quarter's row used by `answer()`; its `broadcast_at` must be within ±1 IST day of a
  quarterly_results meeting for the symbol, and `answer()`'s period_end must equal the target quarter. One event per symbol
  per season.
- **First reaction session S:** the broadcast's IST date if it is a session and the broadcast is before 15:30 IST; else the
  next session. The session calendar is the Nifty 50 index calendar.
- R1 = adj_close(S) ÷ adj_close(S−1) − 1; R5 = adj_close(S+4) ÷ adj_close(S−1) − 1; D5 = adj_close(S+5) ÷ adj_close(S) − 1.
  Each **excess** = the stock return − the Nifty 50 return over the same sessions (simple difference). A stock without a bar
  on every endpoint session is excluded for that measure.
- **Universe filter (on S−1):** median traded value (raw close × raw volume) over the last 20 bars ≥ ₹1 crore and raw close
  ≥ ₹10. (S5 drops the filter.)
- **Holdout guard:** the primary run computes no return for target 2026-09-30 and excludes any event whose last return
  session falls after 2026-09-30 (late filers of the Jun 2026 quarter); the script refuses otherwise.
- Values are the latest stored, not as first filed (restatements are not tracked: a known limitation).

## 6. Statistics
- **Winsorising:** mean-based tests (H1) use excess returns winsorised at the 1st/99th percentile of each season's
  analysis sample, per measure. Rank tests need none. S5 repeats H1 unwinsorised.
- **H1 statistic:** per season, mean(above) − mean(below); decision statistic = the equal-weight mean over seasons with
  ≥ 30 above **and** ≥ 30 below. Also reported: Welch t on the pooled events (df Welch–Satterthwaite).
- **H2–H4 statistic:** per-season Spearman IC (average ranks for ties); decision statistic = the equal-weight mean over
  seasons meeting the minimum (H2 ≥ 100 scored; H3, H4 ≥ 60 scored). Also reported: the pooled IC and, with ≥ 3 seasons,
  t = mean / (sd/√k), df k − 1.
- **Inference (decision):** a bootstrap that resamples **reaction dates** (S) with replacement within each season (results
  cluster on the same days), recomputing the statistic; 10,000 draws, seed 20261027. One-sided p = (1 + #{θ* ≤ 0}) /
  (B + 1); 95 % CI = 2.5th–97.5th percentiles. Opposite-sign p is computed the same way for "reversed".
- **Multiple testing:** the primary family is {H1-R5, H1-R1, H2, H3, H4}, Holm–Bonferroni at family-wise α = 0.05
  (one-sided). Secondary and exploratory tests report raw p and carry no decision.

## 7. Secondary and exploratory (reported, no decision)
- S1 "last year unchanged" baseline: H1 (R1, R5) and H2 over the four seasons, with the cross-season t.
- S2 PAT metric verdict alone (H1).
- S3 strict point-in-time band, Jul–Aug 2026 (H1).
- S4 calibration-free: Spearman IC of PAT `vs_mid_pct` with R1 and R5.
- S5 no liquidity filter; H1 unwinsorised.
- S6 each component's own IC with R5 (surprise, trend, quality for H2; technical, OI, past reactions, trend for H3) — also
  the input to the §9 component rule.
- E1 H1 for F&O and non-F&O names separately.
- E2 outlook proxy, Jul–Aug 2026 filings that have an analysis: IC of the outlook score with R5, and of the composite with
  outlook included. Not point-in-time (generated Oct 2026); model training-data leakage cannot be ruled out from the record.

## 8. Holdout: Oct–Nov 2026 (target quarter 2026-09-30)
Untouched until the confirmation run. It runs **on or after 2026-11-25** (results deadline 14 Nov + 5 sessions + the 1–2
day figure lag), on every Sep 2026 target whose R5 window (D5 for H4) is complete, with the code at the primary run's commit
and the frozen bands (§4.1). Tests: whichever of H1-R5, H2, H3, H4 passed in the primary run, each one-sided at 0.05 with
Holm across those attempted, plus the sign of each component flagged by §9(b).

## 9. Decision rule for the live ranking (registered; nothing else changes weights)
Each output gets a label from its own primary test. Verdict pills ← **H1-R5** (H1-R1 is reported in the same family but the
label rests on R5). Composite score ← **H2**. Upcoming ideas order ← **H3**. Declared ideas order ← **H4**.
- **PASS** = Holm-adjusted p < 0.05 **and** the per-season estimate has the same sign in every season meeting the minimum
  → label "early evidence over N seasons; confirmation pending (Oct–Nov 2026)". After the holdout: confirmed → "tested over
  N + 1 seasons"; not confirmed → "no measurable skill (did not hold out of sample)".
- **FAIL** (not PASS, not REVERSED) → label "**no measurable skill** so far (tested over N seasons, n results)". The output
  may stay on screen with that label; the "not yet tested" label is retired.
- **REVERSED** = estimate < 0 with Holm-adjusted opposite-sign p < 0.05 → label "reversed in testing: higher scores were
  followed by lower returns"; the owner decides whether it stays on screen. No weight is flipped automatically.
- **INSUFFICIENT** (no season meets the minimum) → stays "not yet tested".

**Weights.**
- (a) No weight, threshold or split (z = ±1/±2, PAT 0.6 / revenue 0.4, 35/25/25/15, 40/20/20/20, 40/30/15/15) is raised,
  lowered or tuned from these seasons, whatever the result: too few seasons to tune without overfitting. Provisional weights
  stay.
- (b) The only change allowed: a component of the composite or of an ideas order whose own S6 IC is **negative** with
  Holm-adjusted (within that score's components) two-sided p < 0.05 is marked "harmful (provisional)". Its weight goes to 0
  (the rest renormalised pro rata) **only if** its IC is also negative in the holdout season. Otherwise nothing changes.
- (c) The outlook component's weight is untouched (not testable point-in-time).

## 10. Reproducibility and outputs
- Scripts: `research/earnings_surprise/` (export SQL, dataset build, study). Data and outputs outside git in
  `/home/deploy/earnings-study-data/`; the results document quotes the counts, file hashes, code SHA and this file's
  commit. Nothing is written to the warehouse, the app database or Mongo.
- Every result is reported, including nulls, with per-season tables. Deviations from this file are listed as deviations.

## Amendment A1 — registered 2026-10-27 (IST), before any statistic for any hypothesis was computed
**State at registration:** §1–§10 are unchanged. The dataset has been built (`research/earnings_surprise/build_dataset.py`,
committed with this amendment); its run printed row counts only. No mean, difference, IC or p-value has been computed for
any hypothesis, and no return has been inspected. Two new facts arrived after the registration commit `b3415111`:
(1) the owner added a "results strength" boost to the live AI scanner (~18:05 IST, rule relayed by the coordinator); it is
registered here as **H5** (H4 was already taken by the declared order); (2) the P1 implementation landed
(`backend/services/results_week/scoring.py`, commit `9f78c6ee` on `feat/earnings-surprise-tracker`, 18:03–18:07 IST) and
differs from §4 in several constants; its version of H1–H4 is registered as **S7**.

### A1.1 H5 — the scanner's results-strength boost
No code for the boost was found in any worktree at registration, so the rule is pinned from the relayed live constants.
On the target quarter Q, the event's basis, stored values:
- **PAT YoY** = PAT(Q) ÷ PAT(Q−4) − 1 when PAT(Q−4) > 0. *Loss → profit* (PAT(Q−4) ≤ 0 < PAT(Q)) counts as ≥ +20 %;
  *profit → loss* (PAT(Q−4) > 0 ≥ PAT(Q)) counts as ≤ −10 %. Otherwise undefined (criterion not met).
- **Revenue YoY** when revenue(Q−4) > 0. **EBITDA-margin change** YoY in basis points, when both revenues > 0 and both
  EBITDA are stored.
- **Rated verdict** = the live headline verdict (`scoring.surprise` at `9f78c6ee`: weighted z, band-width cap; S7 inputs).
- **Red flags:** exceptional items > 20 % of PBT; other income > 30 % of PBT (both only with PBT > 0); verdict below (which
  includes "well below").
- **STRONG** = at least 2 of {PAT YoY ≥ +20 %, revenue YoY ≥ +10 %, margin change ≥ +50 bps, verdict above} **and** no red
  flag. **WEAK** = (PAT YoY ≤ −10 % **and** revenue YoY < +5 %) **or** verdict below. A name meeting both is put in neither
  group and counted. **Unflagged** = the other results names in the same sample.
- **Variant per season** (stated exactly): the verdict exists only where the full baseline does.
  - Oct–Nov 2025 and Jan–Feb 2026: **growth-only** (three growth criteria, red flags without the verdict, WEAK without the
    verdict clause). The growth criteria need only Q−4, which every studied season has.
  - Apr–May 2026 and Jul–Aug 2026: **full rule**. A name without a rated verdict there is judged on the other parts,
    exactly as the live rule would judge it.
- **Sample:** §5's events and liquid universe, all four seasons.
- **Outcomes:** R5 and R1 as §5, and **D5** (adj_close(S+5) ÷ adj_close(S) − 1 minus Nifty). The boost is applied by the
  nightly scan after the figures are stored, so D5, the return after the reaction day, is the part it can act on.
- **Statistics:** as §6 for H1: per-season difference of winsorised means (group − unflagged), equal-weight mean over the
  seasons with ≥ 30 names in each group, stratified date-cluster bootstrap (10,000 draws, seed 20261027), Welch t on pooled
  events, cross-season t (k = 4).
- **Family F5** (Holm, α = 0.05 one-sided): STRONG−unflagged > 0 on D5 and on R5; WEAK−unflagged < 0 on D5 and on R5.
  R1 is reported for both groups without a decision. Secondary (no decision): the full rule on its two seasons only; the
  growth-only rule on all four seasons.
- **Decision (STRONG; WEAK mirrored with the sign reversed, −10 / −5 / 0):**
  - **keep +10**: STRONG D5 passes (Holm-adjusted p < 0.05, same sign in every eligible season);
  - **+5**: not the above, but STRONG R5 passes **and** the pooled D5 estimate is > 0;
  - **0**: everything else, including R5 passing with D5 ≤ 0 (the strength is priced on the reaction day, and a boost
    applied after it adds nothing measurable). A significantly reversed D5 (Holm, opposite sign) also gives 0 and is
    flagged to the owner.
  - The holdout run (§8) repeats the D5 and R5 tests on Oct–Nov 2026; a kept or halved value that fails there goes to 0.

### A1.2 S7 — the live code's version of H1–H4
`scoring.py` at `9f78c6ee` differs from §4 in:
- the headline verdict thresholds the weighted z (§4.2 thresholds the clamped score);
- a band wider than 0.35 (PAT) / 0.20 (revenue) relative half-width is not rated;
- trend items are weighted YoY 2 · QoQ 1 · margin 2, and one item is enough;
- OI states are graded 100 / 75 / 50 / 25 / 0 and called only when |price| ≥ 0.5 %, |OI| ≥ 3 % and futures turnover
  ≥ ₹50 cr;
- reaction = clamp(50 + 10 · excess % · w), with w = the volume multiple clamped to [0.5, 2];
- past reactions = the mean event-day × next-day move, scored clamp(50 + 10 · mean);
- a name is ordered only when parts carrying ≥ 50 % of its list's weight are present.

S7 runs H1–H4 with those functions imported from that commit, fed the same point-in-time inputs as §4–§5: DaaS-shaped
metrics from `answer()`, merged quarter rows, adjusted closes and volumes, OI with turnover from the bhavcopy, past
reactions from adjusted closes. The technical part stays the B0 replay (§4.7). The live part reads the scanner's stored
final score, which cannot be replayed. **Family F7** = the S7 versions of {H1-R5, H1-R1, H2, H3, H4}, Holm as §6.

**Label rule (amends §9, conservatively):** an on-screen label may say "early evidence" only if both the registered test
and its S7 counterpart PASS. If either fails, the label is "no measurable skill". If either is REVERSED, the label is
"reversed in testing". §9(b) is unchanged.

## Amendment A2 — registered 2026-10-27 (IST), before any study output was read
**What was found.** The hand check of returns (CUB, 28 Jul 2026) showed that `broadcast_at` is not the first public
filing. CUB filed its "Outcome of Board Meeting" on NSE at 14:40 IST, but its stored `broadcast_at` is 19:17. Across the
dataset, the earliest NSE "Outcome of Board Meeting" filing (the router's exact subject match, on the broadcast's IST date
or the meeting date) comes before `broadcast_at` for 96–100 % of events, with a median lead of 1.5 hours. For 481 / 421 /
438 / 429 events (seasons Oct–Nov 2025 → Jul–Aug 2026), that filing was during market hours but `broadcast_at` was after
15:30. The §5 rule therefore puts the first reaction session **one session late** for about a quarter of events, and their
R1 / R5 miss the reaction day. That biases H1, H2 and H5-R toward null.

**State when this was registered.** The study script (`run_study.py`, commit `954208ce`) had been started on the §5 timing
in the background. None of its output had been read. No statistic had been seen.

**Change.**
- **T2 timing (governs the decision):** filing time = the earlier of `broadcast_at` and that earliest same-day outcome
  filing. S, R1, R5, D5, the S−1 liquidity filter, the H3 signal session (S−1) and the H4 signal session (S) all follow
  from it. The expectation's point-in-time cutoff stays `broadcast_at`, because earlier quarters were known long before
  either time.
- **T1 (the §5 timing as registered):** run and reported in full beside T2.
- Every test, family, threshold, holdout rule and decision rule (§6–§9, A1) is applied to **T2**.
- Where T1 and T2 give different labels, the results document says so.
- The holdout run (§8) uses T2.

## Amendment A3 — registered 2026-10-27 (IST), before any study output was read
**State when this was registered.** The T1 and T2 runs of `run_study.py` finished at 18:36 and 18:38 IST and wrote
their `result.json` files and run logs, including the F5 (H5 as registered) statistics. None of these files, logs or
task outputs had been opened or read. No statistic had been seen.

**What changed in the live code.**
- The scanner's results signal was first committed as `backend/services/results_week/signal.py` in `3581de52` at
  18:12:52 IST, 81 seconds after A1. A1's "no code found" was therefore true when written.
- `790d8132` changed the rule. The coordinator puts the change at ~19:33 IST; the commit is stamped 19:36:50 IST. Two
  changes:
  - a profit fall (PAT YoY < 0, a loss turning into a profit excepted) is never "strong";
  - a rated "below" alongside a strong PAT rise is no longer "weak": it gets no signal.

**How the live rule at `790d8132` differs from A1.1 (which stays the registered H5).**
- (i) "Above" and "below" are the **per-metric** rated verdicts: any of PAT or revenue. A1.1 uses the headline verdict.
- (ii) PAT YoY < 0 (not loss → profit) gives no signal.
- (iii) WEAK = (PAT YoY ≤ −10 % and revenue YoY < +5 %) or (a metric rated below and PAT is not up ≥ 20 % or
  loss → profit). Any other rated below gives no signal.
- (iv) WEAK is checked first, so there is no "conflict" group.
- (v) The filing-analysis fallback (±5 when figures are not stored yet) is not tested. Every studied event has stored
  figures, and the analyses are not point-in-time.
- (vi) Its `surprise()` is `scoring.py` at `790d8132`.

**Added: H5-L (secondary, labelled "new live rule").**
- `figures_facts` and `classify_figures` are imported from `signal.py` + `scoring.py` at `790d8132` and fed the same
  inputs as S7. In the growth-only seasons (Oct–Nov 2025, Jan–Feb 2026) no metric is rated, so the verdict clauses are
  empty, as they are live for an unrated name.
- Same tests and statistics as F5 (D5 and R5 for STRONG and WEAK; R1 reported), in its own Holm family **F5L**.
- **Decision:** the A1.1 rule is applied to F5 (the registered result) and to F5L. The recommended live points for each
  of STRONG and WEAK are the **smaller in magnitude** of the two outcomes. Both are reported.

**Not changed.**
- S7 stays pinned to `scoring.py` at `9f78c6ee`.
- The live ideas and OI rules changed after that commit, for example in `315c54c8` (total-OI thresholds 0.5 % / 2 %,
  expiry-week handling). Those later rules are **not tested** here, and the results document lists them.
- T2 timing governs (A2).

## Log
| When (IST) | What | Commit |
|---|---|---|
| 2026-10-27 18:00:31 | Registered before any verdict, score or return was computed; pushed to origin 18:00:35 | `b341511143eda11b4467c13d5772189b85c4c904` |
| 2026-10-27 | This log row added (no change to §1–§10) | `dc0f86be` |
| 2026-10-27 18:11:31 | Amendment A1 (H5, S7) registered before any statistic; pushed 18:11:35 | `c5bc89a1bb70b7eea68d9b6efbdb7f8565e74e4b` |
| 2026-10-27 18:19:16 | Amendment A2 (T2 timing governs) registered before any study output was read; pushed 18:19:20 | `168c8fd419ccc7c1e26e28e774467ae6ea372d87` |
| 2026-10-27 19:39:19 | Amendment A3 (H5-L, the live rule at `790d8132`) registered before any study output was read; pushed 19:39:22 | `517cefcffa6ac8e7fa466c916bc010ebea5f6b20` |
