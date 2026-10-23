# Index tape: compare Kite's closing quote with the tape's OWN end-of-day day: test cases (authored before implementation)

Ask (user, 2026-10-23): once the end-of-day data for a day is loaded, Kite's quote must not be shown; Kite is for while the market is live (and, until the day's
end-of-day data exists, its final snapshot labelled Close). Bug found: the Overview's index tiles compared Kite's closing quote with the home payload's
`as_of`, which is the breadth/dashboard date (stock_ohlcv, 19 Oct that evening), not the date of the tape's own daily bar (Yahoo, already 23 Oct). So Kite's 23 Oct close
showed on NIFTY 50 / NIFTY BANK / INDIA VIX although their 23 Oct end-of-day close was there.

Fix: each tape tile carries `as_of`, the date of its latest daily bar; the screens compare Kite's day with that.

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | get_index_tape returns each tile with `as_of` = the date of that ticker's last daily bar; a ticker with no history has no tile value and no date | pytest | dates |
| TC-2 | /api/markets/home passes each tile's `as_of` through; a tile whose value was replaced by the live snapshot has `as_of` null | pytest | field |
| TC-3 | Overview tile: Kite final snapshot of 23 Oct and the tile's own as_of 23 Oct: NO Kite close shown (end of day shown) even though the payload's as_of is 19 Oct | e2e | absent |
| TC-4 | Overview tile: the tile's as_of 22 Oct and Kite's final snapshot 23 Oct: "Close · 23 Oct · Kite" shown | e2e | label |
| TC-5 | no tile as_of (older backend): falls back to the payload's as_of as before | e2e | unchanged |
| TC-6 | Markets tab index cards use the same rule | e2e | absent/label |
| TC-7 | existing desk-market and markets specs and backend overview tests still pass; tsc exit 0 | all | pass |
