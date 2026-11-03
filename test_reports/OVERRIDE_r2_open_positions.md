# OVERRIDE — Open Positions: real broker positions and the live signed-in walk

REASON: Both of the test account's broker sessions have ended (`BROKER_SESSION_EXPIRED` on the 31 Oct staging read; brokers
end sessions daily and the owner signs in again each day), and the Open Positions workspace needs a deploy of this branch to
staging and a signed-in session; neither is available to the agent (no deploy, no session token, no broker password, and the
staging database is not written). So no real broker position has ever been read by this code. Everything else is verified in
`r2_open_positions_20261031.md`, and every broker-position figure in that report is labelled CONSTRUCTED or MOCK.

What the owner's check must cover, once the PR is merged and deployed (frontend image rebuilt, backend process restarted):
1. Sign in to ICICI Direct (and Zerodha) from Settings › Brokers, then open `/v5/app/page/positions`: each account's "Read
   <time> · N open positions" line, and a futures or options row named as its NSE contract (ICICI code SONBLW shows as
   SONACOMS, CNXBAN as BANKNIFTY). A row that cannot be named is listed under "Not mapped", never valued.
2. A Zerodha monthly contract (`NIFTY26NOV23000CE`): its expiry day is taken from the listed futures expiry of that month;
   confirm it equals the contract's real expiry. This is the one mapping with no broker-published expiry in the row.
3. Compare each group's P&L with the broker's own screen (it is the broker's figure, not recomputed), and the Greeks and
   settle prices with the NSE end-of-day chain of the day shown ("options and futures priced at the <date> close").
4. Set a stop and target on a broker underlying: `position_levels` gains one document for that user and underlying; "Remove"
   deletes it. Nothing is sent to the broker.
5. `position_snapshots` gains one document per account only when its positions change; `broker_as_of` stays null (the
   position reads send no broker time for the book).
6. "Margin · Zerodha" needs the platform's Kite login of the day; without it the screen says so and shows no figure.

Not claimed anywhere: the broker's day realised P&L (no route returns it), a stop or target set at the broker, or any order.
