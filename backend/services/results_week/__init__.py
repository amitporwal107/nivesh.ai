"""Earnings Surprise & Guidance Tracker, Phase 1 ("Results week"): docs/EARNINGS_SURPRISE_TRACKER.md.

  scoring   the §4 rules as pure functions (verdict vs historical trend, composite, reaction, OI build-up, ideas)
  loaders   failure-isolated reads (DaaS, Mongo, app Postgres); each failure is a gap, never a silent neutral
  build     one day's answer (GET /api/desk/results-week) from the loaders and the rules
  store     the nightly insert-once snapshot (results_week_days)

Paper / research only: ideas are ordered for review, nothing here places an order.
"""
