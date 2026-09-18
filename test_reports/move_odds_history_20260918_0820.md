# Functionality Verification Report — Move odds: daily history with outcomes

- **Branch:** feat/tpd3-mvp (page + DaaS commits cherry-picked for staging)
- **Date:** 2026-09-18 (test cases authored 08:20 IST, before implementation)
- **Author:** Claude (full-stack developer + design engineer + QA)
- **Environment:** local unit + mocked Playwright first; staging after deploy go-ahead
- **Changed areas:** backend routes/services: yes (DaaS router + app proxy) · frontend src: yes

## Summary
User request 2026-09-18: a progressive day-by-day history of the published estimates — for each session, what was
predicted and how it turned out, stepped through with a date filter, with newly-promoted stocks colour-coded.
Owner choices (AskUserQuestion, same day): top 20 stocks per session; "new" = not in the previous session's top 20;
also track follow-through at T+3 and T+5.

**Data reality at build time:** two published v4 runs exist (target 2026-09-17 graded, 2026-09-18 pending tonight).
The view starts with one graded session and gains one per trading day. The 15/16 Sep forward-ledger rows are v2/v3,
a different model from the one the page serves, and are deliberately NOT shown here.

## Contract
**DaaS** `GET /v1/move-odds/history?head=p_up5_1d&model=v4&sessions=30&top=20` (internal plan only) →
`{data: {head, model, top_n, sessions: [{target_session, data_as_of, frozen_at, scored, base_rate, state: graded|pending,
summary: {touched, touch_rate, top_n_touched, top10_touched}, rows: [{rank, symbol, company_name, p, is_new,
outcome: {state, touched, move_pct, reference_close, within3, within5, sessions_available}}]}]}}`.
Outcome rule (verified to reproduce nidp.tpd_run_grades exactly on run 1): up5 high >= prev_close x 1.05, up10 x 1.10,
down5 low <= prev_close x 0.95, down10 x 0.90, on the target session; within3/within5 apply the same level to the
highest high (lowest low) of the target session plus the next 2 / 4 available sessions, measured from the SAME
reference close the prediction was made against. `is_new` is null when there is no previous published session.
**App** `GET /api/move-odds/history` behind `require_feature("move_odds")`, passthrough.
**V5** an [Estimates | History] toggle on the Move odds screen; History keeps the four head tabs, lists sessions
newest-first, and shows the selected session's top 20 with outcome columns and a legend for new entries.

## Test Cases
| ID | Area | Case | Expected | Verified by |
|---|---|---|---|---|
| TC-50 | DaaS | Shape and ordering | sessions newest-first; each has <= top rows, rank 1..N by estimate desc, symbol tiebreak | unit |
| TC-51 | DaaS | Outcomes match the official grade | for run 1 (2026-09-17) the derived per-stock outcomes reproduce tpd_run_grades: up5 86, up10 11, down5 7, down10 0 | unit + staging data test |
| TC-52 | DaaS | Ungraded session | a session whose prices are not in yet → state "pending", outcome fields null, never a fabricated result | unit |
| TC-53 | DaaS | New-entry flag | is_new true only for symbols absent from the previous session's top N; null on the earliest session | unit |
| TC-54 | DaaS | Partial forward window | within3/within5 report sessions_available and stay null while the window is incomplete | unit |
| TC-55 | DaaS | Gate and validation | non-internal plan 403; unknown head or out-of-range top 400 (the DaaS validation handler) | unit |
| TC-56 | App | Proxy + flag | no session 401; not allowlisted 403 feature_not_enabled; allowlisted passthrough unchanged | unit + staging |
| TC-57 | UI | History view | toggle switches panels; sessions newest-first; selecting a date shows its top 20; every shown % equals the API | Playwright mocked |
| TC-58 | UI | New-entry colour coding | new symbols carry the marker and a legend explains it; a symbol present in the previous session does not | Playwright mocked |
| TC-59 | UI | Pending + vocabulary | a pending session says grades are due, shows no outcome, and the D2 banned-word scan passes | Playwright mocked |
| TC-60 | UI | Mobile 390 px | the history table fits, no horizontal page scroll | Playwright mocked |
| TC-61 | Staging | Real API + UI | owner session: history endpoint 200 with the real graded 17 Sep session; the page renders it with matching numbers | staging curl + Playwright |

## API / Endpoint Tests (staging)
Deployed dev 4f3e6111 (pushed 08:34 IST). All four workflows success: nidp-stack-vm staging (the DaaS serving this
endpoint), app backend, app frontend, Android APK.

**Unit, before the push:** DaaS `pytest nidp/tests/services/test_daas_move_odds.py` → `17 passed` (TC-50..TC-55);
app `pytest tests/test_move_odds_routes.py tests/test_move_odds_diagnostics.py tests/test_move_odds_live.py --noconftest`
→ `29 passed` (TC-56). Re-run on the dev branch together: `46 passed`.

**Staging, real (08:47 IST), owner session via a private temp file, deleted after:**
```
HTTP 200
head p_up5_1d | top_n 5 | sessions 2

2026-09-18  state=pending  scored=997  base=0.0758222246503496
  summary: {'graded_rows': None, 'touched': None, 'touch_rate': None, 'top10_touched': None, 'top_n_touched': None}
   #1 SHAREINDIA    34.1%  is_new=True  touched=None  move=None within5=None avail=0
   #2 RATNAVEER     28.7%  is_new=False touched=None  move=None within5=None avail=0

2026-09-17  state=graded  scored=994  base=0.0758222246503496
  summary: {'graded_rows': 994, 'touched': 86, 'touch_rate': 0.08651911468812877, 'top10_touched': 3, 'top_n_touched': 2}
   #1 PNCINFRA      36.6%  is_new=None  touched=True  move=0.054596846176733216 within5=None avail=1
   #4 RATNAVEER     27.6%  is_new=None  touched=True  move=0.12292938099389716 within5=None avail=1
```
TC-51 on real data: the 17 Sep summary carries the official grade (86 of 994 touched, 3 of the top 10) and the
per-stock outcomes agree with it. TC-52: today's session is `pending` with every outcome field null and
`sessions_available: 0` — nothing invented. TC-53: `is_new` is null on 17 Sep, the earliest session held. TC-54:
`within5` null while only one session of prices exists.

## UI / Playwright Tests
**Mocked (local):** `npx playwright test e2e/tests/research-move-odds.spec.ts --project=desktop-chrome` → `24 passed`
(TC-57..TC-60 new, the other 20 unchanged). On the dev branch with research-access.spec.ts: `30 passed, 1 skipped`
(pre-existing skip); `npm run build` → `✓ built`.

**Real staging (08:51:21 IST), no mocks:**
```
history API → HTTP 200, 2 session(s): 2026-09-18(pending), 2026-09-17(graded)
  2026-09-18 (pending): 20 rows, 0 reached, new: SHAREINDIA, TEGA, ALOKINDS, MOTISONS, EXICOM, WHEELS, QUADFUTURE, VENUSPIPES, INDOTHAI, IFCI
  2026-09-17 (graded): 20 rows, 10 reached, new: none
same URL without a session → HTTP 401
  ✓  1 staging-move-odds-history.spec.cjs:12:1 › TC-61 history on the real page equals the live API (3.3s)
  1 passed (4.5s)
```
The spec walks every session and asserts, per row, that the shown estimate equals the API value to one decimal, that the
outcome cell equals the API's own state (reached / did not / pending), and that the new marker is present exactly when
`is_new` is true — so the 10 new names on 18 Sep are marked and the 17 Sep rows carry no marker at all. Date chips match
the API order, newest first. The D2 banned-vocabulary scan passes. Screenshot: staging-move-odds-history.png.

## Data Correctness (staging)
- The outcome rule was checked against the grader before any code was written: running it over run 1 reproduces
  nidp.tpd_run_grades exactly — up5 86, up10 11, down5 7, down10 0 of 994, all 994 symbols matched to price rows — and
  the top 10 shows the same 3 hits the grader recorded in `top10_hits`.
- 10 of the top 20 reached +5% on 17 Sep against a 7.6% base rate. That is one session and is not evidence of an edge;
  it is shown because it is what the published run actually did.
- `within3` / `within5` are dashes everywhere today because only one session of forward prices exists
  (`sessions_available: 1`). They fill in as sessions pass; an incomplete window never reads as a miss.
- Depth is two sessions (17 Sep graded, 18 Sep pending tonight) and grows by one per trading day. The 15/16 Sep
  forward-ledger rows are v2/v3, a different model, and are excluded rather than mixed in.

## Verdict: PASS
