"""nidp-index-constituents — NSE per-index constituent CSVs.

Sources:
    https://archives.nseindia.com/content/indices/ind_nifty50list.csv
    …nifty100list.csv, nifty500list.csv, niftybanklist.csv, niftyitlist.csv
Cadence:   Quarterly (rebalance) + on-event
Output:    nidp.index_constituents  +  Kafka topic nidp.index_constituents.v1
"""
