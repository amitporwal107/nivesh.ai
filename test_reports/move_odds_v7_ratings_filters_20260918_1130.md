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
| TC-80 | DaaS | Session resolution + access | api (unit) | not_published → no rows; refusal for the expected session → 503 withheld; public-plan key → 403 || PASS (unit) |
| TC-81 | DaaS | Grades | unit | A ≥ 70, B 50–69.9, C < 50; `partial` when coverage < 80; symbol without a V3 row → grade null, not a default || PASS (unit) + 997/997 on staging data |
| TC-82 | DaaS | Sector rating | unit | median of coverage ≥ 80 scores in the sector, with n; sector with none → null || PASS (unit) + 22/22 on staging data |
| TC-83 | DaaS | Cap buckets | unit | LARGE/MID/SMALL/MICRO_CAP → Large/Mid/Small/Micro; null → null || PASS (unit) |
| TC-84 | DaaS | Ratio catalogue | unit | available iff ≥ 5% non-null and > 1 distinct; reasons for the rest; values aligned to `ratio_keys`; missing → null; dividend yield and pledge carry the zero-may-mean-missing note || PASS (unit) + 920/920 sampled values on staging |
| TC-85 | DaaS | 1-year return | unit | computed from adjusted closes 252 sessions apart; null with < 253 bars || PASS (unit) + 34/35 on staging (1 explained) |
| TC-86 | DaaS | Event categories | unit | every published (type, subtype) maps to a category; material = non-neutral; latest = max time; categories by count || PASS (unit) + 997/997 counts on staging |
| TC-87 | DaaS | Vocabulary | unit | the payload passes the DaaS banned-word scan || PASS (unit) |
| TC-88 | App | Proxy + gate | api (unit) | 403 when not allowlisted; 200 body passed through unchanged; 503 withheld with `detail`; 502 when DaaS is down || PASS (unit) + staging 401 unauth / 200 owner |
| TC-89 | UI | Rating columns | e2e mocked | each row shows the grade letter and score and the sector grade and score equal to the payload; partial marked || PASS |
| TC-90 | UI | Cap filter | e2e mocked | All / Large / Mid / Small / Micro filter the rows; the count updates || PASS |
| TC-91 | UI | Ratio panel | e2e mocked | groups and recent/preceding/historical columns render; live ratios selectable; no-data ratios disabled with their reason || PASS |
| TC-92 | UI | Ratio conditions | e2e mocked | `>` / `<` conditions filter correctly; rows without a value for an active condition are excluded and the count says how many || PASS |
| TC-93 | UI | Event categories | e2e mocked | a category keeps only stocks with it; Material / Latest reorder; the header states how many stocks have it || PASS |
| TC-94 | UI | Sortable columns | e2e mocked | Stock, rating, the larger estimate and Other way sort both ways with aria-sort, blanks last (v2 removed the Sec. rating / Up / Down / Events headers) || PASS |
| TC-95 | UI | Stock modal | e2e mocked | opens from a row; score, grade, both bars, six chips; no BUY/HOLD/SELL; kept sections present; Escape closes and focus returns; D2 scan passes with it open || PASS |
| TC-96 | UI | History columns | e2e mocked | Rating now and the sector grade shown (as of the scores date, said so); headers sort || PASS |
| TC-97 | UI | Profile failure | e2e mocked | estimates still render; rating cells "—" with a stated reason; filters needing the profile disabled || PASS |
| TC-98 | UI | Mobile 390 px | e2e mocked | no horizontal page scroll; modal fits the viewport || PASS (after fixing a clipping bug it exposed) |
| TC-99 | Staging | Real data | e2e staging | page cells equal the profile payload the page received; a sample equals the DB || PASS |
| TC-101 | UI (v2) | Hero | e2e mocked | lead names the stock with the largest estimate, its side and base-rate multiple; cards follow their stated rules with API numbers; the disclaimer sits above the hero; cards open the stock; D2 scan || PASS |
| TC-102 | UI (v2) | Row reading | e2e mocked | the big number = the larger estimate with its side, × base and "about 1 session in K" computed from the API; stays ink; table is five columns || PASS |
| TC-103 | UI (v2) | Leaner history | e2e mocked | six header cells (five + open); within-3 / within-5 kept on the move line; a row opens the stock || PASS |
| TC-100 | Data | Values are right | SQL | sampled ratios agree with their source rows; P/E agrees with market cap ÷ TTM profit within 10% for ≥ 90% of rows that have both; 1-year return recomputed independently || PASS on the definitional check; FAIL as first written (see Data) |

## API / Endpoint Tests (staging)
**Unit (local, this session):** `/opt/nidp/venv/bin/python -m pytest nidp/tests/services/test_daas_move_odds_profile.py
nidp/tests/services/test_daas_move_odds.py -q` → `26 passed, 7 warnings in 1.60s`;
`pytest backend/tests/test_move_odds_routes.py -q` → `12 passed in 0.55s` (`-k tc88` → `1 passed, 11 deselected`).

**Deploy:** dev `dd7fffdd` (11:55 IST) → all four workflows `completed success` (NIDP staging, app backend, frontend,
Android APK); dev `cc0e4e42` (12:11, frontend-only label-casing fix). No migration: the endpoint only reads.

**Deployed DaaS** (`nidp-daas-api-staging`, restarted 11:57 IST, called from inside with its own internal token):
```
HTTP 200 in 1.42 s | bad key -> 401 | latest 200
status final run 2026-09-18 2026-09-17 rows 997 scores_as_of 2026-09-16 features_as_of 2026-09-16 r1y window {'from': '2025-09-10', 'to': '2026-09-17'}
available ratios 24 of 44 | sectors 22
grades Counter({'C': 553, 'B': 429, 'A': 14, None: 1})
caps Counter({'Small': 434, 'Mid': 346, 'Large': 196, 'Micro': 13, None: 8})
same run as latest: True | rows match latest universe: True
```
**App proxy on staging:** `/api/move-odds/profile` → `401` without a session (route live; `/api/move-odds/nope` → 404).
With the owner's session (`auth/me` 200, aporwal107@gmail.com, move_odds true):
```
app /api/move-odds/profile 200 434801 bytes
status final rows 997 | identical to the DaaS payload: True
```

## UI / Playwright Tests
**Mocked (local, this session):** `npx playwright test e2e/tests/research-move-odds.spec.ts e2e/tests/research-access.spec.ts
--project=desktop-chrome` → `51 passed` (after cc0e4e42 too); `tsc --noEmit` exit 0; `npx vite build` → `✓ built`.
TC-89..TC-98 and TC-101..TC-103 are new; TC-22, TC-23, TC-24, TC-27, TC-33, TC-34/36, TC-71, TC-72, TC-74, TC-75, TC-76
were updated for the stock dialog and the v2 table. The mocked profile (`e2e/fixtures/move-odds-profile.json`) is cut
from the real 18 Sep payload and says so in its `_note`, with its three edits listed.

**Bug found by the tests and fixed before deploy:** at 390 px the page's single grid column grew to the 620 px table's
minimum width, so the hero cards, toolbar and ratio panel ran off the right edge; an ancestor clipped them, so the old
"document does not scroll sideways" assertion still passed. Fixed with `minmax(0, 1fr)` columns; TC-98 now also checks
that no element's right edge passes the viewport.

**Real staging (owner's session, no mocks), `staging-move-odds-v7.spec.cjs`:**
```
live run 2026-09-18: 997 rows · profile 997 rows, scores 2026-09-16, features 2026-09-16
profile the page received === DaaS payload fetched directly: rows, sectors, run
hero: INDIAGLYCO 68.7% down · both ways SHAREINDIA 34.1%/42.6% · filings SHAREINDIA 3 material
top 3 rows: INDIAGLYCO — 68.7% | AQYLON C 50.9% | AFCONS C 44.9%
table overflow at 1280px: 0px
filters: Large cap 196 · ROCE > 15% → 400 (123 without ROCE left out)
event category management: 88 stocks
history: 20 rows, 8 of the first 8 rating badges checked against the profile
  ✓  1 … TC-99 v7 + v2 against live data: hero, rows, ratings, filters, stock view, history (5.0s)
390px clipped elements: none
  ✓  2 … phone › TC-99 390px: nothing runs off the screen, the stock view fits (2.2s)
  2 passed (8.2s)
```
The spec checks the hero against its stated rules, the first ten rows' big / other / side / rating / sector grade, the
cap filter, a ROCE condition with its "left out" count, an event category, all six question chips, the D2 scan with the
stock dialog open and with the four questions unfolded, the history rating badges, and the table fit.
Found on the live page and fixed in `cc0e4e42`: category labels were lowercased ("m&a"), and suggested thresholds in
inactive condition chips looked like typed values.

**Re-run after `cc0e4e42` reached staging** (bundle `index-QMTdEkm_.js`, 12:18 IST; the spec now also asserts the hero's
category label keeps its casing):
```
hero: INDIAGLYCO 68.7% down · both ways SHAREINDIA 34.1%/42.6% · filings SHAREINDIA 3 material
table overflow at 1280px: 0px
filters: Large cap 196 · ROCE > 15% → 400 (123 without ROCE left out)
  ✓  1 staging-move-odds-v7.spec.cjs:30:1 › TC-99 v7 + v2 against live data: hero, rows, ratings, filters, stock view, history (5.8s)
390px clipped elements: none
  ✓  2 staging-move-odds-v7.spec.cjs:136:3 › phone › TC-99 390px: nothing runs off the screen, the stock view fits (3.0s)
  2 passed (10.0s)
```
**Superseded in part (12:14 IST):** the owner then asked for the pop-up to be the copilot chat's stock card, completely
unchanged (BUY/HOLD/SELL included). That change is verified in its own report, move_odds_stock_card_20260918_1220.md.

## Data Correctness (staging)
`tc100.py` compares the deployed DaaS payload with nidp_staging, computed independently of the endpoint's code:
```
run 2026-09-18 (run_id 3), 997 rows, scores 2026-09-16, features 2026-09-16
(a) quality: 997/997 match score (1 dp), grade band and partial flag; mismatches: []
(b) sector ratings: 22/22 medians and counts equal the recomputation; mismatches: []
(c) ratios: 920/920 sampled values (40 stocks x 23 ratios) equal stock_features_daily; mismatches: []
(d) 1-year return: 34 of 35 sampled stocks with a full year agree to 0.01 pt on their own calendar (window 2025-09-10 → 2026-09-17); others: [('SKFINDIA', 'own calendar differs', '2026-09-17', '2025-08-25', -68.6, '-65.95')]
(e) events: 997/997 stocks' event counts equal tpd_run_events for the run; mismatches: []
```
(d): SKFINDIA's own price history has gaps, so its 253rd own session is 25 Aug, not 10 Sep; both methods give about
−66% to −69%, which looks like an unadjusted corporate action rather than a real fall.

**P/E: the check as first written failed, and the criterion was wrong.** TC-100 asked for P/E within 10% of market
cap ÷ TTM profit for ≥ 90% of stocks. Result: `954 with both, 855 within 10% = 89.6%, 30 off by more than 50%` — FAIL
as written. Every outlier's stored P/E equals close ÷ TTM EPS exactly; the gap comes from the comparator: holding
companies (BAJAJFINSV, GRASIM, CHOLAHLDNG, BBTC) report total profit including minority interests, and some TTM profit
values look wrong (ZFCVINDIA implied 8.9 against 56.1). The definitional check: `958 of 958 stored P/Es = close ÷ EPS_TTM
within 1%`. The page shows NIDP's P/E faithfully. Two look implausible and are left as on record, not hidden:
SKFINDUS 0.04 (shown "0.0×") and KIRIINDUS 0.53, probably one-off gains inside EPS.

## Findings for the owner (not changed by this work)
1. **Today's top estimate rests on a bad input.** INDIAGLYCO leads the list and the hero at 68.7% down. Its model input
   "change over 5 sessions" is −79.1%, but NSE's closes give −19.9% (310.40 on 10 Sep → 248.70 on 17 Sep), and
   `prices_eod_adjusted` holds a single INDIAGLYCO row. It also has no V3 score, sector or cap on record.
2. **The v2 hero names three stocks.** Closer to a short list than D1 allowed; built as designed, with each card's rule
   and base-rate multiple stated.
3. `return_252d_pct` in stock_features_daily is wrong (hence the page computes 1-year return itself); P/E < 1 rows above.

## Inputs required from user
- A staging session token (received 12:07 IST, used for TC-99, then deleted from the scratchpad).

## Verdict: PASS
