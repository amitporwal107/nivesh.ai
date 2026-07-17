# Functionality verification — Ray backfill: pool-per-loop, real retries, BSE AttachHis

- **Date:** 2026-07-17
- **Branch / commits:** `dev` @ `9d491ae3` (pool + retries), `859b2faa` (AttachHis)
- **Environment:** STAGING — `nidp-stack-vm` + `nivesh-app-vm`, DB `nidp_staging`
- **Changed areas:** `backend/nidp/deploy/vm/ray_day_backfill.py` (new to VCS),
  `backend/nidp/services/document_parser/service.py`

All three defects below were found by **reading the log of a run that looked healthy**.
The driver reported progress the whole time it was losing days.

---

## TC1 — asyncpg pool must not outlive its event loop

A Ray worker process is reused across day-tasks; each task is its own `asyncio.run()`,
i.e. its own event loop. `nidp.shared.storage.pg` caches the pool in a module global, and
an asyncpg connection is bound to the loop that created it. So a worker's **first** day
succeeded and every later day on that worker died in 0.0s.

Reproduced against the real staging DB (two `asyncio.run()` in one process — exactly what
a reused worker does):

```
=== CURRENT CODE: pool cached across event loops ===
  task1 (fresh worker): 91499 pending docs
  task2 (REUSED worker) FAILED -> InterfaceError: cannot perform operation: another operation is in progress

=== FIXED CODE: close_pool() in finally, inside the same loop ===
  task1 (reused worker): 91499 pending docs
  task2 (reused worker): 91499 pending docs
  task3 (reused worker): 91499 pending docs
```

Fix: `await pg.close_pool()` in a `finally` **inside** the same loop (the function already
existed and was never called), plus a defensive `pg._pool = None` at task start to drop any
pool a hard-crashed predecessor left behind.

Confirmed on the relaunched run:
```
InterfaceError now : 0        (was 32 days killed)
0.0s day failures  : 0
days LOST          : 0
```
**PASS**

## TC2 — a failed day must go back on the queue, not be counted as done

The driver treated "task returned" as "day parsed" — but a returned `{"error": ...}` is a
crash. Measured on the previous run:

```
days consumed by driver : 43
-> real parse runs      : 11
-> InterfaceError @0.0s : 32   <-- consumed, parsed NOTHING, never retried
```

It would have printed `done: 80 days` having parsed 11. Fix: bounded requeue
(`MAX_DAY_RETRIES=2`), an ObjectRef->day map so a hard-dead task's day is still recoverable,
a loud unrecovered-day list, and `main()` returns 1 — a run that skipped work can no longer
exit clean. Relaunched run shows the new banner and zero losses:
```
in-flight cap: 5 days | vision: OFF (429-storms) | day retries: 2
```
**PASS**

## TC3 — aged BSE attachments are recoverable via AttachHis

The relaunched run's first completed day:
```
[1/69] 2026-01-30  parsed=6 failed=1164 skipped=0  41.3s
```
6 of 1,170. Cause: BSE serves an attachment from `/corpfiling/AttachLive/<file>` only while
recent, then MOVES it to `/corpfiling/AttachHis/<file>` — same filename. `parser_bse.py`
only ever constructs AttachLive, so every attachment older than the live window 404s. A
6-month backfill is made almost entirely of these.

Tested against the two URLs that **actually failed in the halted run**:
```
6d25e8c4-7970   AttachLive=404   AttachHis=200   magic=%PDF   10,057,931b
9fd40998-5fa7   AttachLive=404   AttachHis=200   magic=%PDF      662,187b
```
Both return real PDFs. `_download()` now falls back to the archive twin on a 404; the
fallback is BSE-only and AttachLive-only, so a genuine 404 elsewhere still raises.
**PASS at the URL level** — see limitation 1: not yet exercised in-pipeline.

## TC4 — vision tier off for bulk backfill

Measured 444 OpenAI rate-limit 429s in one hour, producing nothing: each attempt rasterises
a page (`pdftoppm`, ~89% CPU) and is then refused, dragging throughput 511 -> 306/min.
`vision_available()` gates on a non-empty `OPENAI_API_KEY`, so the driver ships
`OPENAI_API_KEY=""` in `runtime_env.env_vars` — no product-code change. Scanned docs park as
`skipped_non_text` and stay re-runnable in a later, rate-aware pass.
**PASS**

---

## Known limitations (honest scope)

1. **The AttachHis fix has NOT run in the pipeline.** TC3 proves the URLs resolve and the
   code compiles; it does **not** prove the deployed parser stores those PDFs. The redeploy
   + relaunch is blocked on an expired `/app/.gcp-token`. Until that runs, the expected
   recovery of the ~1,164/day BSE slice is a **projection, not a result**.
2. **~1,164 documents burned one of five `parse_attempts`** on day 2026-01-30 during the
   halted run. Re-fetch is gated at `parse_attempts < 5`, so four remain — no loss, but the
   budget is not infinite and each un-fixed pass costs a fifth of it.
3. **Backfill is INCOMPLETE.** 29,710 parsed / 15 of 84 days at halt; ~91.5k documents remain
   `parse_status='pending'`. The DB is the queue, so a re-run resumes exactly where this
   stopped. Nothing here claims the corpus is done.
4. **The vision tier still has no rate-limit backoff.** TC4 works around it for bulk
   backfill by switching the tier off. The underlying defect — no retry/backoff on 429 — is
   untouched and will resurface for any rate-sensitive vision use.
5. **UNVERIFIED on prod.** Everything above is staging. Prod tracks `main` and still carries
   the AttachLive-only downloader.

## Verdict: PASS
