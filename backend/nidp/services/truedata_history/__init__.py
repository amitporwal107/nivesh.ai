"""TrueData long daily stock history (2010 → each symbol's first prices_eod_adjusted date), stitched to our basis.

Research only: nidp.prices_eod_history (migration 191), read through nidp.v_prices_eod_long_research and the DaaS route
GET /v1/prices/research-long/{symbol}. See service.py for the load and bars.py for the rules.
"""
