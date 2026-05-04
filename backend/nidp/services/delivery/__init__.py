"""nidp-delivery — NSE sec_bhavdata_full delivery percentage.

Source:    https://archives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv
Cadence:   Daily T+1 ~10:00 IST
Output:    nidp.delivery_data  +  Kafka topic nidp.delivery.v1
"""

# Side-effect: register validation rules
from . import validators  # noqa: F401
