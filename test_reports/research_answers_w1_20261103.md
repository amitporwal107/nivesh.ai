# Functionality Verification Report: Research Copilot W1 (five research answers), round 2

- **Branches:**
  - **Round 1:** `feat/research-answers-w1` was merged as **#458** at 101b98b4 (owner, 2 Nov 22:42 UTC) and deployed to staging (backend container restarted 22:46 UTC).
  - **Round 2 (this report):** `feat/research-answers-w1-r2`, from origin/dev 19d8d974, code at 5f70e2bc. It carries the owner's 3 Nov rules and the fixes to defects found in the deployed round 1.
- **Date:** 2026-11-03
- **Author:** Claude (Full stack developer + QA engineer; domain and SEBI-wording review)
- **Environment:** staging. Branch code ran in-process inside `nivesh-staging-app-backend` from a scratch copy, against the live staging DaaS and the NIDP warehouse, read-only. Nothing was deployed or restarted. The scratch copy was deleted after each run.
- **Changed areas:** backend services: yes · CI workflow allowlist: yes · DaaS router: no (round 1's route is live) · frontend src: **no**
- **Test cases:** `test_reports/research_answers_w1_TESTCASES.md`. Written before round 1; TC-B10, TC-P1, TC-P2 and TC-CI were added on 3 Nov for the owner's rules.

## Summary

Round 1 (#458) added five deterministic visual answers: `financial_trend`, `valuation_view`, `ownership_trend`, `peer_compare` and `company_risks`. It also fixed the research-thesis routing bug and added the cash-flow DaaS route. Round 2 adds the following.

1. **Compliance wording** (owner, 3 Nov: "do not use words like buy, stop loss, target").
   - "Which FIIs entered or exited" now reads "Which FIIs started or ended a holding".
   - The output lint covers buy, sell, hold, target, price target, stop loss / SL, entry, exit, accumulate, book profit, upside, downside, multibagger, "should invest", recommend, pick, cheap, expensive, and under- and overvalued.
   - It runs over every string the answers show, the facts lines the explanation reads, and the research suggestion templates.
   - The stock analyst receives a `WORDING_RULE` with the facts of these five answers.
   - Question-reading regexes are unchanged.
2. **Production data** (owner, 3 Nov: TrueData only on staging; "on prod please use our snapshot data"). With no cash-flow rows and null TrueData balance-sheet columns, the cash, liquidity and leverage checks say "Not in our data". No figure from them appears, nothing is estimated, and nothing crashes.
3. **CI.** The workflow's own allowlist was run on this branch and on untouched origin/dev in the same image. The three failures are identical and pre-existing. `tests/test_copilot_research_answers.py` was added to the allowlist.
4. **Defects in the deployed round 1, found on staging data and fixed:**
   - **Fund-house path.** The reader called `/v1/smart-money/amc`, which does not exist (the router is under `/desk`). So every ownership answer on staging says "the data platform does not serve the fund-house view yet (HTTP 404)", which is false. It now calls `/v1/desk/smart-money/amc`.
   - **Fund-house double count.** That view sums every plan of a scheme, about 2× the filing for all 9 sample companies. Its figures are now shown only when they agree with the company's shareholding filing.
   - **Balance-sheet provenance.** An untagged balance-sheet row no longer names the P&L row's provider.

**Correction to round 1's report and PR #458:** they said `/smart-money/amc` "is not live on the running DaaS". That was wrong. The path was mine and it was wrong; the route itself exists under `/desk`.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-R1 | routing | 101 owner questions × 3 fillers; with thread stock TCS; with no company and no thread (on the new dev base) | unit | 100% | **PASS**: 303/303, 101/101, 101/101 |
| TC-R2…R6 | routing | Thesis not trade_validity; ownership trend vs event; thread stock; market-wide; multi-company; acronyms | unit | as stated | **PASS** |
| TC-R7 | regression | 9 existing Copilot/suggestions suites (on dev 19d8d974 + this branch) | unit | all pass | **PASS**: 687 passed |
| TC-B1…B6, B8, B9 | builders | As in round 1 (trend, valuation, ownership, peers, risk checks, freshness, registration, failure) | unit | as stated | **PASS** |
| TC-B3+ | ownership (new) | Fund-house reader calls `/desk/smart-money/amc`; figures hidden when the total disagrees with the filing (notice gives both numbers); read failure → named missing source | unit + real data | as stated | **PASS**: 9 of 9 real companies hidden with the notice; TIMEX has no fund-house holding |
| TC-B5+ | risk checks (new) | An untagged balance-sheet row reads "provider not recorded on the row" | unit | as stated | **PASS** |
| TC-B7 / TC-B10 | compliance | Extended word list × 6 data variants × 6 answers; facts lines; suggestion templates; lint self-test; `WORDING_RULE` in the facts | unit + real data | 0 hits | **PASS**: unit; 0 hits over 96 real payloads + facts |
| TC-P1 | production data | No cash flow, null balance-sheet columns: 8 checks "Not in our data", no figure from them | unit + real data | as stated | **PASS** |
| TC-P2 | production data | The other answers valid; computed ROE blank | unit | as stated | **PASS** |
| TC-D1 | DaaS | Round 1's route: SQL columns, cash-flow handler | unit | as stated | **PASS**; and now live (below) |
| TC-CI | CI | The workflow's own allowlist, branch vs untouched origin/dev, same image | unit | identical pre-existing failures | **PASS**: 3 = 3 |
| TC-S1…S4 | real data | Live DaaS, route SQL, production shape; warehouse spot checks; gap honesty | api (in-process) + data | valid, matching | **PASS** |
| TC-S5 | live chat | The five questions asked as a signed-in user in staging chat | e2e | real answers | **BLOCKED**: staging runs round 1; round 2 needs merge + deploy, and a signed-in session is needed |

## API / Endpoint Tests (staging)

**The live staging DaaS now serves round 1's route.** Read-only, through the running backend's own `daas_client`, 3 Nov:

```
GET /v1/financials/TCS/cashflow -> 200 [('2026-03-31', 52094.0, -4078.0, 'truedata'), ('2025-03-31', 48908.0, -3937.0, 'truedata')]
GET /v1/financials/TCS -> 200 {'period_end': '2026-09-30', 'source': 'screener_in', 'current_assets_cr': 143509.0, 'current_liabilities_cr': 57887.0, 'trade_receivables_cr': 69028.0, 'bs_truedata': True}
GET /v1/smart-money/amc?symbol=TCS -> 404 None None
GET /v1/desk/smart-money/amc?symbol=TCS -> 200 2026-09-01 2026-08-01 count 11 totals {'amcs': 11, 'schemes': 658, 'schemes_up': 148, 'schemes_dn': 224, 'pct_of_equity': 11.61} …
GET /v1/desk/smart-money/amc?symbol=RADICO -> 200 2026-09-01 2026-08-01 count 10 totals {'amcs': 10, 'schemes': 332, …, 'pct_of_equity': 45.64} …
GET /v1/desk/smart-money/amc?symbol=TIMEX -> 200 2026-09-01 2026-08-01 count 0 …
```

**Deployed round-1 code on staging** (in-process, `/app/backend`, read-only):
```
Has promoter holding of TCS increased? -> ownership_trend | missing: ['Mutual-fund holdings by fund house (nidp.mf_holdings_deltas): the data platform does not serve the fund-house view yet (HTTP 404)'] | …
What are the biggest risks for TCS? -> company_risks | missing: [] | None of the 13 checks that could run is flagged for TCS.
```

**Round-2 branch code, real-data check.** Command:
```
sudo docker exec -w /tmp/research_w1_backend -e PYTHONPATH=/tmp/research_w1_backend nivesh-staging-app-backend python /tmp/research_w1_realcheck.py
```

Modes:
- **S1:** live DaaS.
- **S2:** the route SQL run on the warehouse via `nidp-psql.sh`.
- **P:** production shape (S2 rows with the TrueData balance-sheet columns null, no cash-flow rows).

Final run (54 S1 + 21 S2 + 21 P builds):
```
S1 | Has promoter holding of TCS increased?     | ownership_trend:TCS | valid=True | missing=0 | TCS at Sep 26, percent of shares: Promoters 71.77% (±0.00 pp); FIIs 9.01% (−0.06 pp); DIIs 13.57% (+0.16 pp) …
S1 | What are the biggest risks for TCS?        | company_risks:TCS   | valid=True | missing=0 | None of the 13 checks that could run is flagged for TCS.
S1 | What are the biggest risks for ADANIPORTS? | company_risks:ADANIPORTS | valid=True | missing=0 | 1 of the 13 checks that could run is flagged for ADANIPORTS: Current ratio.
S1 | What are the biggest risks for ITC?        | company_risks:ITC   | valid=True | missing=0 | 2 of the 11 checks that could run are flagged for ITC: EBITDA margin trend; Piotroski F-score.
P  | What are the biggest risks for TCS?        | company_risks:TCS   | valid=True | missing=0 | None of the 5 checks that could run is flagged for TCS; 8 could not run for lack of data.
COMPLIANCE LINT over 96 real payloads + facts: 0 hits []
TOTAL builds: 96 contract problems: 0 max secs: 3.39
```

**Fund-house cross-check on real data.** Every company in the sample with fund-house holdings was hidden, with a notice:

| Company | Disclosed total | Filing (Sep 26) |
|---|---|---|
| TCS | 11.61% | 5.65% |
| RELIANCE | 19.21% | 10.31% |
| INFY | 43.37% | 22.96% |
| HDFCBANK | 60.81% | 31.88% |
| ITC | 35.82% | 17.02% |
| ADANIPORTS | 8.61% | 4.95% |
| ASIANPAINT | 21.03% | 9.93% |
| RADICO | 45.64% | 21.40% |
| ICICIBANK | 65.26% | 29.39% |
| TIMEX | no holding | — |

The double count was measured on the warehouse: TCS has 658 scheme entries for Sep 2026 vs Aug 2026, of which 309 are named Direct and 318 Regular, but only 169 distinct (house, share-count) pairs. The sum is 42.02 crore shares of 361.81 crore outstanding.

**Production-shape TCS `company_risks` (P):**
- Debt to equity, debt growth, current ratio, CFO ÷ PAT, PAT vs cash-flow growth, free cash flow, receivables and working capital: all `Not in our data`, value none.
- Interest cover 54.4×, pledge 0.68%, promoter change ±0.00 pp, margin trend and Piotroski 4/9: all run.
- Notice "Cash-flow statements for TCS are not in our data yet…". KPIs "Latest balance sheet: not in our data" and "Latest cash-flow year: not in our data".

**Real capture** `backend/tests/fixtures/research_visual_capture.json` was re-taken from this run (9 payloads, including `company_risks:production`). Its test checks the contract, the lint, the live cash-flow route, the fund-house mismatch notice and the production shape.

**pytest** (throwaway `nivesh/backend:staging` container, `--network none`, on dev 19d8d974 + this branch):
- `python -m pytest tests/test_copilot_research_answers.py -q -p no:cacheprovider` → `585 passed, 1 warning in 1.66s`
- `python -m pytest tests/test_copilot_visual.py tests/test_copilot_visual_chat.py tests/test_copilot_events.py tests/test_copilot_prompts_mode.py tests/test_copilot_trade_idea.py tests/test_quick_hedge_chat.py tests/test_open_book.py tests/test_broker_trades.py tests/test_suggestions.py -q -p no:cacheprovider` → `687 passed, 2 warnings in 41.11s`

### CI: "Backend unit tests (allowlist)", side by side

The PR check fails on every recent PR, including docs-only #450, and its logs cannot be read with our token. So each tree's own workflow allowlist (parsed from its `.github/workflows/backend-tests.yml`) was run on a full `git archive` of each tree, in the same `nivesh/backend:staging` image, with the workflow env:

```
python -m pytest -q -p no:cacheprovider -rfE --tb=line $(allowlist)
```

| Tree | Allowlist files | Result |
|---|---|---|
| untouched origin/dev 19d8d974 | 296 | `3 failed, 8151 passed, 34 skipped, 15 warnings in 235.15s` (exit 1) |
| this branch 5f70e2bc | 297 (+ `tests/test_copilot_research_answers.py`) | `3 failed, 8736 passed, 34 skipped, 15 warnings in 235.92s` (exit 1) |

The failures are identical and pre-existing (`diff` of the sorted `FAILED` lines is empty):

| Failing test | Error |
|---|---|
| `nidp/tests/shared/test_market_data_source.py::test_ms11_committed_file_is_current` | `assert ('shadow' == 'current'` |
| `nidp/tests/shared/test_truedata_client.py::test_sw7_shipped_switch_keeps_truedata_off` | `assert ('shadow' == 'current'` |
| `tests/test_move_odds_filing_analysis.py::test_tc10_tc11_route_gate_validation_and_payload` | `IndexError: list index out of range` |

The +585 passing tests on the branch are exactly this branch's test file. The same comparison on the earlier dev tip 1beb5c92 gave 3 = 3 as well (8,112 vs 8,705). UNVERIFIED: GitHub's runner failure list (logs unreadable); the local run uses the staging image's dependency set, not a fresh `uv pip install`.

## UI / Playwright Tests

No frontend source changed. UNVERIFIED: no Playwright run renders the research payloads. The real capture is ready for a spec.

## Data Correctness (staging)

The round-1 spot checks still hold:
- TCS P/E 17.5386 against a sector median of 23.8905, lower on 142 of 208 sessions.
- The IT peer order matches the warehouse.
- TCS current ratio 143,509 ÷ 57,887; FY26 CFO 52,094 ÷ PAT 49,454.
- RADICO pledge 7.0691.
- ASIANPAINT pledge and debt.
- The ICICIBANK FII conflict.

The live DaaS cash-flow rows equal the warehouse rows (52,094 / −4,078 for FY26).

**Fund-house double count:** measured as described above (658 entries, 169 distinct; 42.02 of 361.81 crore shares, 11.61%, against 5.65% filed).

## Inputs required from user

- **To finish TC-S5:**
  - merge and deploy this follow-up PR;
  - a signed-in staging session to ask the five questions in chat.
- **Decision for the owner or the smart-money owner:** the DaaS `/desk/smart-money/amc` double count (and so, likely, the desk's Smart Money AMC drill-down) needs a fix in `_AMC_SQL`, for example de-duplicating a scheme's plans. It is not changed here.

## Unverified

- **UNVERIFIED: live chat on staging (TC-S5).**
- **UNVERIFIED: the stock analyst's prose** against `WORDING_RULE`; no LLM call was made.
- **UNVERIFIED: production** itself; the production shape was simulated on staging data.
- **UNVERIFIED: the desk Smart Money page's AMC figures.**
- **UNVERIFIED: Playwright rendering.**
- **UNVERIFIED: GitHub's CI failure list.**

## Verdict: BLOCKED

TC-S5 (live chat as a signed-in user) cannot run before this follow-up PR is merged and deployed, and it needs a signed-in session. Every other test case, including the owner's 3 Nov compliance, production-data and CI cases, passed with the real outputs above.
