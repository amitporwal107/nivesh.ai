"""Closing Bell — speak every beat in every language with edge-tts (one male anchor per language).
Runs in the tools image, work dir at /w. Writes /w/tts/<lang>/<sid>_<i>.mp3 and /w/tts/fit.json.

All languages share one picture and one timeline, so each beat gets one slot. Pass 1 speaks everything at the
language's base rate. The slot is the English length, widened only when another language would need to speak
more than 20% faster to fit. Pass 2 re-speaks any language longer than the slot at the rate that fits (at most
+20% over its base).
usage: python synth.py            env: CB_LANGS (default en,hi,ta,mr,gu)
"""
import asyncio
import json
import math
import os

import edge_tts

from i18n import BASE_RATE, LANGS, VOICES

ONLY = [l for l in os.environ.get("CB_LANGS", ",".join(LANGS)).split(",") if l in LANGS]
SEGS = json.load(open("/w/script.json"))["segments"]
MAX_SPEEDUP = 1.20


def dur(path):        # edge-tts default output is CBR 48 kbit/s mono mp3
    return os.path.getsize(path) * 8 / 48000


async def say(sem, path, text, voice, rate):
    async with sem:
        for attempt in range(5):
            try:
                await edge_tts.Communicate(text, voice, rate=f"+{rate}%").save(path)
                if os.path.getsize(path) > 2000:
                    return
            except Exception as e:  # noqa: BLE001 — retried, then raised
                if attempt == 4:
                    raise RuntimeError(f"tts failed for {path}: {type(e).__name__}") from e
            await asyncio.sleep(3 * (attempt + 1))
        raise RuntimeError(f"tts produced an empty file: {path}")


async def main():
    sem = asyncio.Semaphore(6)
    beats = [(s["id"], i, b) for s in SEGS for i, b in enumerate(s["beats"])]
    for lang in ONLY:
        os.makedirs(f"/w/tts/{lang}", exist_ok=True)
    await asyncio.gather(*[say(sem, f"/w/tts/{l}/{sid}_{i}.mp3", (b.get("texts") or {}).get(l) or b["text"], VOICES[l], BASE_RATE[l])
                           for l in ONLY for sid, i, b in beats])
    fit, redo = {}, []
    for sid, i, b in beats:
        d = {l: dur(f"/w/tts/{l}/{sid}_{i}.mp3") for l in ONLY}
        slot = max([d.get("en", 0)] + [d[l] / MAX_SPEEDUP for l in ONLY if l != "en"])
        rates = {}
        for l in ONLY:
            rate = BASE_RATE[l]
            if d[l] > slot * 1.01:
                rate = min(BASE_RATE[l] + 20, math.ceil((100 + BASE_RATE[l]) * d[l] / slot - 100) + 1)
                redo.append((l, sid, i, b, rate))
            elif l == "en" and d[l] < slot * 0.92:
                # English is usually the shortest: speak it a little slower (never below normal speed) to fill the slot
                rate = max(0, math.floor((100 + BASE_RATE[l]) * d[l] / (slot * 0.97) - 100))
                if rate < BASE_RATE[l]:
                    redo.append((l, sid, i, b, rate))
            rates[l] = rate
        fit[f"{sid}_{i}"] = {"slot": round(slot, 2), "base": {l: round(d[l], 2) for l in ONLY}, "rate": rates}
    await asyncio.gather(*[say(sem, f"/w/tts/{l}/{sid}_{i}.mp3", (b.get("texts") or {}).get(l) or b["text"], VOICES[l], rate)
                           for l, sid, i, b, rate in redo])
    for sid, i, _ in beats:
        fit[f"{sid}_{i}"]["final"] = {l: round(dur(f"/w/tts/{l}/{sid}_{i}.mp3"), 2) for l in ONLY}
    json.dump({"langs": ONLY, "beats": fit}, open("/w/tts/fit.json", "w"), indent=1)
    tot = {l: round(sum(v["final"][l] for v in fit.values()), 1) for l in ONLY}
    print("synthesised", len(beats), "beats x", len(ONLY), "languages; spoken seconds", tot, "; re-spoken", len(redo), flush=True)

asyncio.run(main())
