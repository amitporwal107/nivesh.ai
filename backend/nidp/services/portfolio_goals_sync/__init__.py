"""Sync user_goals from Nivesh Postgres → NIDP TimescaleDB.

Reads:
  gs://{NIDP_GCS_BUCKET}/portfolio/goals/{date}/goals.jsonl
  gs://{NIDP_GCS_BUCKET}/portfolio/goals/latest.json

Writes:
  portfolio.user_goals     (migration 056)
  portfolio.sync_audit_log (dataset='goals')

Feeds the V3 Add score's gap_fit_0_10 / need_score_0_10 once the
NIDP-side v3-bundle endpoint is built.
"""
