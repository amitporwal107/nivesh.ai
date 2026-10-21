# Desk F&O tab: stock search by name or partial ticker

Worktree /home/deploy/nivesh-trading-desk (feat/trading-desk-backend), UNCOMMITTED.
Files: frontend-v5/src/pages/CopilotApp/screens/tradingdesk/FnoTab.tsx, fno-buildup.ts, frontend-v5/e2e/tests/copilot-app-desk-lab.spec.ts.
Not changed: the standalone OptionsLab.tsx (same ticker-only box; see NOT verified).

## Finding (live staging, before the change, session token supplied by the user)
- Exact tickers worked: RELIANCE, M&M, BAJAJ-AUTO each answered 200 on /api/fno/{symbol}/expiries|futures|chain.
- Failing inputs: "Tata Motors" → "A ticker is letters, digits, & or -" (names refused); TATAMOTORS → "not in NSE's F&O list ... (213 stocks have futures)".
  The F&O data holds TMPV (Tata Motors' passenger-vehicle future) and no TATAMOTORS on 2026-10-19; the app's instrument search still lists TATAMOTORS.
- The search endpoint GET /api/search/instruments reads a static list (routes/portfolio.py, instruments_data) capped at 15: "tata" returns TCS, TATAMOTORS, TATASTEEL only.

## Change
Exact F&O ticker: loads as before, no search call. Anything else: the F&O list's own tickers containing the text (spaces/hyphens ignored,
prefix first) + /api/search/instruments hits, F&O only, once each. One → loads; several → "Pick one" buttons (max 8); none → says which of:
named stock not in F&O / no stock matches / search unavailable. A search failure no longer blocks a typed ticker or a partial-ticker match.

## Test cases (authored before the code): TC-34 x2 in copilot-app-desk-lab.spec.ts
1 exact ticker never calls the search; 2 a name with one F&O match loads it (one search call); 3 several matches listed, local + search merged, non-F&O hit left out, pick loads;
4 spaces ignored ("fix short" → FIXSHORT, request made); 5 a non-F&O stock is named and refused, no chain request; 6 no match; 7 search 502 → message for a name, partial ticker still offered, typed ticker still loads.
Existing TC-32 (unknown ticker text, format error, placeholder) kept passing; its placeholder assertion updated to "Name or ticker, e.g. TCS".

## Real output
tsc --noEmit: TSC_OK
Playwright (mocked, vite build + preview, copilot-app-desk* specs, SHOT excluded): 133 passed (2.4m)
New build against LIVE staging reads (local preview, /api proxied GET-only to staging with the user's session cookie; nothing written):
  "Tata Motors"        → "Tata Motors (TATAMOTORS) is not in NSE's F&O list for 19 Oct 2026 (213 stocks have futures), so it has no option chain to load."
  "tata"               → offers TATACONSUM, TATAELXSI, TATAPOWER, TATASTEEL, TCS
  "tata power"         → TATAPOWER loaded (200 expiries/futures/chain)
  "bajaj auto"         → BAJAJ-AUTO loaded (200 x3)
  "reliance industries"→ RELIANCE loaded;  "infosys" → INFY loaded
  "mahindra"           → offers KOTAKBANK, TECHM, M&M
  "zzzz corp"          → "No stock matches “zzzz corp”. Try the NSE ticker, e.g. RELIANCE."
  "RELIANCE"           → loaded, no search call

## NOT verified / open
- Not deployed: the live page https://staging.niveshcopilot.com:8443/v5/app/trader/desk?tab=fno still runs the old code.
- "Tata Motors" cannot resolve to TMPV: neither the F&O list nor the search has company names for it. Needs a name column in the F&O data (DaaS /desk/fno-buildup) or a refreshed instrument list. Not guessed.
- The static instrument list lacks many names (e.g. Tata Power by name works only via the ticker match).
- OptionsLab.tsx (standalone lab) not changed. Mobile layout of the suggestion buttons not checked.

## Verdict: BLOCKED (not deployed to staging; see OVERRIDE_fno_symbol_search.md)
