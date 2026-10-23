# F&O Lab: latest quotes on the new views: test cases (authored before implementation)

Ask (user, 2026-10-23): refresh the F&O Lab with the latest quotes. The build-up table, the header spot and several trader tools already overlay the platform's Kite
feed; the new Candidates cards and the index card did not. Rule used everywhere: live quotes only while the feed's mode is "live"; after the close, the final
snapshot only for a day newer than the screen's own end-of-day day (labelled Close, never Live); never when delayed, expired or not connected.
The end-of-day figures (the build-up, the scores) are never overwritten: the latest quote is a separate, labelled line.

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | feed live: a Candidates card shows a "Live" line with the cash last price and change, and the near-month future's last price, change and OI; the end-of-day figures above are unchanged | e2e | text |
| TC-2 | the near-month OI is labelled as that contract's own and not comparable with the build-up's summed OI change | e2e | text |
| TC-3 | feed closed with a final snapshot newer than the scan's day: the line is labelled "Close · <day> · Kite", never "Live" | e2e | label |
| TC-4 | feed closed and the snapshot is not newer than the scan's day (the bhavcopy has caught up): no latest-quote line | e2e | absent |
| TC-5 | feed delayed / expired / not connected: no latest-quote line, end-of-day card alone | e2e | absent |
| TC-6 | a stock Kite sent nothing for shows no line (never 0) | e2e | absent |
| TC-7 | a failed snapshot read leaves the cards as they were | e2e | cards |
| TC-8 | the index card shows the live (or closing) spot label under the end-of-day spot while the feed allows; the card's end-of-day figures stay | e2e | label |
| TC-9 | 390px: no sideways overflow with the live line shown | e2e | 0 |
| TC-10 | existing lab specs still pass; tsc exit 0 | e2e, tsc | pass |
