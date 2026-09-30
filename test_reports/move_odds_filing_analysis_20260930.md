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

## API / Endpoint Tests (staging)
_pending_

## UI / Playwright Tests
_pending_

## Data Correctness (staging)
_pending_

## Inputs required from user
- none yet

## Verdict: BLOCKED
