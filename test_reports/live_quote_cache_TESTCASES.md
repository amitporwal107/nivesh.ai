# Test Cases — Live quote cache (PR C)

- **Branch:** feat/live-quote-cache (off origin/dev b74c7f4f)
- **Date:** 2026-10-24
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** local throwaway container from `nivesh/backend:staging` (worktree mounted read-only, `--network none`); staging after merge + restart + market hours
- **Changed areas:** backend routes/services: yes · frontend src: no

Authored before implementation. Every fake (Kite, ticker, Mongo, Redis, clock) in the unit tests is labelled MOCK in the test file.
Results are recorded in `test_reports/OVERRIDE_live_quote_cache.md`, not here.

## Design under test (summary)
- Feed carries NIFTY + BANKNIFTY options (config `LIVE_OPTION_UNDERLYINGS`, `LIVE_OPTION_EXPIRIES`=2,
  `LIVE_OPTION_STRIKES_EACH_SIDE`=15), centred on the ATM from the index quote (NIFTY 50 / NIFTY BANK), else the near future;
  re-centred on every universe rebuild; last in priority (dropped first over the 3000 cap); full-mode subscription.
- `make_quote` and the REST path keep top of book (`bid`, `ask`, `bid_qty`, `ask_qty` from depth buy[0]/sell[0]) and the exchange stamp.
- Leader writes changed quotes to Redis `nivesh:quote:<qkey>` (TTL `LIVE_QUOTE_CACHE_TTL_S`=600) in one pipeline at most once
  per second, plus `nivesh:quote:chain:<UNDERLYING>:<YYYY-MM-DD>` (hash `strike|type` -> qkey).
- Leader writes one `kite_live_minute` doc per open-session minute (`_id` `YYYY-MM-DDTHH:MM`, first write wins, TTL index on
  `saved_at`, `LIVE_MINUTE_TTL_DAYS`=90).
- `/api/live/quotes` reads Redis (MGET) first, snapshot for the rest; `GET /api/live/option-chain` serves the cached chain.

## Test Cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | Config | Defaults and parsing of the five new settings; empty underlyings turns options off; out-of-range values clamp | unit | NIFTY,BANKNIFTY / 2 / 15 / 600 / 90; clamped values; "" -> [] |
| TC-2 | Options | `option_contracts` keeps the 2 nearest unexpired expiries per configured underlying; expired, other underlyings, FUT, and rows missing token/strike/expiry are skipped | unit | exact contract set; metadata underlying, expiry, strike, option_type, lot_size, tradingsymbol, token |
| TC-3 | ATM | `atm_strike` picks the nearest listed strike; a tie takes the lower; no strikes or no spot gives None | unit | as stated |
| TC-4 | Options | `select_options` takes ATM ±N per expiry, both CE and PE, clipped at the chain ends; an underlying with no spot is reported missing, not guessed | unit | 2N+1 strikes x 2 types; missing list |
| TC-5 | Feed | Options are a universe set, ordered LAST, subscribed in full mode, quoted under `NFO:` on REST, decorated with OPT metadata | integration | `sets["options"]`, tail of `ordered`, ("full", tokens), `NFO:<sym>` asked |
| TC-6 | ATM | ATM from the NIFTY 50 / NIFTY BANK quote; when the index quote is absent, from the near-month future | integration | centre strike matches the source |
| TC-7 | Re-centre | Spot moves; at the next 15-min rebuild the window re-centres; dropped strikes leave the subscription | integration | new window; set_tokens diff |
| TC-8 | Pending | First pass has no spot (no quotes yet): options pending; the next pass, once the index quote exists, adds them without waiting 15 min | edge | options appear on pass 2 |
| TC-9 | Cap | Universe over the cap drops options first, then futures | edge | options truncated before any other set |
| TC-10 | Depth | `make_quote` with depth: bid/ask/qty from buy[0]/sell[0]; no depth, empty levels or zero price give None (never 0); exchange_ts None when Kite gave no stamp; received_at set | unit | as stated |
| TC-11 | Depth | REST quote() depth and a full-mode tick's depth both reach the stored quote | integration | bid/ask on the quote |
| TC-12 | Cache | Leader cache pass writes every changed quote to `nivesh:quote:<qkey>` with all spec fields, correct kind (EQ/INDEX/FUT/OPT), TTL = setting | integration | keys, fields, TTL |
| TC-13 | Cache | Chain index hash `nivesh:quote:chain:NIFTY:<expiry>` maps `strike|type` -> qkey, replaced on re-centre, same TTL | integration | hash content |
| TC-14 | Batching | Many ticks between passes -> one pipeline execute; a second pass inside the same second writes nothing; the next second writes only the quotes that changed | unit | executes count, written keys |
| TC-15 | TTL refresh | During the open session an unchanged quote is re-written after TTL/2 so a quiet contract does not vanish while the leader lives | edge | rewrite after TTL/2 |
| TC-16 | Follower | A follower's cache pass writes nothing (only the lease leader writes) | unit | no Redis call |
| TC-17 | Redis down | Client getter raises or pipeline fails: feed tick still publishes the snapshot, cache pass returns without raising, one warning (class name only) per window; recovers after backoff | failure | snapshot ok; 1 warning; later write lands |
| TC-18 | Redis absent | REDIS_URL not configured (getter returns None): no warning, no crash, cache simply absent | failure | no warning |
| TC-19 | Minute | Open session: one `kite_live_minute` doc per minute with compact rows (s,p,b,a,bq,aq,o,v,t) for indices, futures and options; same minute again writes nothing; next minute writes a new doc | integration | doc ids, rows |
| TC-20 | Minute | First write wins: a doc already present for the minute (another leader) is kept unchanged | edge | original doc kept |
| TC-21 | Minute | No minute doc outside the open session | edge | none |
| TC-22 | Minute | TTL index on `saved_at` = `LIVE_MINUTE_TTL_DAYS` days; an index-option conflict is logged and does not stop the feed starting | unit/failure | index present; no raise |
| TC-23 | API | `GET /api/live/option-chain?underlying=NIFTY&expiry=` returns rows grouped by strike with CE/PE, each with received_at, age_seconds and `stale` when older than 2x cadence | api | grouped rows; stale flags |
| TC-24 | API | Option chain with Redis unavailable -> 200, rows [], cache "unavailable"; Redis up but no chain -> 200, rows [], cache "empty" | api/failure | as stated, no fabricated rows |
| TC-25 | API | Option chain needs sign-in; bad expiry is 422 | api/failure | 401 / 422 |
| TC-26 | API | `/api/live/quotes` serves fresher Redis quotes (bid/ask included) and fills the rest from the snapshot; body keys unchanged | api | merged quotes, same top-level keys |
| TC-27 | API | `/api/live/quotes` with Redis down -> exactly the snapshot answer (fallback) | api/failure | identical to snapshot path |
| TC-28 | Regression | Existing suites stay green: test_kite_live_feed, test_fno_quotes, test_kite_intraday, test_kite_platform_login | regression | all pass |
| TC-29 | Build | `python -m compileall -q backend` | build | no output, exit 0 |
| TC-30 | Data (staging, after deploy) | During market hours: `nivesh:quote:*` key count ~ universe size; `kite_live_minute` gains one doc per minute; `/api/live/option-chain` rows fresh | data | counts in band (NOT RUNNABLE before merge + restart + market hours) |
