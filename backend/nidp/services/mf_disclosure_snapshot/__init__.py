"""nidp-mf-disclosure-snapshot — weekly SID/factsheet snapshot + diff.

Source:    Per-AMC scheme info / factsheet pages (top-10 AMCs only)
Cadence:   Weekly
Output:    nidp.mf_scheme_disclosure_snapshot
           nidp.mf_scheme_events  (derived from snapshot diff)

Each AMC publishes scheme-info documents (SID), monthly factsheets, and
addendum pages on its own site with no shared schema. We register one
adapter per AMC under amc_dispatch.py; running this service walks
every registered AMC, snapshots the values that drive event detection
(TER, risk-o-meter, primary/secondary manager, AUM), and diffs against
the previous snapshot to emit mf_scheme_events.

v1: scaffolding + dispatcher. Per-AMC adapters land incrementally —
each AMC's site needs hand-tested selectors. Adapters not yet
implemented log a stub warning and contribute zero rows.
"""
__all__ = ["service"]
