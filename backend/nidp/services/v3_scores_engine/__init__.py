"""V3 Scores Engine — nightly persistence of MF + Stock composite scores.

Pulls primitives from the existing v_v3_mf_primitives / v_v3_stock_primitives
views, invokes the Nivesh-side scorers (services.v3_scoring +
services.stock_scoring) to compute Quality + Health, and persists results to
nidp.v3_mf_scores_daily / nidp.v3_stock_scores_daily for DaaS to serve.

Scope: Quality + Health only. Exit/Add are portfolio-aware (need overlap,
tax_ratio, sector_gap) and remain on-the-fly downstream.
"""
