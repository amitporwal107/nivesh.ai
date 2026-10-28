"""Closing Bell — speak every beat with edge-tts (single male anchor). Runs in the tools image, work dir at /w.
usage: python synth.py            env: CB_VOICE (default en-US-AndrewMultilingualNeural), CB_RATE (default +8%)"""
import asyncio
import json
import os

import edge_tts

VOICE = os.environ.get("CB_VOICE", "en-US-AndrewMultilingualNeural")
RATE = os.environ.get("CB_RATE", "+8%")
SEGS = json.load(open("/w/script.json"))["segments"]
os.makedirs("/w/tts", exist_ok=True)


async def main():
    sem = asyncio.Semaphore(4)

    async def one(path, text):
        async with sem:
            for attempt in range(5):
                try:
                    await edge_tts.Communicate(text, VOICE, rate=RATE).save(path)
                    if os.path.getsize(path) > 2000:
                        return
                except Exception as e:  # noqa: BLE001 — retried, then raised
                    if attempt == 4:
                        raise RuntimeError(f"tts failed for {path}: {type(e).__name__}") from e
                await asyncio.sleep(3 * (attempt + 1))
            raise RuntimeError(f"tts produced an empty file: {path}")

    jobs = [one(f"/w/tts/{s['id']}_{i}.mp3", b["text"]) for s in SEGS for i, b in enumerate(s["beats"])]
    await asyncio.gather(*jobs)
    print("synthesised", len(jobs), "beats with", VOICE, RATE, flush=True)

asyncio.run(main())
