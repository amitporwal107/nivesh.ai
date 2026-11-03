# Test cases — AI scanner daily watchlist (/app/watchlist)

- **Date:** 2026-10-26 · **Branch:** `feat/ai-scanner-watchlist` (worktree `/home/deploy/nivesh-ai-watchlist`, off `origin/dev` b554d2be)
- **Roles:** FULL_STACK_DEVELOPER + QA_ENGINEER + DESIGN_ENGINEER (+ DOMAIN_EXPERT: wording, data trust)
- Authored before implementation, after the API and UI design below.

## The ask (user, 2026-10-26)

A watchlist of the Top AI scanner ideas every day, cash and F&O, rotated after each day's AI scanner job, every day's list
stored, a dateline view, inside the existing `/app/watchlist`. Each entry: stock details, an F&O OI / Greeks view, live
prices while the market is open, links to strategies and paper trade.

## Decisions

- Capture by a **nightly job with a system identity** (user, 2026-10-26): a context-local "system caller" in
  `deps.get_current_user` that only in-process job code can set; an HTTP request can never carry it.
- Wording: "ideas", "strategy that fits", never picks / recommended (user, 2026-10-25).
- Sign-in only — not the public, no-login research watchlist (`/api/public/research-watchlist`).

## Design

**Backend**
- `deps.system_caller(user)` context manager + `get_current_user` returns that user only inside it. `require_admin` still
  refuses it (not an admin).
- Store `services/ai_watchlist_store.py`, Mongo `ai_watchlist_days`, one document per `list_date` (the scan date):
  `cash` (top 10 from the ideas engine, `POST /api/desk/strategy/ideas` logic with `limit: 10`) and `fno` (top 10 from
  `regime_fit.build_top(limit=10, classes=[index_options, stock_fno], distinct=True)`, both classes merged by the route's
  own rule), each entry a snapshot of what the route returned on that day, plus the sources' dates, ranking notes and caveats.
  A list is written once per day; an existing day is never changed.
- Job `scripts/build_ai_watchlist.py`: needs the day's scan in `positional_signals` (else exit 2, nothing written),
  `--skip-if-done`, `--dry-run` (build and print, write nothing), `--date`.
- Cron `deploy/nivesh-staging/ai-watchlist.cron`: 20:15 and 22:15 IST Mon–Fri (after the 19:45 / 21:45 scanner runs).
- Route `GET /api/desk/ai-watchlist?date=` (signed in): the day's lists (newest by default), `available_dates` with counts
  (the dateline), and per entry the earlier list dates it was on in the last 30 days and its run of consecutive list days.

**Frontend** (`screens/workspace/AiScannerWatchlist.tsx`, first block of `screens/Watchlist.tsx`)
- Dateline: one chip per stored day, newest first, with the counts; picking one shows that day.
- Cash | F&O switch.
- Cash row: rank, icon + symbol, name · sector, setup + score, the close on the list day, the latest price (Kite live while
  the session is open, Kite close after it) and the change since the list day, plan status, the strategy that fits, how many
  list days in a row; links: Chart ›, Strategy › (the plan in the desk's Strategy Builder), Option chain › (F&O stocks),
  Paper trade (the scanner's levels), View trades ›.
- F&O row: rank, underlying, structure, expiry, fit; OI / Greeks view: the legs (strike, type, side, lots, premium), net
  delta / gamma / theta / vega, the underlying's futures OI build-up (EOD) and, while live, the live net premium against the
  listed one; links: Open in F&O lab ›, Option chain ›, OI build-up ›, Payoff, Paper trade, View trades ›.

## Backend cases (pytest, unit)

| ID | Case | Expected |
|----|------|----------|
| B-1 | `get_current_user` inside `system_caller` | the system user, no session read |
| B-2 | outside it (and in a concurrent task) | the normal cookie / bearer check (401 without one) |
| B-3 | `require_admin` inside it | 403 (the system user is not an admin) |
| B-4 | job: no scan for the date | exit 2, nothing written |
| B-5 | job: `--skip-if-done` with the day stored | nothing built, exit 0 |
| B-6 | job: `--dry-run` | built, printed, nothing written |
| B-7 | job: build | one document: 10 cash (ideas order), 10 F&O merged by fit then R:R, notes, dates |
| B-8 | store: a day is written once | a second write for the same day does not overwrite |
| B-9 | route: default = newest day; `?date=` that day; unknown date → 404; bad date → 422; no session → 401 |
| B-10 | route: dateline counts; earlier dates and run of days per entry |

## Staging cases (real data)

| ID | Case | Expected |
|----|------|----------|
| S-1 | `--dry-run` on staging before merge (read only) | 10 cash + up to 10 F&O built from the 26 Oct scan |
| S-2 | first real run after merge | `ai_watchlist_days` has 2026-10-26 |
| S-3 | `GET /api/desk/ai-watchlist` without a session | 401 |

## Frontend cases (Playwright, mocked API)

| ID | Case | Expected |
|----|------|----------|
| F-1 | the block is first on /app/watchlist | AI scanner watchlist with the dateline and the newest day picked |
| F-2 | dateline | one chip per day, newest first, counts; a click loads that day (`?date=`) |
| F-3 | cash row details | symbol, setup, score, list-day close, change since, strategy that fits, days on the list |
| F-4 | live price | with a live quote: price, "Live" label and change since the list day from it |
| F-5 | cash links | Chart › / Strategy › / Option chain › go to the desk URLs; Paper trade posts the scanner levels |
| F-6 | F&O row | legs, net Greeks, OI build-up line; Payoff on demand; Paper trade posts kind "strategy" |
| F-7 | F&O links | Open in F&O lab › → desk lab with `lab_focus`; Option chain › / OI build-up › |
| F-8 | empty / failing | no list yet → says when the job runs; a route failure → error with retry, rest of the page intact |
| F-9 | wording | no picks / recommended / suggested |
| F-10 | phone 390px | no sideways scroll |
| R-1 | existing watchlist specs | pass |
