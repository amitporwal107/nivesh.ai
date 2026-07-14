"""dlq_redrive — reprocess quarantined feed entries from dq.dlq_findings.

Re-runs each PENDING Gate-1 DLQ entry for its (feed, target_date) and
transitions replay_status: REPLAYED on success, INVESTIGATING after N
failed attempts, DROPPED when aged out. See service.py.
"""
