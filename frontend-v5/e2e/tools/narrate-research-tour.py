#!/usr/bin/env python3
"""
narrate-research-tour.py — add an Indian voiceover to the Research tab tour.

Reads the timed transcript from the caption files (the single source of truth):
  public/research-tab-tour.en.vtt   -> English  voiceover  -> research-tab-tour.mp4
  public/research-tab-tour.hi.vtt   -> हिंदी    voiceover  -> research-tab-tour-hi.mp4

For each cue it synthesises an Indian neural voice (edge-tts), lays each clip at its
cue start time (so the narration tracks the on-screen action), then muxes the track
onto the silent master (research-tab-tour.webm), freezing the final frame so the
closing line lands. This matches the Copilot tour's EN/`-hi` convention.

Deps (already used to produce the committed assets):  pip install edge-tts pydub
Run:  python3 e2e/tools/narrate-research-tour.py            # from frontend-v5/
"""
import asyncio
import os
import re
import subprocess
import sys

import edge_tts
from pydub import AudioSegment

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.normpath(os.path.join(HERE, "..", "..", "public"))
SILENT_MASTER = os.path.join(PUBLIC, "research-tab-tour.webm")
WORK = os.path.join(HERE, "_narrate_tmp")

# Indian neural voices; a small rate bump keeps each line inside its scene window.
CUTS = {
    "en": {"vtt": "research-tab-tour.en.vtt", "out": "research-tab-tour.mp4",    "voice": "en-IN-NeerjaNeural", "rate": "+6%"},
    "hi": {"vtt": "research-tab-tour.hi.vtt", "out": "research-tab-tour-hi.mp4", "voice": "hi-IN-SwaraNeural",  "rate": "+6%"},
}
FREEZE_TAIL_S = 3  # extend the video by holding the last frame so the closing VO lands


def parse_vtt(path):
    """Return [(start_ms, text), ...] from a WEBVTT file."""
    cues, ts, text = [], None, []
    ts_re = re.compile(r"(\d\d):(\d\d)[:.](\d\d)")  # mm:ss.mmm (hours not used here)
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if "-->" in line:
            if ts is not None and text:
                cues.append((ts, " ".join(text).strip())); text = []
            m = ts_re.search(line.split("-->")[0])
            ts = (int(m.group(1)) * 60 + int(m.group(2))) * 1000
        elif line.strip() in ("", "WEBVTT"):
            if ts is not None and text:
                cues.append((ts, " ".join(text).strip())); ts, text = None, []
        else:
            text.append(line.strip())
    if ts is not None and text:
        cues.append((ts, " ".join(text).strip()))
    return cues


async def synth_cue(text, voice, rate, out):
    await edge_tts.Communicate(text, voice, rate=rate).save(out)


def build_track(lang, cfg):
    cues = parse_vtt(os.path.join(PUBLIC, cfg["vtt"]))
    track = AudioSegment.silent(0)
    for i, (start_ms, text) in enumerate(cues):
        clip_path = os.path.join(WORK, f"{lang}_{i:02d}.mp3")
        asyncio.run(synth_cue(text, cfg["voice"], cfg["rate"], clip_path))
        if len(track) < start_ms:
            track += AudioSegment.silent(start_ms - len(track))
        track += AudioSegment.from_file(clip_path)
    voice_path = os.path.join(WORK, f"voice_{lang}.m4a")
    track.export(voice_path, format="ipod", bitrate="128k")
    return voice_path, len(track)


def mux(voice_path, out_name):
    out = os.path.join(PUBLIC, out_name)
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", SILENT_MASTER, "-i", voice_path,
        "-filter_complex", f"[0:v]tpad=stop_mode=clone:stop_duration={FREEZE_TAIL_S},format=yuv420p[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-profile:v", "high", "-crf", "27", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-shortest", out,
    ], check=True)
    return out


def main():
    if not os.path.exists(SILENT_MASTER):
        sys.exit(f"silent master not found: {SILENT_MASTER}")
    os.makedirs(WORK, exist_ok=True)
    for lang, cfg in CUTS.items():
        voice_path, dur = build_track(lang, cfg)
        out = mux(voice_path, cfg["out"])
        print(f"{lang}: {dur/1000:.1f}s voiceover -> {out}")


if __name__ == "__main__":
    main()
