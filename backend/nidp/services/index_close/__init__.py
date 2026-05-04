"""nidp-index-close — NSE ind_close_all (daily index OHLC + ratios).

Source:    https://archives.nseindia.com/content/indices/ind_close_all_{DDMMYYYY}.csv
Cadence:   Daily T+0 ~18:30 IST
Output:    nidp.index_eod  +  Kafka topic nidp.index_close.v1
"""

# Side-effect: register validation rules
from . import validators  # noqa: F401
