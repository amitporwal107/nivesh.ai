"""Nivesh Intelligence Data Platform (NIDP).

Isolated, append-only data foundation per the NIDP PRD. Lives in its own
`nidp` Postgres schema and does not import or write to any existing
backend service. Validation precedes any wiring into the live system.

PRD-aligned modules:
    sources/      — shared HTTP fetchers (NSE cookie session, RBI, etc.)
    ingestion/    — one ingester per data source (bhavcopy, fii_dii, …)
    storage/      — append-only writers + per-run job log
    validation/   — freshness, schema, cross-source reconciliation
    migrations/   — `nidp.*` schema migrations (idempotent)

Entry point: `python -m nidp.cli ingest <source> [--date YYYY-MM-DD]`.
"""
__all__ = []
