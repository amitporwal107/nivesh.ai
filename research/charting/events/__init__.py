"""Historical pattern event dataset -- docs/charting.md S35.2 ("Historical event dataset",
"Versioning") and cost PRD Phase 4 (S36; `.claude/workspace/charting-pattern-engine/
prd-transaction-cost-tax-v1.md` S18, S21, S22, S26-S30).

Public surface:
  - `extraction.extract_events` / `extraction.extract_events_multi` -- one row per confirmed
    pattern instance (task item 1-5).
  - `controls.random_control_rows` / `controls.buy_next_open_baseline_rows` -- S18.3 comparison
    groups, same row schema (task item 8; infrastructure only, never run for results here).
  - `writer.write_run` -- hashed, immutable run-folder artifact writer (task item 7).
  - `pipeline.build_event_dataset` -- the top-level entry point: per-symbol extraction, the S35
    pre-sealed/post-sealed segment guard, and an optional `writer.write_run` call, in one place.
  - `costs_bridge.CostConfig` -- every cost-engine knob this package exposes, with its defaults.
  - `schema` -- shared constants/version stamps/the "level broken" per-family mapping.
  - `stops` -- docs/charting.md §37.2/§37.3: the initial stop (Layer 1 structural + Layer 2 ATR
    floor), the §37.2 targets, and the per-horizon target/stop outcome walk (task item 1-4).

Nothing in this package edits `patterns.py`, `context.py`, `config.py`, `replay.py`,
`research/costs/*` or `research/index_history/*` -- it only imports their public functions.
"""
from research.charting.events import controls, costs_bridge, extraction, outcomes, pipeline, schema, stops, writer

__all__ = ["controls", "costs_bridge", "extraction", "outcomes", "pipeline", "schema", "stops", "writer"]
