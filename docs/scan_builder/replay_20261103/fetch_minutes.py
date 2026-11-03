"""Today's 1-minute Kite candles for every stock in the scan dashboard universe (read-only; replay of 3 Nov 2026).

Runs inside nivesh-staging-app-backend. Resumable: one JSON line per symbol in OUT; symbols already there are skipped.
Pacing: the scan builder's shared Redis gate (nivesh:sb:intraday:next_call_at, <= 1.5 Kite historical calls/s across the
app's workers AND this job), so the app's own intraday reads are never crowded out. Never prints a token.
"""
import asyncio, json, sys, time
from pathlib import Path

sys.path.insert(0, "/app")
OUT = Path(sys.argv[1])
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 0
WORKERS = 2
DAY = "2026-11-03"


async def main():
    from services.scan_builder import data as D
    from services.scan_builder import intraday as SI
    from services.kite_live_feed.intraday import IntradayService
    await SI._refresh_platform_token()
    panel = D.load_panel_file(D.CACHE_DIR)
    syms = list(panel.symbols)
    done = set()
    if OUT.exists():
        for ln in OUT.read_text().splitlines():
            try:
                done.add(json.loads(ln)["s"])
            except Exception:
                pass
    todo = [s for s in syms if s not in done]
    if LIMIT:
        todo = todo[:LIMIT]
    print(f"universe {len(syms)}, already {len(done)}, to fetch {len(todo)}", flush=True)
    store = SI.RedisStore()
    svc = IntradayService()
    t0 = time.monotonic(); n_ok = n_empty = n_err = 0
    q = asyncio.Queue()
    for s in todo:
        q.put_nowait(s)
    stats = {"ok": 0, "empty": 0, "err": 0, "n": 0, "stop": False}
    fh = OUT.open("a")

    async def worker():
        while not q.empty() and not stats["stop"]:
            s = q.get_nowait()
            t = await store.reserve(SI.PREFIX + "next_call_at", time.time(), SI.SPACING_S, 60)
            if t is not None and t > time.time():
                await asyncio.sleep(t - time.time())
            elif t is None:
                await asyncio.sleep(SI.LOCAL_SPACING_S)
            try:
                r = await svc.bars(s, "1m", 1, session_open=False)
            except Exception as e:  # noqa: BLE001 — recorded per symbol, the run continues
                stats["err"] += 1
                fh.write(json.dumps({"s": s, "err": type(e).__name__ + ":" + str(e)[:80]}) + "\n")
                continue
            if r.get("availability") in ("token_missing", "token_expired"):
                print("STOP: Kite token", r.get("availability"), flush=True)
                stats["stop"] = True
                return
            bars = [b for b in r.get("bars") or [] if str(b[0]).startswith(DAY)]
            stats["ok" if bars else "empty"] += 1
            fh.write(json.dumps({"s": s, "a": r.get("availability"), "d": r.get("session_dates"), "b": bars}) + "\n")
            fh.flush()
            stats["n"] += 1
            if stats["n"] % 100 == 0:
                print(f"{stats['n']}/{len(todo)} ok {stats['ok']} empty {stats['empty']} err {stats['err']} "
                      f"{time.monotonic() - t0:.0f}s", flush=True)

    await asyncio.gather(*(worker() for _ in range(WORKERS)))
    fh.close()
    n_ok, n_empty, n_err = stats["ok"], stats["empty"], stats["err"]
    print(f"DONE ok {n_ok} empty {n_empty} err {n_err} in {time.monotonic()-t0:.0f}s", flush=True)

asyncio.run(main())
