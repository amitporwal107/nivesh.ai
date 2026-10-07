# Test cases — "Candidates" mode (events + bulk/block deals, no odds-model score)

Authored 2026-10-03, after the API shape and UI placement were decided (research into the existing
`/api/movers` family, the unmounted v4 dashboard, and the Research feed screen) and alongside
implementation, not strictly before it — this was an exploratory feature (the ask required first
discovering that the Movers UI existed but was unrouted, and that no "events-only, no model score"
view existed anywhere). Noted here rather than silently claimed as upfront.

## What was asked

Owner, from the live `/v5/research` filings screen: a link to the Movers page for "potential Monday
candidates" — a timeline of events + bulk deals plus a candle chart, for stocks worth a look before
the next session, **purely on the basis of market events and bulk deals** (explicitly not the odds
model — confirmed via AskUserQuestion: candidate rule = "material filing or bulk/block deal in the
last session", UI = "wire up the existing [unmounted] dashboard", branch = "new branch off dev").

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-C01 | backend | `/movers/candidates` merges a filing + a deal on the same symbol into one row | unit (mocked conn) | one candidate, 2 signals, types `{fil, dealB}` | PASS |
| TC-C02 | backend | ranking | unit | higher bulk/block deal value (qty×price) ranks first; filing-only ranks last | PASS |
| TC-C03 | backend | liquidity floor | unit | a symbol below `MIN_TURNOVER`, or with no EQ price row at all on the session, is dropped, not shown with a dash | PASS |
| TC-C04 | backend | empty day | unit | `count=0`, `candidates=[]`, but `rule`/`disclaimer` still present (never silently absent) | PASS |
| TC-C05 | backend | no EQ session on record | unit/failure | `404`, not a fabricated empty 200 | PASS |
| TC-C06 | backend | route order | unit | `/movers/candidates` registered before `/movers/{symbol}` (else it would 404 as a fake stock "CANDIDATES") | PASS |
| TC-C07 | backend (proxy) | app-side forwarding | unit | `session`/`limit` forwarded verbatim; `None` dropped, not sent as `null` | PASS |
| TC-C08 | backend (proxy) | route order | unit | `/api/movers/candidates` before `/api/movers/{symbol}` | PASS |
| TC-C09 | frontend | feed screen link | e2e (mocked) | `feed-candidates-link` visible only when `features.move_odds`; click deep-links to Movers, mode = Candidates selected | PASS |
| TC-C10 | frontend | candidate rail | e2e (mocked) | rows show symbol/name/pct + a FILING/DEAL/FILING+DEAL badge, never an odds badge | PASS |
| TC-C11 | frontend | hero | e2e (mocked) | shows signal count + synthesis text from the disclosure titles, not an "odds model" tile | PASS |
| TC-C12 | frontend | chart + timeline | e2e (mocked) | `mv-chart` (candles) and `mv-log` (event/deal timeline) render for the selected candidate | PASS |
| TC-C13 | frontend | no model framing | e2e (mocked) | `mv-model-panel`, `mv-attr` (sensitivity), `mv-copilot`, `mv-tech`, `mv-lift` all absent in Candidates mode | PASS |
| TC-C14 | frontend | disclaimer | e2e (mocked) | the API's own `rule`/`disclaimer` strings render verbatim | PASS |
| TC-C15 | frontend | selection swap | e2e (mocked) | picking a second candidate swaps hero + chart + timeline to its own events | PASS |
| TC-C16 | frontend | filter chips | e2e (mocked) | ALL / FILING / DEAL narrow the rail correctly | PASS |
| TC-C17 | frontend | empty day | e2e (mocked) | honest empty-state message, not a blank list | PASS |
| TC-C18 | frontend | regression | e2e (mocked) | all 42 pre-existing Movers v4/v1 Playwright cases still pass unmodified | PASS |
| TC-C19 | backend | regression | unit | all 62 pre-existing `test_movers_v4.py` / `test_movers_proxy.py` cases still pass unmodified | PASS |
| TC-C20 | app | staging HTTP: `GET /api/movers/candidates` is live and correctly routed/gated on the deployed app | api | real HTTP response, not 404/500 | PASS (401 unauthenticated — route confirmed live; an authenticated response is TC-C21) |
| TC-C21 | app | staging UI: the feed link, live login, real `move_odds` flag state for the test account | e2e (live) | link visible/working against the real deployed app | **BLOCKED** — needs a human session (owner or a session token), not a credential/deploy blocker any more |
| TC-C22 | data | staging DB: the SQL in `candidates()` executes against real `nidp.corporate_announcements` / `nidp.bulk_deals` / `nidp.block_deals` / `nidp.prices_eod` without error, real row counts in a sane band | data | real counts, no SQL errors | PASS |
| TC-F1 | frontend | clicking a filing's company name on the feed opens Candidates mode pinned to that symbol/session (no new backend call — built from the feed row the UI already has) | e2e (mocked) | PASS — see `movers_filing_row_link_20261003.md` |
| TC-F2 | frontend | a "← Back to filings" button, shown only on this pinned path, returns to the feed | e2e (mocked) | PASS |
| TC-F3 | frontend | without `features.move_odds`, a filing row carries no stock link at all | e2e (mocked) | PASS |

TC-C01–C20 and TC-C22: all PASS, with real command output in the dated report below. TC-C21 is the one
thing still **BLOCKED** — see `OVERRIDE_movers_candidates.md`. The branch is merged (with a concurrent
`dev` FORWARD-tab commit), pushed, deployed, and the `move_odds` allowlist now includes the owner's
account; what's left is a human-authenticated look at the live page.
