"""nidp-nse-reference-snapshot — daily NSE price band / F&O / ETF flags per symbol.

Sources (nsearchives.nseindia.com):
  content/equities/sec_list.csv        price band per symbol (2/5/10/20/No Band)
  content/fo/fo_mktlots.csv            F&O underlyings (lot sizes)
  content/equities/eq_etfseclist.csv   exchange-traded funds
Target: nidp.security_reference_daily (migration 138), one row per symbol per day.
"""
