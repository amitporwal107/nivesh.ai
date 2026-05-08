"""nidp-amfi-nav-history — historical NAV backfill via MFAPI.in.

Source:    https://api.mfapi.in/mf/{scheme_code} (per-scheme JSON)
Cadence:   On-demand backfill / weekly gap-fill
Output:    nidp.mf_nav_daily   (source = 'MFAPI')

Why MFAPI.in:
    AMFI's own historical NAV report endpoint is per-scheme, POST-form,
    capped at ~90-day windows. Backfilling 10 yrs × 10k schemes against
    it is brittle. MFAPI.in is an unofficial JSON aggregator over the
    same AMFI data — much faster for bulk backfill. We tag the source
    as 'MFAPI' so primary-vs-backfill provenance stays clear.

Daily ingest stays AMFI-direct (amfi_nav). This service is run only
to fill historical gaps.
"""
__all__ = ["service"]
