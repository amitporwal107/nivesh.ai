# F&O forward test: near-month short build-up, recorded at signal time and judged later: test cases (authored before implementation)

Ask (user, 2026-10-23): complete the paper-trading page from the design: the forward-test panel. The existing PaperDesk already has the summary tiles, the open/closed trade table, the trade record (signal,
entry and exit rules, costs, gross/net, flags) and the price alerts; the missing piece is the forward test of the one hypothesis the research left standing.
Hypothesis (docs/FO_STAGE_B2_FINDINGS_20261023.md): a stock whose NEAR-MONTH future shows price down and OI up (the contract's own figures, not summed over expiries) under the production floors (|price| >= 0.5%,
OI >= 3%) underperforms the F&O universe over the next 5 sessions, net of an assumed 0.15% round trip. It was inconclusive (permutation p 0.02 for the production floors, 0.06 for the first frozen setting; 50 pooled sessions).
Rules fixed now: each session's signals are RECORDED when the session's data is in and never reconstructed or overwritten (first write wins); entry at the next session's open, exit at the close 5 sessions after the
signal, on adjusted prices; outcome = direction (short) x (stock return - equal-weight universe return) minus 0.15%; no result (mean, t) is shown until 30 sessions have a judged signal; Newey-West lag 4.
Two settings are recorded: `production_floors` (primary) and `no_threshold` (every near-month short build-up). The five frozen volume-floor settings are NOT recorded (they need 20 sessions of the contract's own volume at signal time).

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | near-month state: price % from the contract's change_pct, OI % = change_in_oi / (oi - change_in_oi); a missing figure gives no state (never 0) | pytest | numbers |
| TC-2 | classification: production_floors fires only when price <= -0.5 and OI >= +3; no_threshold on any price down and OI up; a zero change never fires | pytest | sets |
| TC-3 | recording is first-write-wins: a second record for the same session changes nothing | pytest | doc |
| TC-4 | evaluation: entry next open, exit close 5 sessions after, direction short, benchmark-relative, net of 0.15%; a session without 5 later sessions is open, not judged | pytest | numbers |
| TC-5 | below 30 judged sessions mean and t are null and `sessions_needed` says how many more; at or above 30 they are computed | pytest | null / numbers |
| TC-6 | GET /api/fno/forward-test with nothing recorded: zeros, the hypothesis text and the reason, no price read; with records: counts and the evaluation | pytest | body |
| TC-7 | the panel shows the hypothesis, signals recorded / judged / still open, the 30-session progress bar, the past result stated as inconclusive, and no performance number before 30 sessions | e2e | text |
| TC-8 | a failed read shows the notice; nothing recorded shows "recording has not started"; 390px no overflow; tsc exit 0 | e2e, tsc | pass |
