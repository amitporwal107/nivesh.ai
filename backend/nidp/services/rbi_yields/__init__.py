"""nidp-rbi-yields — RBI G-Sec / T-Bill yields.

Sources:
    https://www.rbi.org.in/Scripts/ReferenceRateArchive.aspx  (HTML form)
    https://www.rbi.org.in/Scripts/BS_NSDPDisplay.aspx?param=4 (G-Sec daily)
Cadence:   Daily (T+0 evening)
Output:    nidp.rbi_yields  +  Kafka topic nidp.rbi_yields.v1

Replaces the existing macro_ingester.py bug where India 10Y was
proxied via yfinance ^TNX (= US 10Y).
"""

# Side-effect: register validation rules
from . import validators  # noqa: F401
