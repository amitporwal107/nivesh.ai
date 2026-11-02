# Functionality Verification Report: Research Copilot W1 (five research answers)

- **Branch:** feat/research-answers-w1 (from origin/dev fb66b6d0; origin/dev 1beb5c92 (#452) merged in at 0818f92f; code at b59f2cd5)
- **PR:** #458 (base dev), not merged
- **Date:** 2026-11-03 (round 1: 2–3 Nov; round 2 on the owner's 3 Nov rules: compliance wording, production data, CI)
- **Author:** Claude (Full stack developer + QA engineer; domain and SEBI-wording review)
- **Environment:** staging. Builders ran in-process inside `nivesh-staging-app-backend` from a scratch copy, against the live staging DaaS and the NIDP warehouse, read-only. Nothing was deployed or restarted. The scratch copy was deleted after each run.
- **Changed areas:** backend routes/services: yes · DaaS router: yes · CI workflow allowlist: yes · frontend src: **no**
- **Test cases:** `test_reports/research_answers_w1_TESTCASES.md`. Written before implementation; TC-B10, TC-P1, TC-P2 and TC-CI were added on 3 Nov for the owner's rules.

## Summary

Five deterministic visual answers were added to the Copilot chat. Their routing, builders and DaaS reads are in new modules `services/copilot_visual/research_{intents,readers,builders}.py`; the shared files get registration lines and three small routing fixes:

| Intent | What it answers |
|---|---|
| `financial_trend` | Revenue, EBITDA, PAT and margins over quarters and fiscal years |
| `valuation_view` | P/E and P/B against the sector label's median and the stored P/E history; growth scenarios only when asked |
| `ownership_trend` | Promoter, FII, DII and MF holding over quarters, pledge, fund houses |
| `peer_compare` | Named companies, or a company and its sector peers |
| `company_risks` | 13 fixed, stated checks across debt, liquidity, cash flow, working capital, pledge and margins |

All five are pinned to `stock_analyst`, and the facts block names the stock as its subject.

**Routing fixes:**
- "Build a research thesis for TCS" no longer goes to `trade_validity`.
- "weaken" means trade validity only when it is said about a trade.
- Metric acronyms (EV, FCF, NIM, GNPA, TTM…) are never read as tickers.

**DaaS change (read-only):**
- `/financials/{s}` also returns `source`, the balance-sheet columns and `bs_truedata`.
- New `GET /financials/{s}/cashflow`.

Both go live only after a daas-api restart.

**Fixture:** a routing fixture of 101 of the owner's questions.

**Round 2 (owner, 3 Nov 2026):**
1. **Compliance wording.**
   - "Which FIIs entered or exited" became "Which FIIs started or ended a holding".
   - The output lint now also covers stop loss / SL, entry, exit, accumulate, book profit, upside, downside, price target, multibagger and "should invest". It runs over every string the answers show, the facts lines the explanation reads, and the research suggestion templates.
   - The stock analyst receives a wording rule with the facts of these five answers (`WORDING_RULE`, appended in `copilot_visual.prepare`).
   - The routing regexes that recognise such words in a question are unchanged: they read a question, they give no advice.
2. **Production data** (TrueData only on staging; prod uses our snapshot data). With no cash-flow rows and null TrueData balance-sheet columns, every check that needs them says "Not in our data". No figure from them appears, nothing is estimated, and nothing crashes. This is proven by tests and by a real-data run in production shape.
3. **CI.** The workflow's own allowlist was run on this branch and on untouched origin/dev in the same image. The three failures are identical and pre-existing; this branch adds none. `tests/test_copilot_research_answers.py` was added to the allowlist.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-R1 | routing | 101 owner questions × 3 company fillers; as written with thread stock TCS; with no company and no thread | unit | 100% match the fixture | **PASS**: 303/303, 101/101, 101/101 |
| TC-R2 | routing | Research thesis → no visual; trade thesis / still valid → trade_validity; "margin weakening" → financial_trend | unit | as stated | **PASS** |
| TC-R3 | routing | Ownership trend vs event chip split | unit | as stated | **PASS** |
| TC-R4 | routing | Thread stock for an entity-less company question; feed wording keeps going to the feed | unit | as stated | **PASS** |
| TC-R5 | routing | Market-wide questions never use the thread stock | unit | not W1 | **PASS** |
| TC-R6 | routing | Multi-company extraction in sentence order; metric acronyms not tickers; causal/segment → no visual | unit | as stated | **PASS** |
| TC-R7 | regression | 9 existing Copilot/suggestions suites | unit | all pass | **PASS**: 671 passed |
| TC-B1 | financial_trend | One basis, 8 quarters, YoY rules, providers notice, lender, depth, no Source column when none stated | unit | as stated | **PASS** |
| TC-B2 | valuation_view | vs sector median with formula, own-history range and percentile, EV/EBITDA gap, scenarios only when asked | unit | as stated | **PASS** |
| TC-B3 | ownership_trend | Field-wise merge; no public %; pledge validation; source conflict; large-move notice; fund-house 404 | unit | as stated | **PASS** |
| TC-B4 | peer_compare | Exact sector label; no map → notice; named set; lender gap; one-recognised notice | unit | as stated | **PASS** |
| TC-B5 | company_risks | 13 rules; cash-flow 404 → no cash figure; balance-sheet columns not served; lender n/a; materiality; one revenue basis | unit | as stated | **PASS** |
| TC-B6 | freshness | Filings never get the stale-price notice; an over-cadence filing gets "newer filing may exist" | unit | as stated | **PASS** |
| TC-B7 / TC-B10 | compliance | Extended word list over blocks, KPIs, notices, chips, caveat, facts lines and research suggestion templates; 6 data variants (full, lender, failure, cash-flow 404, production, thread stock) × 6 answers; the lint catches the owner's words, including the old "entered or exited"; the explanation gets `WORDING_RULE` | unit + real data | 0 hits | **PASS**: unit; and 0 hits over 96 real payloads + facts |
| TC-B8 | registration | INTENTS, BUILDERS, validate, AGENT_FOR = stock_analyst; `prepare` facts subject and wording rule | unit | as stated | **PASS** |
| TC-B9 | failure | Every read failing → valid payload of notices, no figure | failure | as stated | **PASS** |
| TC-P1 | production data | No cash-flow rows, null balance-sheet columns: company_risks shows 8 checks "Not in our data", no cash or balance-sheet figure; interest cover (P&L) still runs | unit + real data | as stated | **PASS** |
| TC-P2 | production data | The other four answers are valid on production-shaped data; computed ROE blank | unit | as stated | **PASS** |
| TC-D1 | DaaS | New SELECT columns; cash-flow handler (fake pool); route registered | unit | as stated | **PASS** |
| TC-CI | CI | The workflow's own allowlist, branch vs untouched origin/dev, same image | unit | identical pre-existing failures | **PASS**: 3 = 3, identical (table below) |
| TC-S1 | real data | 5 intents × 10 real symbols + extras, live DaaS in-process | api (in-process) | all valid, < 30 s | **PASS** |
| TC-S2 | real data | New route SQL run verbatim on the warehouse; company_risks fed those rows | data | correct | **PASS** |
| TC-S3 | data check | Payload figures against warehouse rows | data | match | **PASS** |
| TC-S4 | gap honesty | TIMEX (no financials, no shareholding) | edge | gaps named | **PASS** |
| TC-S5 | live chat | Each intent asked as a signed-in user in staging chat | e2e | real answer | **BLOCKED**: needs merge to dev + app-backend restart (+ daas-api restart for the cash-flow route and columns) |

## API / Endpoint Tests (staging)

The visual answers are not HTTP routes of their own: the chat route calls them in-process (`routes/chat.py`, `copilot_visual.prepare`). Staging runs `origin/dev`, so the branch was checked by running its builders inside the staging backend container (the real `daas_client`, the real DaaS, the real warehouse).

- **Live DaaS route status (before merge):** `GET /v1/financials/TCS/cashflow` → `404`. `GET /v1/smart-money/amc?symbol=TCS` → `404` (a route already on dev that is not live on the running DaaS). Both are named missing sources in the answers.
- **Command:**
  ```
  sudo docker exec -w /tmp/research_w1_backend -e PYTHONPATH=/tmp/research_w1_backend nivesh-staging-app-backend python /tmp/research_w1_realcheck.py
  ```
- **Modes:**
  - **S1:** every read through the live DaaS as deployed.
  - **S2:** `rr.financials` / `rr.cashflow` answered by this branch's `FINANCIALS_SQL` / `CASHFLOW_SQL`, run read-only on the warehouse via `nidp-psql.sh` (re-exported 3 Nov).
  - **P (production shape):** the S2 rows with the TrueData-fillable balance-sheet columns set to null and no cash-flow rows.
- **Final round-2 run, abridged.** The full log is in the session scratchpad. 54 S1 + 21 S2 + 21 P builds; the thesis question resolves to no visual in each mode.
  ```
  S1 | How has revenue grown over the last 5 years for TCS? | financial_trend:TCS | valid=True | TCS reported revenue of ₹73,188 Cr (+11.2% year on year) and PAT of ₹13,934 Cr (+15.4%) for the Sep 26 quarter. …
  S1 | Is TCS expensive or cheap?                           | valuation_view:TCS  | valid=True | TCS trades at 17.5× trailing earnings (2 Nov 2026), 26.6% below the median P/E of its sector label (23.9×); …
  S1 | Has promoter holding of ICICIBANK increased?         | ownership_trend:ICICIBANK | valid=True | ICICIBANK at Sep 26, percent of shares: FIIs 34.68% (+0.89 pp); DIIs 41.78% (−0.54 pp) …
  S2 | What are the biggest risks for ADANIPORTS?           | company_risks:ADANIPORTS | valid=True | 1 of the 13 checks that could run is flagged for ADANIPORTS: Current ratio.
  P  | What are the biggest risks for TCS?                  | company_risks:TCS | valid=True | None of the 5 checks that could run is flagged for TCS; 8 could not run for lack of data.
  P  | What are the biggest risks for ASIANPAINT?           | company_risks:ASIANPAINT | valid=True | 1 of the 5 checks that could run is flagged for ASIANPAINT: Promoter pledge.
  P  | What are the biggest risks for HDFCBANK?             | company_risks:HDFCBANK | valid=True | For a bank or lender like HDFCBANK, these checks mostly do not apply, …
  P  | How has revenue grown over the last 5 years for TCS? | financial_trend:TCS | valid=True | TCS reported revenue of ₹73,188 Cr (+11.2% year on year) …
  COMPLIANCE LINT over 96 real payloads + facts: 0 hits []
  TOTAL builds: 96 contract problems: 0 max secs: 3.3
  ```
- **Production-shape payload, TCS company_risks (P), checks table:**
  - Debt to equity, Debt growth vs profit growth, Current ratio, Cash from operations ÷ PAT, PAT growth vs cash-flow growth, Free cash flow, Receivables vs revenue growth and Working capital days: all `None | Not in our data`.
  - Interest cover `54.4×`, Promoter pledge `0.68%`, Promoter holding change `±0.00 pp`, EBITDA margin trend `25.7% vs 27.3%` and Piotroski `4 of 9`: all run (P&L, shareholding and features exist on prod).
  - Notice: "Cash-flow statements for TCS are not in our data yet, so the cash checks show no figure." KPIs show "Latest balance sheet: not in our data" and "Latest cash-flow year: not in our data".
- **Real capture committed:** `backend/tests/fixtures/research_visual_capture.json`, re-taken 3 Nov with 9 payloads including `company_risks:production`. `test_c2_research_real_capture_matches_the_contract` re-validates it and lints it. The stale capture failed this lint before it was re-taken, which shows the guard works.
- **pytest** (throwaway `nivesh/backend:staging` container, `--network none`):
  - `python -m pytest tests/test_copilot_research_answers.py -q -p no:cacheprovider` → `583 passed, 1 warning in 1.72s`
  - `python -m pytest tests/test_copilot_visual.py tests/test_copilot_visual_chat.py tests/test_copilot_events.py tests/test_copilot_prompts_mode.py tests/test_copilot_trade_idea.py tests/test_quick_hedge_chat.py tests/test_open_book.py tests/test_broker_trades.py tests/test_suggestions.py -q -p no:cacheprovider` → `671 passed, 2 warnings in 41.29s`
- **Routing fixture:** `named company (3 fillers): 303/303; thread stock TCS: 101/101; no company, no thread -> never a W1 answer: 101/101`.

### CI: "Backend unit tests (allowlist)", side by side

The PR check fails on every recent PR, including docs-only #450, and its logs cannot be read with our token. So each tree's own workflow allowlist (parsed from its `.github/workflows/backend-tests.yml`) was run in the same `nivesh/backend:staging` image, with the workflow's env, on a full `git archive` of each tree:

```
python -m pytest -q -p no:cacheprovider -rfE --tb=line $(allowlist)
```

| Tree | Allowlist files | Result |
|---|---|---|
| untouched origin/dev 1beb5c92 | 296 | `3 failed, 8112 passed, 34 skipped, 15 warnings in 246.73s` (exit 1) |
| this branch b59f2cd5 | 297 (+ `tests/test_copilot_research_answers.py`) | `3 failed, 8705 passed, 34 skipped, 15 warnings in 243.82s` (exit 1) |

The failures are identical on both, and pre-existing. `diff` of the sorted `FAILED` lines prints nothing:

| Failing test | Error |
|---|---|
| `nidp/tests/shared/test_market_data_source.py::test_ms11_committed_file_is_current` | `assert ('shadow' == 'current'` |
| `nidp/tests/shared/test_truedata_client.py::test_sw7_shipped_switch_keeps_truedata_off` | `assert ('shadow' == 'current'` |
| `tests/test_move_odds_filing_analysis.py::test_tc10_tc11_route_gate_validation_and_payload` | `IndexError: list index out of range` |

The extra 593 passing tests on the branch are this branch's 583 plus 10 suggestion-template cases (5 new templates × 2 personas). UNVERIFIED: whether GitHub's runner fails on exactly these three (its logs cannot be read with our token). The local run uses the staging image's dependency set, not a fresh `uv pip install`.

## UI / Playwright Tests

No frontend source changed. The frontend schema parses any intent, and the answers use only existing block types.

UNVERIFIED: no Playwright run renders the new payloads. The real capture is ready for a spec.

## Data Correctness (staging)

Read-only through `~/.config/nivesh/nidp-psql.sh`, 2–3 Nov 2026:

| Payload figure | Warehouse | Match |
|---|---|---|
| TCS P/E 17.5×, sector median 23.9×, −26.6%, lower on 142 of 208 sessions | `pe_now 17.5386`, `sector_med 23.8905`, `lower_days 142`, `days 208` | yes |
| TCS IT peers: TCS, INFY, HCLTECH, WIPRO, TECHM, LTM, PERSISTENT, OFSS | top 8 by `market_cap_cr` with `lower(sector)='it'` on 2026-11-02, same order | yes |
| TCS Sep 26 revenue ₹73,188 Cr (+11.2%), PAT ₹13,934 Cr (+15.4%) | 73,188 / 65,799; 13,934 / 12,075 | yes |
| TCS current ratio 2.48×; FY26 CFO ÷ PAT 1.05×; FCF ₹48,016 Cr | 143,509 ÷ 57,887; 52,094 ÷ 49,454; 52,094 − 4,078 | yes |
| RADICO pledge 7.07% / 2.85%; ADANIPORTS promoters 66.03% | NSE_SHP rows | yes |
| ASIANPAINT pledge 11.85% (Jun 26); debt +48.2% to ₹2,900 Cr (0.13× equity) | 11.8490 / 6.26; 911+1,047 → 1,622+1,278, equity 22,409 | yes |
| ICICIBANK FII conflict (NSE 50.44 vs screener.in 34.68) | both rows for 2026-09-30 | yes |

**Data traps handled:**
- **FII definition gap:** NSE and screener.in differ on FII % for 7 of 807 shared quarters, all depository-receipt names.
- **Pledge with no promoter:** 1,149 NSE pledge rows have no promoter holding.
- **Public %:** screener.in's `public_pct` is retail only.
- **Fundamentals on one day only:** features carry fundamentals only on the latest day.
- **Quarter depth:** mostly 8–9 quarters.
- **Cash flow:** 214 companies; the table has no filing timestamp, so it cannot be used for look-ahead-safe studies.
- **Production:** none of the TrueData-filled data exists there.

## Inputs required from user

- None for this report.
- TC-S5 needs:
  - the PR merged and the app backend redeployed;
  - a daas-api restart on the NIDP VM (the restart is denied to the agent);
  - a signed-in staging session.

## Unverified

- **UNVERIFIED: live chat on staging (TC-S5).** It needs the merge, the restarts and a signed-in session.
- **UNVERIFIED: the new DaaS route and columns live.** They need a daas-api restart; their SQL was run verbatim.
- **UNVERIFIED: the fund-house view on staging.** `/smart-money/amc` answers 404 on the running DaaS.
- **UNVERIFIED: the production run itself.** The production shape was simulated on staging data; no prod run, and none intended before release.
- **UNVERIFIED: the stock analyst's prose.** No LLM call was made. The wording rule is in its input; its compliance with the rule was not observed.
- **UNVERIFIED: Playwright rendering**, and the exact GitHub runner failure list.

## Verdict: BLOCKED

TC-S5 (live chat on staging as a signed-in user) cannot run before the merge and the backend and DaaS restarts. Every other test case, including the owner's 3 Nov compliance, production-data and CI cases, passed with the real outputs above.
