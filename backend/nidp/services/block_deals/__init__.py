"""nidp-block-deals — NSE block deals ingestion service.

Source:    https://nsearchives.nseindia.com/content/equities/block.csv
Cadence:   Daily T+0 ~18:30 IST
Output:    nidp.block_deals  +  Kafka topic nidp.block_deals.v1
"""

# Side-effect: register validation rules
from . import validators  # noqa: F401
