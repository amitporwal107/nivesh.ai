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

## Blocker section — rewritten (owner directive, 2026-09-23)

The pack's manifest lists six `critical_blockers`:

```
trendline fitted line with intercept · trendline_value_at · production convergence caller
parallelism metric · ADX chart service · stock_vs_sector_relative_strength
```

The first four are **not four items**. They are one chain, and stating them separately overstated
the work by implying four independent builds:

```text
fit_line()  ->  trendline_value_at()  ->  width_ratio() at pivots  ->  classify_pair()
                                                                        |
                                                            CONVERGING / PARALLEL / EXPANDING
```

**Convergence and parallelism must not be certified as separate primitives.** They are two bands of
the same ratio `w`. A certification suite that tests them independently would be testing one
function twice and would imply a channel detector can skip the convergence computation, which is
false.

The manifest's first four entries are therefore superseded by one: **geometry foundation — fitted
lines, projected line values, pivot-based width ratio.** The pack body is filed verbatim and not
edited; this is the correction of record.

### Status: the geometry foundation is delivered (2026-09-23)

| Primitive | Where |
|---|---|
| `Line(slope, intercept)`, `fit_line()` | `research/charting/geometry.py` |
| `trendline_value_at(line, x)` | ibid |
| `width_ratio(upper, lower, first_pivot, last_pivot)` | ibid — measured at pivots |
| `line_direction()` — G4 percentage flatness | ibid |
| `classify_pair()` — five bands, two of them deliberate gaps | ibid |
| NI-3 config loader, fingerprint-verified on load | `research/charting/ni3_config.py` |

35 tests, all passing; full suite 1,122. The frozen v1 `config_hash` is **unchanged** at
`05167d3a…` — the new thresholds are read from the NI-3 configuration, which verifies
`de86626c…` when loaded, so nothing was added to `CONFIG` and the three live families cannot have
been affected.

**The two traps are now hard CI gates**, exactly as directed:

- `test_F2_the_percentage_flatness_rule_is_not_the_atr_drift_rule` — builds a line the ATR test
  calls FLAT and the G4 percentage test calls RISING, and asserts the two verdicts differ. A
  detector using `boundary_drift` for a P-1 family fails here.
- `test_C2_width_is_measured_at_the_pivots_not_at_the_formation_bars` — a structure whose
  pivot-based `w` is PARALLEL (0.884) and whose bar-based `w` is CONVERGING (0.100). The two
  conventions do not merely differ numerically; they emit **different shapes**. A bar-based detector
  would call a channel a wedge.

### What this unblocks

| Wave | Families | State |
|---|---|---|
| A | — | **done** |
| B — head & shoulders, inverse H&S | +2 | unblocked now; needs only the sloped neckline, not the P-1 detector |
| Parallel — double bottom, double top, cup & handle | +3 | never blocked |
| C — the seven P-1 shapes | +7 | unblocked; needs the NI-3 §2 seven-step detector and its 9 fixtures |
| D — the four P-2 flags and pennants | +4 | needs wave C (their bodies are P-1 shapes) |

The registry remains the authority: none of these flips to `enabled` because code exists. Each waits
on its fixture certification and, for P-1, on reproducing fingerprint `de86626c…`.

## Recommended next step

With wave A delivered, the next two are independent and can run in parallel:

1. **Wave B + the three unblocked families** — head & shoulders and inverse H&S need only
   `trendline_value_at`; double bottom, double top and cup & handle need nothing new. That is five
   families, and it takes the registry from 3 enabled to 8 without touching the P-1 engine.
2. **NLA-005** — batch versus sequential replay equivalence. One test, the only uncovered case in a
   release-blocking suite, and exactly the class of defect that stays invisible until a live run
   disagrees with a backtest.

---

# Wave D close-out — implementation complete, certification pending

**Owner position, 2026-09-23:** implementation is frozen here. No further detector behaviour is
added; the remaining path is certification.

All 19 registered families now have detector implementations. **Only the original 3 are enabled**,
and that distinction holds through certification.

## 1. The P-2 reuse is correct

`patterns_p2` delegates to `patterns_p1.evaluate_candidate` rather than duplicating line fitting,
the fit tolerance, containment, crossing or classification. Two copies of the seven-step engine
would drift and only one would be covered by the frozen fixtures.

The `FLAT/FLAT/PARALLEL` handling is correctly localised: P-1 rejects it because the live RECTANGLE
family owns that geometry, while NI-3 §3 permits it as a flag body. The detector reads that specific
rejection reason as a legitimate body shape; nothing is recomputed.

Building the classification table **from** the frozen configuration was what exposed two incorrect
key names (`body_max_retracement_pct`, `body_max_rel_volume`) before they became silently encoded
behaviour.

## 2. The 2% reach rate is measured behaviour, not a defect

Under the frozen NI-3 configuration, across all 50 snapshot symbols:

```text
7,543 valid poles
    -> 4,536 fail the length gates (F3/F4/F5)        60%
    -> 2,860 have fewer than 4 confirmed pivots      38%
    ->   147 reach shape testing                      2%
    ->    20 emitted   (5 bull flag, 15 bull pennant)
```

Recorded as observed behaviour, **not corrected by relaxing F2/F3/F4/F5**. NI-3 §3 discloses the
cause and forbids the fix after results: "If very short flags are wanted, the fix is a smaller body
swing, which would be a new decision before the freeze, never a change after results."

`test_the_disclosed_body_length_limitation_is_real_and_is_not_tuned_away` pins the arithmetic — four
pivots at the 3/3 swing cost need roughly 15 bars, while F3 plus F2 cap a body at 14 — so the
parameters cannot be quietly relaxed to make flags more numerous.

## 3. The bear-side zeroes stay an observation

| | |
|---|---|
| Bull flag | 5 |
| Bull pennant | 15 |
| **Bear flag** | **0** |
| **Bear pennant** | **0** |

There is not enough here to call this a detector defect or a specification defect. It is a question
for study plan v2, consistent with the freeze.

## 4. The fixture lesson is now a testing standard

Seen repeatedly across waves B, C and D: **hand-built OHLCV can fail to exercise the geometry it was
meant to, even when the geometry rule is correct.** Every such failure in this work was a fixture
defect; none was a detector defect.

- A 9-bar separation fixture found nothing because the frozen 10-bar rule correctly rejected it.
- An invalidation fixture fell through a trough, which *displaces it as a swing low*.
- P-1 fixture 7 placed a crossing outside the window the engine selected; then, moved inside, the
  line-built series went degenerate past the crossing and the detected pivots stopped being the
  intended ones.
- A P-2 synthetic produced no body while real data produced 20 patterns.

**Standard:** test a rule at the level the rule lives at. Geometry rules take an explicit pivot
window or fitted lines; only end-to-end behaviour takes a price series. The six §3 fixtures and P-1
fixture 7 follow this.

## 5. What the detection counts do and do not establish

| Observed | Establishes | Does **not** establish |
|---|---|---|
| 14 P-1 shapes over 6 of 7 types | the implementation executes and produces explainable results under the frozen rules | that the 7 P-1 families may be enabled |
| 20 P-2 detections | the same | that the 4 P-2 families may be enabled |
| 132 wave-B/parallel detections | the same | that those 5 families may be enabled |

Certification must still establish the complete detector / replay / no-look-ahead requirements.
**Detection counts never justify enablement.**

## Remaining certification path

```text
19 detector implementations
        -> fixture review
        -> P-0 / P-1 / P-2 replay validation
        -> historical validation
        -> no-look-ahead + determinism verification
        -> certification
        -> explicit registry enablement
```

Every fixture-review finding is classified as **detector defect · fixture defect · replay/lifecycle
assertion · specification decision**. **C-13 stays in the fourth category and must not be resolved
implicitly by certification.**
