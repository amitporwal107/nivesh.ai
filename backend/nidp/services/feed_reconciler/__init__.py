"""feed_reconciler — self-healing catch-up for missed feed runs.

Detects `(feed, trading-day)` gaps in a rolling window and heals them by
re-running the existing idempotent backfill. See service.py.
"""
