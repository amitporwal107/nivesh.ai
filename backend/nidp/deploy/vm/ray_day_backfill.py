"""Ray day-by-day document backfill across nivesh-app-vm + nidp-stack-vm.

WHY THIS WRAPS run_once() INSTEAD OF REIMPLEMENTING THE PARSE
------------------------------------------------------------
The template pipeline did `download -> fitz.get_text() -> results.jsonl`. That
would produce a JSON file, not the corpus, and would silently drop every fix
earned on 2026-07-17:

  * _pg_safe()            — strips NUL *and lone surrogates*. Both crashed real
                            backfills (CharacterNotInRepertoireError at doc ~1,
                            DataError "surrogates not allowed" at doc 4,472).
  * content doc_type      — types transcripts/presentations/annual reports.
  * chunk_text()          — 2k chunks + char/page offsets the RAG index needs.
  * audio_extractor       — issuers file a letter linking an mp3; no PDF tool
                            reaches it. 22x content gain on those docs.
  * atomic documents+chunks write, and parse_attempts bounded retry.

So Ray is used for what Ray is good at — scheduling, resource enforcement,
distribution — and the parsing stays in the code that has been debugged.

THE QUEUE IS THE DATABASE, NOT THIS SCRIPT
------------------------------------------
`pending_days()` reads the days the parser would still act on, mirroring
fetch_pending_docs() exactly (new 'pending', OCR-retryable 'skipped_non_text',
and 'failed' docs under the attempt cap).

Ordered NEWEST-FIRST, and --since-days bounds how far back it goes. Both exist
for the same reason: announcement_classifier only queues filed_at >= now()-30d,
so a document older than that is parsed into a corpus whose announcement can
never be classified. Measured 2026-07-17: a 6-month backfill left 126,994 of
146,091 announcements permanently unclassifiable. Oldest-first spent its effort
on exactly the days that yield the least. --since-days 30 matches the window. Nothing here is authoritative: kill
this driver at any point and re-run it, and it picks up exactly what is left. That property is what made the 2026-07-17
InterfaceError incident (below) a waste of an hour rather than a data loss.

RESOURCE DECLARATIONS ARE THE POINT
-----------------------------------
Per-task num_cpus/memory are not decoration. On 2026-07-17 this VM was
OOM-killed (3GB discover_pending + unbounded 1.4GB whisper containers), taking
SSH, code-server and prod Postgres' host down. Ray's scheduler refuses to place
more tasks than fit — which is strictly better than the flock+MemoryMax I was
otherwise hand-rolling.

TOPOLOGY (measured, not guessed)
--------------------------------
  head   nivesh-app-vm  10.160.0.5  3 CPUs — was 67% idle. ZERO swap, and it is
                                    the NFS server for the staging DB: memory
                                    pressure here degrades the database itself.
  worker nidp-stack-vm  10.160.0.3  1 CPU  — runs prod Postgres, 13 containers,
                                    code-server, and the whisper transcriptions.

Run from nidp-stack-vm (it has the code + DB env):
    /opt/ray-env/bin/python -u ray_day_backfill.py [--limit-days N] [--dry-run]

Exit code is 1 if any day did not parse — "it printed done" must never be the
same thing as "the work happened".
"""
from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
import time
from collections import deque
from datetime import date, timedelta

import ray

BACKEND = "/opt/nidp/dev-repo/nivesh.ai/backend"
# The queue's VPC address. Workers on 10.160.0.5 cannot use "localhost".
DB_HOST = os.environ.get("NIDP_DB_HOST", "10.160.0.3")

# Sized from MEASUREMENT, not guesswork. The first run reserved 3GB/task while
# tasks actually used 265-336MB RSS — so Ray's scheduler capped the cluster at 3
# concurrent tasks (9GiB of 16.44GiB) and left a CPU idle with cores 32% unused.
# The reservation, not the exchanges, was the bottleneck.
#
# num_cpus=0.5: a day-task is I/O-bound (measured %Cpu 25 us / 32.5 idle — it sits
# waiting on downloads, most of which are 404s on expired BSE AttachLive URLs).
#
# 8 was too many. Measured: throughput FELL (467 -> 321/min) while load climbed
# (1.6 -> 11.3) — the tasks were contending, not working. 5 keeps all 4 CPUs busy
# (5 x 0.5 = 2.5 CPU reserved, plus OCR headroom) without the thrash. Past the
# knee, more in-flight is negative throughput.
MAX_IN_FLIGHT = 5
PARSE_LIMIT = 2500          # a day is ~1,468 docs; this bounds the fetch
CONCURRENCY = 3             # in-flight downloads per task -> 5 x 3 = ~15 cluster-wide
TASK_MEM = 1024**3          # 1GB: 3x headroom over the 336MB observed. The whisper
                            # container has its OWN --memory=3g and is capped to one
                            # at a time by flock, so it is not part of this budget.

# A day that errors goes BACK on the queue. On 2026-07-17 a returned {"error":...}
# was counted as "done" and dropped: 32 of 43 days were consumed at 0.0s each and
# never retried, and the driver would have printed "done: 80 days" having parsed 11.
MAX_DAY_RETRIES = 2


@ray.remote(num_cpus=0.5, memory=TASK_MEM, max_retries=1)
def parse_day(day_iso: str) -> dict:
    """Parse one day's documents using the REAL pipeline. Never raises.

    NOTE: do NOT chdir/sys.path to BACKEND here. That path exists only on
    nidp-stack-vm; nivesh-app-vm has no NIDP checkout, which is exactly why the
    driver ships the code via runtime_env={"working_dir": ...}. Ray unpacks it
    per worker and sets CWD to it, so a plain import resolves on BOTH nodes.
    Hardcoding the path made every task on 10.160.0.5 die with FileNotFoundError.
    """
    from nidp.services.document_parser.service import run_once
    from nidp.shared.storage import pg

    # ---- THE POOL MUST NOT OUTLIVE ITS EVENT LOOP -------------------------
    # Ray REUSES a worker process across day-tasks, but asyncio.run() below
    # creates a fresh event loop per task and closes it on the way out.
    # nidp.shared.storage.pg caches its asyncpg pool in a module global, and an
    # asyncpg connection is bound to the loop that created it. So task #2 on any
    # given worker inherited a pool pointing into a CLOSED loop and died on the
    # first query with:
    #     InterfaceError: cannot perform operation: another operation is in progress
    # Signature: the worker's first day succeeds, every later day on that worker
    # fails in 0.0s. Measured 2026-07-17: 32 of 43 days consumed, 11 parsed.
    # Belt: drop any pool a hard-crashed predecessor left behind (its loop is
    # already gone, so there is nothing closeable to leak).
    pg._pool = None

    day = date.fromisoformat(day_iso)
    t0 = time.time()

    async def _run_and_close():
        try:
            return await run_once(
                discover_limit=0,          # discovery is done (143,930 registered) and
                                           # is the call that OOM'd the box at 150000
                parse_limit=PARSE_LIMIT,
                concurrency=CONCURRENCY,
                embed_limit=0,             # embeddings would add ~6KB/chunk = ~28GB
                from_date=day,
                to_date=day + timedelta(days=1),
            )
        finally:
            # Braces: close inside THIS loop, which is the whole point — a pool
            # closed from a different loop is the bug, not the fix.
            try:
                await pg.close_pool()
            except Exception:               # noqa: BLE001 — teardown must not mask the run
                pg._pool = None

    try:
        summary = asyncio.run(_run_and_close())
        summary.update(day=day_iso, host=socket.gethostname(),
                       secs=round(time.time() - t0, 1))
        return summary
    except Exception as e:                                   # noqa: BLE001
        return {"day": day_iso, "host": socket.gethostname(),
                "error": f"{type(e).__name__}: {e}", "secs": round(time.time() - t0, 1)}


async def pending_days(since_days: int | None = None) -> list[str]:
    """Days holding documents the parser would still act on, oldest first.

    MUST mirror fetch_pending_docs()'s predicate: this is the day-level twin of
    that doc-level queue, and the two disagreeing is a silent skip. So it reuses
    the same statuses list and attempt cap rather than restating them.

    An earlier version selected only parse_status='pending'. But fetch_pending_docs
    ALSO retries 'skipped_non_text' (once OCR exists) and 'failed' docs still under
    the attempt cap. Measured 2026-07-17: day 2026-01-30 ended 6 parsed / 1,164
    'failed' (BSE AttachLive 404s) — so the day dropped out of this list entirely,
    and the AttachHis fallback written to recover exactly those documents would
    never have been handed them. The driver would have reported a clean run.
    """
    sys.path.insert(0, BACKEND)
    from nidp.shared.storage import pg
    from nidp.services.document_parser.db import _MAX_PARSE_ATTEMPTS
    from nidp.services.document_parser.pdf_extractor import ocr_available

    statuses = ["pending", "skipped_non_text"] if ocr_available() else ["pending"]
    try:
        pool = await pg.get_pool()
        async with pool.acquire() as c:
            rows = await c.fetch("""
                SELECT DISTINCT filed_at::date AS d
                  FROM nidp.documents
                 WHERE filed_at IS NOT NULL
                   AND ($3::int IS NULL
                        OR filed_at >= (now() - make_interval(days => $3::int)))
                   AND (parse_status = ANY($1::text[])
                        OR (parse_status = 'failed' AND parse_attempts < $2))
                 ORDER BY 1 DESC""", statuses, _MAX_PARSE_ATTEMPTS, since_days)
        return [r["d"].isoformat() for r in rows]
    finally:
        # Same lesson as parse_day: never leave a pool bound to a loop that is
        # about to close. main() opens another loop after this one.
        await pg.close_pool()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-days", type=int, default=None, help="Only the first N days.")
    ap.add_argument("--since-days", type=int, default=None,
                    help="Only days with filed_at within the last N days. Use 30 to match "
                         "the classifier window — older documents parse into a corpus whose "
                         "announcements can never be classified.")
    ap.add_argument("--dry-run", action="store_true", help="List the plan, run nothing.")
    a = ap.parse_args()

    sys.path.insert(0, BACKEND)
    days = asyncio.run(pending_days(a.since_days))
    if a.limit_days:
        days = days[: a.limit_days]
    if not days:
        print("nothing pending", flush=True)
        return 0

    scope = f" (last {a.since_days}d)" if a.since_days else " (ALL history)"
    print(f"{len(days)} days pending{scope}: {days[0]} .. {days[-1]}", flush=True)
    if a.dry_run:
        for d in days[:10]:
            print(f"  would parse {d}")
        print(f"  ... ({len(days)} total)", flush=True)
        return 0

    # working_dir ships the 47MB backend to workers — nivesh-app-vm has no NIDP
    # checkout, and shipping code beats maintaining a second copy of the repo.
    # Ship env to the workers, but REWRITE the DB host first. nidp.env says
    # "@localhost:5434", which is correct on nidp-stack-vm and catastrophically
    # wrong on nivesh-app-vm — that box runs its own postgres containers
    # (including nidp-postgres-standby), so "localhost" silently resolves to a
    # DIFFERENT database and every task fails with:
    #     InvalidPasswordError: password authentication failed for "nidp_staging"
    env = {k: v for k, v in os.environ.items() if k.startswith(("NIDP_", "PG")) and v}
    for k, v in list(env.items()):
        if "://" in v and ("@localhost" in v or "@127.0.0.1" in v):
            env[k] = v.replace("@localhost", f"@{DB_HOST}").replace("@127.0.0.1", f"@{DB_HOST}")
            print(f"  rewrote {k}: localhost -> {DB_HOST} (workers are not on the DB host)", flush=True)

    # ---- VISION OFF FOR BULK BACKFILL -------------------------------------
    # vision_available() gates on a non-empty OPENAI_API_KEY, so this disables
    # the tier without touching product code. Why: measured 2026-07-17, vision
    # took 444 rate-limit 429s in one hour and produced nothing. Each attempt
    # rasterises a page (pdftoppm, ~89% CPU) and is then REFUSED — CPU burned,
    # no text gained, throughput down (511 -> 306/min). OpenAI's per-minute cap
    # is far below what a 5-way parallel backfill offers it. Scanned docs park
    # as skipped_non_text and stay re-runnable in a later, rate-aware pass.
    # Ray workers inherit the raylet's env, so this must be set EXPLICITLY —
    # the NIDP_/PG_ filter above would not carry it.
    env["OPENAI_API_KEY"] = ""

    ray.init(address="auto", logging_level="ERROR", runtime_env={
        "working_dir": BACKEND,
        "excludes": ["tests/", "data/", "**/__pycache__", "**/*.pyc"],
        "env_vars": env,
    })
    res = ray.cluster_resources()
    print(f"cluster: {res.get('CPU',0):.0f} CPUs, {len([n for n in ray.nodes() if n['Alive']])} nodes")
    print(f"in-flight cap: {MAX_IN_FLIGHT} days | vision: OFF (429-storms) | day retries: {MAX_DAY_RETRIES}\n",
          flush=True)

    queue: deque[str] = deque(days)
    ref_day: dict = {}          # ObjectRef -> day, so a dead task's day is recoverable
    attempts: dict[str, int] = {}
    lost: list[str] = []
    done_n = parsed_n = failed_n = requeued_n = 0
    t0 = time.time()

    def submit() -> object | None:
        if not queue:
            return None
        d = queue.popleft()
        ref = parse_day.remote(d)
        ref_day[ref] = d
        return ref

    pending = [r for r in (submit() for _ in range(MAX_IN_FLIGHT)) if r is not None]

    def retry_or_lose(day: str, why: str) -> None:
        nonlocal requeued_n
        attempts[day] = attempts.get(day, 0) + 1
        if attempts[day] <= MAX_DAY_RETRIES:
            queue.append(day)               # back on the queue — NOT counted as done
            requeued_n += 1
            print(f"  [retry {attempts[day]}/{MAX_DAY_RETRIES}] {day}  {why[:90]}", flush=True)
        else:
            lost.append(day)
            print(f"  [LOST] {day} failed {attempts[day]}x: {why[:90]}", flush=True)

    while pending:
        ready, pending = ray.wait(pending, num_returns=1)
        ref = ready[0]
        day = ref_day.pop(ref, "?")
        try:
            r = ray.get(ref)
        except Exception as e:                               # noqa: BLE001
            retry_or_lose(day, f"task died: {type(e).__name__}: {e}")
            r = None
        if r:
            if r.get("error"):
                retry_or_lose(r["day"], r["error"])
            else:
                done_n += 1
                parsed_n += r.get("parsed", 0)
                failed_n += r.get("failed", 0)
                print(f"  [{done_n}/{len(days)}] {r['day']}  parsed={r.get('parsed',0)} "
                      f"failed={r.get('failed',0)} skipped={r.get('skipped_non_text',0)}  "
                      f"{r['secs']}s  @{r['host']}", flush=True)
        nxt = submit()
        if nxt is not None:
            pending.append(nxt)

    el = time.time() - t0
    print(f"\n{done_n}/{len(days)} days parsed, {parsed_n} docs parsed, {failed_n} docs failed "
          f"in {el/60:.1f} min ({parsed_n/max(el/60,1):.0f} docs/min)", flush=True)
    if requeued_n:
        print(f"{requeued_n} transient day-failures were retried and recovered", flush=True)
    if lost:
        # Loud, and non-zero exit. A run that skipped days must never look like a
        # clean one — that is exactly how 32 lost days went unnoticed for an hour.
        print(f"\n!! {len(lost)} DAYS NOT PARSED after {MAX_DAY_RETRIES} retries:", flush=True)
        print(f"   {', '.join(lost)}", flush=True)
        print("   Their documents remain queued (pending, or failed under the attempt "
              "cap) — re-run to pick them up.", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
