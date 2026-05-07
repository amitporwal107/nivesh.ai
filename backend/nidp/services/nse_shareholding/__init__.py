"""nidp-nse-shareholding — NSE quarterly shareholding pattern (XBRL).

Source:    https://www.nseindia.com/api/corporate-share-holdings-master
Cadence:   Daily (rolling list of recent Reg-31 filings)
Output:    nidp.shareholding_pattern  +  Kafka topic nidp.shareholding_pattern.v1
"""

from . import validators  # noqa: F401
