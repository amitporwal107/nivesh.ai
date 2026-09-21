"""Early Pattern Formation, Readiness & Validation — docs/charting.md §34.

Package A of the charting-pattern-engine build (CHART-S24..S27). This package detects
Stage 1-3 pre-breakout structure (§34.3) and scores it, entirely separate from
`research.charting.patterns`' confirmed (post-breakout) population — see
`records.POPULATION` and SNAPSHOT_SCHEMA.md's own `"population": "CONFIRMED | EARLY"`
contract, which already reserves this split.

Point-in-time rule (repo-wide, restated because this package's whole reason to exist is
getting it right for a checkpoint that looks "backwards" at a completed pattern): a value
computed "at bar t" may read `bars[0..t]` only. §34.7.1 (approved 2026-09-21) adds a second,
narrower rule for the offline validation study: a checkpoint's *value* may never depend on
`t_end` (the bar where a completed pattern finished) — only its *bar index* may be used, to
pick `t_ck`, before every actual computation is redone from data physically truncated at
`t_ck`. See `maturity.py` for both definitions and `tests/test_early_lookahead.py` for the
poisoned-future proof.

Scope decision (documented, not a silent gap): v1 of this package detects a single shape —
a rectangle/range-bound consolidation, matching the only fixtures available in
`tests/synth.py` (RECT-1). The pattern-specific triangle/cup-and-handle/flag signals in
§34.6 are deferred; this package's job is the maturity + four-score machinery required by
§34.5/§34.7.1, not a second full geometry engine duplicating `patterns.py`.

Modules:
    maturity  — §34.7.1 live vs. offline maturity definitions, never merged.
    scoring   — §34.5 four independent scores (formation/readiness/confirmation/failure_risk)
                plus the six illustrative components, combined only via
                `CONFIG["early_score_weights"]` where an aggregate is needed.
    records   — Stage 1-3 candidate detection + `EarlyFormationRecord`, population="EARLY".
"""
