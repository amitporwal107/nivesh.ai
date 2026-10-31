# Live Kite quotes across the trader tools: test cases (2026-10-23)

Authored after the audit and the Risk desk edit, before the other four edits (SmartMoney, SetupsToWatch, Reversal, F&O spot).
Audit: the desk Overview / Chart / Scanner / Portfolio tabs, the Trader screen, the F&O build-up and the Watchlist already
use the live overlay. Gaps closed here: Risk desk price marker, Smart-money stock evidence, Setups to watch, Reversal
detail levels, F&O lab spot. Left alone on purpose: entry / stop / target (plans), historical deal and event prices,
broker positions (the broker's own LTP), Paper desk P&L (recorded server-side on end-of-day marks).

Rule for every surface: a live price shows only while the feed's mode is "live" (`useLiveOverlay`); otherwise the
end-of-day figure stays and nothing is guessed. A stock with no quote shows the end-of-day figure, never 0.

| ID | Surface | Scenario | Type | Expected |
|----|---------|----------|------|----------|
| TC-1 | Risk desk | feed live: the range-bar marker reads "Live ₹x" at the live price, data-live set | e2e | marker position uses the live price |
| TC-2 | Risk desk | feed closed / no quote: marker reads "Close ₹x" (last bar), unchanged | e2e | existing behaviour |
| TC-3 | Smart-money evidence | feed live: price and day change come from Kite, labelled live | e2e | live figures |
| TC-4 | Smart-money evidence | no live quote: scanner close and change as before | e2e | unchanged |
| TC-5 | Setups to watch | feed live: a "Live" column with price and day %, a stock with no quote shows — | e2e | column appears only while live |
| TC-6 | Setups to watch | feed not live: no Live column | e2e | unchanged table |
| TC-7 | Reversal detail | feed live: the levels line adds the live price | e2e | "live ₹x (Kite)" present |
| TC-8 | F&O spot | NIFTY live: big number is Kite's Nifty 50 price, label says chain figures are bhavcopy | e2e | live spot |
| TC-9 | F&O spot | index not mapped (FINNIFTY) or feed not live: bhavcopy spot unchanged | e2e | unchanged |
| TC-10 | all | existing desk specs still pass | regression | pass |
| TC-11 | all | tsc clean | static | exit 0 |
