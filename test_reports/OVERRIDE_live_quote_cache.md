# OVERRIDE: live_quote_cache (PR C)

REASON: live verification needs merge to dev, backend restart and market hours (Mon 2026-10-26 09:15 IST); local pytest: 133 passed, 2 warnings in 8.49s (collected: test_kite_live_feed 53, test_live_quote_cache 32 new, test_fno_quotes 12, test_kite_intraday 11, test_kite_platform_login 25); compileall exit 0, no output.

- **Branch:** feat/live-quote-cache (off origin/dev b74c7f4f), not pushed
- **Date:** 2026-10-25
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Changed areas:** backend routes/services: yes · frontend src: one comment only (`tradingdesk/strategy/top-live.ts` header, no code)
- **Test cases:** `test_reports/live_quote_cache_TESTCASES.md` (written before the code)

## What was run (this session, real output)

Throwaway container from `nivesh/backend:staging`, worktree mounted read-only, `--network none`:

    python -m pytest tests/test_kite_live_feed.py tests/test_live_quote_cache.py tests/test_fno_quotes.py tests/test_kite_intraday.py tests/test_kite_platform_login.py -q -p no:cacheprovider
    133 passed, 2 warnings in 8.49s

    (before the new tests existed, the four existing files on the changed code: 101 passed, 2 warnings in 7.55s)

    PYTHONPYCACHEPREFIX=/tmp/pyc python -m compileall -q backend
    compileall exit=0 lines_of_output=0

The two warnings are third-party deprecation notices (starlette `multipart`, google.api_core Python 3.11), not from this change.
A first compileall attempt without PYTHONPYCACHEPREFIX failed with `OSError: [Errno 30] Read-only file system` writing
`__pycache__` into the read-only mount; that was the mount, not the code.

Mutation check (scratch copies of the tree, each mutation must fail at least one new test):

| Mutation | Result |
|---|---|
| remove the once-per-second flush guard | 1 failed (batching test) |
| minute snapshot `insert_one` -> `replace_one` (last write wins) | 2 failed (first-write-wins, retry) |
| options first in the universe priority | 4 failed (ordering, cap, settings, minute rows) |
| `/quotes` ignores the Redis row | 1 failed (Redis-first quotes) |

## Test case results

| ID | Result | Test (backend/tests/test_live_quote_cache.py unless noted) |
|----|--------|------|
| TC-1 | PASS (unit) | test_option_and_cache_settings_defaults_parsing_and_clamps |
| TC-2 | PASS (unit) | test_option_contracts_keep_the_two_nearest_unexpired_expiries_of_configured_underlyings |
| TC-3 | PASS (unit) | test_atm_strike_is_the_nearest_listed_strike_and_a_tie_takes_the_lower |
| TC-4 | PASS (unit) | test_select_options_takes_atm_plus_minus_n_both_types_clipped_at_the_ends_and_never_guesses_a_missing_spot |
| TC-5 | PASS (integration, fakes) | test_options_are_the_last_universe_set_quoted_under_nfo_and_decorated, test_options_are_subscribed_in_full_mode |
| TC-6 | PASS (integration, fakes) | test_atm_comes_from_the_index_quote, test_atm_falls_back_to_the_near_future_when_the_index_quote_is_absent |
| TC-7 | PASS (integration, fakes) | test_the_window_re_centres_on_the_next_rebuild |
| TC-8 | PASS (integration, fakes) | test_the_first_pass_without_a_spot_leaves_options_pending_and_the_next_pass_adds_them |
| TC-9 | PASS (unit) | test_over_the_cap_options_are_dropped_first_then_futures |
| TC-10 | PASS (unit) | test_make_quote_keeps_top_of_book_and_none_never_zero |
| TC-11 | PASS (integration, fakes) | test_rest_and_full_mode_ticks_both_carry_the_top_of_book |
| TC-12 | PASS (fake Redis) | test_the_leader_writes_every_changed_quote_with_the_spec_fields_kind_and_ttl |
| TC-13 | PASS (fake Redis) | test_the_chain_index_maps_strike_and_type_to_the_key_and_is_replaced_on_re_centre |
| TC-14 | PASS (fake Redis) | test_writes_are_batched_once_per_second_and_only_changed_quotes_are_rewritten |
| TC-15 | PASS (fake Redis) | test_during_the_session_a_quiet_quote_is_rewritten_after_half_the_ttl |
| TC-16 | PASS (fake Redis) | test_a_follower_writes_nothing |
| TC-17 | PASS (fake Redis) | test_redis_down_never_breaks_the_feed_warns_once_and_recovers |
| TC-18 | PASS (fake Redis) | test_redis_not_configured_is_silent_and_the_cache_is_simply_absent |
| TC-19 | PASS (fake Mongo) | test_one_compact_minute_doc_per_open_minute_for_indices_futures_and_options |
| TC-20 | PASS (fake Mongo) | test_the_first_write_of_a_minute_wins |
| TC-21 | PASS (fake Mongo) | test_no_minute_doc_outside_the_session_but_the_closing_quotes_are_cached, test_a_failed_minute_write_is_logged_once_and_retried |
| TC-22 | PASS (fake Mongo) | test_the_minute_collection_has_a_configurable_ttl_index_and_a_conflict_does_not_stop_the_start |
| TC-23 | PASS (TestClient, fake Redis) | test_option_chain_groups_by_strike_with_received_at_and_stale_flags |
| TC-24 | PASS (TestClient, fake Redis) | test_option_chain_is_200_with_no_rows_when_the_cache_is_unavailable_or_empty |
| TC-25 | PASS (TestClient) | test_option_chain_needs_sign_in_and_a_valid_expiry |
| TC-26 | PASS (TestClient, fake Redis) | test_quotes_prefer_the_fresher_redis_quote_and_fill_the_rest_from_the_snapshot, test_a_cached_row_round_trips_to_the_snapshot_quote_shape |
| TC-27 | PASS (TestClient, fake Redis) | test_quotes_with_redis_down_are_exactly_the_snapshot_answer |
| TC-28 | PASS | the 101 pre-existing tests in the four existing files, all green |
| TC-29 | PASS | compileall exit 0 |
| TC-30 | NOT RUN | needs merge + restart + market hours (commands below) |

## UNVERIFIED

- Nothing ran against real Kite, real Redis or real Mongo. Unverified: Kite's full-mode depth shape on options, the real
  NFO option rows and tradingsymbols, the ~1,100-instrument subscription, MULTI/EXEC against the shared staging Redis
  (256 MB, allkeys-lru), and the TTL index on a real `kite_live_minute`.
- The staging backend bind-mounts the checkout, so it needs a process restart after the merge (an image rebuild is not needed).
- Size estimate, not measured: each minute document is about 460 rows (about 119 indices, about 220 futures, 208 options at the
  defaults), roughly 40-60 KB. That is about 15-20 MB per session before WiredTiger compression, and about 1 GB over the 90-day TTL.

## Data tests to run after deploy (Mon 2026-10-26, after 09:20 IST)

    # Redis: per-symbol keys ~ /api/live/status instrument_count, plus 4 chain hashes (NIFTY x2 expiries, BANKNIFTY x2)
    # (add -a/--user if the staging Redis requires auth)
    sudo docker exec nivesh-staging-redis redis-cli --scan --pattern 'nivesh:quote:*' | wc -l
    sudo docker exec nivesh-staging-redis redis-cli --scan --pattern 'nivesh:quote:chain:*'
    sudo docker exec nivesh-staging-redis redis-cli HLEN 'nivesh:quote:chain:NIFTY:<nearest expiry>'      # expect 62
    sudo docker exec nivesh-staging-redis redis-cli TTL 'nivesh:quote:NSE:NIFTY 50'                       # 0 < ttl <= 600

    # Mongo, using the backend's own environment (no credential is typed or printed); expect +1 per minute since 09:15
    sudo docker exec nivesh-staging-app-backend python -c "import os; from pymongo import MongoClient; db=MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]; print(db.kite_live_minute.count_documents({'day':'2026-10-26'}), db.kite_live_intraday.count_documents({'day':'2026-10-26'}))"

    # API (signed in): rows with fresh received_at, stale_count small while the socket is healthy
    GET /api/live/option-chain?underlying=NIFTY&expiry=<nearest expiry>
    GET /api/live/status   -> universe.options == 208 at the defaults (0 means no spot yet; it should fill on the next pass)
