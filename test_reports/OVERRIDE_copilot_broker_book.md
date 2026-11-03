# OVERRIDE: copilot_broker_book (open trades on the broker book + 5 s live)
REASON: the market was closed (Saturday 31 Oct / Sunday 1 Nov) and ICICI Direct's session ended at midnight, so these were NOT seen on real data: (1) the 5 s page over a live market session — Kite live prices over the real positions, the chip counting, the pause/resume, the stop at 15:30; (2) a Zerodha position row (the owner's Zerodha account holds none; its Fenix row mapping and its `trades` are unproven on real rows); (3) ICICI funds meaning; (4) the deployed browser (only mocked Playwright; the staging frontend is built from dev on merge). Verified on real data: the no-broker/session-ended/live states over the owner's real accounts (stored read dated, live read, funds, Zerodha margin calculator), the symbol mapping, the plan fallback, the unmapped row, and the real `pnl: null` trap.

Owner checklist (Monday 2 Nov, 09:15-15:30 IST, after the merge + the staging deploy: backend restarts, frontend rebuilds):
1. Settings > Brokers: sign in to ICICI Direct and to Zerodha (the sessions end at midnight / 06:00).
2. Open /v5/app and ask "What are my open trades doing?". Expect: notices only if something is off; "Broker book" KPIs; a "Broker positions" table; Live badges; a chip "Live · updated Ns ago".
3. Watch the chip for 30 s: it counts up to 5 and resets to 0 after each answer; share prices and the P&L of a share row move; a future or option row keeps its price for up to 15 s (hover shows when it was read).
4. Compare with ICICI Direct's own positions screen: quantity, average, price, and the P&L of the share rows (the F&O rows say "Marked at the last price" because ICICI sends no P&L for them: compare the marked figure with ICICI's screen). Compare "Available cash / Collateral / Used margin" with ICICI's funds screen and with Zerodha's.
5. Compare "Margin required" for an F&O position with ICICI's own margin figure (it is Zerodha's calculator: expect a difference).
6. Open Open positions, set a stop for one underlying; ask again (or wait 90 s): the Stop, "To stop" and "Loss at stop" columns follow; the loss is never the stock at zero.
7. Hide the tab for 30 s: the chip says "Paused while you are away"; return: it asks at once. Scroll the answer off screen: no asks (browser network tab).
8. After 15:30 IST the chip says "Updates stopped: the market is closed".
9. Check the broker call volume: `db.position_snapshots` for the account has one document per change in holdings, and its `last_seen_at` moves at most every 15 s.
10. Sign out of one broker (or wait for midnight): ask again; expect "Sign in to <broker> again" and the stored rows badged "As of ...".
