"""nidp-corporate-actions — NSE corporate-action feed.

Source:    https://archives.nseindia.com/content/equities/corp_actions.csv  (rolling)
Cadence:   Daily
Output:    nidp.corporate_actions  +  Kafka topic nidp.corporate_actions.v1
"""

# Side-effect: register validation rules
from . import validators  # noqa: F401
