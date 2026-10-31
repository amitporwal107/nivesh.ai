# OVERRIDE — suggestion engine: live signed-in walk

REASON: The Home suggestion tabs need a deploy of this branch to staging and a signed-in session; neither is available
to the agent (no deploy, no session token, staging database not written). Everything else is verified in
`dtc_r3_suggestions_20261031.md`.

What the live walk must check, once the PR is merged and deployed (frontend image rebuilt, backend process restarted):
1. `GET /api/suggestions?tab=market&mode=trader` as a signed-in user: 200, `schema suggestions-v1`, the four tabs, cards
   with `as_of` dates, in the shape of `frontend-v5/e2e/fixtures/contract-suggestions.json`.
2. Open `/v5/app`: the tabs show; a card click asks its question and the visual answer opens; Dismiss, Useful, Not
   relevant, Refresh and "Why am I seeing this?" work; the My trades tab says "Prices stale" if the paper-trade marks
   are old, and the For you tab says "Broker disconnected" for an ended session.
3. Mongo now holds `suggestion_instances`, `suggestion_events` and `suggestion_feedback` for that user only (the stores
   create their own indexes on first use); nothing else changed.
