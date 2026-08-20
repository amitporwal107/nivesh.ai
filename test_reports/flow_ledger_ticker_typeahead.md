# Functionality Verification Report — FLOW LEDGER ticker type-ahead (NIDP symbol master)

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-08-20
- **Author:** Claude (full-stack-developer + qa-engineer)
- **Environment:** local Vite + Playwright (mocked with REAL staging payloads) **and** a
  live run of the real UI against real staging data (Vite `/api` proxy → staging, real
  session cookie supplied by the user)
- **Changed areas:** backend routes: **no** · frontend src: **yes**
  (`frontend-v5/src/pages/FlowLedger/index.tsx`), e2e: `e2e/tests/flow-ledger.spec.ts`

## Summary

The ledger's name field was free text. A typo, a BSE scrip code, or a company NIDP
does not carry all produced the same shrug from AUTO-FILL, with nothing to say which
of the three had happened. It now suggests as you type, from `nidp.sector_master`.

**No new backend code.** `/api/filings/companies/search` already reads the symbol
master through the DaaS (`GET /v1/symbols/search`) and is what the Research screen's
type-ahead calls. Adding a second endpoint would have been a second contract to keep
true; the page reuses `filingsService.searchCompanies`.

Three behaviours are the point of the tests:

- **A suggestion is only ever a row the master returned.** A failed search shows an
  empty list and no hint — never a guess assembled client-side.
- **A name the master does not carry is still the user's to send.** Zero matches shows
  "No symbol in the NIDP master matches …", and Enter still auto-fills what was typed.
  The dropdown assists the field; it does not gate it.
- **Picking a suggestion fills THAT symbol.** `autoFill` takes an explicit target, so
  the request cannot go out for the half-typed text the pick replaced.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | build | `tsc --noEmit` + `vite build` | build | no new errors, `✓ built` | PASS |
| TC-2 | e2e | ≥2 chars in COMPANY mode lists master matches | e2e | 8 rows, symbol+name+sector | PASS |
| TC-3 | e2e | 1 char asks nothing | edge | zero requests, no list | PASS |
| TC-4 | e2e | ArrowDown ×4 + Enter picks and auto-fills | e2e | `RELIANCE`, fill for RELIANCE | PASS |
| TC-5 | e2e | mousedown picks (blur must not eat the press) | edge | `RELINFRA` | PASS |
| TC-6 | e2e | SECTOR mode never searches the stock master | e2e | zero requests | PASS |
| TC-7 | e2e | search 500 → no list, no hint, no guess | failure | typed symbol still fills | PASS |
| TC-8 | e2e | zero matches → explicit hint, Enter still fills | edge | hint + fill | PASS |
| TC-9 | e2e | fast typing debounced to ONE request | e2e | `["RELIAN"]` | PASS |
| TC-10 | e2e | Escape closes the list | e2e | list gone | PASS |
| TC-11 | regression | pre-existing flow-ledger suite | e2e | 10/10 still pass | PASS |
| TC-12 | api/data | real staging payload behind the mocks | data | real master rows | PASS |
| TC-13 | live UI | real page → real staging → real fill | e2e | live dropdown + fill | PASS |

## TC-12 — the real staging payload (the mocks are this, verbatim)

Session cookie supplied by the user; the endpoint 401s without it.

```
$ curl -s -H "Cookie: session_token=<supplied>" \
    "https://staging.niveshcopilot.com/api/filings/companies/search?q=REL&limit=8"
{"ok": true, "companies": [
 {"symbol":"RELAXO",  "name":"Relaxo Footwears Limited",            "sector":null},
 {"symbol":"RELCHEMQ","name":"Reliance Chemotex Industries Limited","sector":null},
 {"symbol":"RELIABLE","name":"Reliable Data Services Limited",      "sector":null},
 {"symbol":"RELIANCE","name":"Reliance Industries Limited",         "sector":"Oil Gas"},
 {"symbol":"RELIGARE","name":"Religare Enterprises Limited",        "sector":null},
 {"symbol":"RELINFRA","name":"Reliance Infrastructure Limited",     "sector":null},
 {"symbol":"RELTD",   "name":"Ravindra Energy Limited",             "sector":null},
 {"symbol":"RELTD-RE","name":"Ravindra Energy Ltd-RE",              "sector":null}]}

$ ... "?q=ZZQQ&limit=8"   →   {"ok": true, "companies": []}
$ ... "?q=tata%20mot"     →   TMCV / Tata Motors Limited · TMPV / Tata Motors Passenger Vehicles Limited
```

The null sectors are real `sector_master` gaps, not an artefact of the call — which is
why the page renders an absent chip for them and the test asserts the row never prints
the word "null".

## TC-13 — the real UI against real staging data

Vite dev server with its `/api` → staging proxy, real adapters (`VITE_USE_MOCK_API=false`),
the real session cookie in the browser context. Nothing mocked.

```
URL after load: http://localhost:5175/v5/flows

LIVE SUGGESTIONS for 'REL' (from nidp.sector_master via staging):
  0  RELAXO | Relaxo Footwears Limited
  1  RELCHEMQ | Reliance Chemotex Industries Limited
  2  RELIABLE | Reliable Data Services Limited
  3  RELIANCE | Reliance Industries Limited | OIL GAS
  4  RELIGARE | Religare Enterprises Limited
  5  RELINFRA | Reliance Infrastructure Limited
  6  RELTD | Ravindra Energy Limited
  7  RELTD-RE | Ravindra Energy Ltd-RE

field value after pick: RELIANCE
fill summary: AUTO-FILLED FROM NIDP · 90/100 OF STREAM WEIGHT
fiiQ-0: -147
verdict: NEUTRAL / MIXED | coverage 90% · conviction 63%

API calls made by the page:
  GET /api/auth/me
  GET /api/filings/companies/search?q=REL&limit=8
  GET /api/flows/ledger/company/RELIANCE
```

Data check, not just a 200: `fiiQ-0 = -147` is RELIANCE's real latest QoQ FII change in
`nidp.shareholding_pattern` — the same figure the 2026-08-19 auto-fill report measured.
Coverage is 90/100 today against 70/100 then, because S3 (bulk/block deals) now fills.

## TC-1 … TC-11 — Playwright

```
$ npx playwright test e2e/tests/flow-ledger.spec.ts --project=desktop-chrome
  ✓ auth setup — inject dark-theme localStorage (4.1s)
  ✓ renders without an error boundary (3.3s)
  ✓ starts with nothing scored — an empty ledger must not read as neutral (3.3s)
  ✓ the composite is computed in the page and excludes unfilled streams (3.5s)
  ✓ auto-fill puts the real QoQ values into the tracker's own fields (3.9s)
  ✓ a filled stream shows the evidence behind its number (3.5s)
  ✓ an unsourceable stream shows its reason instead of a score (3.9s)
  ✓ auto-fill without a name does not call the API (2.9s)
  ✓ a 502 reads as a data-service problem, not as an empty company (3.4s)
  ✓ fills all four sector streams and reports full coverage (2.7s)
  ✓ suggests symbols from the NIDP master as you type (2.6s)
  ✓ a single character asks nothing — a blank query is not a search (3.1s)
  ✓ keyboard: arrow to a symbol, Enter picks it and auto-fills that symbol (2.9s)
  ✓ clicking a suggestion picks it — blur must not eat the press (2.8s)
  ✓ sector mode does not search the stock master (3.0s)
  ✓ a failed search suggests nothing — never a guess (2.8s)
  ✓ no match says so, and still lets the typed symbol through (2.6s)
  ✓ Escape closes the list (2.8s)
  ✓ a fast typist fires one request, not one per keystroke (3.4s)

  19 passed (38.3s)
```

```
$ npx tsc --noEmit -p tsconfig.json
(no output for the changed files; the one pre-existing error in
 src/pages/Webinar/index.tsx:106 is untouched by this change)

$ npx vite build
✓ built in 19.93s
```

## Known limits (stated, not papered over)

- **Substring ranking is the DaaS's, not the page's.** `q=MP` returns MPHASIS and
  MPSLTD first, then rows matching "mp" anywhere — "Automotive Sta**mp**ings", "Co**mp**any".
  Symbol-prefix hits sort first, so the head of the list is right; the tail is noisy.
  Fixing that means changing `/v1/symbols/search`'s ORDER BY, which is out of scope here.
- **Sector is often null.** Coverage in `sector_master` is partial; the chip is simply
  absent for those rows rather than showing a placeholder.
- **SECTOR mode has no type-ahead.** The ask was stock tickers. `/api/flows/ledger/sectors`
  already exists and would wire the same way — not done, not claimed.
- **Not deployed.** Verified locally against live staging data; staging redeploys from
  `origin/dev`, and this branch has not been pushed.

## Verdict: PASS
