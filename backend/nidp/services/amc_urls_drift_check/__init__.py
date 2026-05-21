"""Daily drift check for AMC + AMFI listing-page URLs.

Pings each portfolio-disclosure candidate URL used by mf_holdings and
amfi_central. Run marked FAILED when any AMC has zero healthy candidates,
so the standard job_log → alert pipeline catches URL rot at hour 0
instead of month 0.

Closes the long-term-monitoring item from project_amc_scrapers_broken.md.
"""
