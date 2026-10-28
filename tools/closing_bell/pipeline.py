"""Closing Bell — nightly orchestrator. Builds the day's market-wrap video from the Smart Trading Desk and
publishes it only when every check passes; otherwise holds it and alerts the operator.

Run by cron on the app VM (deploy/cloudpe/app/closing-bell.cron) every 10 minutes from 22:00 to 00:50 IST on
trading days. Each run decides for itself:
  - already published / held / missed for that date      -> exit quietly
  - snapshot or Top 10 list not ready yet                  -> exit quietly (the next run tries again)
  - not a trading day (weekend / NSE holiday)              -> exit quietly
  - still not ready at the cut-off (00:50)                 -> record "missed" and alert
  - ready                                                  -> build, check, publish or hold

usage: python3 pipeline.py [--date YYYY-MM-DD] [--force] [--dry-run] [--keep-work]
  --force    skip the readiness / state checks (re-build a date)     --dry-run  build + check, do not publish
Paths (env overrides): CB_ROOT=/opt/nivesh-staging/closing-bell  CB_DEST=/opt/nivesh-staging/downloads/closing-bell
                       CB_BACKEND=nivesh-staging-app-backend
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
IST = timezone(timedelta(hours=5, minutes=30))
ROOT = os.environ.get("CB_ROOT", "/opt/nivesh-staging/closing-bell")
DEST = os.environ.get("CB_DEST", "/opt/nivesh-staging/downloads/closing-bell")
BACKEND = os.environ.get("CB_BACKEND", "nivesh-staging-app-backend")
TOOLS_IMAGE = "nivesh/closing-bell-tools:1"
FF_IMAGE = "jrottenberg/ffmpeg:6.1-ubuntu"
MUSIC_URL = "https://upload.wikimedia.org/wikipedia/commons/c/c8/The_Complex_%28ISRC_USUAN1300025%29.mp3"
MUSIC_SHA256 = "c270fb44a69828f6cae7412e077a38b92d55015d30ced549d0d477f864e7e41e"
MIN_FREE_GB = 8          # staging deploys need 6 GB free; never starve them
CUTOFF = (0, 50)         # IST next morning: after this a not-ready day is "missed"
SEGMENT_ORDER = ["s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7"]


def log(msg: str) -> None:
    print(f"{datetime.now(IST):%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def sh(cmd, label, *, input_text=None, check=True, timeout=3600):
    r = subprocess.run(cmd, capture_output=True, text=True, input=input_text, timeout=timeout)
    if r.returncode != 0 and check:
        raise StepFailed(label, (r.stderr or r.stdout)[-1500:])
    return r


class StepFailed(Exception):
    def __init__(self, step, detail):
        super().__init__(f"{step}: {detail}")
        self.step, self.detail = step, detail


def backend(args, label, *, input_text=None, check=True):
    # CB_BACKEND_SCRIPT: run an un-merged copy (tests only), e.g. /tmp/closing_bell.py copied into the container.
    script = os.environ.get("CB_BACKEND_SCRIPT")
    run = ["python", script] if script else ["python", "-m", "scripts.closing_bell"]
    return sh(["docker", "exec", "-i", "-w", "/app/backend", "-e", "PYTHONPATH=/app/backend", BACKEND] + run + args, label,
              input_text=input_text, check=check)


def tools(work, args, label, extra_mounts=(), env=(), network=True):
    cmd = ["docker", "run", "--rm", "--shm-size=1g", "-v", f"{work}:/w", "-v", f"{HERE}:/app:ro", "-w", "/app"]
    for m in extra_mounts:
        cmd += ["-v", m]
    for e in env:
        cmd += ["-e", e]
    if not network:
        cmd += ["--network", "none"]
    return sh(cmd + [TOOLS_IMAGE] + args, label, timeout=3600)


def host_py(args, label, check=True):
    return sh([sys.executable, *args], label, check=check)


def edition_date(now: datetime) -> str:
    """Before noon IST the run belongs to the previous evening's session."""
    d = now.date() if now.hour >= 12 else now.date() - timedelta(days=1)
    return d.isoformat()


def past_cutoff(d: str, now: datetime) -> bool:
    nxt = datetime.fromisoformat(d).date() + timedelta(days=1)
    return now >= datetime(nxt.year, nxt.month, nxt.day, CUTOFF[0], CUTOFF[1], tzinfo=IST)


def state_path(d, kind):
    return os.path.join(ROOT, "state", f"{d}.{kind}")


def finish(d, status, reasons, work, log_path, dry, now=None):
    if status == "failed" and not dry:
        # A transient failure (feed, network) gets one more attempt on the next cron tick before anyone is alerted.
        p = state_path(d, "attempts")
        n = int(open(p).read() or 0) + 1 if os.path.exists(p) else 1
        open(p, "w").write(str(n))
        if n < 2 and not past_cutoff(d, now or datetime.now(IST)):
            log(f"RESULT FAILED (attempt {n}, will retry) {d}: " + "; ".join(reasons))
            return
    summary = {"date": d, "status": status, "reasons": reasons, "log": log_path,
               "url": f"https://staging.niveshcopilot.com/v5/market-commentary/{d}" if status == "published" else None}
    if not dry:
        open(state_path(d, status), "w").write(json.dumps(summary, indent=1))
        r = backend(["notify"], "notify", input_text=json.dumps(summary), check=False)
        log(f"notify: {(r.stdout or r.stderr).strip()[-300:]}")
    log(f"RESULT {status.upper()} {d}" + (": " + "; ".join(reasons) if reasons else ""))


def preflight(work):
    free = shutil.disk_usage("/").free / 1e9
    if free < MIN_FREE_GB:
        raise StepFailed("disk", f"only {free:.1f} GB free on / (need {MIN_FREE_GB} GB; deploys need 6 GB)")
    if sh(["docker", "image", "inspect", TOOLS_IMAGE], "image", check=False).returncode != 0:
        log("building tools image")
        sh(["docker", "build", "-t", TOOLS_IMAGE, HERE], "build tools image", timeout=1800)
    assets = os.path.join(ROOT, "assets")
    os.makedirs(assets, exist_ok=True)
    mp3 = os.path.join(assets, "the_complex.mp3")
    if not os.path.exists(mp3) or hashlib.sha256(open(mp3, "rb").read()).hexdigest() != MUSIC_SHA256:
        log("fetching music bed (Wikimedia Commons, CC BY 3.0)")
        req = urllib.request.Request(MUSIC_URL, headers={"User-Agent": "NiveshClosingBell/1.0 (staging bulletin)"})
        data = urllib.request.urlopen(req, timeout=120).read()
        if hashlib.sha256(data).hexdigest() != MUSIC_SHA256:
            raise StepFailed("music", "downloaded file does not match the pinned sha256")
        open(mp3, "wb").write(data)
    host_py([f"{HERE}/build.py", work, assets, "sfx"], "sfx")
    return assets


def build(d: str, work: str, dry: bool) -> list:
    """Everything from data to checked media. Returns the list of hold reasons (empty = publishable)."""
    assets = preflight(work)
    tok = os.path.join(work, "tok")
    backend(["ensure-bot"], "ensure-bot")
    r = backend(["session", "--ttl-min", "75"], "session")
    old = os.umask(0o077)
    open(tok, "w").write(r.stdout.strip().splitlines()[-1])
    os.umask(old)
    try:
        log("collect")
        r = backend(["collect", "--date", d, "--token-file", "/dev/stdin"], "collect", input_text=open(tok).read())
        open(f"{work}/bundle.json", "w").write(r.stdout)
        host_py([f"{HERE}/cards.py", f"{work}/bundle.json", f"{work}/cards.json"], "cards")
        host_py([f"{HERE}/script_gen.py", f"{work}/cards.json", f"{work}/script.json"], "script")
        r = host_py([f"{HERE}/checks.py", "script", f"{work}/cards.json", f"{work}/script.json"], "checks", check=False)
        open(f"{work}/checks_script.json", "w").write(r.stdout)
        rep = json.loads(r.stdout or "{}")
        if r.returncode != 0:
            return (rep.get("data_fails") or []) + (rep.get("fails") or []) or ["script checks failed"]
        log(f"script checks ok: {rep.get('numbers_checked')} numbers")
        tools(work, ["python", "synth.py"], "synth")
        host_py([f"{HERE}/build.py", work, assets, "timeline"], "timeline")
        host_py([f"{HERE}/build.py", work, assets, "bed"], "bed")
        log("graphics")
        tools(work, ["python", "gfx.py"], "graphics")
        segs = [s["id"] for s in json.load(open(f"{work}/script.json"))["segments"]]
        log("recording desk footage")
        tools(work, ["python", "rec.py"] + [s for s in segs if s != "s0"], "record", extra_mounts=[f"{tok}:/tok:ro"])
    finally:
        rv = backend(["revoke", "--token-file", "/dev/stdin"], "revoke", input_text=open(tok).read() if os.path.exists(tok) else "", check=False)
        if rv.returncode == 0:
            log(f"bot session revoked: {rv.stdout.strip()[-80:]}")
        else:   # never silent: the session still expires by itself (75 min) and the next run clears expired ones
            log(f"WARNING bot session NOT revoked ({(rv.stderr or rv.stdout).strip()[-200:]}); it expires within 75 min")
        if os.path.exists(tok):
            os.remove(tok)
    host_py([f"{HERE}/build.py", work, assets, "footage"] + [s for s in segs if s != "s0"], "footage")
    log("assembling segments")
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(lambda s: host_py([f"{HERE}/build.py", work, assets, "seg", s], f"seg {s}"), segs))
    host_py([f"{HERE}/build.py", work, assets, "final"], "final")
    langs = json.load(open(f"{work}/tts/fit.json"))["langs"]
    others = [l for l in langs if l != "en"]
    if others:
        log(f"language tracks: {', '.join(others)}")
        with cf.ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(lambda l: host_py([f"{HERE}/build.py", work, assets, "lang", l], f"lang {l}"), others))
    host_py([f"{HERE}/build.py", work, assets, "transcript"], "transcript")
    r = host_py([f"{HERE}/checks.py", "media", f"{work}/out/media.json", f"{work}/timeline.json", f"{work}/raw"], "media checks", check=False)
    open(f"{work}/checks_media.json", "w").write(r.stdout)
    return json.loads(r.stdout or "{}").get("fails") or ([] if r.returncode == 0 else ["media checks failed"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-work", action="store_true")
    a = ap.parse_args()
    now = datetime.now(IST)
    d = a.date or edition_date(now)
    os.makedirs(os.path.join(ROOT, "state"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    if not a.force and any(os.path.exists(state_path(d, k)) for k in ("published", "held", "failed", "missed", "no_session")):
        return 0
    if not a.force:
        r = backend(["ready", "--date", d], "ready", check=False)
        try:
            rd = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            log(f"ready check failed: {(r.stderr or '')[-300:]}")
            return 1
        if rd.get("no_session") and not rd.get("snapshot_ready"):
            open(state_path(d, "no_session"), "w").write(json.dumps(rd))
            log(f"{d}: no trading session")
            return 0
        if not rd.get("ready"):
            if past_cutoff(d, now):
                why = [k for k in ("snapshot_ready", "ideas_list") if not rd.get(k)]
                finish(d, "missed", [f"not ready by 00:50 IST: {', '.join(why)} false"], None, None, a.dry_run)
            return 0
    work = os.path.join(ROOT, "work", d)
    if os.path.exists(work):
        shutil.rmtree(work)
    os.makedirs(work)
    log_path = os.path.join(ROOT, "logs", f"{d}.log")
    log(f"START {d} work={work}")
    t0 = time.time()
    try:
        reasons = build(d, work, a.dry_run)
    except StepFailed as e:
        finish(d, "failed", [f"{e.step}: {e.detail[-400:]}"], work, log_path, a.dry_run)
        return 2
    if reasons:
        finish(d, "held", reasons, work, log_path, a.dry_run)
        return 3
    if a.dry_run:
        log(f"DRY RUN ok in {time.time() - t0:.0f}s; not published. Output: {work}/out/web.mp4")
        return 0
    r = host_py([f"{HERE}/publish.py", work, DEST], "publish")
    log(f"published: {r.stdout.strip()}")
    finish(d, "published", [], work, log_path, a.dry_run)
    if not a.keep_work:
        for sub in ("raw", "foot", "seg", "gfx", "tts", "lists", "sfx"):
            shutil.rmtree(os.path.join(work, sub), ignore_errors=True)
    log(f"done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
