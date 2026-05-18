"""Sync raw CAS transactions from Nivesh Mongo → NIDP TimescaleDB.

Reads:
  gs://{NIDP_GCS_BUCKET}/portfolio/transactions/{date}/transactions.jsonl
  gs://{NIDP_GCS_BUCKET}/portfolio/transactions/latest.json

Writes:
  portfolio.user_transactions  (migration 056)
  portfolio.sync_audit_log     (dataset='transactions')

Provides the lot-level history the NIDP-side tax engine and V3 Exit/Switch
scores need but which `portfolio.user_holdings_snapshot` (blended
avg_buy_price only) does not carry.
"""
