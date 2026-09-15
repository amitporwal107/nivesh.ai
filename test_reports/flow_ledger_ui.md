# Functionality Verification Report — FLOW LEDGER UI with NIDP auto-fill

- **Branch:** feat/flow-ledger-ui
- **Date:** 2026-08-19
- **Author:** Claude (full-stack-developer + design-engineer + qa-engineer)
- **Environment:** local build + Playwright (mocked with REAL staging payloads); staging DB for the data layer
- **Changed areas:** backend routes: **yes** (`backend/routes/flow_ledger.py`, `server.py`) · frontend src: **yes** (`pages/FlowLedger`, `services/flowLedger.ts`, `routes.tsx`)

## Summary

The tracker now lives at `/v5/flows` and fills itself from NIDP. The scoring stays in
the page — quarter weights, the ×1.25 consistency bonus, the composite renormalised
over filled streams — because the API returns **input fields, not a verdict**. A
server-computed score would be a second implementation to drift against, and the
page's maths is the part a user can read.

Every auto-filled stream shows the evidence behind its number. Every stream NIDP
cannot source shows the sentence saying why, and stays genuinely unscored — the
composite excludes it and the remaining weights renormalise, so a gap is never
scored as neutral.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | build | clean tree off `dev` compiles | build | `✓ built` | PASS |
| TC-2 | e2e | page renders, no error boundary | e2e | header visible | PASS |
| TC-3 | e2e | empty ledger scores nothing | e2e | `AWAITING DATA`, coverage 0% | PASS |
| TC-4 | e2e | auto-fill writes real QoQ into the fields | e2e | −147/−42/44/−56 | PASS |
| TC-5 | e2e | composite computed in-page, excludes gaps | e2e | coverage 70% | PASS |
| TC-6 | e2e | unsourceable stream shows its reason | e2e | reason + `unfilled` | PASS |
| TC-7 | e2e | filled stream shows its evidence | e2e | filings, down days, OI | PASS |
| TC-8 | e2e | no name → no API call | failure | notice, zero requests | PASS |
| TC-9 | e2e | 502 reads as transport failure, not empty data | failure | error, verdict unchanged | PASS |
| TC-10 | e2e | sector mode fills all four streams | e2e | coverage 100% | PASS |
| TC-11 | data | backfill survives an unstorable row | edge | sweep continues | PASS |

## Playwright (TC-2 … TC-10)

Mocked with the **real** responses from `/v1/flows/ledger/*` on `nidp_staging`, not
invented fixtures — RELIANCE's −147/−42/44/−56 bps are the exchange filings, and both
unavailable reasons are the strings the API actually returns.

```
$ npx playwright test e2e/tests/flow-ledger.spec.ts --project=desktop-chrome
  ✓ auth setup — inject dark-theme localStorage (6.0s)
  ✓ renders without an error boundary (3.1s)
  ✓ starts with nothing scored — an empty ledger must not read as neutral (3.0s)
  ✓ auto-fill puts the real QoQ values into the tracker's own fields (2.9s)
  ✓ the composite is computed in the page and excludes unfilled streams (3.1s)
  ✓ an unsourceable stream shows its reason instead of a score (2.9s)
  ✓ a filled stream shows the evidence behind its number (3.0s)
  ✓ auto-fill without a name does not call the API (2.5s)
  ✓ a 502 reads as a data-service problem, not as an empty company (3.1s)
  ✓ fills all four sector streams and reports full coverage (1.6s)

  10 passed (23.1s)
```

TC-9 is the one worth naming: a transport failure must not render as "no data for
this company", because that is a legitimate and completely different answer. The
error names itself, nothing is overwritten, and the verdict stays `AWAITING DATA`.

## Build (TC-1)

```
$ npm run build          # clean worktree off origin/dev
✓ built in 19.81s
```

Building in `/app` fails on `TS7006` in `frontend-v5/src/pages/Webinar/index.tsx` —
an **untracked** file that is not on `dev` and not part of this change. Verified in a
clean tree for that reason.

## Design notes

- **The proxy is deliberately not best-effort.** `copilot_widgets._daas_get` returns
  `None` on any failure so a widget degrades quietly — correct for a widget, wrong
  here: this endpoint's whole job is to report what NIDP knows, so a silent `None`
  would render as an empty company and be indistinguishable from a real gap. It
  raises 502/503 instead.
- **The proxy forwards symbols and sector names only**, validated against regexes, so
  it cannot be used to reach an arbitrary DaaS path.
- **`window.storage` → `localStorage`.** The original was an artifact API; snapshots
  now persist per browser under `flowledger:`.
- **The DaaS key is read from both `NIDP_DAAS_API_KEY` and
  `NIDP_DAAS_INTERNAL_TOKEN`** — the same asymmetry that silently killed
  `copilot_widgets` on staging.

## TC-11 — a crash the backfill hit while this was being built

The universe sweep died at 22.3% coverage:

```
asyncpg.exceptions.NumericValueOutOfRangeError: numeric field overflow
DETAIL: A field with precision 8, scale 4 must round to an absolute value less than 10^4.
```

An older filing carries a percentage ≥ 10⁴ — the same corruption family as the
`public_pct = 9904` already in the table. Because the writer uses `executemany`, one
bad filing aborts the whole batch and ends the run. Such rows are now dropped and
counted (never clamped — clamping would invent a plausible value for a filing whose
real one is unknown), and a per-symbol write failure no longer ends the sweep.
Restarted: coverage moved past the crash point to **24.1%**.

## UNVERIFIED

- **Not run against deployed staging over HTTP.** The Playwright layer mocks the
  network at the browser; the page has not been loaded against
  `staging.niveshcopilot.com` because that needs a session token and a deploy of both
  the app backend and the DaaS router.
- **The backfill is still running** — 24.1% at the time of writing, from a 17.6%
  baseline. Final coverage is not yet known.

## Deliberately not ported

The artifact's hardcoded `NIFTY 50` tables (`N50_QOQ`, `NIFTY50`) were manual research
standing in for data NIDP did not have. It has it now, and the artifact's own note
warns those two tables use different bases and must never be mixed. Keeping stale
hardcoded numbers beside live ones invites exactly that. They can return as a live
table if wanted — say so and it is a small addition.

## Inputs required from user

- none

## Verdict: PASS
