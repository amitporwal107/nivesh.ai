# Functionality Verification Report — SURAKSHA leak-proof exam prototype (v0.1)

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-07-27
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** **local only** — `http://127.0.0.1:8000`, self-contained FastAPI process + SQLite.
  This is a standalone demo prototype in `suraksha/`; it touches **no** Nivesh/NIDP code, DB, or
  service, and is therefore not deployed to staging. See "Scope note" below.
- **Changed areas:** backend routes/services (Nivesh): **no** · frontend src (Nivesh): **no** ·
  new isolated directory `suraksha/`: yes

## Summary

Built the 1-hour SURAKSHA prototype exactly to the build spec: one FastAPI process (`suraksha/app.py`),
three vanilla HTML/JS pages, SQLite, no React/docker/microservices. It demonstrates the three required
demos — D1 unique-but-equal-difficulty papers, D2 time-locked + biometric-gated key release, D3
permutation-watermark forensics that names a leaker and stamps a fake `FABRICATED` — plus the
append-only hash-chain ledger. Everything below is real, unedited output from a **cold run** (fresh
process, deleted DB) performed this session.

## Scope note (why local, not staging)

The verification protocol's staging requirement targets Nivesh/NIDP product code. This prototype is a
separate, self-contained artifact whose entire point is to run on one laptop with no external
dependency; there is no staging surface for it, and deploying it to staging would be out of scope for
the ask. Verification is therefore the prototype's own acceptance suite + Playwright, run locally
against the real running process — not simulated, not partial. Nothing under `backend/` or
`frontend*/src/` was modified in this session.

## Test Cases

Authored **before** implementation in [`suraksha/TEST_CASES.md`](../suraksha/TEST_CASES.md).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| T01 | seed | `GET /api/candidates` after startup | api | 6 candidates, no passphrase leaked | PASS |
| T02 | vault | key request **before** window | api/failure | 403 `REFUSED_EARLY`, no paper | PASS |
| T03 | ledger | refusal is recorded | api | `REFUSED_EARLY` row for C1 | PASS |
| T04 | identity | wrong biometric after window opens | edge | 403 `REFUSED_AUTH`, no paper | PASS |
| T05 | vault | window + correct biometric (C1) | api | 200, 10 questions, `CANDIDATE-C1` | PASS |
| T06 | assembly | C2's paper vs C1's | api | different item sequence | PASS |
| T07 | assembly | difficulty parity | data | all \|mean_b\|<0.15, pairwise Δ<0.15 | PASS |
| T08 | assembly | uniqueness gate | data | 6 distinct ordered variants, no intra-variant repeat | PASS |
| T09 | forensics | real leak of C2's paper text | api | `IDENTIFIED` C2, ≥6/10, <5 s | PASS |
| T10 | forensics | lorem-ipsum "leak" | api/edge | `FABRICATED` | PASS |
| T11 | forensics | partial leak (6 of 10 questions) | edge | still `IDENTIFIED` C2 | PASS |
| T12 | forensics | same items, **shuffled** order | edge | NOT identified as C2 | PASS |
| T13 | crypto | assembled paper in plaintext at rest? | crypto | zero occurrences | PASS |
| T14 | ledger | verify untouched chain | api | `ok: true` | PASS |
| T15 | ledger | mutate one row via `sqlite3` | failure | `ok:false`, `broken_at` = that row | PASS |
| T16 | exam | autosave + submit | api | score returned, `EXAM_SUBMITTED` ledgered | PASS |
| T17 | UI | 3 demos through the real browser | e2e | all assertions green | PASS |

## API / Endpoint Tests

**Command:** `python3 acceptance.py` (stdlib urllib against the live process), cold run.

```
##########  STARTUP BANNER  ##########
==================================================================
  SURAKSHA prototype ready — http://127.0.0.1:8000
  exam window opens at 00:37:06 (closes 01:07:06)
  candidates: C1/priya/finger1, C2/rohan/finger2, C3/aisha/finger3, C4/vikram/finger4, C5/meera/finger5, C6/arjun/finger6
==================================================================

== T01 seed / candidate roster ==
  PASS  T01  HTTP 200, 6 candidates, no passphrase leaked: [{'id': 'C1', 'name': 'priya'}, {'id': 'C2', 'name': 'rohan'}, {'id': 'C3', 'name': 'aisha'}, {'id': 'C4', 'name': 'vikram'}, {'id': 'C5', 'name': 'meera'}, {'id': 'C6', 'name': 'arjun'}]

== T02/T03 pre-window key request is refused and ledgered ==
  PASS  T02  HTTP 403 REFUSED_EARLY — key requested 299s before window open
  PASS  T03  REFUSED_EARLY row present for C1

== open the window ==
  window now 2026-07-26T19:06:12.763738+00:00 .. 2026-07-26T19:36:12.763738+00:00

== T04 wrong biometric ==
  PASS  T04  HTTP 403 REFUSED_AUTH — biometric mismatch

== T05/T06 key release + per-candidate uniqueness ==
  PASS  T05  C1 watermark=CANDIDATE-C1 questions=10
  PASS  T06  C1=['I013', 'I031', 'I023', 'I011', 'I057', 'I027', 'I053', 'I034', 'I059', 'I035']
              C2=['I038', 'I001', 'I016', 'I010', 'I029', 'I021', 'I034', 'I006', 'I035', 'I044']

== T07 difficulty parity ==
  PASS  T07  mean_b={'C1': -0.0006, 'C2': 0.002, 'C3': 0.0003, 'C4': -0.0146, 'C5': 0.0007, 'C6': -0.0004} max_pairwise_delta=0.0166 tol=0.15

== T08 uniqueness gate ==
  PASS  T08  6 distinct ordered variants, no repeat inside a variant (C1∩C2 share 2 items — set alone does not identify)

== T09 forensics on a real leak (C2) ==
  PASS  T09  IDENTIFIED C2 (rohan) order=10/10 options=10/10 in 6.2ms (wall 21ms); runner-up C1 order=0/10

== T10 fabricated artifact ==
  PASS  T10  FABRICATED (best 0/10, threshold 6) 14.5ms

== T11 partial leak (first 6 questions only) ==
  PASS  T11  IDENTIFIED C2 order=6/10 from 645 chars

== T12 same items, different order -> must NOT be C2 ==
  PASS  T12  FABRICATED (best None 1/10) — order IS the watermark

== T13 no assembled paper in plaintext at rest ==
  PASS  T13  watermark string occurrences in suraksha.db: 0; 6 variant blobs, none containing readable stems (the item BANK is plaintext by design — assembled papers are not)

== T14 ledger chain intact ==
  PASS  T14  ok=True rows=22 head=ea36e706b9cda62c…

== T15 tamper one ledger row -> detected at that exact row ==
  PASS  T15  edited row 13 -> broken_at=13 (row 13 content was modified after it was written); restored -> ok=True

== T16 answer autosave + submit ==
  PASS  T16  score=1/10 answered=10, EXAM_SUBMITTED ledgered

==============================================================
  16/16 cases passed — ALL PASS
==============================================================
ACCEPTANCE_EXIT=0
```

Standalone ledger-tamper run (`python3 tamper_demo.py`), acceptance step 9:

```
before tamper : {'ok': True, 'rows': 37, 'broken_at': None, 'head': 'b347d2500de60f142e4829a61fba4f21f9ac5411b09e2e63adddd80c5396319f'}
target row    : id=13 actor=C1 action=KEY_RELEASED detail='biometric=OK window=OK bytes=2256'
after tamper  : {'ok': False, 'rows': 37, 'broken_at': 13, 'reason': 'row 13 content was modified after it was written'}
after restore : {'ok': True, 'rows': 37, 'broken_at': None, 'head': 'b347d2500de60f142e4829a61fba4f21f9ac5411b09e2e63adddd80c5396319f'}

RESULT: PASS — tamper detected at the exact row
```

## UI / Playwright Tests

- **Spec:** `suraksha/e2e/suraksha.spec.ts` (Playwright 1.60.0, chromium)
- **Command:** `npx playwright test` (from `suraksha/`), cold run

```
Running 6 tests using 1 worker

  ✓  1 e2e/suraksha.spec.ts:17:5 › D2a — pre-window key request is refused, paper stays sealed (1.2s)
  ✓  2 e2e/suraksha.spec.ts:24:5 › D2b — wrong biometric is refused (675ms)
  ✓  3 e2e/suraksha.spec.ts:31:5 › D2c — window + biometric releases the key and renders the watermarked paper (771ms)
  ✓  4 e2e/suraksha.spec.ts:43:5 › D1 — C2 gets a different paper; dashboard shows equal difficulty (1.5s)
  ✓  5 e2e/suraksha.spec.ts:62:5 › D3 — a leaked paper names its leaker; a fake one is stamped FABRICATED (1.5s)
  ✓  6 e2e/suraksha.spec.ts:85:5 › ledger — chain verifies clean from the dashboard (716ms)

  6 passed (9.7s)
PW_EXIT=0
```

## Data Correctness

App test **and** data test — what is actually on disk, not just what the API returned.

```
$ grep -ac 'CANDIDATE-C' suraksha.db
0
$ grep -ac 'mock physics question' suraksha.db
14
$ python -c "... SELECT candidate_id, ciphertext FROM variants ..."
variant blobs: 6
any readable stem inside a sealed variant? False
```

```
$ curl -s http://127.0.0.1:8000/api/ledger/verify
{"ok":true,"rows":37,"broken_at":null,"head":"c389ea02e0f19bdc7ad4e47dc930995245818ba85de22be11ff9dd0d6d319c9e"}

$ python -c "... SELECT candidate_id, LENGTH(ciphertext), HEX(SUBSTR(ciphertext,1,32)) ..."
C1: 2256 bytes  e4f1b8ba7c0a5102b7e5fdd86f4acc730316e4739863b4d53fd56f92381fe4cb...
C2: 2210 bytes  adc5a27d3ccb21dab8196e18b002cf620611ade3901d713eb37391023f828cd9...
C3: 2208 bytes  be9c5243b8e661b036f98d9b9a8aa86c9724a2e36ad278a034f2b94723df4ca1...
C4: 2225 bytes  288a58735a027592e8afbca81e4f2c778ddb819369a5eed97560dc679798f8ce...
C5: 2221 bytes  e1d65aa8330bbe81cb3585bb801c372d2a951bb2658ef8dbf374e43db6f6d206...
C6: 2215 bytes  3b0891104466b13fa8f189bee3197162018a5094a21c18096fb3d29a175915d0...
```

**Result: PASS, with one honest qualification.** No **assembled paper** exists in plaintext at rest
(0 watermark hits; 6 sealed AES-256-GCM blobs, none containing a readable stem). The 14 hits for
`mock physics question` are the **item bank** (`items` table), which is plaintext by design — in the
real architecture the bank is a separately-controlled service. The PRD's success criterion "no
plaintext paper ever exists at rest" is met for assembled papers, which is the leakable artifact;
it is **not** met for the raw bank, and the README states this explicitly.

## Bug found and fixed during verification

`POST /api/forensics` omitted a top-level `total` field that both `acceptance.py` and
`dashboard.html` read — the dashboard verdict line would have rendered `undefined`. Caught by T09
on the first run (`KeyError: 'total'`), fixed in `app.py`, and both suites re-run cold afterwards.

## Deliberately NOT built (per the build spec's "EXPLICITLY CUT")

Quorum/break-glass UI, device attestation, IRT ability scoring/equating, device-kill + resume,
admin vault API, React, auth sessions. The PRD specifies these as FR-12/FR-21, FR-26, FR-29 — they
are absent, not stubbed, and the README says so.

## Known simplifications (documented in `suraksha/README.md`)

- Decryption is **server-side**, not in-browser WebCrypto — the build spec sanctioned this
  ("server decrypt is fine, note it in README as simplification"). The zero-knowledge boundary is
  therefore demonstrated at the storage layer only.
- Master key is `os.urandom(32)` in one process (ephemeral; papers are re-sealed on restart), not an
  HSM and not custodian-split.
- "Biometric" is a passphrase behind a fingerprint-styled field. No UIDAI, no sensor, no liveness.
- No authentication on the admin/dashboard routes — anyone who can reach the port can move the window.

## Inputs required from user

- none

## Verdict: PASS
