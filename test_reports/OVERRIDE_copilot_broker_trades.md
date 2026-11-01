# OVERRIDE: copilot_broker_trades (broker trades in the daily review)
REASON: no real broker FILL has been read. The Saturday/Sunday market was shut, ICICI Direct's session ended at midnight, and Zerodha's live trade book was empty (the read succeeded, 0 fills). So: (1) ICICI Direct's `/trades` field names (`trade_date`, `stock_code`, `action`, `quantity`, `average_price`, `product_type`, `expiry_date`, `right`, `strike_price`, `exchange_code`) are ICICI's documented ones and the endpoint name/body come from ICICI's own SDK, but NO real response was seen; (2) Kite's `trades()` row mapping was run only against a fake; (3) matching, adherence and the review were run on invented fixtures labelled MOCK; (4) nothing has been kept yet (`broker_trade_days` is empty on staging), so "this week" cannot be answered from real days until sessions are live at 17:30 IST on trading days.

Owner checklist (a trading day, after the merge + deploy; backend restarts):
1. Sign in to Zerodha and ICICI Direct in Settings > Brokers in the morning.
2. Trade (or have trades) as usual. After 15:30 open /v5/app and ask "What did I learn from today's trades?". Expect a "Broker trades" section: round trips closed, wins/losses, realised P&L (gross), a "Broker round trips" table, "Did you follow your entry, stop-loss and exit rules?", unmatched legs.
3. Compare each round trip with the broker's own trade book / contract note: contract, quantity (UNITS), entry and exit prices, and the P&L (gross: the broker's prices, no charges). Tell me any row ICICI's `/trades` sends that is missing or differently named.
4. Check an F&O trade: quantity is in units (a lot x its lot size).
5. After 17:30 IST (the daily sync) check `db.broker_trade_days` has one document for the account and day (count of fills; no token); a second ask the same day must not add a document.
6. Next day ask "How did I do this week?": the week should include yesterday from the kept book; a position opened yesterday and closed today is one round trip with its entry day.
7. Set a stop for an underlying (Open positions) BEFORE closing a trade: the round trip says whether the exit honoured it; a stop set after the trade closed is said to be ignored.
8. Sign out of one broker: the review names it, offers Sign in again, and still counts its kept days.
