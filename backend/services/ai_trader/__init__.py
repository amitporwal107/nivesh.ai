"""AI Trader, Phase 1 (docs/prd/AI_TRADER_PHASE1.prd.md): the evidence foundation.

Read-only analytics. Nothing here places, sizes or suggests an order; brokers are not touched. Every number comes from
the point-in-time functions in research/charting (the sealed 2023-01-01..2024-07-31 block is never read) and is
returned as an `Evidence` record, or as UNAVAILABLE with a reason code. A value is never filled or interpolated.
"""
