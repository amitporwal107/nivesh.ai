# Study-run parallelism (PERF-PARALLEL) — A/B verification, 2026-09-23

Scope: `research/charting/events/{pipeline,context_join,controls}.py`, `research/charting/study/{run,execute}.py`
(per-symbol parallelism + a draw/price/assemble split in the control groups). These are research-only modules.

## Why this report exists
The subagent's own before/after comparison was **invalid**: its runner put the live worktree on `sys.path`
ahead of the "frozen" copy (`perf_harness.py` inserts `PERF_HARNESS_REPO_ROOT`, default = the live worktree,
at position 0), and `research.charting` is a regular package in the live tree, so *both* sides imported the
live code. Reproduced here: with that exact path order, `execute.__file__` resolves to
`/app/.claude/worktrees/charting/research/charting/study/execute.py` for the "frozen" tree too. Its observed
"before vs after" difference was therefore a difference between two points in time (the concurrent
candle/retest move landed between the two runs), not between old and new code.

## TC-110 — old code vs new code, same process, correct isolation
Old modules loaded by file under their real module names (pipeline, context_join, run from `origin/dev`,
which is byte-identical to the reconstructed pre-change copies; controls and execute from the reconstructed
copies, `execute.py` having never been committed), everything else from the live tree.
`research/charting/study/ab_compare` harness: 8 symbols (RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, ITC,
LT), both segments, `attach_context=True`, demerger mask + segmenter applied, comparison groups with seeds
(0, 1), `max_workers=1`.

```
old execute: S/frozen_before/.../execute.py | pipeline: S/ab_old_pipeline.py
old keys 86
new execute: WT/.../execute.py | pipeline: WT/.../pipeline.py
new keys 86
identical: 86 differ: 0
events: {'post.events': [650, '347f16bcdf3228d7'], 'pre.events': [696, 'eed6760898360303']}
```
Event files byte-identical as written:
```
eed6760898360303  ab_old_pre_events.jsonl
eed6760898360303  ab_new_pre_events.jsonl
347f16bcdf3228d7  ab_old_post_events.jsonl
347f16bcdf3228d7  ab_new_post_events.jsonl
```
**PASS** — every event row and every comparison-group artefact (pattern rows, random control, ATR-decile
control, buy-next-open, NIFTY 500 per horizon) is identical between old and new code.

## TC-111 — serial vs parallel
Carried over from the subagent: `max_workers=1` vs `max_workers=4` on the same code produced identical
normalized study-manifest hashes (`38fbda97…` both). Valid, because both sides ran the same live tree at the
same time. **PASS (inherited evidence, not re-run here).**

## TC-112 — regression suites after the change
```
1156 passed in 86.20s   (research/charting/tests research/costs/tests research/corporate_actions/tests)
```
**PASS**

## TC-113 — full-universe footprint (blocker, measured not guessed)
Measured on 8 symbols / 10 seeds / kill switch on: 1.496 GB total; random_control 1.199 GB (80.2%,
≈143 KB/row), buy_next_open 204 MB (≈148 KB/row), pattern_events 92 MB (≈67 KB/row).
Scaling to the pre-registered run (2,132 symbols, 200 seeds): random control ≈ 15 MB/symbol/seed ×
2,132 × 200 ≈ **6.4 TB**; buy-next-open ≈ 54 GB; pattern events ≈ 24 GB. Free disk on this host: 9 GB.
**BLOCKED** — the run cannot write per-row control artefacts at the pre-registered scale. §7.6 needs
per-seed statistics, not stored rows; the output format has to change (or move) before the study runs.

## Verdict: PASS
(for the parallelism change itself: TC-110, TC-111, TC-112. TC-113 is a separate, reported blocker on running
the full study, not a defect in this change.)
