# Functionality Verification Report — Mark only the first touch of each level

Date: 2026-09-30 · Branch: `fix/paper-chart-first-touch` · Base: `origin/dev` @ 6c16f6d2

## Defect

Found by inspecting the staging screenshot of OLAELEC (the trade opened from Replay 2025-08-28):
the swing chart drew **five "target" arrows across six sessions**. `target_hit` and `stop_hit` are
per-session facts, so once price sits beyond a level every later session flags too. Five arrows
read as five separate events when it was one level reached and then held.

## Fix

Mark the first session that reaches each level, at most one target arrow and one stop arrow per
trade. On a session flagging both, the stop wins — the conservative reading, and the one the exit
rules already apply (`rules_v1` `same_session_tie`).

`data-marks` now counts markers actually drawn, so the debug attribute and the picture cannot
disagree; the test would otherwise assert a number the eye never sees.

## Test cases

| id | case | result |
|---|---|---|
| TC-PC5 | only the first touch of each level is marked; at most 2 per trade | PASS |
| TC-PC5b | a level held across five sessions still marks once | PASS |

## Real output

```
$ npx tsc --noEmit -p tsconfig.json
(no output)

$ npx playwright test e2e/tests/research-paper-trade-chart.spec.ts --reporter=line
  16 passed (41.5s)

$ npx playwright test research-paper-trades research-paper-trade-chart \
                      research-chart-trade-levels --reporter=line
  32 passed (1.2m)
```

Screenshot with an OLAELEC-shaped fixture (target reached on session 2 and held):

```
flagged sessions: 5 | marks drawn: 1
```

Inspected: a single arrow on the first flagged session, where there were five before.

## Limits

Cosmetic only — no level, exit rule or number changes. UNVERIFIED on staging until deployed.

## Verdict: PASS
