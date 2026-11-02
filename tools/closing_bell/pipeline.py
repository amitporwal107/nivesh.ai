"""Closing Bell — nightly orchestrator. Builds the day's market-wrap video from the Smart Trading Desk and
publishes it only when every check passes; otherwise holds it and alerts the operator.

Run by cron on the app VM (deploy/cloudpe/app/closing-bell.cron) every 10 minutes from 22:00 to 00:50 IST on
trading days. Each run decides for itself:
  - already published / held / missed for that date      -> exit quietly
  - snapshot or Top 10 list not ready yet                  -> exit quietly (the next run tries again)
  - not a trading day (weekend / NSE holiday)              -> exit quietly
  - still not ready at the cut-off (00:50)                 -> record "missed" and alert
  - ready                                                  -> build, check, publish or hold

Opening Bell (--kind opening, owner 2 Nov 2026: publish about 9:10 IST after the pre-open, data-based ranges and
levels, no global cues). Two phases on the morning of D:
  --phase A   (cron 06:30-08:50, every 10 min) everything from the previous session's data: script without the
              pre-open, voices, graphics, desk footage, segments; state <D>.phase_a
  --phase B   (cron 09:08) NSE pre-open -> re-script, re-voice and re-render only the cold open and the pre-open
              segment, lay the ticker + audio over the whole programme, check, publish to /downloads/opening-bell/
  --phase both   A then B in one go (tests; with --allow-stale-preopen a dry run can use an earlier pre-open)
Work, state and logs live under CB_ROOT/opening; editions under CB_DEST_OPEN (default <CB_DEST>/../opening-bell).

usage: python3 pipeline.py [--kind closing|opening] [--phase A|B|both] [--date YYYY-MM-DD] [--force] [--dry-run] [--keep-work]
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
ASSETS = os.path.join(ROOT, "assets")          # music + effects, shared by both editions
ROOT_OPEN = os.environ.get("CB_ROOT_OPEN", os.path.join(ROOT, "opening"))
DEST_OPEN = os.environ.get("CB_DEST_OPEN", os.path.join(os.path.dirname(DEST.rstrip("/")), "opening-bell"))
OPEN_CUTOFF = (8, 50)                          # IST: phase A not done by then -> "missed"
PREOPEN_UNTIL = "09:12"
BACKEND = os.environ.get("CB_BACKEND", "nivesh-staging-app-backend")
TOOLS_IMAGE = "nivesh/closing-bell-tools:1"
FF_IMAGE = "jrottenberg/ffmpeg:6.1-ubuntu"
MUSIC_URL = "https://upload.wikimedia.org/wikipedia/commons/c/c8/The_Complex_%28ISRC_USUAN1300025%29.mp3"
MUSIC_SHA256 = "c270fb44a69828f6cae7412e077a38b92d55015d30ced549d0d477f864e7e41e"
# Staging deploys need 6 GB free; never starve them. A build peaks at about 1 GB, so CB_MIN_FREE_GB must stay >= 7.
MIN_FREE_GB = max(7.0, float(os.environ.get("CB_MIN_FREE_GB") or 8))
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


def open_past_cutoff(d: str, now: datetime) -> bool:
    day = datetime.fromisoformat(d).date()
    return now >= datetime(day.year, day.month, day.day, OPEN_CUTOFF[0], OPEN_CUTOFF[1], tzinfo=IST)


def finish(d, status, reasons, work, log_path, dry, now=None, kind="closing", retry=True):
    if status == "failed" and not dry and retry:
        # A transient failure (feed, network) gets one more attempt on the next cron tick before anyone is alerted.
        p = state_path(d, "attempts")
        n = int(open(p).read() or 0) + 1 if os.path.exists(p) else 1
        open(p, "w").write(str(n))
        late = open_past_cutoff(d, now or datetime.now(IST)) if kind == "opening" else past_cutoff(d, now or datetime.now(IST))
        if n < 2 and not late:
            log(f"RESULT FAILED (attempt {n}, will retry) {d}: " + "; ".join(reasons))
            return
    url = None
    if status == "published":
        url = (f"https://staging.niveshcopilot.com/downloads/opening-bell/{d}/opening-bell-{d}.mp4" if kind == "opening"
               else f"https://staging.niveshcopilot.com/v5/market-commentary/{d}")
    summary = {"date": d, "kind": kind, "status": status, "reasons": reasons, "log": log_path, "url": url}
    if not dry:
        open(state_path(d, status), "w").write(json.dumps(summary, indent=1))
        r = backend(["notify"], "notify", input_text=json.dumps(summary), check=False)
        log(f"notify: {(r.stdout or r.stderr).strip()[-300:]}")
    log(f"RESULT {status.upper()} {d}" + (": " + "; ".join(reasons) if reasons else ""))


def trim_work(work):
    """After a publish: drop the build intermediates and the work copies of the videos (≈1 GB, ≈180 MB of it in out/;
    the published copies are the record). The small JSON / caption / transcript files stay for audit."""
    for sub in ("raw", "foot", "seg", "gfx", "tts", "lists", "sfx"):
        shutil.rmtree(os.path.join(work, sub), ignore_errors=True)
    out = os.path.join(work, "out")
    for f in os.listdir(out) if os.path.isdir(out) else []:
        if f.endswith(".mp4"):
            os.remove(os.path.join(out, f))


def preflight(work):
    free = shutil.disk_usage("/").free / 1e9
    if free < MIN_FREE_GB:
        raise StepFailed("disk", f"only {free:.1f} GB free on / (need {MIN_FREE_GB} GB; deploys need 6 GB)")
    if sh(["docker", "image", "inspect", TOOLS_IMAGE], "image", check=False).returncode != 0:
        log("building tools image")
        sh(["docker", "build", "-t", TOOLS_IMAGE, HERE], "build tools image", timeout=1800)
    assets = ASSETS
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


def bot_session(work):
    tok = os.path.join(work, "tok")
    backend(["ensure-bot"], "ensure-bot")
    r = backend(["session", "--ttl-min", "75"], "session")
    old = os.umask(0o077)
    open(tok, "w").write(r.stdout.strip().splitlines()[-1])
    os.umask(old)
    return tok


def revoke(tok):
    rv = backend(["revoke", "--token-file", "/dev/stdin"], "revoke", input_text=open(tok).read() if os.path.exists(tok) else "", check=False)
    if rv.returncode == 0:
        log(f"bot session revoked: {rv.stdout.strip()[-80:]}")
    else:   # never silent: the session still expires by itself (75 min) and the next run clears expired ones
        log(f"WARNING bot session NOT revoked ({(rv.stderr or rv.stdout).strip()[-200:]}); it expires within 75 min")
    if os.path.exists(tok):
        os.remove(tok)


def script_checks(work, extra=()):
    r = host_py([f"{HERE}/checks.py", "script", f"{work}/cards.json", f"{work}/script.json", *extra], "checks", check=False)
    open(f"{work}/checks_script.json", "w").write(r.stdout)
    rep = json.loads(r.stdout or "{}")
    if r.returncode != 0:
        return (rep.get("data_fails") or []) + (rep.get("fails") or []) or ["script checks failed"]
    log(f"script checks ok: {rep.get('numbers_checked')} numbers")
    return []


def build_open_a(d: str, work: str) -> list:
    """Morning phase A: everything that does not need the pre-open."""
    assets = preflight(work)
    tok = bot_session(work)
    try:
        log("collect (previous session + chains + MCX)")
        r = backend(["collect-open", "--date", d, "--token-file", "/dev/stdin"], "collect-open", input_text=open(tok).read())
        open(f"{work}/bundle.json", "w").write(r.stdout)
        host_py([f"{HERE}/cards_open.py", f"{work}/bundle.json", f"{work}/cards.json"], "cards")
        host_py([f"{HERE}/script_gen.py", f"{work}/cards.json", f"{work}/script.json"], "script")
        fails = script_checks(work)
        if fails:
            return fails
        tools(work, ["python", "synth.py"], "synth")
        host_py([f"{HERE}/build.py", work, assets, "timeline"], "timeline")
        host_py([f"{HERE}/build.py", work, assets, "bed"], "bed")
        log("graphics")
        tools(work, ["python", "gfx.py"], "graphics")
        segs = [s["id"] for s in json.load(open(f"{work}/script.json"))["segments"]]
        log("recording desk footage")
        tools(work, ["python", "rec.py"] + [s for s in segs if s != "s0"], "record", extra_mounts=[f"{tok}:/tok:ro"])
    finally:
        revoke(tok)
    host_py([f"{HERE}/build.py", work, assets, "footage"] + [s for s in segs if s != "s0"], "footage")
    log("assembling segments (all but the cold open and the pre-open)")
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(lambda s: host_py([f"{HERE}/build.py", work, assets, "seg", s], f"seg {s}"), [s for s in segs if s not in ("s0", "o2")]))
    shutil.copyfile(f"{work}/script.json", f"{work}/script_a.json")
    return []


PHASE_B_SEGS = ("s0", "o2")


def phase_a_drift(work: str) -> list:
    """Phase B re-voices only s0 + o2; every other segment keeps its phase-A voices and footage, so its text must be
    unchanged (a deploy between the runs could change it). Returns the segments whose text differs."""
    p = os.path.join(work, "script_a.json")
    if not os.path.exists(p):
        return ["(no phase A script)"]
    texts = lambda s: {x["id"]: [b.get("texts") for b in x["beats"]] for x in s["segments"] if x["id"] not in PHASE_B_SEGS}
    a, b = texts(json.load(open(p))), texts(json.load(open(os.path.join(work, "script.json"))))
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def build_open_b(d: str, work: str, allow_stale: bool) -> list:
    """Morning phase B (09:08): the pre-open, then only s0 + o2 are re-made; ticker and audio over the whole programme."""
    assets = ASSETS
    free = shutil.disk_usage("/").free / 1e9
    if free < MIN_FREE_GB - 2:
        raise StepFailed("disk", f"only {free:.1f} GB free on /")
    log("pre-open (NSE)")
    args = [f"{HERE}/preopen.py", f"{work}/preopen.json", "--date", d,
            "--until", (datetime.now(IST) + timedelta(minutes=2)).strftime("%H:%M") if allow_stale else PREOPEN_UNTIL]
    r = host_py(args + (["--allow-stale"] if allow_stale else []), "pre-open", check=False)
    if r.returncode != 0:
        return [f"pre-open: {(r.stderr or r.stdout).strip()[-300:]}"]
    log(f"pre-open: {r.stdout.strip()[-200:]}")
    host_py([f"{HERE}/cards_open.py", f"{work}/bundle.json", f"{work}/cards.json", f"{work}/preopen.json"], "cards")
    host_py([f"{HERE}/script_gen.py", f"{work}/cards.json", f"{work}/script.json"], "script")
    fails = script_checks(work, ["--require-preopen"])
    if fails:
        return fails
    drift = phase_a_drift(work)
    if drift:
        return [f"script text changed since the morning build in {', '.join(drift)}; its voices no longer match (code or data changed between the runs)"]
    tools(work, ["python", "synth.py"], "synth s0 o2", env=["CB_SEGS=" + ",".join(PHASE_B_SEGS)])
    host_py([f"{HERE}/build.py", work, assets, "timeline"], "timeline")
    host_py([f"{HERE}/build.py", work, assets, "bed"], "bed")
    tools(work, ["python", "gfx.py", "sup", "h1", "h2", "h3", "h4", "pre"], "graphics s0 o2")
    host_py([f"{HERE}/build.py", work, assets, "footage", "o2"], "footage o2")
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(lambda s: host_py([f"{HERE}/build.py", work, assets, "seg", s], f"seg {s}"), ["s0", "o2"]))
    log("final (ticker + audio over the whole programme)")
    host_py([f"{HERE}/build.py", work, assets, "final"], "final")
    langs = json.load(open(f"{work}/tts/fit.json"))["langs"]
    others = [l for l in langs if l != "en"]
    if others:
        with cf.ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(lambda l: host_py([f"{HERE}/build.py", work, assets, "lang", l], f"lang {l}"), others))
    host_py([f"{HERE}/build.py", work, assets, "transcript"], "transcript")
    r = host_py([f"{HERE}/checks.py", "media", f"{work}/out/media.json", f"{work}/timeline.json", f"{work}/raw"], "media checks", check=False)
    open(f"{work}/checks_media.json", "w").write(r.stdout)
    return json.loads(r.stdout or "{}").get("fails") or ([] if r.returncode == 0 else ["media checks failed"])


def main_open(a) -> int:
    global ROOT
    ROOT = ROOT_OPEN
    now = datetime.now(IST)
    d = a.date or now.date().isoformat()
    for sub in ("state", "logs"):
        os.makedirs(os.path.join(ROOT, sub), exist_ok=True)
    final_states = ("published", "held", "failed", "missed", "no_session")
    if not a.force and any(os.path.exists(state_path(d, k)) for k in final_states):
        return 0
    work = os.path.join(ROOT, "work", d)
    log_path = os.path.join(ROOT, "logs", f"{d}.log")
    t0 = time.time()
    if a.phase in ("A", "both"):
        if not a.force and os.path.exists(state_path(d, "phase_a")) and a.phase == "A":
            return 0
        if not a.force:
            r = backend(["ready-open", "--date", d], "ready", check=False)
            try:
                rd = json.loads(r.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                log(f"ready check failed: {(r.stderr or '')[-300:]}")
                return 1
            if rd.get("no_session"):
                open(state_path(d, "no_session"), "w").write(json.dumps(rd))
                log(f"{d}: no trading session")
                return 0
            if not rd.get("ready"):
                if open_past_cutoff(d, now):
                    why = [k for k in ("snapshot_ready", "ideas_list", "chain_ready") if not rd.get(k)]
                    finish(d, "missed", [f"previous session's data not ready by 08:50 IST: {', '.join(why)} false"], None, None,
                           a.dry_run, kind="opening")
                return 0
        if os.path.exists(work):
            shutil.rmtree(work)
        os.makedirs(work)
        log(f"START opening {d} phase A work={work}")
        try:
            reasons = build_open_a(d, work)
        except StepFailed as e:
            finish(d, "failed", [f"phase A {e.step}: {e.detail[-400:]}"], work, log_path, a.dry_run, kind="opening")
            return 2
        if reasons:
            finish(d, "held", reasons, work, log_path, a.dry_run, kind="opening")
            return 3
        open(state_path(d, "phase_a"), "w").write(datetime.now(IST).isoformat(timespec="seconds"))
        log(f"phase A ok in {time.time() - t0:.0f}s")
    if a.phase in ("B", "both"):
        if not os.path.exists(state_path(d, "phase_a")):
            finish(d, "missed", ["the morning build (phase A) had not completed by the 09:08 pre-open run"], None, None, a.dry_run,
                   kind="opening", retry=False)
            return 3
        log(f"START opening {d} phase B")
        try:
            reasons = build_open_b(d, work, a.allow_stale_preopen)
        except StepFailed as e:
            finish(d, "failed", [f"phase B {e.step}: {e.detail[-400:]}"], work, log_path, a.dry_run, kind="opening", retry=False)
            return 2
        if reasons:
            finish(d, "held", reasons, work, log_path, a.dry_run, kind="opening", retry=False)
            return 3
        if a.dry_run or a.allow_stale_preopen:
            log(f"DRY RUN ok in {time.time() - t0:.0f}s; not published. Output: {work}/out/web.mp4")
            return 0
        r = host_py([f"{HERE}/publish.py", work, DEST_OPEN], "publish")
        log(f"published: {r.stdout.strip()}")
        finish(d, "published", [], work, log_path, a.dry_run, kind="opening")
        if not a.keep_work:
            trim_work(work)
        log(f"done in {time.time() - t0:.0f}s")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--kind", choices=["closing", "opening"], default="closing")
    ap.add_argument("--phase", choices=["A", "B", "both"], default="both")
    ap.add_argument("--allow-stale-preopen", action="store_true", help="TESTS ONLY: build with an earlier day's pre-open; never publishes")
    a = ap.parse_args()
    if a.kind == "opening":
        return main_open(a)
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
        trim_work(work)
    log(f"done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
