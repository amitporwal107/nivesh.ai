# Functionality Verification Report — Desk results expectation (frontend)

- **Branch:** feat/desk-results-expectation (worktree /home/deploy/nivesh-desk-expect)
- **Date:** 2026-10-21
- **Author:** Claude (Full-stack developer, frontend fork)
- **Environment:** production build, every `/api/*` route-mocked (no staging backend exists for the new route yet)
- **Changed areas:** backend routes/services: no (backend fork, separate) · frontend src: yes

## Summary
A RESULTS EXPECTATION section in the desk Events tab for stock RESULTS events: the event panel, the timeline's expanded row and the phone sheet.
Upcoming results show the baseline range built from the company's own published quarters; declared results show the filed figure next to it.
Reads `GET /api/markets/events-calendar/expectation?symbol=&date=`. Honesty rules are part of the acceptance criteria (below).
Test cases authored before implementation, from the contract and the design rules.

## Contract read by the UI
`{ symbol, event_date, period_end, period_label, basis, status:'upcoming'|'declared', metrics:[{key,unit,expected:{low,mid,high}|null, same_quarter_last_year, previous_quarter, trend_yoy_pct, filed:{value,broadcast_at,audit_status}|null, vs_mid_pct|null, reliable, note}], method:{name,formula,n_quarters,backtest:{n_quarters,median_abs_err_pct,within_band_pct},universe_backtest:{n,median_abs_err_pct,within_band_pct}}, evidence:[{date,title,category,source,url}], gaps:[] }`

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-E1 | Upcoming, panel | Open an upcoming RESULTS chip: the request carries `symbol` and the event `date` | e2e | One call to `/events-calendar/expectation` with `symbol=TCS&date=...` | PASS |
| TC-E2 | Upcoming, labels | Section label reads `NIVESH BASELINE FROM PUBLISHED RESULTS · NOT A CONSENSUS · NOT A FORECAST`; period label and basis shown | e2e | Exact label text, period, basis | PASS |
| TC-E3 | Upcoming, range | A reliable metric shows low–high with the mid, last-year same quarter, previous quarter and YoY trend | e2e | Figures formatted in ₹ crore / ₹ per the unit, worked out from the payload | PASS |
| TC-E4 | Track record | The method's track record sits inside the same metric/section as the range: stock line ("within its band in X of N quarters") and all-stocks line | e2e | X = round(pct × n / 100); both lines present | PASS |
| TC-E5 | No track record | `backtest` null or n 0: the line says there is no track record for this stock instead of omitting it | e2e | Explicit "no track record" text | PASS |
| TC-E6 | Unreliable metric | `reliable:false` or `expected:null`: "No reliable expectation" plus the backend note, no number range | e2e | Note shown, no range testid | PASS |
| TC-E7 | Declared | `status:'declared'` shows the FILED value beside the range and says inside / above / below the baseline range with the pct vs mid | e2e | Position word and `vs_mid_pct` | PASS |
| TC-E8 | Declared, no beat/miss | No "beat", "miss", "bullish", "bearish", "surprise" wording anywhere in the section | e2e | Text does not match | PASS |
| TC-E9 | Audit status | `audit_status` null shows "audit status not recorded"; a value is shown exactly as sent and "unaudited" never appears unless the API sent it | e2e | Both cases | PASS |
| TC-E10 | Evidence | Evidence rows show date, title, category, source; links open in a new tab with `rel` containing noopener; no sentiment colouring; a non-http(s) url is not a link | e2e | Attributes checked | PASS |
| TC-E11 | Evidence empty | Empty evidence says so | e2e | Empty-state text | PASS |
| TC-E12 | Gaps | `gaps[]` shown as written | e2e | Text present | PASS |
| TC-E13 | Failure | Expectation route 502: error line with Retry; the price-history block and the rest of the panel still render | e2e/failure | Error visible, history still visible | PASS |
| TC-E14 | Loading | While the call is pending a loading block shows | e2e | Loading testid visible | PASS |
| TC-E15 | Not RESULTS | Dividend/bonus events make no expectation call and show no section | e2e | Zero calls, no section | PASS |
| TC-E16 | Timeline | Expanding a RESULTS row in the timeline shows the same section in place | e2e | Section inside the row | PASS |
| TC-E17 | Phone | The phone sheet shows the section; no sideways scroll | e2e (390px) | Section visible, scrollWidth ≤ clientWidth | PASS |
| TC-E18 | Contract drift | Malformed payload shows the error state, not wrong numbers | e2e/failure | Error visible | PASS |
| TC-E19 | Regression | The existing Events and Macro specs and the desk specs still pass; `tsc --noEmit` clean | e2e/tsc | 0 failed | PASS |

## Acceptance (honesty) rules
1. Never "beat", "miss", "bullish", "bearish". 2. Always a track record beside the range. 3. Unreliable → words, not numbers. 4. Audit status only as the API states. 5. Evidence = linked sources, no sentiment.



## UI / Playwright Tests (real output, docker, production build, mocked API)
- **New spec:** `frontend-v5/e2e/tests/copilot-app-desk-expectation.spec.ts` — `12 passed (11.0s)` (TC-E1/E2/E3/E4, E5, E6, E7/E8/E9, E10/E11, E12, E13, E14, E15, E16, E17 phone, E18).
- **tsc:** `npx tsc --noEmit -p tsconfig.json` → exit 0 (run twice, before and after the spec).
- **Whole desk suite** (`playwright test --config pw.copilot-app.config.ts desk`): `16 skipped, 318 passed (5.8m)`, 0 failed; the skips are in other desk specs (strategy-graphs etc.), not in the Events specs.
- **Screenshots looked at:** desktop declared (range bar, midpoint tick, amber ring beyond the range, "Above the baseline range · +6.4% vs midpoint", "UNAUDITED · FILED 2026-10-14 17:42"), phone sheet (390px, no sideways scroll). Desktop upcoming and timeline captured, not separately viewed. Git-ignored under `frontend-v5/e2e/screenshots/desk-expectation/`.

## Rework against the real router (backend 78f2993e), real output
Read `backend/nidp/services/daas_api/routers/desk_expectation.py` and aligned the UI and the mocks to its real shape:
- **Per-metric track record:** the all-stocks line comes from `method.by_metric[key]` (EPS follows profit); `method.universe_backtest` is PAT-only and is no longer used under revenue. The sample size is `within_band_n`; the median error is shown beside the naive "last year's quarter repeated" benchmark; the latest-quarter check is shown as a small sample. The stock's own record (profit-only in the backend) appears under profit and EPS; revenue says "not tested separately".
- **New honesty fields:** `label`, `compared_with` ("vs Nivesh baseline, not vs consensus", beside every filed-vs-range), `audit_basis` (under the audit status), `last_year_note`, per-metric `within_band` (preferred over inferring inside/outside; above/below is then read off low/high), `expected_as_of` ("using only what was published before …"), `sources`, `backtest.note`; a 404 says no results meeting is on file.
- **Units:** the API's "₹ crore" and "₹ a share" are formatted (₹ crore / ₹ per share).
- **Other keys:** every key `events-data.ts` reads for the calendar, history, macro calendar and macro history was checked against `desk_events.py` / `desk_macro.py` output: none missing.
- New/changed cases: TC-E4 (per-metric, no leakage across metrics), TC-E5b (band not yet checked), TC-E9b/E9c (audit "not recorded" / "mixed"), TC-E20/E20b (within_band precedence and fallback), TC-E21 (404). Mock shape = real shape.

Real output (docker, production build, mocked API): `tsc --noEmit` rc 0; `playwright test desk-expectation desk-events desk-macro` → `40 passed (30.3s)` (expectation 18, events 10, macro 12). One run first failed on a stale expectation of mine in TC-E10 (the mock's category/source wording); fixed the assertion and re-ran green. The whole-desk run (318 passed, 0 failed) pre-dates this rework and was not repeated.

## Not verified
- No call to the real `/api/markets/events-calendar/expectation` route (not deployed): the UI now matches the router's code and the mocks match its shape, but no real response has been seen.
- Real data, Investor wording, light mode, months other than October.
- Pre-existing, not touched: the Events headline says "1 companies report results" (no singular form).

## Verdict: IN PROGRESS
Mocked-API specs pass; nothing here has run against the real backend or staging.
