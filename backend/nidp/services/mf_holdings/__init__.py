"""nidp-mf-holdings — monthly portfolio disclosures (top-10 AMCs).

Source:    Per-AMC SEBI-mandated monthly portfolio disclosure pages
Cadence:   Monthly (poll daily; new disclosures land mid-month with M+10 SEBI lag)
Output:    nidp.mf_holdings_monthly  +  Kafka nidp.mf_holdings_monthly.v1

Each AMC publishes the disclosure as Excel/CSV (preferred) or PDF
(fallback), one workbook per scheme or per category. We register one
adapter per AMC under amc_dispatch.py; each adapter returns rows
already shaped for the writer. Schema differences live inside the
adapter — the orchestrator + writer don't care which AMC produced
them.

v1: scaffolding + dispatcher. Per-AMC adapters land incrementally.
"""
__all__ = ["service"]
