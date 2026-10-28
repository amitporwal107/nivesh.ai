"""Closing Bell — host-side media steps (ffmpeg runs in a container; this file is standard library only).

usage: python3 build.py WORK_DIR ASSETS_DIR <step> [args]
  sfx                 make sting.wav / whoosh.wav in ASSETS if missing (synthesised, no licence needed)
  timeline            measure the narration clips -> timeline.json
  bed                 music bed for this edition's length (track played twice, joined at the s4 stinger)
  footage s1 s2 ...   screencast frames -> constant-rate clips foot/<sid>.mp4
  seg s0 s1 ...       assemble segments seg/<sid>.mp4 (footage + cards + captions + ticker + voice + bed)
  final               concat + loudness -> out/master.mp4, out/web.mp4 (22 MB class), poster, media probe
  transcript          out/captions.vtt, out/transcript.json, out/transcript.md
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys

FF_IMAGE = "jrottenberg/ffmpeg:6.1-ubuntu"
BOX = {"idx", "brd", "res", "after", "sec", "n50", "n100", "n200", "n500", "s500", "fii", "ideas", "fno", "watch"}
NF = 36 / 25.0
GAP, TAIL = 0.30, 0.7
TRACK_SECONDS = 267.75   # "The Complex", Kevin MacLeod (CC BY 3.0)


def run(cmd, label, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 and check:
        sys.exit(f"FAIL {label}:\n{r.stderr[-3000:]}")
    return r


def ff(work, assets, args, label):
    cmd = ["docker", "run", "--rm", "-v", f"{work}:/w", "-v", f"{assets}:/assets", "--entrypoint", "ffmpeg", FF_IMAGE,
           "-hide_banner", "-loglevel", "error", "-y"] + args
    run(cmd, label)
    print("ok", label, flush=True)


def probe(work, assets, inner):
    cmd = ["docker", "run", "--rm", "-v", f"{work}:/w", "-v", f"{assets}:/assets", "--entrypoint", "bash", FF_IMAGE, "-c", inner]
    return run(cmd, "probe").stdout


def load(work, name):
    return json.load(open(os.path.join(work, name)))


# ------------------------------------------------------------------ sound effects (once, into ASSETS)
def sfx(work, assets):
    if not os.path.exists(f"{assets}/sting.wav"):
        ff(work, assets, ["-f", "lavfi", "-i", "aevalsrc=exprs='(2*random(1)-1)*0.35*if(lt(t,0.6),pow(t/0.6,2),0)+if(gte(t,0.6),exp(-2.0*(t-0.6))*(0.45*sin(2*PI*110*t)+0.35*sin(2*PI*220*t)+0.3*sin(2*PI*261.63*t)+0.3*sin(2*PI*329.63*t)+0.2*sin(2*PI*440*t))+0.8*sin(2*PI*52*t)*exp(-7*(t-0.6)),0)':s=48000:d=3.4",
                          "-af", "lowpass=f=7000,aformat=channel_layouts=stereo,afade=t=out:st=2.6:d=0.8,loudnorm=I=-18:TP=-3", "-ar", "48000", "/assets/sting.wav"], "sting")
    if not os.path.exists(f"{assets}/whoosh.wav"):
        ff(work, assets, ["-f", "lavfi", "-i", "aevalsrc=exprs='(2*random(2)-1)*pow(sin(PI*t/0.75),2)':s=48000:d=0.75",
                          "-af", "highpass=f=400,lowpass=f=4500,aformat=channel_layouts=stereo,loudnorm=I=-24:TP=-8", "-ar", "48000", "/assets/whoosh.wav"], "whoosh")


# ------------------------------------------------------------------ timeline from the narration clips
def timeline(work, assets):
    segs = load(work, "script.json")["segments"]
    out = probe(work, assets, "for f in /w/tts/s*_*.mp3; do echo \"$(basename $f .mp3) $(ffprobe -v error -show_entries format=duration -of csv=p=0 $f)\"; done")
    D = {l.split()[0]: float(l.split()[1]) for l in out.splitlines() if l.strip()}
    tl, total = {}, 0.0
    for s in segs:
        t = 3.6 if s["id"] == "s0" else 1.5
        beats = []
        for i, b in enumerate(s["beats"]):
            d = D[f"{s['id']}_{i}"]
            beats.append({"i": i, "start": round(t, 2), "dur": round(d, 2), "who": b["who"]})
            t += d + GAP
        end = beats[-1]["start"] + beats[-1]["dur"]
        ln = math.ceil((end + TAIL) * 4) / 4
        tl[s["id"]] = {"len": ln, "start": round(total, 2), "beats": beats}
        total += ln
    json.dump(tl, open(f"{work}/timeline.json", "w"), indent=1)
    print(f"timeline {total:.1f}s = {int(total // 60)}:{total % 60:04.1f}", flush=True)


# ------------------------------------------------------------------ music bed
def bed(work, assets):
    tl = load(work, "timeline.json")
    total = sum(s["len"] for s in tl.values()) + 5
    os.makedirs(f"{work}/sfx", exist_ok=True)
    if total <= TRACK_SECONDS - 5:
        flt = "[0:a]atrim=0:%.2f,asetpts=PTS-STARTPTS" % total
        ins = ["-i", "/assets/the_complex.mp3"]
    else:
        join = (tl.get("s4") or tl[sorted(tl)[len(tl) // 2]])["start"]
        join = min(join, TRACK_SECONDS - 6)
        flt = (f"[0:a]atrim=0:{join + 2:.2f},asetpts=PTS-STARTPTS[a];[1:a]asetpts=PTS-STARTPTS[b];"
               f"[a][b]acrossfade=d=2:c1=tri:c2=tri")
        ins = ["-i", "/assets/the_complex.mp3", "-i", "/assets/the_complex.mp3"]
    ff(work, assets, ins + ["-filter_complex", flt + ",aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,volume=-8.3dB[o]",
                            "-map", "[o]", "-c:a", "pcm_s16le", "/w/sfx/bed.wav"], "bed")


# ------------------------------------------------------------------ footage
def footage(work, assets, sids):
    tl = load(work, "timeline.json")
    os.makedirs(f"{work}/lists", exist_ok=True)
    os.makedirs(f"{work}/foot", exist_ok=True)
    for sid in sids:
        ix = load(work, f"raw/{sid}/index.json")
        fr = [f for f in ix["frames"] if f["t"] <= tl[sid]["len"]]
        if not fr:
            sys.exit(f"FAIL footage {sid}: no frames")
        L = tl[sid]["len"] + 0.2
        lines = []
        for i, f in enumerate(fr):
            start = 0.0 if i == 0 else max(0.0, f["t"])
            end = fr[i + 1]["t"] if i + 1 < len(fr) else L
            lines.append(f"file '/w/raw/{sid}/{f['f']}'\nduration {max(0.001, end - start):.4f}\n")
        lines.append(f"file '/w/raw/{sid}/{fr[-1]['f']}'\n")
        open(f"{work}/lists/{sid}.txt", "w").write("".join(lines))
        ff(work, assets, ["-f", "concat", "-safe", "0", "-i", f"/w/lists/{sid}.txt", "-vf", "fps=25,scale=1440:810,format=yuv420p",
                          "-t", f"{tl[sid]['len']}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", f"/w/foot/{sid}.mp4"], f"footage {sid}")


# ------------------------------------------------------------------ segment assembly
def card_spans(seg, tl):
    B = [b["start"] for b in tl["beats"]]
    beats, L = seg["beats"], tl["len"]
    spans, i = [], 0
    while i < len(beats):
        c = beats[i]["card"]
        j = i
        while j + 1 < len(beats) and beats[j + 1]["card"] == c:
            j += 1
        if c:
            a = 0.0 if (seg["id"] == "s0" and i == 0) else max(0.0, B[i] - 0.2)
            b = (B[j + 1] - 0.25) if j + 1 < len(beats) else L
            spans.append((c, round(a, 2), round(b, 2)))
        i = j + 1
    return spans


def montage_sources(tl):
    """Cold-open footage under the title and headline cards: borrowed from the segments each headline is about."""
    pref = {"title": ("s3", 3.0), "h1": ("s1", 2.0), "h2": ("s5", 4.0), "h3": ("s2", 8.0), "h4": ("s3", 12.0)}
    return {k: (src if src in tl else "s1", min(off, max(0.0, tl.get(src, tl["s1"])["len"] - 8))) for k, (src, off) in pref.items()}


def seg(work, assets, sids):
    script = load(work, "script.json")
    segs = {s["id"]: s for s in script["segments"]}
    order = [s["id"] for s in script["segments"]]
    tl_all = load(work, "timeline.json")
    LT = load(work, "gfx/ticker.json")["L"]
    os.makedirs(f"{work}/seg", exist_ok=True)
    for sid in sids:
        s, tl = segs[sid], tl_all[sid]
        L, B, OFF = tl["len"], [b["start"] for b in tl["beats"]], tl["start"]
        inp, f = [], []

        def add(*a):
            inp.extend(a)
            return sum(1 for x in inp if x == "-i") - 1

        i_bg = add("-loop", "1", "-framerate", "25", "-t", f"{L}", "-i", "/w/gfx/bg.png")
        if sid != "s0":
            i_ft = add("-t", f"{L}", "-i", f"/w/foot/{sid}.mp4")
            f.append(f"[{i_ft}:v]fps=25,scale=1536:864:flags=lanczos,setsar=1[ft]")
        else:
            src = montage_sources(tl_all)
            parts = []
            for k, (c, a, b) in enumerate(card_spans(s, tl)):
                fs, off = src.get(c, ("s1", 2.0))
                ii = add("-ss", f"{off}", "-t", f"{b - a:.3f}", "-i", f"/w/foot/{fs}.mp4")
                f.append(f"[{ii}:v]fps=25,scale=1536:864:flags=lanczos,setsar=1,tpad=stop_mode=clone:stop_duration={b - a:.3f},"
                         f"trim=duration={b - a:.3f},setpts=PTS-STARTPTS[m{k}]")
                parts.append(f"[m{k}]")
            f.append("".join(parts) + f"concat=n={len(parts)}:v=1:a=0[ft]")
        f.append(f"[{i_bg}:v][ft]overlay=24:84:eof_action=pass[v0]")
        cur, n = "v0", 0

        def ov(src_, x, y, extra=""):
            nonlocal cur, n
            n += 1
            f.append(f"[{cur}][{src_}]overlay={x}:{y}{extra}[v{n}]")
            cur = f"v{n}"
        for k, (c, a, b) in enumerate(card_spans(s, tl)):
            if not os.path.exists(f"{work}/gfx/card_{c}/f000.png"):
                continue
            ii = add("-framerate", "25", "-i", f"/w/gfx/card_{c}/f%03d.png")
            d = b - a
            f.append(f"[{ii}:v]format=rgba,tpad=stop_mode=clone:stop_duration={max(0.05, d - NF + 0.1):.3f},trim=duration={d:.3f},"
                     f"fade=t=out:st={max(0, d - 0.25):.3f}:d=0.25:alpha=1,setpts=PTS-STARTPTS+{a}/TB[c{k}]")
            x, y = (1104, 96) if c in BOX else (24, 84)
            ov(f"c{k}", x, y, f":eof_action=pass:enable='between(t,{a},{b})'")
        if sid != "s0":
            ii = add("-framerate", "25", "-i", f"/w/gfx/stinger_{sid}/f%03d.png")
            f.append(f"[{ii}:v]format=rgba,tpad=stop_mode=clone:stop_duration=0.2,fade=t=out:st=1.1:d=0.35:alpha=1[st]")
            ov("st", 24, 84, ":eof_action=pass")
        i_tk = add("-loop", "1", "-framerate", "25", "-t", f"{L}", "-i", "/w/gfx/ticker.png")
        ov(f"{i_tk}:v", f"'-mod(({OFF}+t)*120,{LT:.2f})'", 1024)
        i_fr = add("-loop", "1", "-framerate", "25", "-t", f"{L}", "-i", f"/w/gfx/frame_{sid}.png")
        ov(f"{i_fr}:v", 0, 0)
        for j, b0 in enumerate(B):
            a = max(0.0, b0 - 0.15)
            b = (B[j + 1] - 0.15) if j + 1 < len(B) else L
            ii = add("-loop", "1", "-framerate", "25", "-t", f"{L}", "-i", f"/w/gfx/sup_{sid}_{j}.png")
            f.append(f"[{ii}:v]format=rgba,fade=t=in:st={a:.2f}:d=0.25:alpha=1,fade=t=out:st={max(a + 0.3, b - 0.2):.2f}:d=0.2:alpha=1[s{j}]")
            ov(f"s{j}", 0, 950)
        if sid == "s0":
            f.append(f"[{cur}]fade=t=in:st=0:d=0.5,format=yuv420p[vout]")
        elif sid == order[-1]:
            f.append(f"[{cur}]fade=t=out:st={L - 1.0:.2f}:d=1.0,format=yuv420p[vout]")
        else:
            f.append(f"[{cur}]format=yuv420p[vout]")
        vx = []
        for j, b0 in enumerate(B):
            ii = add("-i", f"/w/tts/{sid}_{j}.mp3")
            ms = int(b0 * 1000)
            f.append(f"[{ii}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms}[x{j}]")
            vx.append(f"[x{j}]")
        f.append("".join(vx) + f"amix=inputs={len(vx)}:normalize=0:duration=longest,apad=whole_dur={L}[vo]")
        f.append("[vo]asplit=2[vo1][vo2]")
        i_bed = add("-ss", f"{OFF}", "-t", f"{L}", "-i", "/w/sfx/bed.wav")
        f.append(f"[{i_bed}:a]aformat=channel_layouts=stereo,apad=whole_dur={L}[bed0]")
        f.append("[bed0][vo2]sidechaincompress=threshold=0.05:ratio=2.5:attack=60:release=500[bd]")
        i_fx = add("-i", "/assets/sting.wav" if sid == "s0" else "/assets/whoosh.wav")
        f.append(f"[{i_fx}:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={L}[fx]")
        f.append(f"[vo1][bd][fx]amix=inputs=3:normalize=0:duration=first,atrim=0:{L},alimiter=limit=0.95[aout]")
        ff(work, assets, inp + ["-filter_complex", ";".join(f), "-map", "[vout]", "-map", "[aout]", "-t", f"{L}", "-r", "25",
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p",
                                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", f"/w/seg/{sid}.mp4"], f"seg {sid} ({L}s)")


# ------------------------------------------------------------------ final encodes + probe
def final(work, assets):
    order = [s["id"] for s in load(work, "script.json")["segments"]]
    tl = load(work, "timeline.json")
    total = sum(tl[s]["len"] for s in order)
    os.makedirs(f"{work}/out", exist_ok=True)
    open(f"{work}/seg/list.txt", "w").write("".join(f"file '/w/seg/{s}.mp4'\n" for s in order))
    ff(work, assets, ["-f", "concat", "-safe", "0", "-i", "/w/seg/list.txt", "-c", "copy", "/w/seg/joined.mp4"], "concat")
    ff(work, assets, ["-i", "/w/seg/joined.mp4", "-c:v", "copy", "-af", f"afade=t=out:st={total - 3:.2f}:d=3,loudnorm=I=-16:TP=-1.5:LRA=11",
                      "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "/w/out/master.mp4"], "master")
    ff(work, assets, ["-i", "/w/out/master.mp4", "-c:v", "libx264", "-preset", "slow", "-crf", "31", "-pix_fmt", "yuv420p",
                      "-profile:v", "high", "-level", "4.1", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "/w/out/web.mp4"], "web encode")
    ff(work, assets, ["-ss", "2.6", "-i", "/w/out/master.mp4", "-frames:v", "1", "-vf", "scale=1280:720:flags=lanczos", "-q:v", "4", "/w/out/poster.jpg"], "poster")
    out = probe(work, assets, "ffprobe -v error -show_entries stream=codec_type,width,height:format=duration,size -of json /w/out/web.mp4; "
                              "echo '@@'; ffmpeg -hide_banner -nostats -i /w/out/web.mp4 -map 0:a -af ebur128 -f null - 2>&1 | grep -E '^\\s+I:' | tail -1")
    j, _, lufs = out.partition("@@")
    p = json.loads(j)
    v = next((x for x in p["streams"] if x["codec_type"] == "video"), {})
    m = re.search(r"(-?\d+\.\d+)\s*LUFS", lufs)
    media = {"duration": float(p["format"]["duration"]), "size": int(p["format"]["size"]), "width": v.get("width"), "height": v.get("height"),
             "has_audio": any(x["codec_type"] == "audio" for x in p["streams"]), "lufs": float(m.group(1)) if m else None, "timeline_total": total}
    json.dump(media, open(f"{work}/out/media.json", "w"), indent=1)
    print("media", json.dumps(media), flush=True)


# ------------------------------------------------------------------ captions + transcript
def transcript(work, assets):
    script, tl, cards = load(work, "script.json"), load(work, "timeline.json"), load(work, "cards.json")
    mm = lambda t: f"{int(t // 60)}:{int(t % 60):02d}"
    vt = lambda t: f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}"
    vtt, sections, md = ["WEBVTT", ""], [], [f"# Closing Bell on the Nivesh Desk — {cards['L']['day_long']}", ""]
    k = 0
    for s in script["segments"]:
        t = tl[s["id"]]
        cues = []
        md += [f"## {mm(t['start'])} — {s['tag']}: {s['title']}", ""]
        for b, bt in zip(s["beats"], t["beats"]):
            a = t["start"] + bt["start"]
            e = a + bt["dur"]
            k += 1
            vtt += [str(k), f"{vt(a)} --> {vt(e)}", b["text"], ""]
            cues.append({"t": mm(a), "text": b["text"], "sup": b["sup"]})
            md += [f"**[{mm(a)}]** {b['text']}  ", f"*On screen: {b['sup']}*", ""]
        sections.append({"tag": s["tag"], "title": s["title"], "start": mm(t["start"]), "cues": cues})
    md += ["---", "", "Market information and education, not investment advice. Ideas are for review, not recommendations.",
           "Music: “The Complex” by Kevin MacLeod (incompetech.com), licensed under Creative Commons Attribution 3.0."]
    open(f"{work}/out/captions.vtt", "w").write("\n".join(vtt))
    json.dump({"date": cards["date"], "sections": sections, "cue_count": k}, open(f"{work}/out/transcript.json", "w"), ensure_ascii=False, indent=1)
    open(f"{work}/out/transcript.md", "w").write("\n".join(md))
    print("transcript cues", k, flush=True)


if __name__ == "__main__":
    work, assets, step, rest = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    {"sfx": lambda: sfx(work, assets), "timeline": lambda: timeline(work, assets), "bed": lambda: bed(work, assets),
     "footage": lambda: footage(work, assets, rest), "seg": lambda: seg(work, assets, rest), "final": lambda: final(work, assets),
     "transcript": lambda: transcript(work, assets)}[step]()
