"""Quality Gate service — Cloud Run Job.

Runs the full post-ingestion pipeline for a given date:
  1. Consistency checks (mf + equity domains)
  2. Quality score computation
  3. Gate decision (PASS → certify, REVIEW → exception queue, FAIL → quarantine)
  4. API cache invalidation

Invoked by Cloud Scheduler at 22:30 IST Mon–Fri, after the snapshot
builder (22:00 IST) and price adjuster (22:30 IST) have settled.
"""
