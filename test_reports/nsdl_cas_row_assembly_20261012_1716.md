# NSDL eCAS extractor: multi-line holding rows

Date: 2026-10-12 · Area: `backend/services/nsdl_cas_extractor.py` · Commit `cfb302fd` · Env: staging (CloudPe)

## Problem

Importing an August-2026 NSDL eCAS ended in "Offline parser found no holdings". The
custom NSDL extractor ran first but rejected most rows as malformed, failed
reconciliation, and the chain fell through to the offline `casparser` library.

Cause: the extractor parsed one text line per holding, while the PDF's text layer
delivers a row as one to five lines when cells are stacked. Seven layouts were found in
the statement (equity ×4 incl. preference, demat MF ×1, folio ×2).

## Change

`_assemble_row` rebuilds the single-line form `ISIN name <columns>` from the ISIN line
and its neighbours, per asset class. Single-line rows are returned unchanged.

## Test cases

| # | Case | Expected |
|---|---|---|
| U1–U13 | Unit tests, one per layout plus guards (made-up ISINs and figures) | pass |
| R1 | Real statement: rejected rows | 0 |
| R2 | Real statement: each class total vs the printed Portfolio Composition | diff 0.00 |
| R3 | Real statement: grand total vs printed | diff 0.00 |
| R4 | Real statement: units × price = value on every E/P/M row | 0 exceptions |
| R5 | Pledged quantity is not read as the holding quantity | covered by U3, U8, R4 |

## Results

Unit tests (`python -m pytest tests/test_nsdl_cas_row_assembly.py`, in the staging backend image):
```
.............                                                            [100%]
13 passed in 0.05s
```

Real statement, run inside the running staging backend container after the CI deploy
(`Deploy backend → CloudPe app VM [staging]`: success). Amounts are deliberately not
recorded here; the statement and its password are kept out of the repo.
```
holdings=117 malformed=0 reconciled=True grand_total_diff=0.0
  class E   ok=True diff=0.0  rows=45
  class P   ok=True diff=0.0  rows=1
  class M   ok=True diff=0.0  rows=17
  class SGB ok=True diff=0.0  rows=1
  class F   ok=True diff=0.0  rows=53
monthly trend points: 13 | statement date: 31-Aug-2026
E/P/M rows where units x price != value: 0
```

Before the change, same statement, same container image:
```
holdings=16 malformed=48 reconciled=False
```

Staging API after deploy:
```
GET https://staging.niveshcopilot.com/api/healthz → HTTP 200 {"status":"ok","service":"portfolio_ingestion","version":"0.1.0","env":"staging"}
```

## Not verified

- The HTTP import end to end (`POST /api/onboarding/gmail/auto-import` or
  `/api/onboarding/upload-cas`) with a real signed-in session, and the holdings then
  shown in the app. That needs the account owner to retry the import.
- Other NSDL statement vintages: only this one real statement was available. Rows that
  are already on a single line take the unchanged path.

## Verdict: PASS
