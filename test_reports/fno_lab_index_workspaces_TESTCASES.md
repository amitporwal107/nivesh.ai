# F&O Lab: NIFTY & BANKNIFTY workspaces: test cases (authored before implementation)

Ask (user, 2026-10-23): build the NIFTY / BANKNIFTY workspaces from the approved design canvas (artboard IndexWorkspace). Decision of record: extend the
existing "NIFTY & BANKNIFTY" view into two independent workspaces behind a selector. Scope of this step: the selector, the existing index card for the
selected index, a new **By expiry** panel (near / next / far, each contract read on its own, never summed) and the research note.
Not in this step (stated, not hidden): the last-five-sessions state history (needs a new backend route) and Greek-weighted exposure (not built; research first).

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | the view shows an index selector (NIFTY, BANKNIFTY); one workspace at a time; NIFTY is open by default | e2e | selector, one card |
| TC-2 | choosing BANKNIFTY shows BANKNIFTY's card and expiry panel and loads that underlying in the page header | e2e | data-symbol |
| TC-3 | By expiry: up to three buckets (Near, Next, Far) from the futures route, each with its expiry date, own build-up state, price change % and OI change % computed from that contract's own change in OI | e2e | values from fixture |
| TC-4 | the OI change % is change_in_oi / (oi - change_in_oi); a contract with a missing figure shows "—", never 0 | e2e | text |
| TC-5 | the panel states that OI is never added across expiries and that a near-month drop with a next-month rise may be rollover | e2e | text |
| TC-6 | the research note says not validated and that index tests are descriptive (no ranking, no claim of skill) | e2e | text |
| TC-7 | a futures route failure leaves the card usable and shows the panel's own problem notice | e2e | notice |
| TC-8 | the existing index-card tests still pass once the selector is used (TC-30 etc.) | e2e | pass |
| TC-9 | 390px: no sideways overflow on the view | e2e | 0 |
| TC-10 | `tsc --noEmit` passes | tsc | exit 0 |
