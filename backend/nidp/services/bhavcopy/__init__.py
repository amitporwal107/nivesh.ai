"""nidp-bhavcopy — NSE EOD bhavcopy (per-stock OHLCV + ISIN).

Sources:
    Post-Jul-2024:  https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip
    Pre-Jul-2024:   https://archives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MMM}/cm{DDMMMYYYY}bhav.csv.zip
Cadence:   Daily T+0 ~18:30 IST
Output:    nidp.prices_eod  +  Kafka topic nidp.bhavcopy.v1
"""
__all__ = ["service"]

# Side-effect: register validation rules
from . import validators  # noqa: F401
