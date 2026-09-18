# Functionality Verification Report — Move odds: the stock pop-up is the copilot chat's stock card

- **Branch:** feat/move-odds-v7 (on dev cc0e4e42)
- **Date:** 2026-09-18 (test cases authored 12:20 IST, before implementation)
- **Author:** Claude (full-stack developer + QA)
- **Environment:** staging (staging.niveshcopilot.com / nidp_staging)
- **Changed areas:** backend routes: yes (app `routes/move_odds.py`) · frontend src: yes (MoveOddsScreen, shared ChatWidget subtitle)

## Summary
Owner, 12:12–12:17 IST, with screenshots of the Move odds pop-up (1) and the copilot chat's RELIANCE card (2): "The 1
needs to be same as 2 as in copilot chat" … "complete card for stock as in copilot chat". Confirmed by AskUserQuestion:
**completely unchanged**, including the "Worth buying now?" chip and its long/short-term BUY / HOLD / SELL
Recommendation. This reverses the 11:20 "scores only" decision for the pop-up; the page's banned-word rule (D2) now
exempts the card and still applies to everything else on the page.

Design: a new gated app route serves exactly what the copilot's Stock Analyst node attaches to its answer —
`instrument_research.get_stock_research(symbol).widget` passed through `research_lenses.build_research_hub("stock", …)`,
with no LLM call — and the pop-up renders it with the copilot's own `ChatWidget` (→ `ResearchHubCard`). The move-odds
sections (four estimates, inputs, events, five checks, paper trade) stay below the card (11:20 decision 2); the
disclaimer stays above every number (C4). If the card cannot be loaded, the pop-up says so and falls back to the v7
quality block from the profile, so the move-odds sections never depend on it.

Also fixed in the shared card: the subtitle joined `[subtitle, meta, risk]`, and for a stock `risk` is an object, so
copilot chat itself showed "[object Object]" (visible in the owner's RELIANCE screenshot). Only string parts are joined.

## Contract
`GET /api/move-odds/stocks/{symbol}/card` (move_odds allowlist; 403 feature_not_enabled otherwise, admins included).
- 200 → `{"data": {"widget_type": "instrument_detail", "data": <widget + research_rail + lens_views + active_lens>}}`
- 404 `not_found` when research has no data for the symbol; 502 `upstream_unavailable` when the market-data source is
  down (the research call's `source_unavailable`); 504 `card_timeout` after 25 s. Symbol pattern as `/stocks/{symbol}`.

## Test Cases
| ID | Area | Case | Type | Expected | Result |
|---|---|---|---|---|---|
| TC-104 | App | Card route | api (unit) | gated like the other move-odds routes (403 for non-allowlisted and admins, no research call); 200 body = `build_research_hub("stock", get_stock_research(sym).widget)` unchanged; 404 / 502 / 504 as above; lower-case symbol upper-cased | |
| TC-105 | UI | Pop-up = copilot card | e2e mocked | the pop-up renders the copilot card: name, STOCK badge, subtitle, last price; chips in `research_rail` order starting "Worth buying now?"; that lens shows the Recommendation (BUY/HOLD/SELL as served); "How's it performed?" shows "Where price sits"; the move-odds sections are below it; disclaimer above; D2 scan passes for the page outside the card | |
| TC-106 | UI | Card failure | e2e mocked | card 502 → "could not be loaded" with the reason, the v7 quality block from the profile, and the move-odds sections still render | |
| TC-107 | UI | No "[object Object]" | e2e mocked | the card subtitle joins only strings (stock `risk` object is not printed) | |
| TC-108 | Staging | Real card | e2e staging + api | on staging the pop-up's card equals the card payload the page received (name, price, chips in order); that payload's price and quality equal DaaS `/v1/features/stocks/{sym}/latest` and `/v1/stocks/scores/{sym}` for the same symbol; the chips switch lenses; no "[object Object]" | |

## API / Endpoint Tests (staging)
_pending_

## UI / Playwright Tests
_pending_

## Data Correctness (staging)
_pending_

## Inputs required from user
- none (the owner's staging session from 12:07 IST is still valid)

## Verdict: BLOCKED
