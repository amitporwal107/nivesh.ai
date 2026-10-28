"""Closing Bell — the gate between a built bulletin and the public page.

Three groups of checks; any failure holds the edition back (nothing is published, the owner is alerted):

  data    the bundle covers the day: index closes, all four heatmaps, sector returns, the Top 10 list
  script  every number in the narration and the captions was taken from cards.json (script_gen's trace),
          and each traced number still equals the value at its path
  media   the final mp4 is the expected length, has an audio track, sane loudness, and the recorder
          reached every desk screen (no login page, no action errors)

usage:
  python3 checks.py script CARDS.json SCRIPT.json            -> JSON report, exit 0 pass / 1 fail
  python3 checks.py media  REPORT_media.json TIMELINE.json RAW_DIR   (REPORT_media from pipeline's ffprobe)
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List

from script_gen import Facts, fmt_in

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Numbers that are part of names, not data: index names, "Top 10", "20-day", "F&O", "Q2" etc.
CONTEXT_OK = [
    r"Nifty (?:500|200|100|50|Next 50|Midcap 150|Smallcap 250|Microcap 250)\b",
    r"\b(?:Next 50|Midcap 150|Smallcap 250|Microcap 250)\b",
    r"Top 10\b", r"\b20-day\b", r"\bthe 500\b",
]
BLOCKING_GAPS = ("index closes missing", "heatmap", "sector index returns", "Top 10 list")


def check_data(cards: Dict[str, Any]) -> List[str]:
    fails = [g for g in cards.get("gaps") or [] if g.startswith(BLOCKING_GAPS)]
    if len(cards.get("idx") or []) < 8:
        fails.append(f"only {len(cards.get('idx') or [])} index closes")
    n500 = (cards.get("movers") or {}).get("Nifty 500") or {}
    if (n500.get("n") or 0) < 450:
        fails.append(f"Nifty 500 heatmap has {n500.get('n')} priced stocks (< 450)")
    if len(cards.get("ideas") or []) < 5:
        fails.append("fewer than 5 Top 10 ideas")
    return fails


def _reformat(F: Facts, t: Dict[str, Any]) -> str:
    v = F.get(t["path"])
    if v is None:
        return "<missing>"
    if t["fmt"] == "text":
        return t["s"] if t["s"] in str(v) else "<not in text>"
    if t["fmt"] == "day":
        return str(int(str(v)[8:10]))
    x = abs(float(v)) if t.get("abs", True) else float(v)
    return {"int": lambda: str(int(round(x))), "0": lambda: f"{x:.0f}", "1": lambda: f"{x:.1f}", "2": lambda: f"{x:.2f}",
            "in0": lambda: fmt_in(x, 0), "in2": lambda: fmt_in(x, 2)}[t["fmt"]]()


def check_script(cards: Dict[str, Any], script: Dict[str, Any]) -> Dict[str, Any]:
    F = Facts(cards)
    fails: List[str] = []
    # 1. every traced number still matches its source value
    for t in script.get("trace") or []:
        again = _reformat(F, t)
        if again != t["s"]:
            fails.append(f"trace mismatch {t['path']}: script says {t['s']}, cards give {again}")
    traced = {t["s"] for t in script.get("trace") or []}
    # also allow the same number spoken without grouping commas (22,749.75 vs 22749.75 inside labels)
    traced |= {s.replace(",", "") for s in traced}
    # 2. no number in any text that did not come through the trace (or a name / the edition's own date)
    L = cards.get("L") or {}
    dates_ok = {str(int(L.get("date", "0000-00-00")[8:10] or 0)), L.get("date", "")[:4],
                str(int(L.get("next_date", "0000-00-00")[8:10] or 0)), L.get("next_date", "")[:4]}
    untraced: List[str] = []
    n_checked = 0
    for seg in script.get("segments") or []:
        for b in seg["beats"]:
            for field in ("text", "sup"):
                s = b.get(field) or ""
                masked = s
                for pat in CONTEXT_OK:
                    masked = re.sub(pat, lambda m: re.sub(r"\d", "#", m.group(0)), masked)
                for tok in NUM.findall(masked):
                    n_checked += 1
                    if tok in traced or tok.replace(",", "") in traced or tok in dates_ok:
                        continue
                    untraced.append(f"{seg['id']} {field}: '{tok}' in “{s[:90]}”")
    fails += [f"untraced number {u}" for u in untraced]
    # 3. required wording (SEBI): ideas framed as review, not recommendations; closing disclaimer present
    all_text = " ".join(b["text"] for s in script["segments"] for b in s["beats"])
    if "not recommendations" not in all_text:
        fails.append("ideas disclaimer missing")
    if "not investment advice" not in all_text:
        fails.append("closing disclaimer missing")
    if re.search(r"\b(buy|sell) (?:now|this)\b|\btarget price\b|\bpicks?\b", all_text, re.I):
        fails.append("advice-like wording (buy now / target price / picks) in narration")
    return {"ok": not fails, "numbers_checked": n_checked, "traced": len(script.get("trace") or []), "fails": fails}


def check_media(media: Dict[str, Any], timeline: Dict[str, Any], raw_dir: str) -> List[str]:
    fails = []
    want = sum(s["len"] for s in timeline.values())
    dur = media.get("duration")
    if dur is None or abs(dur - want) > 1.5:
        fails.append(f"duration {dur} s, timeline says {want:.2f} s")
    if not media.get("has_audio"):
        fails.append("no audio stream")
    if media.get("width") != 1920 or media.get("height") != 1080:
        fails.append(f"frame {media.get('width')}x{media.get('height')}, expected 1920x1080")
    li = media.get("lufs")
    if li is None or not (-18.5 <= li <= -13.5):
        fails.append(f"loudness {li} LUFS outside -18.5..-13.5")
    for sid in sorted(timeline):
        if sid == "s0":
            continue
        p = os.path.join(raw_dir, sid, "index.json")
        if not os.path.exists(p):
            fails.append(f"no footage for {sid}"); continue
        rec = json.load(open(p))
        if rec.get("warm_error"):
            fails.append(f"{sid}: desk screen did not load ({rec['warm_error']})")
        errs = [m for _, m in rec.get("log") or [] if "ACTION ERROR" in m or "LOGIN" in m]
        if errs:
            fails.append(f"{sid}: {errs[0]}")
        if len(rec.get("frames") or []) < 0.5 * timeline[sid]["len"]:
            fails.append(f"{sid}: only {len(rec.get('frames') or [])} frames for {timeline[sid]['len']} s")
    return fails


if __name__ == "__main__":
    kind = sys.argv[1]
    if kind == "script":
        cards, script = json.load(open(sys.argv[2])), json.load(open(sys.argv[3]))
        r = check_script(cards, script)
        r["data_fails"] = check_data(cards)
        r["ok"] = r["ok"] and not r["data_fails"]
        print(json.dumps(r, indent=1, ensure_ascii=False))
        sys.exit(0 if r["ok"] else 1)
    if kind == "media":
        fails = check_media(json.load(open(sys.argv[2])), json.load(open(sys.argv[3])), sys.argv[4])
        print(json.dumps({"ok": not fails, "fails": fails}, indent=1))
        sys.exit(0 if not fails else 1)
    sys.exit("usage: checks.py script|media ...")
