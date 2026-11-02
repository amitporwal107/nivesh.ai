# Functionality Verification Report: Research Copilot W1 (five research answers), round 2

- **Branches:**
  - **Round 1:** `feat/research-answers-w1` was merged as **#458** at 101b98b4 (owner, 2 Nov 22:42 UTC) and deployed to staging (backend container restarted 22:46 UTC).
  - **Round 2 (this report):** `feat/research-answers-w1-r2`, from origin/dev 19d8d974, code at 22652a54. It carries the owner's 3 Nov rules and the fixes to defects found in the deployed round 1.
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
5. **The explanation step** (found by asking round 1 live, signed in). For these five answers the stock analyst used its own template and tools:
   - it quoted a provider's "PAT YoY +4.5%" beside the card's filed +15.4%;
   - it wrote "relatively cheap valuation" and "bullish bias".

   Now, when the facts carry `WORDING_RULE`, `stock_node` explains only the card's data block: no tool reads, no sections, the wording rule applies. Every other stock question keeps the usual path (tested).
6. **Quarter labels** read "Sep 2026", not "Sep 26": the model read "Dec 24" as 24 December.

**Correction to round 1's report and PR #458:** they said `/smart-money/amc` "is not live on the running DaaS". That was wrong. The path was mine and it was wrong; the route itself exists under `/desk`.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-R1 | routing | 101 owner questions × 3 fillers; with thread stock TCS; with no company and no thread (on the new dev base) | unit | 100% | **PASS**: 303/303, 101/101, 101/101 |
| TC-R2…R6 | routing | Thesis not trade_validity; ownership trend vs event; thread stock; market-wide; multi-company; acronyms | unit | as stated | **PASS** |
| TC-R7 | regression | 11 existing Copilot, suggestions and agent suites (on dev 19d8d974 + this branch) | unit | all pass | **PASS**: 720 passed |
| TC-B11 | explanation (new) | Research card explained from the card alone (no tool reads, research prompt, wording rule); an ordinary stock question unchanged; real model on branch code for the five questions | unit + real model | 0 lint hits, card figures only | **PASS**: unit (incl. a lint over the whole explanation request: advice words appear only in the user's question and in the two instructions that forbid them; the non-research path keeps `_SYSTEM`, its tools and no research text); real model 5/5 clean |
| TC-B1…B6, B8, B9 | builders | As in round 1 (trend, valuation, ownership, peers, risk checks, freshness, registration, failure) | unit | as stated | **PASS** |
| TC-B3+ | ownership (new) | Fund-house reader calls `/desk/smart-money/amc`; figures hidden when the total disagrees with the filing (notice gives both numbers); read failure → named missing source | unit + real data | as stated | **PASS**: 9 of 9 real companies hidden with the notice; TIMEX has no fund-house holding |
| TC-B5+ | risk checks (new) | An untagged balance-sheet row reads "provider not recorded on the row" | unit | as stated | **PASS** |
| TC-B7 / TC-B10 | compliance | Extended word list × 6 data variants × 6 answers; facts lines; suggestion templates; lint self-test; `WORDING_RULE` in the facts | unit + real data | 0 hits | **PASS**: unit; 0 hits over 96 real payloads + facts |
| TC-P1 | production data | No cash flow, null balance-sheet columns: 8 checks "Not in our data", no figure from them | unit + real data | as stated | **PASS** |
| TC-P2 | production data | The other answers valid; computed ROE blank | unit | as stated | **PASS** |
| TC-D1 | DaaS | Round 1's route: SQL columns, cash-flow handler | unit | as stated | **PASS**; and now live (below) |
| TC-CI | CI | The workflow's own allowlist, branch vs untouched origin/dev, same image | unit | identical pre-existing failures | **PASS**: 3 = 3 |
| TC-S1…S4 | real data | Live DaaS, route SQL, production shape; warehouse spot checks; gap honesty | api (in-process) + data | valid, matching | **PASS** |
| TC-S5 | live chat | The five questions asked as a signed-in user in staging chat | e2e | real answers | **Round 1 (deployed): RUN twice** (two sessions, below). 5/5 reach their card and stock_analyst. Found live: the false fund-house 404 and "exited" (fixed in #460); in the explanations, "cheap", "bullish", "undervalued" and a figure that contradicts the card (all from the analyst's own template and data; fixed in #460 by the card-only explanation, checked with the real model on branch code). **Round 2 live in chat: BLOCKED** until #460 is merged and deployed |

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
TOTAL builds: 96 contract problems: 0 max secs: 3.88   (final run on the code of 22652a54, whose last commit only changed tests; the earlier run on 5f70e2bc: 3.39)
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
- `python -m pytest tests/test_copilot_research_answers.py -q -p no:cacheprovider` → `588 passed, 2 warnings in 6.57s`
- `python -m pytest tests/test_copilot_visual.py tests/test_copilot_visual_chat.py tests/test_copilot_events.py tests/test_copilot_prompts_mode.py tests/test_copilot_trade_idea.py tests/test_quick_hedge_chat.py tests/test_open_book.py tests/test_broker_trades.py tests/test_suggestions.py tests/test_copilot_agents_oneshot.py tests/test_chat_persona_routing.py -q -p no:cacheprovider` → `720 passed, 2 warnings in 44.17s`

**Other suites that use the stock node** (`tests/test_copilot_symbol_resolution.py`, `tests/test_llm_input_hardening.py`, `tests/test_copilot_trade_idea.py`), branch vs a `git archive` of origin/dev in the same image: both trees give `1 failed, 94 passed`, with the same failure, `test_copilot_symbol_resolution.py::test_stock_node_asks_when_no_symbol`. It is pre-existing and not in the CI allowlist.

### CI: "Backend unit tests (allowlist)", side by side

The PR check fails on every recent PR, including docs-only #450, and its logs cannot be read with our token. So each tree's own workflow allowlist (parsed from its `.github/workflows/backend-tests.yml`) was run on a full `git archive` of each tree, in the same `nivesh/backend:staging` image, with the workflow env:

```
python -m pytest -q -p no:cacheprovider -rfE --tb=line $(allowlist)
```

| Tree | Allowlist files | Result |
|---|---|---|
| untouched origin/dev 19d8d974 | 296 | `3 failed, 8151 passed, 34 skipped, 15 warnings in 235.15s` (exit 1) |
| this branch 5f70e2bc | 297 (+ `tests/test_copilot_research_answers.py`) | `3 failed, 8736 passed, 34 skipped, 15 warnings in 235.92s` (exit 1) |
| this branch e47d1e51  | 297 | `3 failed, 8739 passed, 34 skipped, 15 warnings in 352.61s` (exit 1); the same three failures |
| this branch 22652a54 (final code), run with nothing else on the VM | 297 | `3 failed, 8739 passed, 34 skipped, 15 warnings in 264.22s` (exit 1); the same three failures; 8,739 = dev's 8,151 + this branch's 588 |

The failures are identical and pre-existing (`diff` of the sorted `FAILED` lines is empty):

| Failing test | Error |
|---|---|
| `nidp/tests/shared/test_market_data_source.py::test_ms11_committed_file_is_current` | `assert ('shadow' == 'current'` |
| `nidp/tests/shared/test_truedata_client.py::test_sw7_shipped_switch_keeps_truedata_off` | `assert ('shadow' == 'current'` |
| `tests/test_move_odds_filing_analysis.py::test_tc10_tc11_route_gate_validation_and_payload` | `IndexError: list index out of range` |

The +585 passing tests on the branch are exactly this branch's test file. One run of 22652a54 made while another test run shared the VM's CPUs also failed `tests/test_symbol_lookup.py::test_warm_search_is_fast_on_a_large_universe`, a wall-clock test. Alone it passed 3 times out of 3 (`37 passed`), the branch does not touch symbol lookup, and the uncontended full run above does not fail it. The same comparison on the earlier dev tip 1beb5c92 gave 3 = 3 as well (8,112 vs 8,705). UNVERIFIED: GitHub's runner failure list (logs unreadable); the local run uses the staging image's dependency set, not a fresh `uv pip install`.

**Another measurement of dev's allowlist.** The PR #455 agent counted 6 pre-existing failures on dev: MS-11, SW-7, `test_cas_api_client` ×2, `test_move_odds_filing_analysis` TC-10/11 and `test_nidp_stamp_broadcast_at`. In the `nivesh/backend:staging` image used here, dev has 3 (MS-11, SW-7, TC-10/11). The other three pass in this image, so they depend on the environment (the dependency set or env). Either way, this branch adds no failure in the same environment: 3 = 3 here. Not re-run in a fresh `uv` install, because the VM disk is at 3 GB free and no new image was built.

## Live staging chat (round 1 as deployed), 3 Nov 2026

The five questions were asked through `POST /api/chat/stream` on staging.niveshcopilot.com, as the token owner, in a new chat session created for the check. Persona: investor. The token was read in-process and never printed.

- Cloudflare refuses Python's default User-Agent (error 1010), so a browser User-Agent was sent.
- Staging runs **round 1** (#458; backend restarted 22:46 UTC), so this is TC-S5 for round 1.
- Round 2 (#460) still needs merge and deploy before it can be asked live.

| Question | Card (intent · agent) | Missing sources | Compliance lint, card | Lint, explanation |
|---|---|---|---|---|
| Has promoter holding of TCS increased? | ownership_trend · stock_analyst | "…does not serve the fund-house view yet (HTTP 404)" (**false: the round-1 path bug, fixed in #460**) | `exited` ("Which FIIs entered or exited", **fixed in #460**) | none |
| What are the biggest risks for TCS? | company_risks · stock_analyst; "None of the 13 checks that could run is flagged for TCS." | none | none | `undervalued` (see below) |
| Is TCS expensive or cheap? | valuation_view · stock_analyst; "TCS trades at 17.5× trailing earnings …" | none | none | no explanation: "I'm having trouble connecting right now" (LLM gateway; card shown) |
| Compare TCS with its peers | peer_compare · stock_analyst; "8 companies compared …" | none | none | none |
| How has revenue grown over the last 5 years for TCS? | financial_trend · stock_analyst; revenue FY22–FY26 | none | none | none |

**From the saved assistant messages** (`GET /api/chat/messages`, read-only):
- The `company_risks` explanation says: The company is described as "undervalued valuation". That is the stock analyst's own research data (the features `valuation_signal`), which it fetches beside the card; it is not text from the research card.
- The existing compliance filter turned "bullish" into "[factual data only — no recommendation]".
- Every explanation ends with the compliance node's standard disclaimer, which names buy / sell / hold advice and price targets in order to say Copilot does not give them.

**Round 2 sends `WORDING_RULE` (no undervalued / target / … words) with these answers' facts.** That instructs the model; it does not guarantee the output. **Decision for the owner:**
- A deterministic word filter on these answers' explanation (in the compliance node, outside this PR) would make the rule hold every time.
- The disclaimer's wording itself uses the owner's listed words.

### Second live run (round 1), and the round-2 explanation checked with the real model

A second session asked the same five questions (plus the thesis question) through `POST /api/chat/stream` with `curl`, header on stdin, investor persona, in a new chat session. All six returned HTTP 200. The cards were right; the explanations were not:

| Question | Card | Explanation (stock analyst, round 1) |
|---|---|---|
| How has revenue grown… TCS | financial_trend, no missing | clean |
| Is TCS expensive or cheap? | valuation_view, no missing | "…indicating a relatively **cheap** valuation…" |
| Has promoter holding of TCS increased? | ownership_trend; false 404 missing source; gap text "entered or **exited**" | clean |
| Compare TCS with its peers | peer_compare, no missing | its own Technical/Fundamental template; **"PAT YoY +4.5%"** (the provider's figure) against the card's filed **+15.4%** |
| What are the biggest risks for TCS? | company_risks, 13 checks, none flagged | "The technical tool reports a **bullish** bias…" |
| Build a research thesis for TCS | no research card (instrument_detail from the LangGraph stock path, not trade_validity) | "**bullish** bias", "Valuation is described as **undervalued** relative to peers": the plain stock analyst, outside W1 |

**Round-2 explanation path, real model, branch code** (in-process in `nivesh-staging-app-backend`, scratch copy, `prepare` → facts → `stock_node`, read-only, deleted after):

```
### How has revenue grown over the last 5 years for TCS? -> financial_trend (2.6s, 102 words, tools 0)
lint: []
TCS revenue for the last five fiscal years is shown as follows:  - FY22 → ₹1,91,754 Cr, YoY +16.80%   - FY23 → ₹2,25,458 Cr, YoY +17.58%   - FY24 → ₹2,40,893 Cr, YoY +6.85%   - FY25 → ₹2,55,324 Cr, YoY +5.99%   - FY26 → ₹2,67,021 Cr, YoY +4.58%    The dashboard also notes a revenue CAGR of +8.6% from FY22 to FY26 (4 years). Quarterly revenue data is available only from Dec 2024 to Sep 2026, so earlier quarters are not in our data. Segment‑level revenue and profit figures are not in our data. EBITDA is missing for three of the eight quarters shown.

### Is TCS expensive or cheap? -> valuation_view (2.3s, 123 words, tools 0)
lint: []
The valuation view dated 2 Nov 2026 shows TCS trading at a trailing‑12‑month P/E of 17.5×. The sector median P/E for the “IT” label is 23.9×, making TCS’s P/E 26.6% below that median. Since 29 Dec 2025, the daily P/E has been recorded over 208 sessions; in 68% of those sessions (142 of 208) the P/E was lower than today’s level. The historical range since 29 Dec 2025 is a low of 13.90×, a median of 16.76×, a high of 23.10×, and an average of 17.2×. Other metrics include a P/B of 6.37× (12 Oct 2026), market capitalisation of ₹7,68,844 Cr, and dividend yield of 2.64%. Data not available: EV/EBITDA, any P/E prior to 29 Dec 2025, forward P/E, and valuation‑model growth estimates.

### Has promoter holding of TCS increased? -> ownership_trend (2.1s, 84 words, tools 0)
lint: []
Promoter holding was 71.77% on 30 Sep 2026 (±0.00 pp versus Jun 2026 and versus Sep 2025). The same 71.77% appears in each earlier quarter shown: Dec 2025 (±0.00 pp), Sep 2025 (±0.00 pp), Jun 2025 (±0.00 pp), Mar 2025 (±0.00 pp), Dec 2024 (±0.00 pp). The Δ column for promoters is ±0.00 pp in every quarter, indicating no change over the period.  Data not in our records: individual promoter trade details, FIIs that started or ended holdings, and mutual‑fund holdings before Sep 2025.

### Compare TCS with its peers -> peer_compare (15.4s, 171 words, tools 0)
lint: []
TCS’s trailing‑twelve‑month P/E is 17.5× as of 2026‑11‑02, compared with a median of 22.5× for the eight IT peers. In the latest quarter (Sep 2026) TCS reported revenue growth YoY of 11.23% and PAT growth YoY of 15.40%, an EBITDA margin of 25.7%, ROE of 45.9%, ROCE of 58.6% and a debt‑to‑equity ratio of 0.00×.    Among the peers, the highest revenue‑growth YoY is PERSISTENT at +30.2% (Sep 2026) and the lowest is OFSS at +6.6% (Sep 2026). The top EBITDA margin is OFSS at 48.6% and the lowest is PERSISTENT at 13.6% (both Sep 2026). ROE peaks at TCS (45.9%) and is lowest at WIPRO (15.0%) (Sep 2026). Debt‑to‑equity is highest at WIPRO (0.19×) and lowest at TCS (0.00×).    Valuation figures show TCS market cap of ₹7,68,844 Cr, P/B of 6.37×, promoter holding 71.77%, FIIs 9.01% and DIIs 13.57% (as of 2026‑11‑02).    The sector map covers 545 of 2,488 IT stocks, so any listed peer outside that s

### What are the biggest risks for TCS? -> company_risks (16.1s, 160 words, tools 0)
lint: []
The dashboard shows that none of the 13 risk checks are flagged for TCS. Debt to equity is 0.00× (₹0 Cr debt) as of Sep 2026, and debt growth versus profit growth notes “no debt at either date” for Sep 2026. Interest cover stands at 54.4× for FY26, and the current ratio is 2.48× as of Sep 2026. Cash from operations ÷ PAT is 1.05× (₹52,094 Cr ÷ ₹49,454 Cr) for FY26. PAT grew +1.4% while cash‑flow grew +6.5% from FY25 to FY26. Free cash flow is ₹48,016 Cr (CFO ₹52,094 Cr, capex −₹4,078 Cr) for FY26. Receivables rose +9.0% versus revenue +9.9% from Sep 2025 to Sep 2026. Working‑capital days are 104 days (up from 103) for Sep 2025‑Sep 2026. Promoter pledge is 0.68% of promoter shares as of Jun 2026.  The dashboard cannot check related‑party transactions, debt maturities, auditor remarks or contingent liabilities, and it does not provide a ranked risk impact list. Data unavailable for those i
```

The thesis question is not a W1 answer. Its stock-analyst text ("bullish", "undervalued") comes from the pre-existing stock path and is not changed here.

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
- **UNVERIFIED: the round-2 explanation in live chat.** The real model was checked in-process on branch code (5/5 clean, above); the live chat path for round 2 runs after merge and deploy. `WORDING_RULE` and the research prompt instruct the model; they do not guarantee its output. A deterministic word filter would; that belongs to the compliance node (the separate compliance-wording work), not this PR.
- **UNVERIFIED: production** itself; the production shape was simulated on staging data.
- **UNVERIFIED: the desk Smart Money page's AMC figures.**
- **UNVERIFIED: Playwright rendering.**
- **UNVERIFIED: GitHub's CI failure list.**

## Verdict: BLOCKED

TC-S5 for round 2 (this PR) cannot run before #460 is merged and deployed. TC-S5 for round 1 ran live on staging (section above), and every other test case passed with the real outputs above, including the owner's 3 Nov compliance, production-data and CI cases.
