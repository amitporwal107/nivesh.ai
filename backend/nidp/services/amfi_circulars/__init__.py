"""nidp-amfi-circulars — AMFI notices/circulars/addenda ingester.

Source:    https://www.amfiindia.com/research-information/other-data/notices-circular
Cadence:   Daily (cheap to re-poll; new entries detected by URL hash)
Output:    nidp.mf_amfi_circulars  +  Kafka nidp.mf_amfi_circulars.v1

Why this matters:
    Scheme mergers, name changes, and regulatory addenda are AMFI's
    canonical disclosure surface. Downstream, the mf_disclosure_snapshot
    diff catches TER/manager/risk-o-meter changes; this feed catches
    the *circular-driven* lifecycle events that snapshots miss.
"""
__all__ = ["service"]
