# SURAKSHA prototype — test cases (authored BEFORE implementation)

Per `.claude/VERIFICATION_PROTOCOL.md` §1. Scope = the 3 demos in the build spec.
Runner: `acceptance.py` (stdlib only, drives the real HTTP API of a running `app.py`).

| # | ID | Type | Demo | Case | Expected |
|---|----|------|------|------|----------|
| 1 | T01 | api | — | `GET /api/candidates` after startup seed | 6 candidates C1..C6 returned; no passphrase field leaked |
| 2 | T02 | api | D2 | `POST /api/exam/open` **before** window start | HTTP 403, `reason=REFUSED_EARLY`, no paper body |
| 3 | T03 | ledger | D2 | ledger after T02 | a `REFUSED_EARLY` row exists for that candidate |
| 4 | T04 | api/edge | D2 | `POST /api/exam/open` after window with **wrong** passphrase | HTTP 403, `reason=REFUSED_AUTH`, ledgered |
| 5 | T05 | api | D2 | `POST /api/exam/open` after window, correct passphrase (C1) | HTTP 200, 10 questions, watermark == `CANDIDATE-C1` |
| 6 | T06 | api | D1 | open C2 with correct passphrase | HTTP 200; C2's item sequence **differs** from C1's |
| 7 | T07 | data | D1 | `GET /api/dashboard` mean-b per variant | every variant `|mean_b| < 0.15`, and pairwise `|Δmean_b| < 0.15` |
| 8 | T08 | data | D1 | uniqueness gate | no two candidates share an identical ordered item sequence; no duplicate item inside a variant |
| 9 | T09 | api | D3 | `POST /api/forensics` with C2's exact paper text | `IDENTIFIED`, candidate_id == C2, order match >= 6/10, elapsed < 5000 ms |
| 10 | T10 | api | D3 | forensics with lorem-ipsum / random text | `FABRICATED` |
| 11 | T11 | api/edge | D3 | forensics with a **partial** paper (first 6 questions only) | still `IDENTIFIED` as C2 (graceful degradation) |
| 12 | T12 | api/edge | D3 | forensics with the correct 10 stems but in a **different order** | NOT identified as C2 — proves order (not item identity) is the watermark |
| 13 | T13 | crypto | D2 | grep the SQLite file for an assembled paper's watermark string / rendered variant | zero hits — no assembled paper at rest in plaintext |
| 14 | T14 | api | — | `GET /api/ledger/verify` on an untouched chain | `ok: true` |
| 15 | T15 | failure | — | mutate one ledger row directly with `sqlite3`, re-verify | `ok: false`, `broken_at` == the exact mutated row id |
| 16 | T16 | api | — | `POST /api/exam/submit` for C1 | returns score/total; `EXAM_SUBMITTED` ledgered |
| 17 | T17 | e2e | D1,D2,D3 | Playwright: terminal refuses pre-window, renders paper + watermark post-window, C1≠C2 questions, dashboard forensics names C2 and stamps lorem FABRICATED | all assertions green |

Edge/failure cases deliberately covered: wrong passphrase (T04), unknown candidate (in T04 path),
pre-window (T02), partial artifact (T11), reordered artifact (T12), fabricated artifact (T10),
tampered ledger (T15).

Explicitly **not** built (per build spec "EXPLICITLY CUT"): quorum UI, attestation, IRT scoring,
device-kill, admin vault API, React, auth sessions.
