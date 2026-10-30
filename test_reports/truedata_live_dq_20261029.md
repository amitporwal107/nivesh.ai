# TrueData data-quality checks: live shadow feed + nightly cross-check (PR-5) — verification report, 29 Oct 2026

- **Branch:** `feat/truedata-live-dq`, from dev 0695dd7f.
- **Test cases:** `test_reports/truedata_live_dq_TESTCASES.md`, written before the code.
- **Owner, 29 Oct 2026:** "make sure we keep data quality checks on TrueData", then "go ahead" with:
  - step 1: live checks plus a comparison with Kite;
  - step 2: the nightly cross-check scheduled, with findings in the DQ tables and alerts.

## What changed
| File | What |
|---|---|
| `backend/nidp/shared/market_data_source.py` | `shadow` no longer needs `TRUEDATA_INTEGRATED` (it never switches our feeds off); `truedata` still does, and steps down to `shadow`. Credentials, the env force-current and the licence gate are unchanged. |
| `backend/services/truedata_live/` (new) | `protocol.py` parses TrueData's WebSocket messages. `checks.py` holds the connection and per-tick checks. `compare.py` compares with Kite. `shadow.py` is the runner: lease, login, subscribe, per-minute documents, alerts, start/stop/status. |
| `backend/server.py` | starts/stops the shadow beside the Kite live feed (it starts only when the switch has TrueData on and the WebSocket login is set) |
| `backend/routes/live_quotes.py` | `GET /api/live/truedata/status` (signed in, read only) |
| `backend/nidp/services/truedata_crosscheck/` | `--record`: job_log + validation_runs + validation_findings, alerts on ERROR/CRITICAL. The known OI limit is counted apart (`truedata.fo_oi_overflow`, WARN). |
| `deploy/cloudpe/nidp/nidp-staging-truedata.cron` (new) | weekdays 22:45 IST, a separate `/etc/cron.d` file |
| `docs/MARKET_DATA_SOURCE_SWITCH.md` | the shadow rule; the checks and how to turn them on |
| tests + `.github/workflows/backend-tests.yml` | `tests/test_truedata_live.py` (new) added to the CI list; new cases in the existing TrueData and switch suites |

**Nothing changes for users.** The switch file still says `current`. The live checks start only once:
- the switch is set to `shadow` in a PR;
- the WebSocket login is in the app server's environment.

## Results

### Unit (backend image, network off; synthetic TrueData messages, MOCK — not real data)
```
tests/test_truedata_live.py                      24 passed   (LP-1…6, LC-1…6, LT-1…13, LK-1…5, LR-1…6)
nidp/tests/shared/test_truedata_client.py        40 passed   (incl. NR-1…NR-7)
nidp/tests/shared/test_market_data_source.py     23 passed   (incl. SH-1…SH-4)
tests/test_truedata_adapter.py                   13 passed
tests/test_kite_live_feed.py                     53 passed   (Kite live feed unchanged)
tests/test_live_quote_cache.py                   32 passed
tests/test_market_data_switch_live_feed.py        2 passed
```

### Regression: the full CI allowlist (277 files)
```
3 failed, 7159 passed, 33 skipped in 247.00s
FAILED tests/test_cas_api_client.py::test_sandbox_parse_and_map
FAILED tests/test_cas_api_client.py::test_convenience_helper_returns_list
FAILED tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches
```
These are the same 3 network-only failures `dev` has (same run on dev 0695dd7f: 3 failed, 7125 passed).

### RS-1: real TrueData sandbox WebSocket, 19:38 IST (after hours)
Run inside the staging backend container (its Python, websockets 16, the real Kite cache), from a scratch copy that was
removed after. Writes went to an in-memory store, never staging Mongo. The output was checked for both passwords:
0 hits.
```
login: {"ok": true, "segments": ["EQ","FO","MCX","IND","BSEEQ","BSEIND","BSEFO"], "maxsymbols": 50, "subscription": "tick", "validity": "2026-11-05"}
requested 29 = subscribed 29 (5 indices, NIFTY26NOVFUT, BANKNIFTY26NOVFUT, RELIANCE26NOVFUT, IDEA26NOVFUT, 20 stocks); not_subscribed [], over_limit [], meta_missing []
MINUTE 19:38 {"session": "closed", "messages": 4, "ticks": 29, "heartbeats": 3, "findings": {"LOGIN_EXPIRING": 1}}
MINUTE 19:39 {"session": "closed", "messages": 12, "ticks": 0, "heartbeats": 12, "findings": {}}
ALERT: [Nivesh] TrueData live (shadow): LOGIN_EXPIRING        (sandbox login valid until 2026-11-05: a true alert)
META: RELIANCE ('EQ', tick 0.1, circuit 1042.2–1273.8)   ended: time limit (100 s), logout sent
```
What this shows:
- The near-month futures names came from TrueData's own symbol master (NIFTY-I → NIFTY26NOVFUT).
- Heartbeats arrived every 5 s.
- All 29 touchlines parsed, and no check fired on clean data.
- The Kite comparison was `no_kite_quote` for all 29. After hours the Kite cache rows have expired (10-minute TTL),
  so the comparison needs market hours (RS-3).

### RS-2: nightly cross-check with `--record`, 28 Oct, on the NIDP VM
Run with the job runner's Python and `nidp.env`, plus `--evaluation` because the switch is `current`. The owner approved
writing these rows.
```
exit=0   verdict: DIFFERENT | mode: evaluation (switch is current)
fno: oi_overflow 1 | unexplained 0 | equity equal 3404 / 3404
recorded: {"job_status": "OK", "validation_status": "PASSED", "alerted": false, ...}
findings: [('truedata.fo_oi_overflow', 'WARN', 'INFO')]
```
Database check (real rows):
```
nidp.job_log             truedata_crosscheck | 2026-10-28 | OK | rows_fetched 16140
nidp.validation_runs     truedata_crosscheck | 2026-10-28 | PASSED | rules_run 6 | rules_failed 1 | findings 1 | notes {"verdict": "DIFFERENT", "mode": "evaluation (switch is current)", ...}
nidp.validation_findings truedata.fo_oi_overflow | WARN | INFO | sample [{"contract": "IDEA26NOVFUT", "nse_oi": 6173152800.0, "td_oi": 0.0, ...}]
nidp.v_feed_status       truedata_crosscheck | derived | daily | last_success_at 2026-10-29 21:15:41 | success_count 1
```

### LR-5 on staging: the new API endpoint in the running backend container
Scratch copy, removed after. It used the container's auth and staging Mongo, and a real signed-in session token
passed on stdin.
```
no session -> 401
signed in  -> 200
BODY: {"switch": {"effective": "current", "truedata_on": false, "reasons": []}, "not_started_because": "TrueData is switched off: market data source is 'current' (backend/config/market_data_source.json)", "today": {"day": "2026-10-29", "minutes_recorded": 0, ...}}
token in body: False
```

## UNVERIFIED
- **RS-3, market hours.** These need the PR merged, the WebSocket login in `.env.staging`, the switch at `shadow`, and a
  session (30 Oct, 09:15–15:30):
  - the live per-tick checks on real trades;
  - the Kite agreement rate;
  - the staleness thresholds;
  - whether TrueData's tick sequence numbers are per symbol (SEQ_GAP stays INFO until then).
- **Alert delivery.** It uses the existing email/Telegram channels (`nidp.shared.notify`, the live feed's
  `default_notifier`). No real alert was sent in these runs: the sandbox run used a print notifier, and the nightly run
  had nothing above WARN.
- **The sandbox WebSocket login expires on 5 Nov 2026.** After that the live shadow needs a production login from
  TrueData.

## Verdict: PASS
