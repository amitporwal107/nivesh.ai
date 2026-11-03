# Functionality Verification Report: Research Copilot W1 (five research answers)

- **Branch:** feat/research-answers-w1 (from origin/dev fb66b6d0; dev unchanged at the end, checked 3 Nov 2026)
- **Date:** 2026-11-03 (work 2 to 3 Nov 2026 IST)
- **Author:** Claude (Full stack developer + QA engineer; domain and SEBI-wording review)
- **Environment:** staging. Builders ran in-process inside `nivesh-staging-app-backend` from a scratch copy, against the live staging DaaS and the NIDP warehouse, read-only. Nothing was deployed or restarted. The scratch copy was deleted afterwards.
- **Changed areas:** backend routes/services: yes · DaaS router: yes · frontend src: **no**
- **Test cases (written before implementation):** `test_reports/research_answers_w1_TESTCASES.md`

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

Both go live only after a daas-api restart. Until then the answers name them as "not served by the data platform yet" and show no figure from them.

**Fixture:** a routing fixture of 101 of the owner's questions.

**Data-trust guards (from the real run):**
- **NSE vs screener.in disagreement:** the two sources disagree on FII % for depository-receipt companies, so the answer never computes a change across them and names the conflict.
- **Pledge with no promoter:** NSE pledge figures are shown only when they agree with the promoter holding.
- **Large one-quarter moves:** a move over 5 points gets a "check the filing" notice.
- **Immaterial debt:** debt growth on a tiny base (below 0.1× equity) is not a flag.
- **Revenue basis:** twelve-month revenue is never mixed across bases.
- **Lenders:** checks that do not apply to banks are marked "Not applicable".

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-R1 | routing | 101 owner questions × 3 company fillers; plus as written with thread stock TCS; plus with no company and no thread | unit | 100% match the fixture | **PASS**: 303/303, 101/101, 101/101 |
| TC-R2 | routing | Research thesis → no visual; trade thesis / still valid → trade_validity; "margin weakening" → financial_trend | unit | as stated | **PASS** |
| TC-R3 | routing | Ownership trend vs event chip split | unit | as stated | **PASS** |
| TC-R4 | routing | Thread stock for an entity-less company question; feed wording keeps going to the feed | unit | as stated | **PASS** |
| TC-R5 | routing | Market-wide questions never use the thread stock | unit | not W1 | **PASS** |
| TC-R6 | routing | Multi-company extraction in sentence order; metric acronyms not tickers; causal/segment → no visual | unit | as stated | **PASS** |
| TC-R7 | regression | 9 existing Copilot/suggestions suites | unit | all pass | **PASS**: 671 passed |
| TC-B1 | financial_trend | One basis, 8 quarters, YoY rules, providers notice, lender, depth, no Source column when none stated | unit | as stated | **PASS** |
| TC-B2 | valuation_view | vs sector median with formula, own-history range and percentile, EV/EBITDA gap, scenarios only when asked | unit | as stated | **PASS** |
| TC-B3 | ownership_trend | Field-wise merge; no public %; pledge validation; source conflict; large-move notice; fund-house 404 | unit | as stated | **PASS** |
| TC-B4 | peer_compare | Exact sector label (not substring); no map → notice; named set; lender gap; one-recognised notice | unit | as stated | **PASS** |
| TC-B5 | company_risks | 13 rules; cash-flow 404 → no cash figure; balance-sheet columns not served; lender n/a; materiality; one revenue basis | unit | as stated | **PASS** |
| TC-B6 | freshness | Filings never get the stale-price notice; an over-cadence filing gets "newer filing may exist" | unit | as stated | **PASS** |
| TC-B7 | SEBI lint | buy / sell / hold / target / recommend / pick / cheap / expensive / under- / overvalued in any generated text | unit | 0 hits | **PASS** (4 variants × 6 answers, plus the real capture) |
| TC-B8 | registration | INTENTS, BUILDERS, validate, AGENT_FOR = stock_analyst; `prepare` facts subject | unit | as stated | **PASS** |
| TC-B9 | failure | Every read failing → valid payload of notices, no figure | failure | as stated | **PASS** |
| TC-D1 | DaaS | New SELECT columns; cash-flow handler (fake pool): SQL, symbol normalisation, envelope, route registered | unit | as stated | **PASS** |
| TC-S1 | real data | 5 intents × 10 real symbols + 5 extra questions, in-process DaaS client on staging | api (in-process) | all `validate()==[]`, < 30 s | **PASS**: 75 builds, 0 contract problems, slowest 3.07 s |
| TC-S2 | real data | New route SQL run verbatim (PREPARE/EXECUTE and inlined) on the warehouse; `company_risks` fed those rows | data | figures present and correct | **PASS** |
| TC-S3 | data check | Payload figures against warehouse rows | data | match | **PASS** (table below) |
| TC-S4 | gap honesty | TIMEX (no financials, no shareholding) | edge | gaps named, no estimate | **PASS** |
| TC-S5 | live chat | Each intent asked as a signed-in user in staging chat | e2e | real answer | **BLOCKED**: needs merge to dev + app-backend restart (+ daas-api restart for the cash-flow route and balance-sheet columns) |

## API / Endpoint Tests (staging)

The visual answers are not HTTP routes of their own: the chat route calls them in-process (`routes/chat.py`, `copilot_visual.prepare`). The staging app backend runs `origin/dev` code, so the branch was checked by running its builders inside the staging backend container (the real `daas_client`, the real DaaS, the real warehouse), not by curl to `/api/chat`.

- **Live DaaS route status (before merge):** `GET /v1/financials/TCS/cashflow` → `404 {'error': {'status': 404, 'message': 'Not Found', …}}`. `GET /v1/smart-money/amc?symbol=TCS` → `404` (a route already on dev that is not live on the running DaaS). Both are shown in the answers as named missing sources.
- **Command:**
  ```
  sudo docker exec -w /tmp/research_w1_backend -e PYTHONPATH=/tmp/research_w1_backend nivesh-staging-app-backend python /tmp/research_w1_realcheck.py
  ```
  Output, final run, abridged to one line per intent/symbol (full log in the session scratchpad):
  ```
  S1 | How has revenue grown over the last 5 years for TCS?  | financial_trend:TCS |  3.07s | valid=True | missing=0 | TCS reported revenue of ₹73,188 Cr (+11.2% year on year) and PAT of ₹13,934 Cr (+15.4%) for the Sep 26 quarter. …
  S1 | Is TCS expensive or cheap?                            | valuation_view:TCS |  0.12s | valid=True | missing=0 | TCS trades at 17.5× trailing earnings (2 Nov 2026), 26.6% below the median P/E of its sector label (23.9×); its P/E was lower on 68% of the 208 sessions since 29 Dec 2025.
  S1 | Has promoter holding of TCS increased?                | ownership_trend:TCS |  0.07s | valid=True | missing=1 | TCS at Sep 26, percent of shares: Promoters 71.77% (±0.00 pp); FIIs 9.01% (−0.06 pp); DIIs 13.57% (+0.16 pp) …
  S1 | Compare TCS with its peers                            | peer_compare:TCS |  1.52s | valid=True | missing=0 | 8 companies compared …; TCS's P/E is 17.5× against a median of 22.5× for the set.
  S1 | What are the biggest risks for TCS?                   | company_risks:TCS |  0.12s | valid=True | missing=1 | None of the 7 checks that could run is flagged for TCS; 6 could not run for lack of data.
  S1 | What are the biggest risks for HDFCBANK?              | company_risks:HDFCBANK |  0.19s | valid=True | missing=1 | For a bank or lender like HDFCBANK, these checks mostly do not apply, and the ones that do (asset quality, capital adequacy) are not in our data.
  S1 | Has promoter holding of ICICIBANK increased?          | ownership_trend:ICICIBANK |  0.06s | valid=True | missing=1 | ICICIBANK at Sep 26, percent of shares: FIIs 34.68% (+0.89 pp); DIIs 41.78% (−0.54 pp) …
  S1 | Compare HDFC Bank, ICICI Bank and Axis Bank across …  | peer_compare:HDFCBANK |  0.14s | valid=True | missing=0 | 3 companies compared …; HDFCBANK's P/E is 13.8× against a median of 13.6× for the set.
  S1 | What are the biggest risks for TIMEX?                 | company_risks:TIMEX |  0.10s | valid=True | missing=1 | No check could run for TIMEX: the figures they need are not in our data.
  S1 | Build a research thesis for TCS                       | -> None (no visual)
  S2 | What are the biggest risks for TCS?                   | company_risks:TCS |  0.07s | valid=True | missing=0 | None of the 13 checks that could run is flagged for TCS.
  S2 | What are the biggest risks for ADANIPORTS?            | company_risks:ADANIPORTS |  0.06s | valid=True | missing=0 | 1 of the 13 checks that could run is flagged for ADANIPORTS: Current ratio.
  S2 | What are the biggest risks for ASIANPAINT?            | company_risks:ASIANPAINT |  0.07s | valid=True | missing=0 | 2 of the 13 checks that could run are flagged for ASIANPAINT: Debt growth vs profit growth; Promoter pledge.
  TOTAL builds: 75 contract problems: 0 max secs: 3.07
  ```
- **S2 meaning:** `rr.financials` and `rr.cashflow` were answered by this branch's `FINANCIALS_SQL` / `CASHFLOW_SQL`, run read-only on the warehouse via `nidp-psql.sh` (real rows: TCS 8 quarterly / 12 annual / 2 cash-flow rows; HDFCBANK 0 annual; ICICIBANK 2 quarterly; TIMEX none). Every other read was live. The route itself is UNVERIFIED live until daas-api restarts.
- **Real capture committed:** `backend/tests/fixtures/research_visual_capture.json`, 8 payloads. `test_c2_research_real_capture_matches_the_contract` re-validates them.
- **pytest** (throwaway `nivesh/backend:staging` container, `--network none`):
  - `python -m pytest tests/test_copilot_research_answers.py -q -p no:cacheprovider` → `577 passed, 1 warning in 1.59s`
  - `python -m pytest tests/test_copilot_visual.py tests/test_copilot_visual_chat.py tests/test_copilot_events.py tests/test_copilot_prompts_mode.py tests/test_copilot_trade_idea.py tests/test_quick_hedge_chat.py tests/test_open_book.py tests/test_broker_trades.py tests/test_suggestions.py -q -p no:cacheprovider` → `671 passed, 2 warnings in 41.15s`
  - **Pre-existing failures, not from this branch:** `tests/test_chat_advisor_mode.py` has 3 failures (`test_chat_stream_advisor_sees_client_book`, `test_chat_stream_advisor_fund_research_works`, `test_chat_send_advisor_sees_client_book`). They fail identically on an untouched `git archive origin/dev` copy. That copy also fails `test_honesty_safety_pass.py::test_disabled_patterns_do_not_claim_no_detector_exists`, which passes on this branch.
- **Routing fixture** (offline resolver, `backend/tests/fixtures/research_copilot_routing.json`):
  ```
  cases: 101 | by category: {2: 26, 3: 15, 6: 13, 7: 9, 8: 17, 13: 10, 14: 9, 15: 2}
  named company (3 fillers): 303/303; thread stock TCS: 101/101; no company, no thread -> never a W1 answer: 101/101
  ```

## UI / Playwright Tests

No frontend source changed. The frontend schema parses any intent (`intent: str.catch("unknown")`), and the answers use only existing block types (`kpis`, `bars`, `ranked`, `list`, `notice`).

UNVERIFIED: no Playwright run renders the new payloads. AC-RC-10's Playwright extension is not part of W1. The real capture `backend/tests/fixtures/research_visual_capture.json` is ready for a spec to render.

## Data Correctness (staging)

Read-only through `~/.config/nivesh/nidp-psql.sh`, 2–3 Nov 2026:

| Payload figure | Warehouse | Match |
|---|---|---|
| TCS P/E 17.5×, sector median 23.9×, −26.6%, lower on 142 of 208 sessions (68%), range 13.90–23.10 | `pe_now 17.5386`, `sector_med 23.8905`, `lower_days 142`, `days 208`, min 13.8993, max 23.1043 | yes |
| TCS IT peers: TCS, INFY, HCLTECH, WIPRO, TECHM, LTM, PERSISTENT, OFSS | top 8 by `market_cap_cr` with `lower(sector)='it'` on 2026-11-02, same order | yes |
| TCS Sep 26 revenue ₹73,188 Cr (+11.2% vs ₹65,799 Cr), PAT ₹13,934 Cr (+15.4% vs ₹12,075 Cr) | `nse_financials_quarterly` consolidated rows | yes |
| TCS current ratio 2.48× (Sep 26) | 143,509 ÷ 57,887 | yes |
| TCS FY26 CFO ÷ PAT 1.05×, FCF ₹48,016 Cr | CFO 52,094; FY26 PAT 49,454; capex −4,078 | yes |
| RADICO pledge 7.07% of promoter shares, 2.85% of all | NSE_SHP 7.0691 / 2.85 (40.17 × 7.0691% = 2.84) | yes |
| ADANIPORTS promoters 66.03% | NSE_SHP 66.03 | yes |
| ASIANPAINT pledge 11.85% (Jun 26) flagged; debt +48.2% to ₹2,900 Cr (0.13× equity) flagged | NSE_SHP 11.8490 / 6.26 (52.63 × 11.849% = 6.24); debt 911+1,047 → 1,622+1,278, equity 22,409 | yes |
| ICICIBANK FII conflict named (NSE 50.44 vs screener.in 34.68) | both rows for 2026-09-30 | yes |

**Data traps found and handled (measured):**
- **FII definition gap:** of 807 quarters where both NSE and screener.in report FII %, 7 differ by more than 0.5 points, all depository-receipt names (ICICIBANK, DRREDDY, AXISBANK, WIPRO, UPL, ABCAPITAL, MPIMANIPAL). Promoter % never differs.
- **Pledge with no promoter:** 1,149 NSE_SHP rows carry a pledge with no promoter holding (HDFCBANK 17.53%, ITC 100%).
- **Public % means different things:** screener.in `public_pct` is retail only; NSE's is everything that is not promoter.
- **Fundamentals on one day only:** features carry fundamentals (P/B, ROE, market cap) only on the latest day (2,060 on 2026-11-02, about 1 on earlier days). `pe_vs_sector_pct` is empty; `sector_median_pe` covers 542 stocks.
- **Quarter depth:** quarterly history is mostly 8–9 quarters (Trendlyne from Sep 2024). ICICIBANK has 2 quarters; HDFCBANK has no annual rows.
- **Cash flow:** 214 companies (419 rows, FY2024–FY2026, `source='truedata'`). The table has no filing timestamp, so it cannot be used in look-ahead-safe studies (none are run in W1).

## Inputs required from user

- None for this report.
- TC-S5 needs, from the owner or an operator:
  - the PR merged to dev and the app backend restarted (CI deploy);
  - a daas-api restart on the NIDP VM for the new cash-flow route and columns (the permission classifier denies that restart to me);
  - a signed-in staging session to ask the five questions in chat.

## Unverified

- **UNVERIFIED: live chat on staging (TC-S5).** It needs the merge, the app-backend restart and a signed-in session.
- **UNVERIFIED: the new DaaS route live.** `GET /v1/financials/{s}/cashflow` and the new `/financials` columns need a daas-api restart. Their SQL was run verbatim on the warehouse (TC-S2).
- **UNVERIFIED: the fund-house view on staging.** `/smart-money/amc` (already on dev) answers 404 on the running DaaS, so `ownership_trend` shows no fund-house figures on staging until that restart.
- **UNVERIFIED: Playwright rendering** of the new payloads.
- **UNVERIFIED: the stock analyst's prose.** No LLM call was made, so its explanation of the facts block was not observed. The facts block is at most 4,156 characters, under the 6,000 cap, and none was cut.

## Verdict: BLOCKED

TC-S5 (live chat on staging as a signed-in user) cannot run before the merge and the backend and DaaS restarts. Every other test case passed with the real outputs above.
