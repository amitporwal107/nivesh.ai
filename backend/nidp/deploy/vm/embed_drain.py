"""One-shot embedding drain — clears the chunk backlog the */15 cron cannot.

WHY THIS EXISTS
---------------
The document_parser cron embeds --embed-limit 200 every 15 minutes: an 800/hour
ceiling. Against ~710k unembedded chunks that is weeks, and it loses ground while
the Ray parse backfill adds chunks with embed_limit=0. Nothing is slow —
embed_texts already batches at 128/call — we were just asking for a little at a
time and then sleeping. This asks for large batches and lets OpenAI's TPM set the
pace (TPM is the real ceiling; more local parallelism cannot beat it).

Cost is not the constraint: ~364M tokens at text-embedding-3-small ($0.02/1M) is
~$7. Safe to kill and re-run at any point — embed_pending() only fills NULL
embeddings, so the DB IS the queue and a re-run resumes where it stopped.

TWO DISTINCT "embedded==0" OUTCOMES — do not conflate them
----------------------------------------------------------
An earlier version exited "done" after 3 empty passes, counting these the same:
  * candidates==0  -> the queue is actually empty. Truly done.
  * candidates>0, embedded==0 -> the API REFUSED every candidate (e.g.
    insufficient_quota, which is a 429 the SDK retries but cannot rescue). NOT
    done — declaring victory here silently leaves the corpus unembedded, exactly
    the failure the Embed dashboard tile exists to catch.
So they are tracked separately: a real empty streak exits 0; a refusal streak
hard-stops LOUDLY with a non-zero exit and never claims completion.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, "/opt/nidp/dev-repo/nivesh.ai/backend")

BATCH = int(os.environ.get("EMBED_BATCH", "500"))    # commit granularity: a failed
                                                     # batch re-queues only this many
SHARDS = int(os.environ.get("EMBED_SHARDS", "1"))    # parallel-worker fan-out
SHARD = int(os.environ.get("EMBED_SHARD", "0"))      # this worker's slice 0..SHARDS-1
IDLE_EXIT = int(os.environ.get("EMBED_IDLE_EXIT", "3"))     # empty passes -> truly done
REFUSE_STOP = int(os.environ.get("EMBED_REFUSE_STOP", "5")) # refusal passes -> hard stop


async def main() -> int:
    from nidp.services.document_parser.db import embed_pending
    from nidp.shared.storage import pg

    total = 0
    idle = 0        # consecutive passes with candidates==0 (real drain-complete)
    refused = 0     # consecutive passes with candidates>0 but embedded==0 (API refusing)
    t0 = time.time()
    rc = 0
    try:
        while True:
            try:
                r = await embed_pending(BATCH, shards=SHARDS, shard=SHARD)
            except Exception as e:                       # noqa: BLE001
                # A transport hiccup, not a definitive refusal — log and retry.
                print(f"  batch error: {type(e).__name__}: {e}", flush=True)
                await asyncio.sleep(5)
                continue

            n = r.get("embedded", 0)
            candidates = r.get("candidates", 0)
            total += n

            if n > 0:
                idle = refused = 0
                el = time.time() - t0
                print(f"  [s{SHARD}/{SHARDS}] embedded {total:,} in {el/60:.1f}m "
                      f"({total/max(el,1)*3600:,.0f}/hr)", flush=True)
                continue

            # embedded == 0 — which of the two very different cases is it?
            if candidates == 0:
                idle += 1
                if idle >= IDLE_EXIT:
                    break                                # queue genuinely empty
                await asyncio.sleep(2)
            else:
                refused += 1
                print(f"  !! {candidates} candidates, 0 embedded "
                      f"(refusal {refused}/{REFUSE_STOP}) — API refusing, likely "
                      f"insufficient_quota", flush=True)
                if refused >= REFUSE_STOP:
                    print("\n🔴 STOP: the embedding API refused every candidate "
                          f"{REFUSE_STOP}x in a row. NOT done — "
                          f"{total:,} embedded this run, backlog remains. "
                          "Check OpenAI quota/billing, then re-run.", flush=True)
                    rc = 1
                    break
                await asyncio.sleep(20)
    finally:
        await pg.close_pool()

    if rc == 0:
        print(f"\ndone: {total:,} chunks embedded in "
              f"{(time.time()-t0)/60:.1f} min (queue empty)", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
