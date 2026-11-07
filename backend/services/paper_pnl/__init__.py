"""Real-time paper P&L (Trade Desk › Paper Trading › P&L dashboard; docs/paper_pnl_dashboard/DESIGN.md).

    ledger.py      the accounting: normalized executions -> positions (weighted average), realized / unrealized. Pure.
    book.py        the user's desk paper trades read WITHOUT applying exits, turned into executions. Read-only.
    prices.py      the price of each open position now (Kite live -> Kite REST for contracts off the feed -> Kite close
                   -> the ledger's end-of-day mark), with its status. Read-only; never reaches an order call.
    dashboard.py   the payload: summary, segments, positions, strategies, risk alerts, analytics, reconciliation. Pure.
    timeseries.py  today's P&L curve of the open book from Kite intraday candles.

Nothing here writes to the ledger, fills, exits or the paper account: the live price is for display only.
"""
