# Results: does the Results-week tracker explain post-results returns? (pre-registered study)

**Run:** 2026-10-27 (IST) on the staging warehouse, read-only.
**Design:** `docs/ai_research/EARNINGS_SURPRISE_PREREGISTRATION.md`.
- Registered at `b3415111` (18:00 IST), before any score or return was computed.
- Amendments, each registered before any study output was read:
  - A1 `c5bc89a1` (18:11): H5, the results-strength boost, and S7, the live code's version of H1–H4.
  - A2 `168c8fd4` (18:19): T2 timing governs.
  - A3 `517cefcf` (19:39): H5-L, the live boost rule as changed in `790d8132`.

**Code:** `research/earnings_surprise/` at `4d6344bf` (study, dataset build, parity check, report).
- S7 imports `backend/services/results_week/scoring.py` at `9f78c6ee` (sha256 `2cd9c3b6…`).
- H5-L imports `signal.py` + `scoring.py` at `790d8132` (sha256 `11781da0…`).

**Status:** the primary analysis is complete. The holdout (Oct–Nov 2026) is pending and runs on or after 2026-11-25
(§8). Paper / research only: nothing here is a recommendation. Wording throughout: "vs historical trend", "ordered
for review".

## 1. Bottom line: the registered decision for the live screens (T2 timing, A2)
| Live output | Test | Registered formulas | Live code (S7) | Label under §9 + A1.2 |
|---|---|---|---|---|
| Verdict pills (above / in line / below historical trend) | H1-R5 | PASS (+6.06 pp, Holm p 0.0005) | PASS (+4.78 pp, Holm p 0.0005) | **early evidence over 2 seasons; confirmation pending (Oct–Nov 2026)** |
| Earnings Intelligence Score (composite) | H2 | PASS (IC +0.251) | PASS (IC +0.229) | **early evidence over 2 seasons; confirmation pending (Oct–Nov 2026)** |
| Results-week ideas, upcoming (F&O) | H3 | FAIL (IC +0.040, p 0.15) | FAIL (IC +0.024, p 0.26) | **no measurable skill so far** (4 seasons, 735 F&O results) |
| Results-week ideas, declared (F&O) | H4 | FAIL (IC +0.046, p 0.16) | FAIL (IC +0.063, p 0.08) | **no measurable skill so far** (2 seasons, 386 / 366 results) |

**Weights.**
- No weight, threshold or split changes (§9(a)).
- No component is "harmful (provisional)" under §9(b). No component IC is significantly negative. The OI part of the
  upcoming order has IC −0.007, which is not significant, so its weight stays.

**The scanner's results-strength boost (H5 / H5-L, rule A1.1 + A3).** The registered rule and the live rule at
`790d8132` give the same outcome:

| Group | D5 (after the reaction) | R5 (reaction included) | Points by the rule | Today |
|---|---|---|---|---|
| STRONG | FAIL: +0.42 pp, raw p 0.027, Holm p 0.054 | PASS: +2.90 pp | **+5** | +10 |
| WEAK | FAIL: +0.06 pp, wrong sign | PASS: −1.57 pp (live rule −1.84 pp) | **0** | −10 |

**Recommended live points: STRONG +5, WEAK 0.** The holdout season repeats the D5 and R5 tests. A value that fails
there goes to 0.

**What "explains" means here, which is the most important caveat.**
- H1 and H2 measure returns from the close **before** the filing (R1, R5). They show that the verdict and the composite
  line up strongly with the price reaction to the same results.
- Most of the 5-session gap is already in the first session: H1 is +5.60 pp on R1 against +6.06 pp on R5.
- The part a reader could still act on after the list appears (D5, the 5 sessions after the reaction day) is small. For
  STRONG it is +0.4 pp and not significant after Holm. For WEAK it is about zero.
- So these results **support the verdicts as a description of how results were received. They are not evidence that
  the ranking predicts returns after it is shown.** The labels above should say "explains the results-day reaction",
  not "predicts".

## 2. Sample design and why
- **Seasons** are defined by target quarter: Oct–Nov 2025 = Sep 2025 quarter, … Jul–Aug 2026 = Jun 2026 quarter.
- The warehouse's quarterly history starts at **Sep 2024** (not Dec 2024 as first briefed). The live method needs 7
  published quarters, so it can be replayed for exactly two seasons: Apr–May 2026 and Jul–Aug 2026. Those two are
  primary for H1, H2 and H4.
- **S1**, a simpler "same quarter last year unchanged" baseline (the router's own benchmark), runs on all four seasons
  as a labelled secondary.
- **H3 and H5** need no baseline, or only t−4. They run on all four seasons.
- **H5 variant per season:**
  - Oct–Nov 2025 and Jan–Feb 2026 use the growth-only rule: no metric can be rated without a baseline.
  - Apr–May and Jul–Aug 2026 use the full rule. A name without a rated verdict there is judged on its growth parts,
    exactly as live.
- **Point-in-time:** the expectation uses only quarters known before the filing's `broadcast_at`. The study calls the
  DaaS router's own `answer()`.
- **Band:** calibrated on tested quarters ≤ Jun 2026. This is a look-ahead in the band's scale only, never in returns;
  S3 removes it for Jul–Aug 2026 with the same conclusion.
- **T2 timing (A2):** the first reaction session runs from the earlier of `broadcast_at` and the first NSE "Outcome of
  Board Meeting" filing that day.
- **Returns:** split/bonus-adjusted closes minus the Nifty 50 over the same sessions.
- **Universe:** median traded value ≥ ₹1 crore and close ≥ ₹10 on the session before.
- **Inference:** a bootstrap of reaction dates within season (10,000 draws, seed 20261027), then Holm within each
  family.

## 3. Dataset
Exported 27 Oct 2026 (watermarks: `nse_financials_quarterly` 06:10 IST, `prices_eod_adjusted` 26 Oct 22:34,
`index_eod` 27 Oct 07:44, `fno_bhavcopy` 26 Oct 22:15; Mongo `event_ai_analysis` 664 RESULTS docs). Files live in
`/home/deploy/earnings-study-data/`, outside git (sha256 in §8).

| Season (target quarter) | Events built | Excluded | Exclusion reasons | Liquid | Live method: PAT not reliable |
|---|---|---|---|---|---|
| Oct–Nov 2025 (2025-09-30) | 1,683 | 243 | no price bar on S−1 113 · no calendar meeting for the quarter 99 · meeting not within ±1 day of `broadcast_at` 27 · no `broadcast_at` 4 | 1,167 | all (no baseline possible) |
| Jan–Feb 2026 (2025-12-31) | 1,797 | 132 | no calendar meeting 63 · no price bar 64 · no `broadcast_at` 3 · meeting not within ±1 day 2 | 1,198 | all (no baseline possible) |
| Apr–May 2026 (2026-03-31) | 1,757 | 185 | no price bar 116 · no calendar meeting 52 · meeting not within ±1 day 9 · no `broadcast_at` 7 · window reaches the holdout 1 | 1,236 | 848 (+2 zero-width band) |
| Jul–Aug 2026 (2026-06-30) | 1,902 | 239 | no price bar 156 · no calendar meeting 56 · window reaches the holdout 14 · window beyond the price calendar 7 · no `broadcast_at` 2 · meeting not within ±1 day 4 | 1,333 | 993 |

Backtest records behind the band: PAT 938 (Mar 2026) + 967 (Jun 2026) = 1,905; revenue 1,591 + 1,588 = 3,179. The
110 PAT / 129 revenue Sep 2026 records were **not** used: the holdout is untouched.

## 4. Every result (T2 governs; generated by `report.py` from `result_T2.json` and `result_T1.json`)
Group differences are in percentage points of excess return; ICs are Spearman. "Holm p" is within the test's own family.

#### Counts (T2, liquid universe)

| Season | Events | Liquid | R5 | D5 | Verdict above / in line / below (registered) | Live-code verdict above / in line / below | H5 strong / weak / unflagged | H5-L strong / weak / unflagged | F&O (S−1) |
|---|---|---|---|---|---|---|---|---|---|
| Oct–Nov 2025 | 1683 | 1167 | 1162 | 1161 | 0 / 0 / 0 | 0 / 0 / 0 | 315 / 174 / 678 | 315 / 174 / 678 | 180 |
| Jan–Feb 2026 | 1797 | 1198 | 1198 | 1197 | 0 / 0 / 0 | 0 / 0 / 0 | 305 / 162 / 731 | 305 / 162 / 731 | 182 |
| Apr–May 2026 | 1757 | 1236 | 1225 | 1224 | 95 / 833 / 107 | 48 / 513 / 74 | 456 / 202 / 578 | 449 / 177 / 610 | 185 |
| Jul–Aug 2026 | 1902 | 1333 | 1333 | 1333 | 106 / 885 / 76 | 80 / 499 / 48 | 623 / 141 / 569 | 589 / 127 / 617 | 202 |

#### F1 — registered formulas (H1–H4) (T2, governs)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| H1-R5 | +6.06 pp | [+4.14 pp, +7.78 pp] | <0.0001 | 0.0005 | +5.89 pp (t 6.77, p <0.0001) | — | yes | PASS |
| H1-R1 | +5.60 pp | [+4.24 pp, +6.82 pp] | <0.0001 | 0.0005 | +5.46 pp (t 9.23, p <0.0001) | — | yes | PASS |
| H2 | +0.251 | [+0.204, +0.291] | <0.0001 | 0.0005 | +0.243 (n 2471) | — | yes | PASS |
| H3 | +0.040 | [-0.037, +0.121] | 0.1455 | 0.2910 | +0.033 (n 735) | 0.84 (0.2315) | no | FAIL |
| H4 | +0.046 | [-0.044, +0.142] | 0.1559 | 0.2910 | +0.040 (n 386) | — | yes | FAIL |

Per season:

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| H1-R5 | Apr–May 2026 | 95 / 107 | +3.42 pp / -3.50 pp | +6.92 pp | yes |
| H1-R5 | Jul–Aug 2026 | 106 / 76 | +0.60 pp / -4.59 pp | +5.19 pp | yes |
| H1-R1 | Apr–May 2026 | 95 / 107 | +2.52 pp / -2.92 pp | +5.44 pp | yes |
| H1-R1 | Jul–Aug 2026 | 106 / 76 | +1.58 pp / -4.18 pp | +5.76 pp | yes |
| H2 | Apr–May 2026 | 1219 | — | +0.250 | yes |
| H2 | Jul–Aug 2026 | 1252 | — | +0.251 | yes |
| H3 | Oct–Nov 2025 | 167 | — | +0.178 | yes |
| H3 | Jan–Feb 2026 | 182 | — | -0.033 | yes |
| H3 | Apr–May 2026 | 184 | — | +0.022 | yes |
| H3 | Jul–Aug 2026 | 202 | — | -0.007 | yes |
| H4 | Apr–May 2026 | 184 | — | +0.066 | yes |
| H4 | Jul–Aug 2026 | 202 | — | +0.026 | yes |

#### F7 — live code, S7 (H1–H4) (T2, governs)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| S7-H1-R5 | +4.78 pp | [+2.53 pp, +6.71 pp] | <0.0001 | 0.0005 | +4.52 pp (t 4.08, p <0.0001) | — | yes | PASS |
| S7-H1-R1 | +3.99 pp | [+2.64 pp, +5.29 pp] | <0.0001 | 0.0005 | +3.84 pp (t 5.30, p <0.0001) | — | yes | PASS |
| S7-H2 | +0.229 | [+0.180, +0.271] | <0.0001 | 0.0005 | +0.219 (n 2479) | — | yes | PASS |
| S7-H3 | +0.024 | [-0.050, +0.102] | 0.2625 | 0.2625 | +0.027 (n 735) | 0.83 (0.2333) | no | FAIL |
| S7-H4 | +0.063 | [-0.025, +0.154] | 0.0774 | 0.1548 | +0.060 (n 366) | — | yes | FAIL |

Per season:

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| S7-H1-R5 | Apr–May 2026 | 48 / 74 | +3.16 pp / -2.20 pp | +5.37 pp | yes |
| S7-H1-R5 | Jul–Aug 2026 | 80 / 48 | +1.48 pp / -2.71 pp | +4.19 pp | yes |
| S7-H1-R1 | Apr–May 2026 | 48 / 74 | +1.75 pp / -1.36 pp | +3.11 pp | yes |
| S7-H1-R1 | Jul–Aug 2026 | 80 / 48 | +1.90 pp / -2.96 pp | +4.86 pp | yes |
| S7-H2 | Apr–May 2026 | 1223 | — | +0.248 | yes |
| S7-H2 | Jul–Aug 2026 | 1256 | — | +0.211 | yes |
| S7-H3 | Oct–Nov 2025 | 167 | — | +0.083 | yes |
| S7-H3 | Jan–Feb 2026 | 182 | — | -0.029 | yes |
| S7-H3 | Apr–May 2026 | 184 | — | -0.022 | yes |
| S7-H3 | Jul–Aug 2026 | 202 | — | +0.065 | yes |
| S7-H4 | Apr–May 2026 | 183 | — | +0.078 | yes |
| S7-H4 | Jul–Aug 2026 | 183 | — | +0.048 | yes |

#### F5 — results-strength boost (H5, registered A1.1) (T2, governs)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| H5-STRONG-D5 | +0.42 pp | [-0.01 pp, +0.80 pp] | 0.0272 | 0.0544 | +0.61 pp (t 3.23, p 0.0006) | 4.27 (0.0118) | yes | FAIL |
| H5-STRONG-R5 | +2.90 pp | [+2.35 pp, +3.41 pp] | <0.0001 | 0.0004 | +2.95 pp (t 11.41, p <0.0001) | 20.03 (0.0001) | yes | PASS |
| H5-WEAK-D5 (tests < 0) | +0.06 pp | [-0.32 pp, +0.42 pp] | 0.6284 | 0.6284 | +0.08 pp (t 0.32, p 0.6241) | 0.45 (0.6581) | no | FAIL |
| H5-WEAK-R5 (tests < 0) | -1.57 pp | [-2.09 pp, -1.06 pp] | <0.0001 | 0.0004 | -1.55 pp (t -5.17, p <0.0001) | -12.86 (0.0005) | yes | PASS |

Per season:

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| H5-STRONG-D5 | Oct–Nov 2025 | 312 / 676 | -1.52 pp / -1.88 pp | +0.37 pp | yes |
| H5-STRONG-D5 | Jan–Feb 2026 | 305 / 730 | -0.17 pp / -0.41 pp | +0.24 pp | yes |
| H5-STRONG-D5 | Apr–May 2026 | 451 / 571 | +0.66 pp / -0.04 pp | +0.70 pp | yes |
| H5-STRONG-D5 | Jul–Aug 2026 | 623 / 569 | +0.23 pp / -0.14 pp | +0.37 pp | yes |
| H5-STRONG-R5 | Oct–Nov 2025 | 312 / 676 | +0.41 pp / -2.37 pp | +2.78 pp | yes |
| H5-STRONG-R5 | Jan–Feb 2026 | 305 / 731 | +1.89 pp / -0.71 pp | +2.60 pp | yes |
| H5-STRONG-R5 | Apr–May 2026 | 451 / 572 | +2.75 pp / -0.53 pp | +3.28 pp | yes |
| H5-STRONG-R5 | Jul–Aug 2026 | 623 / 569 | +1.30 pp / -1.64 pp | +2.94 pp | yes |
| H5-WEAK-D5 | Oct–Nov 2025 | 173 / 676 | -2.11 pp / -1.88 pp | -0.23 pp | yes |
| H5-WEAK-D5 | Jan–Feb 2026 | 162 / 730 | -0.22 pp / -0.41 pp | +0.18 pp | yes |
| H5-WEAK-D5 | Apr–May 2026 | 202 / 571 | -0.15 pp / -0.04 pp | -0.11 pp | yes |
| H5-WEAK-D5 | Jul–Aug 2026 | 141 / 569 | +0.27 pp / -0.14 pp | +0.41 pp | yes |
| H5-WEAK-R5 | Oct–Nov 2025 | 174 / 676 | -3.97 pp / -2.37 pp | -1.60 pp | yes |
| H5-WEAK-R5 | Jan–Feb 2026 | 162 / 731 | -2.12 pp / -0.71 pp | -1.41 pp | yes |
| H5-WEAK-R5 | Apr–May 2026 | 202 / 572 | -2.43 pp / -0.53 pp | -1.90 pp | yes |
| H5-WEAK-R5 | Jul–Aug 2026 | 141 / 569 | -3.01 pp / -1.64 pp | -1.37 pp | yes |

#### F5L — the new live rule at 790d8132 (H5-L, A3) (T2, governs)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| H5L-STRONG-D5 | +0.41 pp | [-0.02 pp, +0.79 pp] | 0.0304 | 0.0608 | +0.57 pp (t 3.01, p 0.0013) | 3.32 (0.0226) | yes | FAIL |
| H5L-STRONG-R5 | +2.90 pp | [+2.34 pp, +3.41 pp] | <0.0001 | 0.0004 | +2.96 pp (t 11.38, p <0.0001) | 21.23 (0.0001) | yes | PASS |
| H5L-WEAK-D5 (tests < 0) | +0.06 pp | [-0.31 pp, +0.42 pp] | 0.6283 | 0.6283 | +0.04 pp (t 0.16, p 0.5646) | 0.65 (0.7185) | no | FAIL |
| H5L-WEAK-R5 (tests < 0) | -1.84 pp | [-2.32 pp, -1.35 pp] | <0.0001 | 0.0004 | -1.81 pp (t -5.98, p <0.0001) | -9.23 (0.0013) | yes | PASS |

Per season:

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| H5L-STRONG-D5 | Oct–Nov 2025 | 312 / 676 | -1.52 pp / -1.88 pp | +0.37 pp | yes |
| H5L-STRONG-D5 | Jan–Feb 2026 | 305 / 730 | -0.17 pp / -0.41 pp | +0.24 pp | yes |
| H5L-STRONG-D5 | Apr–May 2026 | 444 / 603 | +0.66 pp / -0.11 pp | +0.77 pp | yes |
| H5L-STRONG-D5 | Jul–Aug 2026 | 589 / 617 | +0.21 pp / -0.05 pp | +0.26 pp | yes |
| H5L-STRONG-R5 | Oct–Nov 2025 | 312 / 676 | +0.41 pp / -2.37 pp | +2.78 pp | yes |
| H5L-STRONG-R5 | Jan–Feb 2026 | 305 / 731 | +1.89 pp / -0.71 pp | +2.60 pp | yes |
| H5L-STRONG-R5 | Apr–May 2026 | 444 / 604 | +2.75 pp / -0.49 pp | +3.24 pp | yes |
| H5L-STRONG-R5 | Jul–Aug 2026 | 589 / 617 | +1.45 pp / -1.52 pp | +2.97 pp | yes |
| H5L-WEAK-D5 | Oct–Nov 2025 | 173 / 676 | -2.11 pp / -1.88 pp | -0.23 pp | yes |
| H5L-WEAK-D5 | Jan–Feb 2026 | 162 / 730 | -0.22 pp / -0.41 pp | +0.18 pp | yes |
| H5L-WEAK-D5 | Apr–May 2026 | 177 / 603 | +0.08 pp / -0.11 pp | +0.19 pp | yes |
| H5L-WEAK-D5 | Jul–Aug 2026 | 127 / 617 | +0.07 pp / -0.05 pp | +0.11 pp | yes |
| H5L-WEAK-R5 | Oct–Nov 2025 | 174 / 676 | -3.97 pp / -2.37 pp | -1.60 pp | yes |
| H5L-WEAK-R5 | Jan–Feb 2026 | 162 / 731 | -2.12 pp / -0.71 pp | -1.41 pp | yes |
| H5L-WEAK-R5 | Apr–May 2026 | 177 / 604 | -2.72 pp / -0.49 pp | -2.23 pp | yes |
| H5L-WEAK-R5 | Jul–Aug 2026 | 127 / 617 | -3.64 pp / -1.52 pp | -2.12 pp | yes |

#### Secondary H5-R1 (T2; raw p, no decision)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| H5-STRONG-R1 | +2.50 pp | [+2.16 pp, +2.81 pp] | <0.0001 | — | +2.44 pp (t 14.23, p <0.0001) | 28.69 (<0.0001) | yes |  |
| H5-WEAK-R1 (tests < 0) | -1.58 pp | [-1.98 pp, -1.20 pp] | <0.0001 | — | -1.56 pp (t -8.28, p <0.0001) | -19.59 (0.0001) | yes |  |
| H5L-STRONG-R1 | +2.52 pp | [+2.17 pp, +2.83 pp] | <0.0001 | — | +2.49 pp (t 14.43, p <0.0001) | 26.42 (<0.0001) | yes |  |
| H5L-WEAK-R1 (tests < 0) | -1.80 pp | [-2.18 pp, -1.41 pp] | <0.0001 | — | -1.75 pp (t -9.35, p <0.0001) | -8.72 (0.0016) | yes |  |

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| H5-STRONG-R1 | Oct–Nov 2025 | 313 / 678 | +1.43 pp / -0.93 pp | +2.36 pp | yes |
| H5-STRONG-R1 | Jan–Feb 2026 | 305 / 731 | +1.65 pp / -0.70 pp | +2.35 pp | yes |
| H5-STRONG-R1 | Apr–May 2026 | 455 / 575 | +2.19 pp / -0.51 pp | +2.70 pp | yes |
| H5-STRONG-R1 | Jul–Aug 2026 | 623 / 569 | +1.04 pp / -1.55 pp | +2.59 pp | yes |
| H5-WEAK-R1 | Oct–Nov 2025 | 174 / 678 | -2.43 pp / -0.93 pp | -1.50 pp | yes |
| H5-WEAK-R1 | Jan–Feb 2026 | 162 / 731 | -2.10 pp / -0.70 pp | -1.40 pp | yes |
| H5-WEAK-R1 | Apr–May 2026 | 202 / 575 | -2.22 pp / -0.51 pp | -1.71 pp | yes |
| H5-WEAK-R1 | Jul–Aug 2026 | 141 / 569 | -3.28 pp / -1.55 pp | -1.73 pp | yes |
| H5L-STRONG-R1 | Oct–Nov 2025 | 313 / 678 | +1.43 pp / -0.93 pp | +2.36 pp | yes |
| H5L-STRONG-R1 | Jan–Feb 2026 | 305 / 731 | +1.65 pp / -0.70 pp | +2.35 pp | yes |
| H5L-STRONG-R1 | Apr–May 2026 | 448 / 607 | +2.19 pp / -0.43 pp | +2.62 pp | yes |
| H5L-STRONG-R1 | Jul–Aug 2026 | 589 / 617 | +1.21 pp / -1.52 pp | +2.73 pp | yes |
| H5L-WEAK-R1 | Oct–Nov 2025 | 174 / 678 | -2.43 pp / -0.93 pp | -1.50 pp | yes |
| H5L-WEAK-R1 | Jan–Feb 2026 | 162 / 731 | -2.10 pp / -0.70 pp | -1.40 pp | yes |
| H5L-WEAK-R1 | Apr–May 2026 | 177 / 607 | -2.63 pp / -0.43 pp | -2.19 pp | yes |
| H5L-WEAK-R1 | Jul–Aug 2026 | 127 / 617 | -3.65 pp / -1.52 pp | -2.13 pp | yes |

#### Secondary H5-full-2seasons (T2; raw p, no decision)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| H5full-strong-D5 | +0.53 pp | [+0.05 pp, +1.01 pp] | 0.0166 | — | +0.50 pp (t 1.93, p 0.0270) | — | yes |  |
| H5full-strong-R5 | +3.11 pp | [+2.44 pp, +3.72 pp] | <0.0001 | — | +3.00 pp (t 8.45, p <0.0001) | — | yes |  |
| H5full-weak-D5 (tests < 0) | +0.15 pp | [-0.43 pp, +0.62 pp] | 0.6827 | — | +0.11 pp (t 0.33, p 0.6275) | — | no |  |
| H5full-weak-R5 (tests < 0) | -1.64 pp | [-2.45 pp, -0.96 pp] | <0.0001 | — | -1.59 pp (t -3.64, p 0.0001) | — | yes |  |

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| H5full-strong-D5 | Apr–May 2026 | 451 / 571 | +0.66 pp / -0.04 pp | +0.70 pp | yes |
| H5full-strong-D5 | Jul–Aug 2026 | 623 / 569 | +0.23 pp / -0.14 pp | +0.37 pp | yes |
| H5full-strong-R5 | Apr–May 2026 | 451 / 572 | +2.75 pp / -0.53 pp | +3.28 pp | yes |
| H5full-strong-R5 | Jul–Aug 2026 | 623 / 569 | +1.30 pp / -1.64 pp | +2.94 pp | yes |
| H5full-weak-D5 | Apr–May 2026 | 202 / 571 | -0.15 pp / -0.04 pp | -0.11 pp | yes |
| H5full-weak-D5 | Jul–Aug 2026 | 141 / 569 | +0.27 pp / -0.14 pp | +0.41 pp | yes |
| H5full-weak-R5 | Apr–May 2026 | 202 / 572 | -2.43 pp / -0.53 pp | -1.90 pp | yes |
| H5full-weak-R5 | Jul–Aug 2026 | 141 / 569 | -3.01 pp / -1.64 pp | -1.37 pp | yes |

#### Secondary H5-growth-4seasons (T2; raw p, no decision)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| H5growth-strong-D5 | +0.43 pp | [-0.00 pp, +0.82 pp] | 0.0258 | — | +0.60 pp (t 3.19, p 0.0007) | 3.98 (0.0142) | yes |  |
| H5growth-strong-R5 | +2.97 pp | [+2.40 pp, +3.49 pp] | <0.0001 | — | +3.01 pp (t 11.65, p <0.0001) | 16.89 (0.0002) | yes |  |
| H5growth-weak-D5 (tests < 0) | +0.10 pp | [-0.33 pp, +0.51 pp] | 0.6746 | — | +0.03 pp (t 0.10, p 0.5413) | 0.94 (0.7908) | no |  |
| H5growth-weak-R5 (tests < 0) | -1.71 pp | [-2.26 pp, -1.18 pp] | <0.0001 | — | -1.71 pp (t -5.50, p <0.0001) | -11.36 (0.0007) | yes |  |

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| H5growth-strong-D5 | Oct–Nov 2025 | 312 / 676 | -1.52 pp / -1.88 pp | +0.37 pp | yes |
| H5growth-strong-D5 | Jan–Feb 2026 | 305 / 730 | -0.17 pp / -0.41 pp | +0.24 pp | yes |
| H5growth-strong-D5 | Apr–May 2026 | 444 / 629 | +0.64 pp / -0.10 pp | +0.74 pp | yes |
| H5growth-strong-D5 | Jul–Aug 2026 | 619 / 603 | +0.26 pp / -0.12 pp | +0.37 pp | yes |
| H5growth-strong-R5 | Oct–Nov 2025 | 312 / 676 | +0.41 pp / -2.37 pp | +2.78 pp | yes |
| H5growth-strong-R5 | Jan–Feb 2026 | 305 / 731 | +1.89 pp / -0.71 pp | +2.60 pp | yes |
| H5growth-strong-R5 | Apr–May 2026 | 444 / 630 | +2.79 pp / -0.61 pp | +3.40 pp | yes |
| H5growth-strong-R5 | Jul–Aug 2026 | 619 / 603 | +1.39 pp / -1.71 pp | +3.09 pp | yes |
| H5growth-weak-D5 | Oct–Nov 2025 | 173 / 676 | -2.11 pp / -1.88 pp | -0.23 pp | yes |
| H5growth-weak-D5 | Jan–Feb 2026 | 162 / 730 | -0.22 pp / -0.41 pp | +0.18 pp | yes |
| H5growth-weak-D5 | Apr–May 2026 | 151 / 629 | +0.11 pp / -0.10 pp | +0.21 pp | yes |
| H5growth-weak-D5 | Jul–Aug 2026 | 111 / 603 | +0.13 pp / -0.12 pp | +0.25 pp | yes |
| H5growth-weak-R5 | Oct–Nov 2025 | 174 / 676 | -3.97 pp / -2.37 pp | -1.60 pp | yes |
| H5growth-weak-R5 | Jan–Feb 2026 | 162 / 731 | -2.12 pp / -0.71 pp | -1.41 pp | yes |
| H5growth-weak-R5 | Apr–May 2026 | 151 / 630 | -2.73 pp / -0.61 pp | -2.12 pp | yes |
| H5growth-weak-R5 | Jul–Aug 2026 | 111 / 603 | -3.42 pp / -1.71 pp | -1.72 pp | yes |

#### Secondary S1 (T2; raw p, no decision)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| S1-H1-R5 | +4.32 pp | [+3.04 pp, +5.50 pp] | <0.0001 | — | +4.51 pp (t 7.65, p <0.0001) | 12.89 (0.0005) | yes |  |
| S1-H1-R1 | +4.16 pp | [+3.34 pp, +4.91 pp] | <0.0001 | — | +4.17 pp (t 10.94, p <0.0001) | 25.89 (<0.0001) | yes |  |
| S1-H2 | +0.236 | [+0.203, +0.263] | <0.0001 | — | +0.234 (n 4822) | 17.24 (0.0002) | yes |  |

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| S1-H1-R5 | Oct–Nov 2025 | 71 / 104 | -0.72 pp / -4.92 pp | +4.21 pp | yes |
| S1-H1-R5 | Jan–Feb 2026 | 81 / 119 | +2.32 pp / -2.14 pp | +4.46 pp | yes |
| S1-H1-R5 | Apr–May 2026 | 127 / 96 | +2.03 pp / -3.08 pp | +5.11 pp | yes |
| S1-H1-R5 | Jul–Aug 2026 | 136 / 77 | +1.50 pp / -1.99 pp | +3.49 pp | yes |
| S1-H1-R1 | Oct–Nov 2025 | 71 / 104 | +1.14 pp / -2.71 pp | +3.85 pp | yes |
| S1-H1-R1 | Jan–Feb 2026 | 81 / 119 | +1.55 pp / -2.37 pp | +3.92 pp | yes |
| S1-H1-R1 | Apr–May 2026 | 127 / 96 | +1.76 pp / -2.66 pp | +4.42 pp | yes |
| S1-H1-R1 | Jul–Aug 2026 | 136 / 77 | +1.46 pp / -3.00 pp | +4.46 pp | yes |
| S1-H2 | Oct–Nov 2025 | 1158 | — | +0.241 | yes |
| S1-H2 | Jan–Feb 2026 | 1192 | — | +0.196 | yes |
| S1-H2 | Apr–May 2026 | 1219 | — | +0.252 | yes |
| S1-H2 | Jul–Aug 2026 | 1253 | — | +0.257 | yes |

#### Secondary S2 (T2; raw p, no decision)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| S2-R5 | +5.76 pp | [+4.01 pp, +7.44 pp] | <0.0001 | — | +5.79 pp (t 6.57, p <0.0001) | — | yes |  |
| S2-R1 | +6.26 pp | [+5.04 pp, +7.48 pp] | <0.0001 | — | +6.24 pp (t 9.58, p <0.0001) | — | yes |  |

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| S2-R5 | Apr–May 2026 | 70 / 95 | +2.21 pp / -3.90 pp | +6.11 pp | yes |
| S2-R5 | Jul–Aug 2026 | 67 / 79 | +2.20 pp / -3.21 pp | +5.41 pp | yes |
| S2-R1 | Apr–May 2026 | 70 / 95 | +2.80 pp / -3.38 pp | +6.18 pp | yes |
| S2-R1 | Jul–Aug 2026 | 67 / 79 | +2.39 pp / -3.95 pp | +6.34 pp | yes |

#### Secondary S3 (T2; raw p, no decision)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| S3-R5 | +4.89 pp | [+3.09 pp, +6.67 pp] | <0.0001 | — | +4.89 pp (t 4.57, p <0.0001) | — | yes |  |
| S3-R1 | +5.35 pp | [+3.63 pp, +6.87 pp] | <0.0001 | — | +5.35 pp (t 7.04, p <0.0001) | — | yes |  |

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| S3-R5 | Jul–Aug 2026 | 122 / 84 | +0.53 pp / -4.36 pp | +4.89 pp | yes |
| S3-R1 | Jul–Aug 2026 | 122 / 84 | +1.45 pp / -3.90 pp | +5.35 pp | yes |

#### Secondary S4 (T2; raw p, no decision)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| S4-R1 | +0.364 | [+0.322, +0.403] | <0.0001 | — | +0.363 (n 1478) | — | yes |  |
| S4-R5 | +0.272 | [+0.216, +0.323] | <0.0001 | — | +0.272 (n 1475) | — | yes |  |

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| S4-R1 | Apr–May 2026 | 728 | — | +0.365 | yes |
| S4-R1 | Jul–Aug 2026 | 750 | — | +0.364 | yes |
| S4-R5 | Apr–May 2026 | 725 | — | +0.273 | yes |
| S4-R5 | Jul–Aug 2026 | 750 | — | +0.271 | yes |

#### Secondary S5 (T2; raw p, no decision)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| S5a-noliq-R5 | +5.03 pp | [+3.72 pp, +6.23 pp] | <0.0001 | — | +4.85 pp (t 6.88, p <0.0001) | — | yes |  |
| S5a-noliq-R1 | +5.10 pp | [+4.06 pp, +6.20 pp] | <0.0001 | — | +4.95 pp (t 10.28, p <0.0001) | — | yes |  |
| S5b-unwins-R5 | +6.40 pp | [+4.42 pp, +8.15 pp] | <0.0001 | — | +6.22 pp (t 6.78, p <0.0001) | — | yes |  |
| S5b-unwins-R1 | +5.78 pp | [+4.37 pp, +7.06 pp] | <0.0001 | — | +5.64 pp (t 9.17, p <0.0001) | — | yes |  |

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| S5a-noliq-R5 | Apr–May 2026 | 124 / 178 | +2.44 pp / -2.88 pp | +5.31 pp | yes |
| S5a-noliq-R5 | Jul–Aug 2026 | 144 / 111 | +0.83 pp / -3.92 pp | +4.74 pp | yes |
| S5a-noliq-R1 | Apr–May 2026 | 126 / 178 | +2.27 pp / -2.52 pp | +4.78 pp | yes |
| S5a-noliq-R1 | Jul–Aug 2026 | 144 / 111 | +1.77 pp / -3.64 pp | +5.42 pp | yes |
| S5b-unwins-R5 | Apr–May 2026 | 95 / 107 | +3.55 pp / -3.66 pp | +7.21 pp | yes |
| S5b-unwins-R5 | Jul–Aug 2026 | 106 / 76 | +0.71 pp / -4.87 pp | +5.58 pp | yes |
| S5b-unwins-R1 | Apr–May 2026 | 95 / 107 | +2.57 pp / -3.05 pp | +5.61 pp | yes |
| S5b-unwins-R1 | Jul–Aug 2026 | 106 / 76 | +1.59 pp / -4.36 pp | +5.95 pp | yes |

#### Secondary S6 (T2; raw p, no decision)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| S6-H2-surprise | +0.215 | [+0.169, +0.258] | <0.0001 | 0.0006 | +0.213 (n 2094) | — | yes |  |
| S6-H2-trend | +0.288 | [+0.241, +0.330] | <0.0001 | 0.0006 | +0.290 (n 2470) | — | yes |  |
| S6-H2-quality | +0.057 | [-0.021, +0.134] | 0.0751 | 0.1502 | +0.057 (n 755) | — | yes |  |
| S6-H3-tech_m1 | +0.071 | [+0.002, +0.142] | 0.0207 | 0.1242 | +0.059 (n 735) | 1.77 (0.0878) | no |  |
| S6-H3-oi_m1 | -0.007 | [-0.076, +0.066] | 0.5655 | 0.8691 | -0.008 (n 749) | -0.21 (0.5757) | no |  |
| S6-H3-past | +0.082 | [+0.015, +0.152] | 0.0085 | 0.0680 | +0.081 (n 719) | 3.65 (0.0177) | yes |  |
| S6-H3-trend_up | +0.065 | [-0.013, +0.145] | 0.0501 | 0.2004 | +0.066 (n 697) | 4.06 (0.0135) | yes |  |

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| S6-H2-surprise | Apr–May 2026 | 1027 | — | +0.216 | yes |
| S6-H2-surprise | Jul–Aug 2026 | 1067 | — | +0.214 | yes |
| S6-H2-trend | Apr–May 2026 | 1219 | — | +0.281 | yes |
| S6-H2-trend | Jul–Aug 2026 | 1251 | — | +0.295 | yes |
| S6-H2-quality | Apr–May 2026 | 5 | — | -0.289 | no |
| S6-H2-quality | Jul–Aug 2026 | 755 | — | +0.057 | yes |
| S6-H3-tech_m1 | Oct–Nov 2025 | 167 | — | +0.179 | yes |
| S6-H3-tech_m1 | Jan–Feb 2026 | 182 | — | +0.024 | yes |
| S6-H3-tech_m1 | Apr–May 2026 | 184 | — | -0.001 | yes |
| S6-H3-tech_m1 | Jul–Aug 2026 | 202 | — | +0.082 | yes |
| S6-H3-oi_m1 | Oct–Nov 2025 | 180 | — | +0.070 | yes |
| S6-H3-oi_m1 | Jan–Feb 2026 | 182 | — | -0.051 | yes |
| S6-H3-oi_m1 | Apr–May 2026 | 185 | — | +0.027 | yes |
| S6-H3-oi_m1 | Jul–Aug 2026 | 202 | — | -0.073 | yes |
| S6-H3-past | Oct–Nov 2025 | 167 | — | +0.131 | yes |
| S6-H3-past | Jan–Feb 2026 | 167 | — | +0.029 | yes |
| S6-H3-past | Apr–May 2026 | 184 | — | +0.104 | yes |
| S6-H3-past | Jul–Aug 2026 | 201 | — | +0.063 | yes |
| S6-H3-trend_up | Oct–Nov 2025 | 149 | — | +0.109 | yes |
| S6-H3-trend_up | Jan–Feb 2026 | 181 | — | +0.068 | yes |
| S6-H3-trend_up | Apr–May 2026 | 184 | — | +0.036 | yes |
| S6-H3-trend_up | Jul–Aug 2026 | 183 | — | +0.047 | yes |

#### Exploratory E1 (T2; raw p, no decision)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| E1-FnO-R5 | — | — | — | — | — | — | — | INSUFFICIENT |
| E1-FnO-R1 | — | — | — | — | — | — | — | INSUFFICIENT |
| E1-nonFnO-R5 | +6.31 pp | [+4.24 pp, +8.19 pp] | <0.0001 | — | +6.24 pp (t 6.63, p <0.0001) | — | yes |  |
| E1-nonFnO-R1 | +5.78 pp | [+4.31 pp, +7.09 pp] | <0.0001 | — | +5.69 pp (t 8.84, p <0.0001) | — | yes |  |

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| E1-FnO-R5 | Apr–May 2026 | 7 / 12 | +4.96 pp / +0.47 pp | +4.49 pp | no |
| E1-FnO-R5 | Jul–Aug 2026 | 16 / 6 | +0.66 pp / -2.93 pp | +3.59 pp | no |
| E1-FnO-R1 | Apr–May 2026 | 7 / 12 | +3.12 pp / -0.80 pp | +3.92 pp | no |
| E1-FnO-R1 | Jul–Aug 2026 | 16 / 6 | +1.15 pp / -3.45 pp | +4.60 pp | no |
| E1-nonFnO-R5 | Apr–May 2026 | 88 / 95 | +3.30 pp / -4.00 pp | +7.30 pp | yes |
| E1-nonFnO-R5 | Jul–Aug 2026 | 90 / 70 | +0.59 pp / -4.74 pp | +5.33 pp | yes |
| E1-nonFnO-R1 | Apr–May 2026 | 88 / 95 | +2.47 pp / -3.19 pp | +5.66 pp | yes |
| E1-nonFnO-R1 | Jul–Aug 2026 | 90 / 70 | +1.66 pp / -4.24 pp | +5.89 pp | yes |

#### Exploratory E2 (T2; raw p, no decision)

| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |
|---|---|---|---|---|---|---|---|---|
| E2-outlook | +0.324 | [+0.243, +0.404] | <0.0001 | — | +0.324 (n 356) | — | yes |  |
| E2-composite+outlook | +0.280 | [+0.176, +0.387] | <0.0001 | — | +0.280 (n 336) | — | yes |  |

| Test | Season | n | Group means (a / b) | Estimate | Eligible |
|---|---|---|---|---|---|
| E2-outlook | Jul–Aug 2026 | 356 | — | +0.324 | yes |
| E2-composite+outlook | Jul–Aug 2026 | 336 | — | +0.280 | yes |

#### T1 (§5 timing as registered) beside T2

| Test | T1 estimate | T1 p | T1 result | T2 estimate | T2 p | T2 result |
|---|---|---|---|---|---|---|
| H1-R5 | +4.38 pp | <0.0001 | PASS | +6.06 pp | <0.0001 | PASS |
| H1-R1 | +4.23 pp | <0.0001 | PASS | +5.60 pp | <0.0001 | PASS |
| H2 | +0.201 | <0.0001 | PASS | +0.251 | <0.0001 | PASS |
| H3 | +0.028 | 0.2270 | FAIL | +0.040 | 0.1455 | FAIL |
| H4 | +0.055 | 0.1312 | FAIL | +0.046 | 0.1559 | FAIL |
| S7-H1-R5 | +3.28 pp | 0.0010 | PASS | +4.78 pp | <0.0001 | PASS |
| S7-H1-R1 | +3.07 pp | <0.0001 | PASS | +3.99 pp | <0.0001 | PASS |
| S7-H2 | +0.186 | <0.0001 | PASS | +0.229 | <0.0001 | PASS |
| S7-H3 | +0.058 | 0.0908 | FAIL | +0.024 | 0.2625 | FAIL |
| S7-H4 | +0.059 | 0.1080 | FAIL | +0.063 | 0.0774 | FAIL |
| H5-STRONG-D5 | +0.37 pp | 0.0287 | FAIL | +0.42 pp | 0.0272 | FAIL |
| H5-STRONG-R5 | +2.36 pp | <0.0001 | PASS | +2.90 pp | <0.0001 | PASS |
| H5-WEAK-D5 | +0.28 pp | 0.9380 | FAIL | +0.06 pp | 0.6284 | FAIL |
| H5-WEAK-R5 | -1.26 pp | <0.0001 | PASS | -1.57 pp | <0.0001 | PASS |
| H5L-STRONG-D5 | +0.37 pp | 0.0270 | FAIL | +0.41 pp | 0.0304 | FAIL |
| H5L-STRONG-R5 | +2.35 pp | <0.0001 | PASS | +2.90 pp | <0.0001 | PASS |
| H5L-WEAK-D5 | +0.29 pp | 0.9467 | FAIL | +0.06 pp | 0.6283 | FAIL |
| H5L-WEAK-R5 | -1.53 pp | <0.0001 | PASS | -1.84 pp | <0.0001 | PASS |

#### Registered decisions (T2)

```json
{
 "verdict pills": {
  "registered": "PASS",
  "live_code": "PASS",
  "label": "early evidence; confirmation pending (Oct\u2013Nov 2026)"
 },
 "composite score": {
  "registered": "PASS",
  "live_code": "PASS",
  "label": "early evidence; confirmation pending (Oct\u2013Nov 2026)"
 },
 "upcoming ideas order": {
  "registered": "FAIL",
  "live_code": "FAIL",
  "label": "no measurable skill so far"
 },
 "declared ideas order": {
  "registered": "FAIL",
  "live_code": "FAIL",
  "label": "no measurable skill so far"
 },
 "results_strength_boost": {
  "registered_H5": {
   "STRONG": {
    "D5": "FAIL",
    "R5": "PASS",
    "points": 5,
    "reversed_flag": false
   },
   "WEAK": {
    "D5": "FAIL",
    "R5": "PASS",
    "points": 0,
    "reversed_flag": false
   }
  },
  "live_rule_H5L": {
   "STRONG": {
    "D5": "FAIL",
    "R5": "PASS",
    "points": 5,
    "reversed_flag": false
   },
   "WEAK": {
    "D5": "FAIL",
    "R5": "PASS",
    "points": 0,
    "reversed_flag": false
   }
  },
  "recommended": {
   "STRONG": 5,
   "WEAK": 0
  }
 },
 "harmful_components_provisional": []
}
```

T1 decisions, for comparison:

```json
{
 "verdict pills": {
  "registered": "PASS",
  "live_code": "PASS",
  "label": "early evidence; confirmation pending (Oct\u2013Nov 2026)"
 },
 "composite score": {
  "registered": "PASS",
  "live_code": "PASS",
  "label": "early evidence; confirmation pending (Oct\u2013Nov 2026)"
 },
 "upcoming ideas order": {
  "registered": "FAIL",
  "live_code": "FAIL",
  "label": "no measurable skill so far"
 },
 "declared ideas order": {
  "registered": "FAIL",
  "live_code": "FAIL",
  "label": "no measurable skill so far"
 },
 "results_strength_boost": {
  "registered_H5": {
   "STRONG": {
    "D5": "FAIL",
    "R5": "PASS",
    "points": 5,
    "reversed_flag": false
   },
   "WEAK": {
    "D5": "FAIL",
    "R5": "PASS",
    "points": 0,
    "reversed_flag": false
   }
  },
  "live_rule_H5L": {
   "STRONG": {
    "D5": "FAIL",
    "R5": "PASS",
    "points": 5,
    "reversed_flag": false
   },
   "WEAK": {
    "D5": "FAIL",
    "R5": "PASS",
    "points": 0,
    "reversed_flag": false
   }
  },
  "recommended": {
   "STRONG": 5,
   "WEAK": 0
  }
 },
 "harmful_components_provisional": []
}
```

## 5. Reading the results
- **H1 (verdict pills).** Results rated above trend outperformed those rated below by ~5–7 pp over the reaction, in
  both seasons, under both the registered formulas and the live code.
  - The result is robust to every registered check: no liquidity filter (S5a +5.0 pp), no winsorising (S5b +6.4 pp),
    the strict point-in-time band (S3 +4.9 pp), PAT alone (S2 +5.8 pp), and the calibration-free PAT surprise rank
    (S4 IC +0.27 on R5, +0.36 on R1).
  - The simple "last year unchanged" baseline shows the same pattern in all four seasons (S1 +4.3 pp, cross-season
    t 12.9).
  - The live code rates fewer names (its band-width cap): 48 / 74 and 80 / 48 tails against 95 / 107 and 106 / 76, with
    a slightly smaller gap.
  - F&O names alone are too few in the tails to test (E1: 7–16 per tail per season, "insufficient").
- **H2 (composite).** IC ≈ +0.25 in both seasons.
  - The trend component carries the most (S6 IC +0.29), more than the surprise (+0.22).
  - Quality is barely measurable: present for 5 results in Apr–May 2026 and 755 in Jul–Aug (see §7).
  - The registration did **not** test whether the 7-quarter baseline adds anything over simple YoY growth; the
    descriptive magnitudes (S1 vs H1) are similar. That is a question for a new registration, not a conclusion here.
- **H3 (upcoming order).** Per-season ICs +0.178, −0.033, +0.022, −0.007: one good season, then nothing. No measurable
  skill.
  - Of its parts, past reactions (+0.08, raw p 0.009) and the scanner's technical score (+0.07, raw p 0.02) lean
    positive. Neither survives Holm.
  - OI build-up, the largest weight at 30, is ≈ 0 (−0.007).
- **H4 (declared order → D5).** +0.066 and +0.026: positive but not significant. Two seasons of ~190 F&O names cannot
  detect an IC below ~0.14.
- **H5 (boost).**
  - STRONG names led unflagged results by +2.9 pp over R5 in every season, and by +0.4 pp in D5. The D5 lead was
    positive in all four seasons (+0.24 to +0.77 pp) but the Holm-adjusted p is 0.054, just above the bar.
  - WEAK names lagged by −1.6 pp over R5, but D5 shows no further lag (+0.06 pp).
  - The registered rule therefore gives STRONG +5 and WEAK 0, and the new live rule gives the same.
- **E2 (outlook, exploratory, not point-in-time).** The filing analysis has the highest IC of any input (+0.32 with R5,
  Jul–Aug 2026, n 356). It was generated in Oct 2026, so no decision can rest on it (see §7). It is a reason to start
  storing it point-in-time from now on.
- **T1 vs T2.** Every label is the same. With the corrected timing, H1 / H2 effects are larger (e.g. H1-R5 +4.38 →
  +6.06 pp), as expected when ~23 % of reaction sessions move one day earlier.

## 6. Data tests and reproducibility (all run this session)
- **Replay = live endpoint:** `parity_check.py` compared 12 evenly spaced primary-season meetings with the live DaaS
  `GET /v1/desk/events-calendar/expectation`. **12 / 12 match** on expected mid, filed value and `reliable`, for both PAT
  and revenue. The band is not compared (frozen calibration, §4.1).
- **Returns by hand from the warehouse (CUB, Jun 2026 quarter):**
  - T1: S = 29 Jul, R1 = 228.86 / 238.14 − 1 = −3.90 %, Nifty +1.10 % → R1x −5.00 %; R5x −18.02 %. Matches the dataset.
  - T2 (outcome filed 14:40 IST on 28 Jul): S = 28 Jul, R1 = 238.14 / 221.45 − 1 = +7.54 %, Nifty −0.04 % → R1x +7.58 %;
    R5x −10.83 %. Matches.
  - GABRIEL (T1) also matches.
- **Determinism:** the full study was run twice on each timing, at 18:36 / 18:38 IST and again at 19:54 IST after H5-L
  was added. F1, F7, F5 and every secondary family are byte-identical between the runs. The first runs' output was not
  read until after A3 (see the A3 note).
- **Statistics helpers:** the t-tail, Holm and Spearman functions were checked against known values before the run
  (t(1.96, ∞) 0.0250; t(2.0, 3) 0.0697; Holm 0.01 / 0.03 / 0.04 → 0.03 / 0.06 / 0.06).

## 7. Deviations from the registration, and limitations
**Deviations (all registered before results were seen, listed here as required):**
- A1: H5 added; S7 added; the label rule tightened (both the registered test and S7 must PASS).
- A2: T2 timing governs; T1 is reported beside it.
- A3: H5-L added; recommended points are the smaller in magnitude of H5 and H5-L.
- "Pooled D5 estimate" in A1.1's +5 rule was read as the registered statistic, the equal-weight mean over seasons
  (+0.42 pp). The Welch pooled difference (+0.61 pp) has the same sign, so the reading does not matter.

**Limitations:**
1. **Two seasons for the live method**, four for H3 / H5. Effects smaller than ~2.5 pp (H1) or IC ~0.07 (H2), ~0.10
   (H3) and ~0.14 (H4) are not detectable. "No measurable skill" is not "no effect".
2. **Contemporaneous outcome (§1 caveat).** R1 / R5 include the reaction, so they measure explanation, not tradable
   prediction. The live tracker also gets its figures from Trendlyne / Screener, sometimes a day or two after the
   filing, so on screen the verdict can trail the reaction it "explains".
3. **`broadcast_at` is not the first public filing** (A2). It trails the NSE outcome filing by a median 1.5 h and
   crosses the close for ~25 % of events. T2 fixes that with the outcome filing. An outcome filing about some other
   board item on the same day could occasionally set the time too early.
4. **Quality inputs are mostly missing.** Trendlyne rows carry no PBT, other income, exceptional items or tax:
   - the Dec 2025 and Mar 2026 quarters have them only on 1 and 12 Screener rows;
   - Jun 2026 has PBT on 1,319 Screener rows;
   - `exceptional_items_cr` is null everywhere.

   The quality component and the boost's red-flag veto are therefore close to untested. The live code reads the same
   data, so its quality flags are mostly "not checked".
5. **The technical part is a replay** (the scanner's base score B0 on adjusted bars, macro multiplier omitted). The
   live ideas read the stored final score, which cannot be replayed (`stock_technical_features` exists only for 23 / 26
   Oct).
6. **Untested later live changes.** The live ideas and OI rules changed after `9f78c6ee` (e.g. `315c54c8`: total-OI
   thresholds 0.5 % / 2 %, expiry-week handling, OI across months). S7 tests the `9f78c6ee` version only.
7. **The boost's filing-analysis fallback** (±5 when figures are not stored yet) is not tested.
8. **Outlook (E2) is not point-in-time.** The analyses were generated on 27 Oct 2026 (claude-sonnet-5-5, tools off and
   isolated) for filings from July–August. Training-data leakage cannot be ruled out from the record, and the model
   reads the results it scores.
9. **Values are the latest stored, not as first filed** (restatements are not tracked).
10. **Price returns only:** dividends are not added back (e.g. CUB went ex-dividend inside its window).
11. **Excess return is a simple difference vs the Nifty 50** (no beta, size or sector adjustment). Clustering is
    handled by date, not by sector.
12. **The band's scale uses same-season errors** (§4.1). S3, with a strict point-in-time band, gives the same result.

## 8. What happens next
- **Holdout run** on or after **2026-11-25**: Sep 2026 quarter results with complete windows, T2 timing, frozen bands
  and this code.
  - It confirms or withdraws "early evidence" for the verdict pills and the composite.
  - It re-tests the boost's D5 / R5: +5 stays only if it holds; any value that fails goes to 0.
  - It checks the sign of any component flagged by §9(b) (none is flagged).
- **Changes to the live screens implied by this study (owner's decision; not made here):**
  - the verdict pills and the composite: "early evidence (2 seasons), explains the results-day reaction; confirmation
    pending";
  - both ideas orders: "no measurable skill so far";
  - the boost: STRONG +10 → +5, WEAK −10 → 0.
- **Worth registering separately** (not concluded here): does the 7-quarter baseline add anything over plain YoY
  growth; does a post-reaction (D5) design have skill for the declared list; store the filing analysis point-in-time so
  the outlook can be tested.

Data file hashes (sha256):
- `quarters.csv` 68e990a7… · `calendar.csv` 468192c4… · `bars.csv` a5dc606b… · `nifty50.csv` 19562aaa… ·
  `niftybees.csv` 6b42d3aa… · `fno.csv` c872ed5a… · `outcome.csv` 4c622327… · `eaa.csv` 45e98298…
- outputs: `events_T2.csv` efe6c791… · `events_T1.csv` 9b8ced5e…
