"""TrueData company financial statements → the NIDP warehouse: balance-sheet columns and finance costs on
nidp.nse_financials_quarterly, fiscal-year cash flows in nidp.nse_financials_cashflow. Fill-only, recorded in
nidp.truedata_fundamentals_fills (migration 190), switch-gated (backend/config/market_data_source.json).

    python -m nidp.services.truedata_fundamentals --help
"""
