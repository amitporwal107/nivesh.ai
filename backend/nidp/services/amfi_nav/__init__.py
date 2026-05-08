"""nidp-amfi-nav — AMFI daily NAV (drives mf_nav_daily + mf_scheme_master).

Source:    https://www.amfiindia.com/spages/NAVAll.txt
Cadence:   Daily ~22:30 IST (T+0 close, AMFI publishes after AMCs declare)
Output:    nidp.mf_nav_daily, nidp.mf_scheme_master upserts
           Kafka topics nidp.mf_nav_daily.v1, nidp.mf_scheme_master.v1

NAVAll.txt is a single pipe-delimited file (~10k schemes, ~5MB).
Format is a sectioned header — AMC-name and scheme-type are repeated as
header rows, so the parser carries them as state across data rows.
"""
__all__ = ["service"]

from . import validators  # noqa: F401
