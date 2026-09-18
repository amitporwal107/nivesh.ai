# Functionality Verification Report — Move odds v7 + v2 design: ratings, cap and ratio filters, event categories, stock modal, hero

- **Branch:** feat/move-odds-v7 (off origin/dev 5128f5d3)
- **Date:** 2026-09-18 (TC-80..TC-100 authored ~11:30 IST before implementation; TC-101..TC-103 written with the v2 changes after the v2 design arrived at 11:33)
- **Author:** Claude (design engineer + full-stack developer + QA)
- **Environment:** staging (staging.niveshcopilot.com / nidp_staging)
- **Changed areas:** backend routes/services: yes (DaaS router + app proxy) · frontend src: yes (MoveOddsScreen)

## Summary
The owner's new design ("Move Odds standalone", continuation of the stock-analysis-rankings PRD, whose core rule is to
keep *movement probability* apart from *investment quality*) puts each stock's quality next to its move odds: a stock
rating and a sector rating per row, market-cap and ratio filters, event-category filters, and a stock modal with
question chips.

Owner decisions (AskUserQuestion, 2026-09-18 ~11:20 IST):
1. **Scores only.** The modal shows the quality score, the fundamentals and technicals bars and "What stands out". No
   BUY/HOLD/SELL row; the first chip is "Quality in brief", not "Worth buying now?". D2 unchanged.
2. **Kept features stay, inside the modal.** Four estimates, inputs on record, events, the five hourly checks and the
   paper trade become modal sections; the Live column keeps the entry-signal pill and paper indicator.
3. **Deploy approved** once local tests pass (DaaS staging workflow + dev push).

Rule kept although the design moved it: the disclaimer stays above the numbers (C4), not at the foot of the aside.

**v2 design** (`docs/Move Odds v2 standalone (1).html`, received 11:33 IST mid-build, "refine the screen to v2"). Diffed
against the v7 template; the changes are a hero (one sentence + three stock cards: highest odds, cuts both ways, most
material filings), the four questions folded behind "What this does and doesn't tell you", a five-column table
(Stock · rating | Chance of a N% touch = the larger estimate with its side, × base and "about 1 session in K" | Other way
| Live | ›), a leaner history (sector grade and within-3/5 folded into the stock and move cells), and the side panels
wrapping instead of a fixed column. Built as designed except where it would break a rule already agreed:
- the big number, its bar and the direction pill stay **ink** (the design colours them mint/red/indigo by direction;
  kept rule from v7: direction is a reading, not a forecast);
- the big number is labelled with its **side** ("upside · …"/"downside · …") and the caption says it is the larger of
  the two estimates, because "Chance of a 5% touch" alone reads like a combined probability no model produces;
- the "Chance of a N% touch" header sorts by that larger figure (the design's handler sorted by the up estimate);
- the history keeps within-3 / within-5 (requested this morning) on the move line instead of dropping them;
- **flag for the owner:** the hero names three stocks. That is closer to a short list than spec D1 ("no short-list
  cut") allowed; built because it is the owner's design, and each card states its rule and base-rate multiple.
- v6's "both directions at equal size" check (TC-71) is superseded by the design: the larger now leads.

## Contract
New, read-only, internal-plan: `GET /v1/move-odds/profile?model=v4` → app `GET /api/move-odds/profile` (move_odds flag).
Resolves the session exactly as `/latest` does (not_published → no rows; refusal → 503 withheld). For the published
run's universe it returns, per symbol, values as of the run's `data_as_of` (each block carries its own as-of date):

- **Rating** = V3 quality score (`nidp.v3_stock_scores_daily`, latest row ≤ data_as_of): grade **A ≥ 70, B 50–69.9,
  C < 50**; `partial` when quality input coverage < 80%. Fundamentals and technicals composites from
  `quality_components`. No score → null, never a default.
- **Sector rating** = median quality score of the sector's scored stocks with coverage ≥ 80% on the same score date,
  with its count; same grade bands. No such stock → null.
- **Cap** = `market_cap_bucket` → Large / Mid / Small / Micro; null stays null.
- **Ratios** from `nidp.stock_features_daily` (latest row ≤ data_as_of; TTM sales/profit fields from
  `v_stock_fundamentals_latest` took 11.5 s, so they are listed as "held in NIDP but not served on this page yet"), plus
  **1-year return computed here** from `prices_eod_adjusted` over 252 sessions (only with ≥ 253 bars) because the
  stored `return_252d_pct` matches neither the raw nor the adjusted 252-session change (TATACHEM stored +3.2% vs
  −22.6% computed, 2026-09-16). A ratio is *available* iff non-null for ≥ 5% of the universe and > 1 distinct value
  (the metric-registry rule). Unavailable ratios are listed with a reason and cannot be selected.
- **Events** from the run's `tpd_run_events`: categories mapped from (type, subtype) onto the classifier's category
  names; *material* = classified positive, negative or mixed; latest event time.

## Test Cases
| ID | Area | Case | Type | Expected | Result |
|---|---|---|---|---|---|
| TC-80 | DaaS | Session resolution + access | api (unit) | not_published → no rows; refusal for the expected session → 503 withheld; public-plan key → 403 | |
| TC-81 | DaaS | Grades | unit | A ≥ 70, B 50–69.9, C < 50; `partial` when coverage < 80; symbol without a V3 row → grade null, not a default | |
| TC-82 | DaaS | Sector rating | unit | median of coverage ≥ 80 scores in the sector, with n; sector with none → null | |
| TC-83 | DaaS | Cap buckets | unit | LARGE/MID/SMALL/MICRO_CAP → Large/Mid/Small/Micro; null → null | |
| TC-84 | DaaS | Ratio catalogue | unit | available iff ≥ 5% non-null and > 1 distinct; reasons for the rest; values aligned to `ratio_keys`; missing → null; dividend yield and pledge carry the zero-may-mean-missing note | |
| TC-85 | DaaS | 1-year return | unit | computed from adjusted closes 252 sessions apart; null with < 253 bars | |
| TC-86 | DaaS | Event categories | unit | every published (type, subtype) maps to a category; material = non-neutral; latest = max time; categories by count | |
| TC-87 | DaaS | Vocabulary | unit | the payload passes the DaaS banned-word scan | |
| TC-88 | App | Proxy + gate | api (unit) | 403 when not allowlisted; 200 body passed through unchanged; 503 withheld with `detail`; 502 when DaaS is down | |
| TC-89 | UI | Rating columns | e2e mocked | each row shows the grade letter and score and the sector grade and score equal to the payload; partial marked | |
| TC-90 | UI | Cap filter | e2e mocked | All / Large / Mid / Small / Micro filter the rows; the count updates | |
| TC-91 | UI | Ratio panel | e2e mocked | groups and recent/preceding/historical columns render; live ratios selectable; no-data ratios disabled with their reason | |
| TC-92 | UI | Ratio conditions | e2e mocked | `>` / `<` conditions filter correctly; rows without a value for an active condition are excluded and the count says how many | |
| TC-93 | UI | Event categories | e2e mocked | a category keeps only stocks with it; Material / Latest reorder; the header states how many stocks have it | |
| TC-94 | UI | Sortable columns | e2e mocked | Stock, rating, the larger estimate and Other way sort both ways with aria-sort, blanks last (v2 removed the Sec. rating / Up / Down / Events headers) | |
| TC-95 | UI | Stock modal | e2e mocked | opens from a row; score, grade, both bars, six chips; no BUY/HOLD/SELL; kept sections present; Escape closes and focus returns; D2 scan passes with it open | |
| TC-96 | UI | History columns | e2e mocked | Rating now and the sector grade shown (as of the scores date, said so); headers sort | |
| TC-97 | UI | Profile failure | e2e mocked | estimates still render; rating cells "—" with a stated reason; filters needing the profile disabled | |
| TC-98 | UI | Mobile 390 px | e2e mocked | no horizontal page scroll; modal fits the viewport | |
| TC-99 | Staging | Real data | e2e staging | page cells equal the profile payload the page received; a sample equals the DB | |
| TC-101 | UI (v2) | Hero | e2e mocked | lead names the stock with the largest estimate, its side and base-rate multiple; cards follow their stated rules with API numbers; the disclaimer sits above the hero; cards open the stock; D2 scan | |
| TC-102 | UI (v2) | Row reading | e2e mocked | the big number = the larger estimate with its side, × base and "about 1 session in K" computed from the API; stays ink; table is five columns | |
| TC-103 | UI (v2) | Leaner history | e2e mocked | six header cells (five + open); within-3 / within-5 kept on the move line; a row opens the stock | |
| TC-100 | Data | Values are right | SQL | sampled ratios agree with their source rows; P/E agrees with market cap ÷ TTM profit within 10% for ≥ 90% of rows that have both; 1-year return recomputed independently | |

## API / Endpoint Tests (staging)
_pending_

## UI / Playwright Tests
_pending_

## Data Correctness (staging)
_pending_

## Inputs required from user
- none so far

## Verdict: BLOCKED
