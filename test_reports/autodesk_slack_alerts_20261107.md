# Functionality Verification Report — Desk support alerts to Slack (notifier, first slice)

- **Branch:** feat/autodesk-slack-alerts (local, not pushed)
- **Date:** 2026-11-07
- **Author:** Claude (Account 2)
- **Environment:** throwaway container from the staging image + throwaway Postgres. NOT staging.
- **Changed areas:** backend routes/services: yes (new routers/alerts.py, 4 lines in main.py) · frontend src: no

## Summary
Built the send-only notifier: event classification and fixed messages, Slack incoming-webhook transport, retry, dedupe,
burst control, DB cursor (existing autodesk.event_cursors), admin-only test route, background pump started from main.py.
Only support issues are published (owner decision 7 Nov); agent-chat mirroring and inbound Slack are not built.
All tests use a fake transport (labelled MOCK) and a made-up webhook string. Nothing was sent to Slack by these tests.

## Test Cases
Source: docs/autodesk/testcases_alerts_slack.md (written before the code).

| ID | Scenario | Type | Result |
|----|----------|------|--------|
| AD-AL-01..06 | content, severity, IST/UTC, account label, wording lint, truncation | unit | PASS |
| AD-AL-07..09 | URL never leaks, not configured, bad credentials not retried | unit | PASS |
| AD-AL-10..12, 15 | retry, Retry-After, permanent errors, critical first | unit | PASS |
| AD-AL-13, 14 | restart without repeat or skip; rollback leaves no alert | db | PASS |
| AD-AL-16..19 | dedupe, separate keys, burst, resolved | unit | PASS |
| AD-AL-23..25 | send-only, no order code, failing transport never raises | unit | PASS |
| AD-AL-26 | admin-only test route (401, 403, 200, 503, 502) | api (TestClient, fake user) | PASS |
| AD-AL-20..22 | workflow chat | — | NOT BUILT (deferred by owner) |
| AD-AL-27, 28 | real message in the channel; real alert from a forced check | real channel | NOT RUN |

Changes to the written test cases: AD-AL-19 expected a thread reply; an incoming webhook returns no message id, so RESOLVED
is a new top-level message instead.

## API / Endpoint Tests
- **pytest** (throwaway container, `sudo bash backend/scripts/run_autodesk_tests.sh <worktree> tests/autodesk tests/test_order_path_guard.py`):
  `199 passed in 40.38s` (whole desk suite, includes the notifier tests and the order-path guard).
- The route was tested with a faked signed-in user. It was NOT called on staging (not deployed; no session token).

## UI / Playwright Tests
Not applicable: no frontend change.

## Data Correctness
Cursor and outbox cases ran on a throwaway Postgres. UNVERIFIED on staging data: no real events were read.
UNVERIFIED: that a message reaches channel C0CFKMTJNUD. A hand-sent test (curl, HTTP 200 `ok`) was made earlier this day
with the webhook the owner pasted; the owner has not yet confirmed seeing it, and the webhook URL is exposed in chat and must be rotated.

## Inputs required from user
- Rotate the webhook, store the new URL as AUTODESK_SLACK_WEBHOOK_URL in the staging environment (never in code or chat).
- Go-ahead to run AD-AL-27/28 after deploy; a staging admin session for the route.

## Verdict: BLOCKED
