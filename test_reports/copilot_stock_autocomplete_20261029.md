# Functionality Verification Report — Copilot stock autocomplete (ticker, full name, partial name)

- **Branch:** feat/copilot-stock-autocomplete (from dev f5c299b9), worktree /home/deploy/nivesh-strategy-copilot
- **Date:** 2026-10-29
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** backend tests in the staging backend image (`--network none`); mocked Playwright on a production build; staging after merge
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
Owner, 29 Oct: "Please allow autocompletetion of the stock based on ticker full name partial nae ...or provide suggestion
in the copilot chat".

What was there, measured on staging 29 Oct (read-only):
- The `/app` ask box called `GET /api/chat/instrument-search` with the **whole draft**. A question like "Plan a breakout
  trade for tvs mo" therefore found nothing; only a box holding just a name matched.
- Picking a row sent "Tell me about X" instead of completing the sentence.
- The desk's Copilot panel had no suggestions.
- The route's stock list is `daas_client.list_stock_universe(limit=800)`: **800 symbols and no company names**. LT,
  HINDUNILVR and EXIDEIND are not in it. Name search only reached a curated list of 60.
- The data platform already has `/v1/symbols/search` over the full symbol master (symbol, company name, sector,
  industry, ISIN). It handles `tvs mo` → TVSMOTOR, `hindustan uni` → HINDUNILVR and `exide` → EXIDEIND. It has no
  short forms (`hul` → nothing; `l&t` → L&T Finance, not LT), no word order (`motor tvs` → nothing), no indices
  (`nifty` → nothing), and weak ranking (`infosys` lists HCL Infosystems first).

What changes:
- **Backend: `GET /api/chat/instrument-search`, additive.**
  - **Source.** Stocks now come from the symbol-master search.
  - **Additions.** The Copilot resolver's own short forms (hul, l&t, sbi, …), the NSE F&O index underlyings (NIFTY,
    BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50; `kind: "index"`), and any-order word matching.
  - **Ranking.** Exact ticker, then ticker prefix, then name-word prefix (in order before any order), then substrings.
  - **Fallback.** The old universe / curated fallback stays for a data platform that is down.
  - **Tail mode.** `tail=1` takes the text *before the cursor*, finds the stock being typed at its end (the last 1–3
    words, skipping ordinary words), and answers `{stocks, funds: [], fragment, fragment_start}`.
  - Without `tail` the answer keeps its shape; stock rows only gain `kind`.
- **Frontend.**
  - The `/app` ask box and the desk's Copilot panel show **stock completions** for the fragment at the cursor:
    "TVSMOTOR · TVS Motor Company Limited". Tab, Enter on the highlighted row, or a click **replaces the fragment with
    the ticker** and keeps the rest of the sentence. Nothing is sent.
  - Typing only a name still also offers "Research <name>" (as before).

## Test Cases
> Authored UP FRONT (2026-10-29, before implementation). Files:
> - B = `backend/tests/test_chat_instrument_search.py` (CI)
> - F = `frontend-v5/e2e/tests/copilot-app-stock-complete.spec.ts`

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| SC-1 | B | `itc` | unit | ITC first (exact ticker), then the rest | PASS |
| SC-2 | B | `tvs mo`, `TVSMOTOR`, `hindustan uni` | unit | TVSMOTOR / TVSMOTOR / HINDUNILVR first | PASS |
| SC-3 | B | `motor tvs` (word order) | unit | TVSMOTOR | PASS |
| SC-4 | B | Short forms `hul`, `l&t`, `sbi` | unit | HINDUNILVR, LT, SBIN first, with their names | PASS |
| SC-5 | B | `nifty`, `bank nifty` | unit | NIFTY index first; BANKNIFTY; `kind: "index"` | PASS |
| SC-6 | B | `infosys` | unit | INFY before HCL-INSYS (name-word prefix beats a substring) | PASS |
| SC-7 | B | Data platform down (search returns None) | unit | The old universe / curated fallback answers, as before | PASS |
| SC-8 | B | Tail: "Plan a breakout trade for tvs mo" | unit | fragment "tvs mo", fragment_start at "tvs", TVSMOTOR first, no funds | PASS |
| SC-9 | B | Tail: "how is the market", "trade plan for ", one letter | unit | No fragment, no rows (ordinary words, trailing space, too short) | PASS |
| SC-10 | B | Tail: "compare infy and tcs" | unit | fragment "tcs" → TCS | PASS |
| SC-11 | B | No `tail`: shape unchanged (stocks: symbol, name, sector [+kind]; funds as before); limit respected; < 2 chars → empty | unit | as stated | PASS |
| SC-12 | F | `/app` box: type "Plan a breakout trade for tvs mo" | e2e | Completion row "TVSMOTOR" first. Tab → "Plan a breakout trade for TVSMOTOR " with the cursor after it; nothing sent | PASS |
| SC-13 | F | Arrow + Enter on a completion; click on a completion | e2e | Inserts the ticker, does not send; the next Enter sends the completed sentence | PASS |
| SC-14 | F | Text after the cursor is kept ("trade tvs mo| on breakout") | e2e | → "trade TVSMOTOR on breakout" | PASS |
| SC-15 | F | A name alone ("infy") | e2e | The completion row plus "Research Infosys Limited" (sends) | PASS |
| SC-16 | F | Desk Copilot panel | e2e | The same completions; Tab inserts; Enter with no highlight sends | PASS |
| SC-17 | regression | Composer specs (TC-10 …), research, screens, desk, trade-idea; backend allowlist dev vs branch | e2e+unit | No new failure | PASS |
| SC-18 | staging | After merge: `GET /api/chat/instrument-search?q=…&tail=1` on staging for the SC-1 … SC-10 cases | api | Real symbol-master answers as expected | PENDING (after merge; no session needed) |

## Tests run (real output, 2026-10-29, branch feat/copilot-stock-autocomplete)
- **SC-1 … SC-11:** `pytest tests/test_chat_instrument_search.py` → `25 passed, 2 warnings in 6.97s`.
- **Run against the REAL staging symbol master** (the new module's source piped into the running backend as an in-memory
  script, read-only; nothing written).
  - Plain search: `itc` → ITC, ITCHOTELS…; `tvs mo` / `TVSMOTOR` / `motor tvs` → TVSMOTOR; `hindustan uni` / `hul` →
    HINDUNILVR; `l&t` → LT, LTF, LTTS; `sbi` → SBIN first; `nifty` → NIFTY (index), NIFTYNXT50, BANKNIFTY…;
    `bank nifty` → BANKNIFTY; `infosys` → INFY, then HCL-INSYS; `exide` → EXIDEIND; `sona blw` → SONACOMS.
  - Tail search: "…for tvs mo" → `tvs mo` → TVSMOTOR; "compare infy and tcs" → `tcs` → TCS; "trade tata mot" →
    `tata mot` → TMCV, TMPV; "entry for sona bl" → SONACOMS; "how is hul" → HINDUNILVR; "Plan a trade on l&t" → LT;
    "buy a put on nifty" → NIFTY; "how is the market" → nothing.
- **Bug found by the real-data run, not by the fake master.** The first tail rule picked the best-scoring fragment, so
  "…for tvs mo" became `mo` → MOL / MOIL (a short-ticker prefix outscored the two-word name).
  - Fixed: the LONGEST fragment with a good match wins.
  - MOL and MOIL were added to the test master; the suite passes and the real run above is after the fix.
- **SC-12 … SC-16:** `playwright test e2e/tests/copilot-app-stock-complete.spec.ts` → `5 passed (11.3s)`. `tsc --noEmit`
  → exit 0.
- **SC-17, frontend regression:** copilot-app (TC-10 ask-box suggestions), desk (the dock), trade-idea, screens, research,
  contract-chart and advisor, with the new spec → `4 skipped, 118 passed (2.0m)`, **0 failed**.
- **SC-17, backend regression:** the CI allowlist (267 files, + the new suite) → `3 failed, 6972 passed, 28 skipped`.
  - The same tree content measured 6947 for #403 (`dev` f5c299b9 is that merge); +25 = the new suite.
  - The same 3 failures as `dev`, which predate this branch (`test_cas_api_client` ×2, `test_nidp_stamp_broadcast_at`
    ×1). **No regression.**

## Inputs required from user
- The merge (per-PR approval). SC-18 needs no session: the route is public, as it is today.

## Verdict: BLOCKED
