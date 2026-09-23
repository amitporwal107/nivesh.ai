# Certification pack v2.0 — coverage assessment against the code

Date: 2026-09-23
Pack: `docs/certification/CHARTING_CERTIFICATION_PACK_V2.md` (1,545 lines, 41 sections)
Checked against: `research/charting/` (831 test functions in 56 files, 1,087 assertions passing)

## Verdict

The pack is **consistent with `docs/charting.md` §39 and with the code**. Its registry counts, its
six critical blockers and its volume rules all match what the code actually does — checked
programmatically, not by eye. Two of its suites are **already largely certified** by tests that
exist today, and in one respect our tests are stronger than the pack requires.

## What the pack asks for

| Suite | Cases | Subject |
|---|---|---|
| `PIV-001..009` | 9 | pivot detection and confirmation lag |
| `NLA-001..006` | 6 | no-look-ahead (marked a **release blocker**) |
| `GEO / LIFE / BRK / VOL` | 24 | per-detector geometry, lifecycle, breakout, volume |
| `PAT-*` matrix (§30) | 29 × each enabled detector | the same, applied per family |
| Research gates `R1..R9` | 9 | research integrity |

## Already certified by existing tests

### PIV suite — 8 of 9 covered

| Case | Covered by |
|---|---|
| PIV-001 normal high / PIV-002 normal low | `test_swings.py: test_find_swings_detects_a_simple_high_and_low_pivot_on_the_same_bar` |
| PIV-003 equal high | `test_tie_rule_equal_highs_resolves_to_the_latest_bar` |
| PIV-004 equal low | `test_tie_rule_equal_lows_resolves_to_the_latest_bar` |
| PIV-005 tie handling | `test_tie_rule_three_way_plateau_only_the_last_bar_wins`, `test_find_swings_raises_on_an_unsupported_swing_tie_rule` |
| PIV-006 insufficient future bars | `test_find_swings_ignores_candidates_too_close_to_either_edge` |
| PIV-007 replay as-of | `test_lookahead.py: test_swings_as_of_is_unaffected_by_poisoning_every_bar_after_t` |
| PIV-008 future-bar mutation | same |
| PIV-009 deterministic repeat | `test_replay.py: test_replay_is_deterministic_across_repeated_runs_same_input` |

Plus `test_confirmation_lag_is_exactly_right_bars`, which pins `pivot_confirmed_at = pivot_bar +
right_bars` directly — the rule §39.4 owns.

### NLA suite — 5 of 6 covered

| Case | Covered by |
|---|---|
| NLA-001 sequential replay | `test_b1_nothing_dated_at_or_before_t_plus_2_differs` |
| NLA-002 future price mutation | `test_patterns_lookahead.py: test_detect_as_of_unaffected_by_poisoning_every_bar_after_t` |
| NLA-003 future volume mutation | same file — the poisoning fixture writes `volume = 9_999_999.0` into future bars |
| NLA-004 future pivot mutation | `test_swings_as_of_is_unaffected_by_poisoning_every_bar_after_t` |
| NLA-006 incomplete candle | `test_incomplete_bar_poisoning_does_not_affect_completed_bar_output` |

**Our tests exceed the pack here.** The suite carries **negative controls** —
`test_negative_control_peeking_detector_leaks_future_into_the_past_view`,
`test_negative_control_a_three_bar_peek_is_caught_for_sr_and_hh_hl`, and three more. These prove the
*test itself* can detect a leak, which is the failure mode a no-look-ahead suite is most exposed to:
a test that passes because it is blind. The pack does not ask for this; it should.

## Genuine gaps the pack surfaces

| Gap | Why it matters |
|---|---|
| **NLA-005 — batch vs sequential equivalence** | No test asserts that a batch replay result equals the sequential one. `test_replay.py` proves repeat-determinism on the *same* input path, which is a different property. This is the one NLA case not covered, and NLA is a declared release blocker. |
| Per-detector `PAT-*` matrix applied uniformly | Coverage today is thorough but organised by module, not by the 29-case grid per family. Certifying against the grid would show holes per family rather than per module. |
| `GEO-003 boundary tolerance` / `GEO-006 invalid geometry` for HH_HL | `test_patterns.py` covers rectangle and S/R boundary cases more heavily than HH_HL. |

## Where the pack and §39 differ

Both are recorded rather than silently reconciled; **§39 governs**.

| Topic | Pack | §39 | Note |
|---|---|---|---|
| Class C indicators | §9 and §26 specify ADX certification in detail | §39.7/§39.9 mark all Class C as PROPOSED, unfrozen, outside fingerprint `de86626c…` | Agreement in substance — the pack's §26 is a *future* certification, not a claim that ADX is served. §39.10 records that ADX is a private `regime` helper. |
| Fitted geometry | §27 "fitted geometry prerequisites" | §39.15 prerequisites | Same four items, same order. |
| Flatness | §28 certifies both conventions separately | §39.8 + §39.16 C-1 | Agreement: the split by family group is deliberate and must not be harmonised. |

## What is blocked, and why it is not a test problem

The pack's §38 readiness split matches §39.10. Of its 16 disabled families, none can be certified
because none can be detected: the fitted line with an intercept, `trendline_value_at()`, a production
convergence caller and a parallelism metric do not exist. The certification suites for those families
are therefore **specifications, not pending tests** — writing them now would produce 16 families'
worth of tests that cannot run.

The exception worth acting on: **double bottom, double top and cup & handle need no fitted line** —
only swing, ATR and similarity tolerances, all of which exist. They are the cheapest families to move
from "specified" to "certified".

## Recommended next step

Close **NLA-005** first. It is one test, it is the only uncovered case in a release-blocking suite,
and batch-versus-sequential divergence is exactly the class of defect that stays invisible until a
live run disagrees with a backtest.
