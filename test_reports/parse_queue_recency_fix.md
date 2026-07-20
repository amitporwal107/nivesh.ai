# Verification — parse queue starved recent filings (recency-priority fix)

- **Date:** 2026-07-20  **Branch:** `dev` @ `5d74ad9f`  **Env:** STAGING (`nidp-stack-vm`, `nidp_staging`)
- **Changed:** `nidp/services/document_parser/db.py` — `_FETCH_PENDING_SQL` ORDER BY.

## Root cause (defect, not a queue-latency non-issue)
The `*/15` parser drains `fetch_pending_docs` **oldest-INGESTED first** (`ingested_at ASC`).
Measured on staging: a ~16.6k `pending` backlog, 3 days deep (mostly old backfilled/
discovered docs), so every freshly-filed material announcement lands at the BACK — a
filing ingested tonight waits ~3 days at ~200 docs/hr. Its AI insight needs parsed chunk
text, so with 0 chunks the generator can't run → the panel shows "no insight." This hit
today's material filings (Acme Solar, VA Tech Wabag, and others) while their older
filings were fine.

Parse pipeline was otherwise HEALTHY: 200 parsed last hour, 50 last 15 min, cron running.
So: a real prioritization defect, not a stall.

## Fix
`ORDER BY (parse_status='pending') DESC, filed_at DESC NULLS LAST` — parse the most
recent filing first; the low-value backlog drains behind it and in quiet periods.

## Test Cases
- TC1: recent filings now sit at the FRONT of the pending queue.
- TC2: force-parsing a starved filing produces chunks (unblocks it now).
- TC3: once parsed, the filing is insight-eligible (the OpenAI cron then generates).

## TC1 — recent-first ordering ✅
```
Top of pending queue (new ORDER BY): all 2026-07-20 announcement_attachments
  a71b7d3c, 8b9608b8, b279e8c0, feaefd0b, 0af4779d  (today's filings, front of queue)
```

## TC2 — starved filings force-parsed ✅
```
Acme Solar   45c316c5:  pending -> parsed, 1 chunk  (short intimation letter)
VA Tech Wabag fe0ad2c1:  pending -> parsed, 8 chunks
```

## TC3 — now insight-eligible ✅ (generation is the running cron's job)
Both are now classified-material + parsed + signal-less → they enter the filing_insights
generator's material-pending set. The OpenAI cron (verified working: 100 insights/40 min)
will produce their insight on its next tick (~within the hour). Generation itself was
already proven end-to-end (Turtlemint, Acme's older filings).

## Verdict: PASS
