"""nidp-nse-financials — NSE quarterly/annual financial results (XBRL).

Source:    https://www.nseindia.com/api/corporates-financial-results
Cadence:   Daily (rolling list of recent filings)
Output:    nidp.nse_financials_quarterly
           +  Kafka topic nidp.nse_financials.v1
"""

# Side-effect: register validation rules
from . import validators  # noqa: F401
