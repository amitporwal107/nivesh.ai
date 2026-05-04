"""nidp-bulk-deals — NSE bulk deals ingestion service.

Source:    https://archives.nseindia.com/content/equities/bulk.csv
Cadence:   Daily, post-market (~18:30 IST)
Output:    nidp.bulk_deals  +  Kafka topic nidp.bulk_deals.v1
"""
__all__ = ["service"]

# Side-effect: register validation rules
from . import validators  # noqa: F401
