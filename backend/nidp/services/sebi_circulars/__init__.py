"""nidp-sebi-circulars — SEBI circulars and master circulars ingester.

Source:    https://www.sebi.gov.in/sebirss.xml (scheduled); Legal > Circulars and
           Legal > Master Circulars listing pages, page 1 (backfill, --source listing)
Cadence:   Every 3 h, 09:15-21:15 IST, Mon-Sat (the feed holds only about the latest 30 items)
Output:    nidp.sebi_circulars (migration 163), read by DaaS GET /v1/circulars/sebi

Only links under /legal/circulars/ and /legal/master-circulars/ are kept. The feed also carries
enforcement notices naming individuals with their PAN; the parser drops them and they are never
stored.
"""
__all__ = ["service"]
