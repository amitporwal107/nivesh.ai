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
| TC-104 | App | Card route | api (unit) | gated like the other move-odds routes (403 for non-allowlisted and admins, no research call); 200 body = `build_research_hub("stock", get_stock_research(sym).widget)` unchanged; 404 / 502 / 504 as above; lower-case symbol upper-cased | PASS (unit) |
| TC-105 | UI | Pop-up = copilot card | e2e mocked | the pop-up renders the copilot card: name, STOCK badge, subtitle, last price; chips in `research_rail` order starting "Worth buying now?"; that lens shows the Recommendation (BUY/HOLD/SELL as served); "How's it performed?" shows "Where price sits"; the move-odds sections are below it; disclaimer above; D2 scan passes for the page outside the card | PASS (mocked + staging) |
| TC-106 | UI | Card failure | e2e mocked | card 502 → "could not be loaded" with the reason, the v7 quality block from the profile, and the move-odds sections still render | PASS (mocked) |
| TC-107 | UI | No "[object Object]" | e2e mocked | the card subtitle joins only strings (stock `risk` object is not printed) | PASS (mocked + staging) |
| TC-108 | Staging | Real card | e2e staging + api | on staging the pop-up's card equals the card payload the page received (name, price, chips in order); that payload's price and quality equal DaaS `/v1/features/stocks/{sym}/latest` and `/v1/stocks/scores/{sym}` for the same symbol; the chips switch lenses; no "[object Object]" | PASS |

## API / Endpoint Tests (staging)
**Unit (local):** `/opt/nidp/venv/bin/python -m pytest backend/tests/test_move_odds_routes.py -q` → `13 passed in 0.73s`
(TC-104 new: 200 body equals `build_research_hub("stock", get_stock_research(sym).widget)` with BUY/HOLD/SELL kept;
403 for non-allowlisted and admin without running research; 422 bad symbol; 404 / 502 / 504).

**Deploy:** dev `fb0941bf` pushed 12:27 IST; staging backend route live 12:37:49, V5 bundle `index-B1irDgLs.js` live
12:30:01 (both polled on the public URLs).

**Staging, owner's session (real, no mocks):**
```
PNCINFRA: 200 in 1.0s · instrument_detail · name 'PNCINFRA' · price ₹134.44 · chips 8 · rec Sell/Sell
INDIAGLYCO: 200 in 0.8s · instrument_detail · name 'INDIAGLYCO' · price ₹1,111.70 · chips 4 · rec Hold/Buy
RELIANCE: 200 in 0.5s · instrument_detail · name 'RELIANCE' · price ₹1,240.00 · chips 8 · rec Sell/Sell
unknown symbol: 404
no session: 401
```
RELIANCE at ₹1,240.00 is the price in the owner's copilot-chat screenshot — the same card.

## UI / Playwright Tests
**Mocked (local):** `npx playwright test e2e/tests/research-move-odds.spec.ts e2e/tests/research-access.spec.ts
--project=desktop-chrome` → `53 passed`; `tsc --noEmit` exit 0; `npx vite build` → `✓ built in 19.46s`. The card
fixtures `move-odds-card-{PNCINFRA,ANTELOPUS}.json` are real card bodies captured from the staging DaaS through the same
two functions (their `_note` says so). Every D2 scan on the page now runs with the copilot card hidden (`screenText`),
so the card may carry BUY/HOLD/SELL while the rest of the page is still held to D2.

**Real staging (owner's session), `staging-move-odds-v7.spec.cjs`, 12:38 IST:**
```
card INDIAGLYCO: "INDIAGLYCO" ₹1,111.70 -3.10% · chips Worth buying now? | How's it performed? | How risky is it? | What's new?
  ✓  1 … TC-99 v7 + v2 against live data: hero, rows, ratings, filters, stock view, history (6.2s)
390px clipped elements: none
  ✓  2 … phone › TC-99 390px: nothing runs off the screen, the stock view fits (2.5s)
  2 passed (10.0s)

card PNCINFRA: ₹134.44 -4.19% · rec Sell/Sell · lenses Worth buying now? (621 chars), How's it performed? (416 chars), Cheap or pricey? (382 chars), How risky is it? (305 chars), Compare to peers (404 chars), Any red flags? (494 chars), Who runs it? (376 chars), What's new? (494 chars)
  ✓  1 … TC-108 a full copilot card (PNCINFRA): every lens switches, equal to the payload the page received (3.9s)
  1 passed (5.0s)
```
Asserted: the chips equal the card payload's `research_rail` in order; name, price and the long-term stance are shown;
the subtitle reads "PNCINFRA · NSE · Construction · Small cap" with no "[object Object]"; every lens switches;
"How's it performed?" shows "Where price sits"; the move-odds inputs render below; the D2 scan outside the card passes.
The screenshot matches the owner's copilot card layout (header + price, lens rail, Where price sits, RSI / MACD /
momentum cards, source line).

## Data Correctness (staging)
`tc108.py`: the card payload the page received vs the staging DaaS for the same symbol:
```
PNCINFRA: card price ₹134.44 | DaaS features close 134.44 (as of 2026-09-16) → MATCH
PNCINFRA: card quality 28 | DaaS scores quality_score 28.48 → MATCH
INDIAGLYCO: card price ₹1,111.70 | DaaS features close 1111.7 (as of 2026-09-01) → MATCH
INDIAGLYCO: card quality 58 | DaaS scores quality_score 58.48 → MATCH
```
The card is faithful to NIDP. **But NIDP is stale for INDIAGLYCO:** its latest features row is 1 Sep, so the card (and
copilot chat) shows ₹1,111.70 while NSE closed it at ₹248.70 on 17 Sep, and the page's rating block shows no V3 score
because none is within 14 days. This is the same fault behind the bad "change over 5 sessions" (−79.1% vs NSE −19.9%)
that makes INDIAGLYCO today's top estimate. It needs a fix in the features pipeline; this page only shows it.

## Inputs required from user
- none beyond the staging session supplied at 12:07 IST (deleted from the scratchpad after these runs).

## Verdict: PASS
