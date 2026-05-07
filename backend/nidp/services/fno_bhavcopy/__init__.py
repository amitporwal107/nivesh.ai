"""nidp-fno-bhavcopy — NSE F&O EOD bhavcopy.

Source:    https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_*.csv.zip
Cadence:   Daily, ~18:00 IST
Output:    nidp.fno_bhavcopy  +  Kafka topic nidp.fno_bhavcopy.v1
"""

from . import validators  # noqa: F401
