"""Closing Bell — put a checked edition on the site and update the edition list the page reads.

usage: python3 publish.py WORK_DIR DEST_DIR [--retain N]
DEST_DIR is served at /downloads/closing-bell/ by the edge nginx. Writes:
  DEST/<date>/closing-bell-<date>.mp4, poster.jpg, captions.vtt, transcript.json, edition.json
  DEST/index.json   {"latest": date, "editions": [edition.json ..., newest first]}   (atomic replace)
Editions older than the newest N (default 45, about 1 GB) are removed from the list and from disk.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def atomic_json(path: str, obj) -> None:
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def plain(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "")


def main(work: str, dest: str, retain: int) -> dict:
    cards = json.load(open(f"{work}/cards.json"))
    script = json.load(open(f"{work}/script.json"))
    media = json.load(open(f"{work}/out/media.json"))
    d = cards["date"]
    ed_dir = os.path.join(dest, d)
    os.makedirs(ed_dir, exist_ok=True)
    files = {"video": f"closing-bell-{d}.mp4", "poster": "poster.jpg", "captions": "captions.vtt", "transcript": "transcript.json"}
    for key, src in (("video", "web.mp4"), ("poster", "poster.jpg"), ("captions", "captions.vtt"), ("transcript", "transcript.json")):
        tmp = os.path.join(ed_dir, ".tmp-" + files[key])
        shutil.copyfile(os.path.join(work, "out", src), tmp)
        os.chmod(tmp, 0o644)
        os.replace(tmp, os.path.join(ed_dir, files[key]))
    secs = round(media["duration"])
    edition = {
        "date": d, "day_long": cards["L"]["day_long"], "title": f"Closing Bell — {cards['L']['day_long']}",
        "duration_s": secs, "duration_label": f"{secs // 60}:{secs % 60:02d}",
        "headlines": [{"kicker": h["kicker"], "big": plain(h["big"]), "small": h["small"]} for h in script.get("headlines") or []],
        "segments": [{"tag": s["tag"], "title": s["title"]} for s in script["segments"]],
        "files": {k: f"{d}/{v}" for k, v in files.items()},
        "published_at": datetime.now(IST).isoformat(timespec="seconds"),
        "voice": "en-US-AndrewMultilingualNeural (edge-tts)",
        "music": "“The Complex” by Kevin MacLeod (incompetech.com), CC BY 3.0",
        "disclaimer": "Market information and education, not investment advice. Ideas are for review, not recommendations.",
    }
    atomic_json(os.path.join(ed_dir, "edition.json"), edition)
    idx_path = os.path.join(dest, "index.json")
    idx = json.load(open(idx_path)) if os.path.exists(idx_path) else {"editions": []}
    eds = [e for e in idx.get("editions") or [] if e.get("date") != d] + [edition]
    eds.sort(key=lambda e: e["date"], reverse=True)
    keep, drop = eds[:retain], eds[retain:]
    for e in drop:
        old = os.path.join(dest, e["date"])
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["date"]) and os.path.isdir(old):
            shutil.rmtree(old)
    atomic_json(idx_path, {"schema": "closing-bell-index-v1", "latest": keep[0]["date"], "updated_at": edition["published_at"], "editions": keep})
    return {"published": d, "editions": len(keep), "removed": [e["date"] for e in drop]}


if __name__ == "__main__":
    args = sys.argv[1:]
    retain = 45
    if "--retain" in args:
        i = args.index("--retain")
        retain = int(args[i + 1])
        del args[i:i + 2]
    print(json.dumps(main(args[0], args[1], retain)))
