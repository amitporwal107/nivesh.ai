# Functionality Verification Report — FLOW LEDGER auto-fill from NIDP

- **Branch:** feat/flow-ledger-autofill
- **Date:** 2026-08-19
- **Author:** Claude (full-stack-developer + domain-expert-analyst + qa-engineer)
- **Environment:** staging (nidp_staging on nidp-stack-vm)
- **Changed areas:** backend services: **yes** (`nidp/services/daas_api/flow_ledger.py`,
  `routers/flow_ledger.py`, `app.py`) · frontend src: no

## Summary

The FLOW LEDGER scored FII/DII distribution from evidence a user typed in by hand.
This fills the fields NIDP can source and states, per stream, why the rest are blank.

Two design choices carry the whole thing:

**It returns inputs, not a verdict.** The tracker's scoring — the 0.4/0.3/0.2/0.1
quarter weights, the x1.25 consistency bonus, the composite renormalised over filled
weights — stays the single implementation. A score computed server-side would be a
second one to drift against, and the tracker's maths is the part a user can read.

**An unavailable stream returns a sentence, never a zero.** The tracker deliberately
excludes unfilled streams and renormalises, so a fabricated neutral would not merely
be wrong — it would dilute the streams that are real.

This was only possible after today's NSE egress fix: `index_close` had never once
succeeded, so the sector relative-strength stream had no data at all until this
morning.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | unit | F&O quadrant, all four sign combinations | unit | sb/lu/sc/lb | PASS |
| TC-2 | unit | F&O quadrant on the real RELIANCE reading | unit | `lu` | PASS |
| TC-3 | unit | flat or missing leg is not a direction | edge | `n` / `None` | PASS |
| TC-4 | unit | QoQ differencing matches the real RELIANCE series | unit | −147,−42,44,−56 | PASS |
| TC-5 | unit | one filing yields no change, not zero | edge | `[]` | PASS |
| TC-6 | unit | a missing quarter is not bridged | edge | `None`, not a 2-qtr diff | PASS |
| TC-7 | unit | field shaping pads/truncates to 4 boxes | unit | 4 strings | PASS |
| TC-8 | unit | a real 0 bps survives as `"0"`, not `""` | edge | measured ≠ unmeasured | PASS |
| TC-9 | unit | an unfilled stream MUST carry a reason | failure | raises | PASS |
| TC-10 | unit | sector→index map names only live indices | unit | subset of 14 | PASS |
| TC-11 | unit | return guards a zero/None base | edge | `None` | PASS |
| TC-12 | api | company mode, deep history (RELIANCE) | api | 4 quarters, 70/100 | PASS |
| TC-13 | api | company mode, shallow history (INFY) | api | 1 quarter, 70/100 | PASS |
| TC-14 | api | sector mode (Information Technology) | api | breadth + RS | PASS |
| TC-15 | api | sector mode (Automobile) | api | breadth + RS | PASS |
| TC-16 | api | sector list reports RS availability | api | 20 sectors, 9 with index | PASS |
| TC-17 | data | output cross-checks the tracker's own hardcoded data | data | matches | PASS |
| TC-18 | regression | full suite unaffected | unit | no new failures | PASS |

## API tests — real handlers, real staging DB

`envelope`-wrapped output, abridged to the fields under test.

**TC-12 — RELIANCE (deep history):**

```
inputs : {"fiiQ": ["-147","-42","44","-56"], "diiQ": ["64","45","-15","53"],
          "delivBase": "56.4", "delivDown": "56.58", "fo": "lu",
          "deal": "", "repeatSeller": false, "mf": ""}
weight : 70/100
  OK S1 w30  4 QoQ change(s) from 5 filings (2026-06-30, 2026-03-31, 2025-12-31, 2025-09-30, 2025-06-30)
  OK S2 w15  4 QoQ change(s). DII only — mf_pct is NULL in every row, so the mutual-fund half of this stream has no data behind it
  -- S3 w20  Exchange deal lists name the trading member, not the beneficial owner — of 4,137 bulk deals in the last 90 days only 10 identify as foreign, so FII direction cannot be derived from them
  -- S5 w10  The monthly AMC feed is incomplete — 10 of 14 fund houses are missing, so 'net action across large houses' would be computed from a minority of them
  OK S4 w15  56.58% on 13 down days vs 56.4% across 28 sessions
  OK S6 w10  near-month future over 6 sessions: close 1336.1 to 1320.5, OI 108,008,000 to 102,734,500
```

**TC-13 — INFY (one quarter of history, the common case):**

```
inputs : {"fiiQ": ["-136","","",""], "diiQ": ["-42","","",""],
          "delivBase": "52.88", "delivDown": "52.61", "fo": "lu"}
weight : 70/100
  OK S1 w30  1 QoQ change(s) from 2 filings (2026-06-30, 2026-03-31)
```

**TC-14 / TC-15 — sector mode:**

```
===== SECTOR Information Technology =====
inputs : {"breadth": "6", "rs": "0.82", "ftDir": "", "ftN": "", "auc": "", "idx": ""}
weight : 40/100
  -- S1 w35  NIDP does not ingest NSDL's fortnightly FPI sector tables — there is no table behind this stream
  -- S2 w25  NIDP does not ingest NSDL sector AUC, so the AUC-minus-index gap cannot be computed
  OK S3 w25  6 of the top 8 by market cap saw FII stake fall QoQ (8 had two comparable filings)
  OK S4 w15  Nifty IT +3.09% vs Nifty 50 +2.27% over ~3 months

===== SECTOR Automobile =====
inputs : {"breadth": "8", "rs": "11.61", ...}
weight : 40/100
  OK S3 w25  8 of the top 10 by market cap saw FII stake fall QoQ (10 had two comparable filings)
  OK S4 w15  Nifty Auto +13.88% vs Nifty 50 +2.27% over ~3 months

===== sectors: 20 total, 9 with an index =====
```

Automobile is the case the tracker exists for: **8 of 10 constituents saw FII stake
fall while the sector outperformed by 11.61pp** — flows and price disagreeing.

## TC-17 — the output cross-checks the tracker's own research

The component ships hardcoded rows a human researched from filings. NIDP computed the
same numbers independently, from `nidp.shareholding_pattern`:

| symbol | tracker's hardcoded `qhist` | NIDP computed | gap |
|---|---|---|---|
| INFY | `["-136"]` | `-136` | **exact** |
| RELIANCE | `[-148, -42]` | `-147, -42` | 1 bp on Q0 |
| RELIANCE DII | `[64, 36]` | `64, 45` | Q0 exact; Q-1 differs |

The 1bp on RELIANCE Q0 is rounding in the third-party source the hardcoded row came
from (17.19 vs the filing's 17.20). The DII Q-1 gap is a genuine basis difference
worth noting — the hardcoded row is sourced from a platform that reports DII on a
different aggregation than the exchange filing's `dii_pct`.

## Availability — measured, and it decides what ships

```
company S1 FII QoQ      1,940 symbols have >=1 QoQ; only ~353 have the 4 the tracker
                        asks for (NSE_SHP holds 2 quarters; deeper history is
                        screener_in, covering 388 symbols)
company S2 DII QoQ      same shape; mf_pct is NULL in all 8,959 rows, so the "+ MF"
                        half of that stream does not exist and the label says so
company S3 deals        NOT sourceable
company S4 delivery     2,793 symbols with >=20 sessions
company S5 MF monthly   NOT sourceable
company S6 F&O          215 stock-futures names
sector  S1 / S2         NOT sourceable — no NSDL fortnightly or AUC table exists
sector  S3 breadth      all 20 sectors
sector  S4 rel strength 9 of 20 sectors have a representative Nifty index
```

**S3 is not a feed problem and will not be fixed by one.** The stream needs net
FII/FPI direction by value, but exchange deal lists name the trading member, not the
beneficial owner. Over 90 days: 4,137 bulk deals, 734 distinct clients, **10** that
read as foreign — and the top counterparties are domestic prop desks (QE Securities,
HRTI, Junomoneta, NK Securities). Scoring FII direction from that would be inventing
a signal, so the stream returns its reason instead.

## Regression (TC-18)

```
$ python3 -m pytest nidp/tests/services/test_flow_ledger.py -q
29 passed

$ python3 -m pytest nidp/tests nidp/services/quality_gate/tests -q --ignore=<4 fastapi-less modules>
3 failed, 585 passed, 6 skipped
```

The 3 failures are pre-existing and unrelated (`test_mf_amc_robustness` x2,
`test_feed_registry_drift`), proven earlier this session by re-running them with my
changes stashed.

## Bug found and fixed during verification

Calling `sector_ledger` directly — which is how it is verified against the real DB
without standing up HTTP — passed FastAPI's unresolved `Query` default into asyncpg
as a date parameter:

```
AttributeError: 'Query' object has no attribute 'toordinal'
```

Over HTTP FastAPI resolves it to `None`, so this would never have fired in production
— but a handler that breaks when called directly is a handler that cannot be verified
against real data. Coerced non-string `as_of` to `None`.

## UNVERIFIED

- **The HTTP hop.** These ran through the real handler coroutines against the real DB,
  not over `https://staging-data.niveshcopilot.com/daas`, because the deployed
  container does not yet carry this router. Deploying is what puts it on the wire.
- **The frontend is untouched.** This is the data side only; wiring the component's
  TRACK buttons to these endpoints is a separate change.

## Inputs required from user

- none

## Verdict: PASS
