"""nidp-fred-macro — global macro indicators from FRED.

Source:    https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES_ID}
           (No API key required for public series — CSV download endpoint.)
Cadence:   Daily T+0 ~22:00 UTC (FRED publishes US-market-close data overnight)
Output:    nidp.fred_macro

Curated series:
    DGS10            — US 10-year Treasury yield (daily, %)
    DGS2             — US 2-year Treasury yield (daily, %)
    DTWEXBGS         — US dollar trade-weighted index (daily, index)
    DCOILBRENTEU     — Brent crude spot (daily, USD/bbl)
    DCOILWTICO       — WTI crude spot (daily, USD/bbl)
    VIXCLS           — CBOE VIX (daily, index)
    GOLDAMGBD228NLBM — Gold London PM fix (daily, USD/oz)
    FEDFUNDS         — Fed Funds effective rate (monthly, %)

These complement RBI yields (India-specific) for cross-asset regime
classification.
"""
__all__ = ["service", "parser", "writer"]

# Side-effect: register validation rules
from . import validators  # noqa: F401
