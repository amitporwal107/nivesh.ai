# Functionality Verification Report — Move odds: filing analysis in the stock view

- **Branch:** feat/move-odds-event-why
- **Date:** 2026-09-30
- **Author:** Claude (full-stack developer + design engineer + QA)
- **Environment:** staging (staging.niveshcopilot.com / nivesh_staging Mongo)
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
The Move odds stock view lists "Events on record" with rules-only labels that have been wrong since the CIE LLM
enrichment died on 2026-09-19 (PB Fintech's -36% day read "M&A, positive"). This adds a separate "Filing analysis"
block fed by the corporate-event AI analyses in Mongo `event_ai_analysis` (owner's master prompt, claude-sonnet-5,
tool-less). New endpoint `GET /api/move-odds/stocks/{symbol}/filing-analysis`. Estimates are untouched; the block is
context, not a forecast and not a model input.

Selection rules (enforced in `services/move_odds_filing_analysis.py`):
- only `tool_isolation == "tools_off+isolated"` analyses (compact or single_full modes);
- filed in the last 30 days, newest first, at most 5 filings; one row per filing (latest analysis wins);
- a filing the importance filter dropped is not shown: dropped = a filter verdict exists and no pass
  (first filter, same-model second opinion, or resolution CONFIRMED/PARTIALLY_CONFIRMED with importance >= 60) keeps it;
- evidence status from the resolution pass if present, else the first filter pass, else `NOT_CHECKED`;
- no research inputs (document text, Trendlyne material) leave the backend.

## Test Cases
> Authored UP FRONT — after API + UI design, before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | service | isolated analysis within 30 days, filter include=true | unit | returned with summary, band, materiality, certainty, evidence status | |
| TC-2 | service | analysis flagged NOT_ISOLATED | unit | excluded | |
| TC-3 | service | filter include=false, no second/resolution keep | unit | excluded | |
| TC-4 | service | filter false, second opinion include=true | unit | returned | |
| TC-5 | service | filter false/LOW, resolution CONFIRMED imp 72 | unit | returned, evidence CONFIRMED | |
| TC-6 | service | two analyses of one filing (batch5 + batch50) | unit | one row, latest analyzed_at | |
| TC-7 | service | analysis with no filter doc (pre-filter order-win run) | unit | returned, evidence NOT_CHECKED | |
| TC-8 | service | 7 kept filings | unit | 5 newest returned, `more` = 2 | |
| TC-9 | service | response never carries `input` / document text | unit | no `input` key | |
| TC-10 | route | user not on move_odds allowlist | api | 403 feature_not_enabled | |
| TC-11 | route | bad symbol `A;B` | api | 422 | |
| TC-12 | route | staging, symbol with analyses (e.g. SAPPHIRE) | api (staging) | 200, rows match Mongo | |
| TC-13 | route | staging, symbol with none (POLICYBZR) | api (staging) | 200, rows [] | |
| TC-14 | ui | stock view shows Filing analysis rows (mocked API) | e2e | block with summary, band, evidence, disclaimer | |
| TC-15 | ui | filing-analysis API fails | e2e | "could not be loaded" note; estimates still render | |
| TC-16 | ui | existing Move odds spec | e2e | still passes | |

## API / Endpoint Tests
- **pytest (local, real FastAPI app + real move_odds gate, Mongo read injected):**
  `/opt/nidp/venv/bin/python -m pytest tests/test_move_odds_filing_analysis.py tests/test_move_odds_routes.py -q -p no:cacheprovider`
  - Output: `25 passed in 0.57s`. Reverse order: `25 passed in 0.61s`.
  - Covers TC-1..TC-11 plus a 502 when Mongo fails. Result: PASS.
- **Staging endpoint (TC-12, TC-13):** NOT RUN. The route only exists on staging after PR #191 is merged to dev and
  deployed. UNVERIFIED on staging.

## UI / Playwright Tests
- `npx playwright test research-move-odds --reporter=line` (mocked API; fixture labelled MOCK)
  - Output: `50 passed (1.8m)`, including the new TC-14, TC-14b and TC-15, plus TC-16 (the existing 47 cases, among them
    TC-26 banned words and TC-98 phone width). Result: PASS.
- The block's screenshot was captured, but not viewed: the image reader timed out on a hook.

## Data Correctness
- The staging Mongo dump failed: the GCP token had expired (`Request had invalid authentication credentials`).
- Instead, the same documents were rebuilt from the pipeline's source files with the loader's own builder
  (`to_mongo.to_doc`) and run through `select()`:
  - `docs 2953 unreadable 0`.
  - `symbols with any doc: 1057 | symbols with rows shown: 103 | rows shown: 114`.
  - `evidence mix: Counter({'CONFIRMED': 93, 'PARTIALLY_CONFIRMED': 21})`.
  - `SAPPHIRE -> [('2026-09-22T16:02', 'LITIGATION', 'slightly_negative', 'PARTIALLY_CONFIRMED')]`.
  - `KSB -> []`: resolution CONFIRMED but importance 25, correctly hidden.
  - `POLICYBZR -> None`: its crash was a regulator paper, not a filing.
- **Finding:** `rows containing a page-banned word: 4`. Examples: GANESHBE "agreed to sell its ... businesses",
  PRESTIGE "CPPIB to invest". These are factual uses, but the page's D2 vocabulary rule bans the words outright. Owner
  decision needed.

## Inputs required from user
- Merge PR #191 to dev. This is a live staging deploy; check app-vm disk first.
- Decide on the four summaries that use banned words.

## Verdict: BLOCKED
