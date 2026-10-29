"""Closing Bell — put a checked edition on the site and update the edition list the page reads.

usage: python3 publish.py WORK_DIR DEST_DIR [--retain N]
DEST_DIR is served at /downloads/closing-bell/ by the edge nginx. Writes:
  DEST/<date>/closing-bell-<date>.mp4, poster.jpg, captions.vtt, transcript.json, edition.json
  DEST/index.json   {"latest": date, "editions": [edition.json ..., newest first]}   (atomic replace)
Every language the night was built in is published: closing-bell-<date>-<lang>.mp4, captions_<lang>.vtt,
transcript_<lang>.json (English keeps the original names). edition.json lists them under "languages".
Editions older than the newest N (default 45) are removed from the list and from disk; non-English videos are
kept for the newest LANG_RETAIN (default 15) editions only, to protect disk space (about 20 MB per language).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from i18n import LABELS, VOICES  # noqa: E402

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


def copy_in(src: str, dst: str) -> None:
    tmp = os.path.join(os.path.dirname(dst), ".tmp-" + os.path.basename(dst))
    shutil.copyfile(src, tmp)
    os.chmod(tmp, 0o644)
    os.replace(tmp, dst)


def main(work: str, dest: str, retain: int, lang_retain: int = 15) -> dict:
    cards = json.load(open(f"{work}/cards.json"))
    script = json.load(open(f"{work}/script.json"))
    media = json.load(open(f"{work}/out/media.json"))
    d = cards["date"]
    ed_dir = os.path.join(dest, d)
    os.makedirs(ed_dir, exist_ok=True)
    files = {"video": f"closing-bell-{d}.mp4", "poster": "poster.jpg", "captions": "captions.vtt", "transcript": "transcript.json"}
    for key, src in (("video", "web.mp4"), ("poster", "poster.jpg"), ("captions", "captions.vtt"), ("transcript", "transcript.json")):
        copy_in(os.path.join(work, "out", src), os.path.join(ed_dir, files[key]))
    languages = [{"code": "en", "label": LABELS["en"], "video": f"{d}/{files['video']}", "captions": f"{d}/{files['captions']}",
                  "transcript": f"{d}/{files['transcript']}"}]
    for code in [c for c in LABELS if c != "en"]:
        srcs = {"video": f"web_{code}.mp4", "captions": f"captions_{code}.vtt", "transcript": f"transcript_{code}.json"}
        if not all(os.path.exists(os.path.join(work, "out", s)) for s in srcs.values()):
            continue
        names = {"video": f"closing-bell-{d}-{code}.mp4", "captions": f"captions_{code}.vtt", "transcript": f"transcript_{code}.json"}
        for k in srcs:
            copy_in(os.path.join(work, "out", srcs[k]), os.path.join(ed_dir, names[k]))
        languages.append({"code": code, "label": LABELS[code], **{k: f"{d}/{v}" for k, v in names.items()}})
    secs = round(media["duration"])
    edition = {
        "date": d, "day_long": cards["L"]["day_long"], "title": f"Closing Bell — {cards['L']['day_long']}",
        "duration_s": secs, "duration_label": f"{secs // 60}:{secs % 60:02d}",
        "headlines": [{"kicker": h["kicker"], "big": plain(h["big"]), "small": h["small"]} for h in script.get("headlines") or []],
        "segments": [{"tag": s["tag"], "title": s["title"]} for s in script["segments"]],
        "files": {k: f"{d}/{v}" for k, v in files.items()},
        "languages": languages,
        "published_at": datetime.now(IST).isoformat(timespec="seconds"),
        "voices": {x["code"]: VOICES[x["code"]] for x in languages},
        "music": "“The Complex” by Kevin MacLeod (incompetech.com), CC BY 3.0",
        "disclaimer": "Market information and education, not investment advice. Ideas are for review, not recommendations.",
    }
    atomic_json(os.path.join(ed_dir, "edition.json"), edition)
    idx_path = os.path.join(dest, "index.json")
    idx = json.load(open(idx_path)) if os.path.exists(idx_path) else {"editions": []}
    eds = [e for e in idx.get("editions") or [] if e.get("date") != d] + [edition]
    eds.sort(key=lambda e: e["date"], reverse=True)
    keep, drop = eds[:retain], eds[retain:]
    for e in keep[lang_retain:]:          # older editions: English only (disk), the other languages' files go
        for lg in [x for x in e.get("languages") or [] if x["code"] != "en"]:
            for k in ("video", "captions", "transcript"):
                fp = os.path.join(dest, lg[k])
                if os.path.exists(fp):
                    os.remove(fp)
        e["languages"] = [x for x in e.get("languages") or [] if x["code"] == "en"]
    for e in drop:
        old = os.path.join(dest, e["date"])
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["date"]) and os.path.isdir(old):
            shutil.rmtree(old)
    atomic_json(idx_path, {"schema": "closing-bell-index-v1", "latest": keep[0]["date"], "updated_at": edition["published_at"], "editions": keep})
    return {"published": d, "languages": [x["code"] for x in languages], "editions": len(keep), "removed": [e["date"] for e in drop]}


if __name__ == "__main__":
    args = sys.argv[1:]
    retain = 45
    lang_retain = 15
    if "--lang-retain" in args:
        i = args.index("--lang-retain")
        lang_retain = int(args[i + 1])
        del args[i:i + 2]
    if "--retain" in args:
        i = args.index("--retain")
        retain = int(args[i + 1])
        del args[i:i + 2]
    print(json.dumps(main(args[0], args[1], retain, lang_retain)))
