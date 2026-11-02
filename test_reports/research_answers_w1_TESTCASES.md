# Research Copilot W1: test cases (written before implementation)

- **Branch:** feat/research-answers-w1 (from origin/dev fb66b6d0)
- **Date:** 2026-11-02
- **Author:** Claude (Full stack developer + QA engineer; domain/SEBI review)
- **Scope:** five deterministic visual answers in the Copilot chat, backend only:
  `financial_trend` (category 2), `valuation_view` (6), `ownership_trend` (8), `peer_compare` (7) and
  `company_risks` (13, the runnable half of 14, and 3). It also fixes the routing bug where "Build a research
  thesis for TCS" goes to `trade_validity`. It adds a routing fixture built from the owner's sample questions.
- **Requirement:** docs/research_copilot/RESEARCH_COPILOT_REQUIREMENTS.md (FR-RC-01, 02, 03, 05, 06, 14; AC-RC-01, 03, 08, 09).

## Design (API and answer), fixed before the tests

**Routing.** Rules live in `services/copilot_visual/research_intents.py`. The shared resolver calls them:
- **Named stock:** the research rules run after the trade checks (validity, exit, position size, decision words)
  and before the event chips.
- **No stock named, but the thread has one:** the research rules run before the market-wide answers, and only
  for company-shaped wording. "Which stocks…" and "find stocks…" are never a company question.
- **Research-thesis or research-report wording** gets no visual answer and falls through to the LangGraph path.
- **Causal questions** ("why did margins fall", "what is driving growth", segment questions) get no visual answer
  either. They need filing text, not a numbers card.
- **Ownership: trend vs event.** A question about a holding's level or direction ("has promoter holding
  increased", "over time", "FII ownership over 4 quarters", "is smart money accumulating this stock", "which
  funds entered") goes to `ownership_trend`. A question about a disclosure ("pledge change", "SAST",
  "insider", "ownership filings", "disclosures") stays with `event_intelligence` (the Ownership chip).

**Data.** Every read goes through DaaS in-process; nothing queries the warehouse from the app.

| Intent | DaaS reads |
|---|---|
| `financial_trend` | `/financials/{s}` (quarterly and annual); `/features/stocks/{s}/latest` |
| `valuation_view` | `/features/stocks/{s}/latest` and `/features/stocks/{s}` (stored daily P/E history) |
| `ownership_trend` | `/shareholding/{s}`; `/smart-money/amc` |
| `peer_compare` | `/features/scan-snapshot` (sector label and industry); `/features/bulk`; `/financials/{s}` per company |
| `company_risks` | `/financials/{s}` (with the balance-sheet columns); **new** `/financials/{s}/cashflow`; `/shareholding/{s}`; `/features/stocks/{s}/latest` |

**DaaS change (read-only, same PR):**
- `/financials/{s}` also returns `source`, `current_assets_cr`, `current_liabilities_cr`,
  `trade_receivables_cr`, `inventory_cr`, `trade_payables_cr` and `bs_truedata` (the provenance tag).
- New route `GET /financials/{s}/cashflow` reads `nidp.nse_financials_cashflow`.

**Contract.** Answers use the existing blocks only (`kpis`, `bars`, `ranked`, `list`, `notice`), so no frontend
change is needed.

**Filed evidence.** Filed statements use `Sources.filed()`. They never get the stale-price notice. They get a
warning only when the newest filing is older than its filing cadence.

**Wording (SEBI, evidence only).** No buy, sell, hold, target, recommend or pick. No cheap, expensive,
undervalued or overvalued verdict. Every number carries its source and date. Any field we lack is stated as
"not in our data".

## Test Cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-R1 | routing | Every W1-category question from the owner's bank, with a company inserted (3 fillers: TCS, Reliance, HDFC Bank), resolves to its expected intent in the committed fixture | unit | 100% of fixture rows match |
| TC-R2 | routing | "Build a research thesis for TCS" and "Build a complete research thesis for Reliance" resolve to None (no visual). "Has my thesis on INFY weakened?" stays `trade_validity`. "Is margin weakening for TCS?" goes to `financial_trend` | unit | as stated |
| TC-R3 | routing | Ownership split: "Has promoter holding of TCS increased?" → `ownership_trend`. "Has there been promoter pledge change in INFY?" and "Any ownership filings for TCS?" → `event_intelligence`. "Show promoter holding changes" (no stock) → `event_intelligence` | unit | as stated |
| TC-R4 | routing | Entity-less question with a thread stock ("What is the current ratio?", last_symbol=TCS) → `company_risks` TCS with `symbol_from_thread`. The same question with no thread → not a W1 intent. `wants_thread_symbol` is True for research wording | unit | as stated |
| TC-R5 | routing | Market-wide questions ("Which stocks are FIIs accumulating?", "Find stocks with increasing FII and DII ownership") never resolve to a W1 intent | unit | not W1 |
| TC-R6 | routing | "Compare HDFC Bank, ICICI Bank and Axis Bank" → `peer_compare` with symbols [HDFCBANK, ICICIBANK, AXISBANK]. EV, FCF, NIM, GNPA, NNPA and TTM are never read as tickers | unit | as stated |
| TC-R7 | regression | Existing suites pass unchanged: test_copilot_visual.py, test_copilot_visual_chat.py, test_copilot_events.py, test_copilot_prompts_mode.py, test_copilot_trade_idea.py, test_quick_hedge_chat.py, test_open_book.py, test_broker_trades.py, test_suggestions.py | unit | all pass |
| TC-B1 | financial_trend | One basis (consolidated when the newest quarter has it). At most 8 quarters. YoY only against the same quarter a year earlier. A notice when the quarters come from more than one provider. Banks show no EBITDA margin. The real depth is stated. `validate()` returns [] | unit | as stated |
| TC-B2 | valuation_view | P/E vs sector median is computed with its formula stated. The P/E range and percentile cover the stored history, with the period named. EV/EBITDA says "not in our data". No cheap or expensive verdict. Scenario rows appear only when the question gives growth percentages | unit | as stated |
| TC-B3 | ownership_trend | Field-wise merge, NSE first. screener.in `public_pct` is never shown. A blank pledge reads "not reported", never 0. `/smart-money/amc` 404 → a missing source and no fund-house figure. Fewer than 4 quarters → a depth notice | unit | as stated |
| TC-B4 | peer_compare | Peers share the exact sector label, never a substring match ("IT" does not match "Capital Goods"). Fallback is the industry; with neither, a notice. An explicit list compares those companies only. Banks get the asset-quality gap notice | unit | as stated |
| TC-B5 | company_risks | Every check states its rule. Cashflow route 404 → the cash-flow source is named missing and no cash-flow figure appears (AC-RC-03 analogue). Balance-sheet columns not served → "not served by the data platform yet". Banks → "not applicable" for D/E, current ratio and working capital. A fixed "cannot check here" list | unit | as stated |
| TC-B6 | freshness | Filed statements never get the "older than the previous session" notice. A quarterly filing older than its cadence gets a "newer filing may exist" warning | unit | as stated |
| TC-B7 | SEBI lint | Across all generated text of the five answers (titles, headlines, notes, notices, cells, follow-ups, caveat): zero hits for buy, sell, hold, target, recommend, pick, cheap, expensive, undervalued, overvalued | unit | 0 hits |
| TC-B8 | registration | All five intents are in INTENTS, BUILDERS and validate's list, with AGENT_FOR = stock_analyst. The facts block names the stock as its subject | unit | as stated |
| TC-B9 | failure | Every DaaS read failing → each answer is still a valid payload of notices with no figure (never raises) | failure | as stated |
| TC-D1 | DaaS | `/financials` SELECT carries the new columns. `/financials/{s}/cashflow` handler: SQL, symbol normalisation and envelope (fake pool) | unit | as stated |
| TC-S1 | real data | Five intents × about 10 real symbols (TCS, RELIANCE, INFY, HDFCBANK, ITC, ADANIPORTS, ASIANPAINT, RADICO, a bank, a small cap without data) through the real in-process DaaS client in the staging backend container (scratch copy, read-only). Every payload passes `validate()`, each build takes under 30 s | api (in-process) | all valid |
| TC-S2 | real data | The new route's own SQL constants run read-only on the warehouse (nidp-psql) for the sample symbols. company_risks is fed those rows (labelled as such) and shows CFO/PAT, current ratio and receivables. Figures cross-checked against raw rows | data | match |
| TC-S3 | data check | Spot-check payload figures against the warehouse: TCS Sep-26 quarter revenue, RADICO pledge, TCS P/E and sector median, ADANIPORTS promoter % | data | match |
| TC-S4 | gap honesty | Small cap without data: each answer names what is missing and shows no estimate | edge | as stated |
| TC-B10 | compliance (added 3 Nov, owner rule) | No buy, sell, hold, target, price target, stop loss / SL, entry, exit, accumulate, book profit, upside, downside, multibagger, "should invest", recommend, pick, cheap, expensive, under- or overvalued anywhere the answers show text: blocks, KPIs, notices, follow-up chips, caveat, facts lines, research suggestion templates. The explanation step gets a wording rule | unit + real data | 0 hits |
| TC-P1 | production data (added 3 Nov, owner rule) | No cash-flow rows and null TrueData balance-sheet columns: the cash, liquidity and leverage checks say "Not in our data", no figure from them, no crash | unit + real data | as stated |
| TC-P2 | production data (added 3 Nov) | The other four answers stay valid on production-shaped data; computed ROE blank, never estimated | unit | as stated |
| TC-CI | CI (added 3 Nov) | The workflow's own allowlist ("Backend unit tests (allowlist)") on this branch and on untouched origin/dev, same image: the branch adds no failure | unit | identical pre-existing failures |
| TC-S5 | live chat | Each intent asked as a signed-in user on staging chat | e2e | **BLOCKED until merge + backend restart (and a daas-api restart for the cash-flow route)** |
