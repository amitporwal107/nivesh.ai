# Functionality Verification Report — Event lifecycle engine (Phase 1, part 1)

- **Branch:** feat/event-lifecycle-engine (off dev @43643094, which contains PR #170)
- **Date:** 2026-09-25
- **Author:** Claude (full-stack-developer + qa-engineer)
- **Environment:** staging (nidp_staging)
- **Changed areas:** backend routes/services: **yes** (new `nidp/services/event_lifecycle/`) · frontend src: **no**

## Summary

PRD v1.1 §3/§5.1 require a persistent `transaction_id` spanning a deal's filings. nidp has no such
concept — a repo-wide grep for `transaction_id | event_group | parent_event | deal_id | supersede`
returns nothing, and `stock_events` is one row per filing.

This adds the classification half: family, lifecycle stage, confounding flag and transaction
grouping, as pure functions. Persistence is deliberately NOT in this commit — see the QIP finding
below, which changes how it should be built.

Every rule is derived from the real subject vocabulary in `nidp.corporate_announcements`
(2026-01-19..2026-09-25), not from a specification.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | family | Recognises BUYBACK and QIP_PREF | unit | both | PASS |
| TC-2 | family | Debt buyback is NOT a share buyback | unit/edge | None | PASS |
| TC-3 | family | Reg-32 deviation statements excluded | unit/edge | None | PASS |
| TC-4 | family | Warrant conversions excluded | unit/edge | None | PASS |
| TC-5 | stage | Full buyback sequence in order | unit | 7 stages | PASS |
| TC-6 | stage | Most-specific marker wins | unit/edge | OFFER_CLOSED not ANNOUNCED | PASS |
| TC-7 | stage | Bare subject → UPDATE, never a guess | unit | UPDATE | PASS |
| TC-8 | confounding | Results bundled with the event flagged | unit | True | PASS |
| TC-9 | confounding | Results alone not flagged | unit | False | PASS |
| TC-10 | grouping | One run = one transaction | unit | ordinal 1 | PASS |
| TC-11 | grouping | Long gap starts a new transaction | unit | 1,1,2,2 | PASS |
| TC-12 | grouping | Symbols/families never share | unit | 3 distinct | PASS |
| TC-13 | grouping | 60-day threshold is the boundary | unit/edge | 59→same, 92→split | PASS |
| TC-14 | grouping | Order-independent | unit | identical | PASS |
| TC-15 | data | Runs over the real corpus | data | 176 transactions | PASS |
| TC-16 | data | Exclusions fire on real filings | data | 38 rejected | PASS |

## Unit tests

```
$ /app/research/tpd3_forward/venv/bin/python -m pytest nidp/tests/services/test_event_lifecycle.py -q
................                                                         [100%]
16 passed in 0.04s
```

## Data correctness (staging)

Run over every buyback / QIP / preferential filing resolving to an NSE symbol:

```
candidate filings (naive LIKE): 434
family: {'BUYBACK': 151, 'QIP_PREF': 245, 'None': 38}   confounded with results: 9

TRANSACTIONS: 176 from 396 filings across 162 (symbol, family) pairs
  companies with >1 transaction in the same family: 14
    ALMONDZ QIP_PREF -> 2 · DEVX QIP_PREF -> 2 · ECORECO QIP_PREF -> 2 · GANDHITUBE BUYBACK -> 2
```

The 38 rejections are real filings that mention the family but are not part of its lifecycle —
four "Statement Of Deviation Or Variation In Utilisation" among them, exactly the predicted trap.

Stage distribution:

```
BUYBACK   UPDATE 54 · ANNOUNCED 31 · OFFER_CLOSED 18 · PROPOSED 14 · OFFER_OPEN 13
          RECORD_DATE 12 · APPROVED 7 · COMPLETED 2
QIP_PREF  UPDATE 180 · APPROVED 30 · PROPOSED 26 · COMPLETED 8 · ANNOUNCED 1
```

## FINDING — QIP/preferential cannot be staged from metadata

| Family | Staged from metadata |
|---|---|
| BUYBACK | **64%** (54 of 151 UPDATE) |
| QIP_PREF | **33%** (180 of 245 UPDATE) |

BSE subjects for QIP are mostly the bare category name ("Announcement under Regulation 30
(LODR)-Preferential Issue", n=38). Adding `description` was measured and recovers only 15 of 180
(73% → 67% UPDATE), so the stage information is in the **attachment PDF**.

**Consequence for Phase 1:** buyback can proceed on metadata alone; QIP/preferential needs
`document_parser` integration before its lifecycle is usable. That is a sequencing decision, not a
defect, and it is why persistence is not in this commit.

## Not done

- No persistence — no migration, no `transaction_id` written. Deliberate, pending the QIP decision.
- `v_announcement_security` (migration 154) does not expose `description`; the probe joined back to
  `corporate_announcements`. Worth adding if the service needs it.
- Linking accuracy vs a human-labelled gold set (PRD §15.2 Phase-2 exit gate, >=97%) NOT measured.
  The 176 transactions are self-consistent but unvalidated against ground truth.

## Inputs required from user

- none

## Verdict: PASS
