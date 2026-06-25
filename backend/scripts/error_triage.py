#!/usr/bin/env python3
"""error_triage.py — hourly Cloud Logging error triage for Nivesh.

Runs on nivesh-app-vm via /etc/cron.d/error-triage.

Pipeline:
  1. Query Cloud Logging for ERROR/WARNING/CRITICAL entries in the last 24h
     across nivesh-main-app, admin-app, nidp-console.
  2. Cluster by (exceptionClass, endpoint|jobName, normalized msg).
  3. Read existing docs/operations/error-backlog.md, dedupe by <!-- sig: HASH -->.
  4. For each genuinely new cluster, ask OpenAI (gpt-4o-mini) for a root-cause
     and fix suggestion, given the cluster info + relevant code snippets.
  5. Append to backlog in a fresh clone of the repo; push branch + open PR.
  6. POST all clusters (new + recurring) to /api/work/issues/ingest so they
     appear on the work.niveshcopilot.com dashboard.

Auth (all stdlib, no pip deps):
  GCP    — VM metadata server token (the VM's attached SA must have
           roles/logging.viewer or equivalent)
  GitHub — GH_TOKEN env var OR /opt/nivesh/.gh_pat
  OpenAI — OPENAI_API_KEY env var OR /opt/nivesh/.openai_key

Exit codes:
  0 — success (with or without new clusters)
  1 — fatal error
  2 — missing credentials
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────

PROJECT = "niveshdataintelligence"
APPS = ["nivesh-main-app", "admin-app", "nidp-console"]
REPO_OWNER = "amitporwal107"
REPO_NAME = "nivesh.ai"
REPO_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
BACKLOG_PATH = "docs/operations/error-backlog.md"
LOOKBACK_HOURS = 24
PAGE_SIZE = 1000
MAX_ENTRIES_PER_APP = 5000
MIN_CLUSTER_COUNT = 2  # singletons ignored unless severity=CRITICAL or has exceptionClass
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_MAX_TOKENS = 350
GH_TOKEN_FILE = "/opt/nivesh/.gh_pat"
OPENAI_KEY_FILE = "/opt/nivesh/.openai_key"
WORK_INGEST_URL = os.environ.get("WORK_INGEST_URL", "http://localhost:8001/api/work/issues/ingest")
WORK_INGEST_SECRET = os.environ.get("WORK_INGEST_SECRET", "")
METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/"
    "instance/service-accounts/default/token"
)

# JSON logging so the existing Ops Agent (Docker logs path) does NOT pick this
# up — but a custom file-tail receiver can. For now, write plain INFO to stderr.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("error_triage")


# ── Auth helpers ────────────────────────────────────────────────────────────

def get_gcp_token() -> str:
    """Fetch an OAuth2 access token from the GCE metadata server."""
    req = urllib.request.Request(
        METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["access_token"]


def read_secret(env_var: str, fallback_path: str) -> str | None:
    val = os.environ.get(env_var)
    if val:
        return val.strip()
    if Path(fallback_path).is_file():
        return Path(fallback_path).read_text().strip()
    return None


# ── Cloud Logging query ─────────────────────────────────────────────────────

def query_logging(token: str, app: str) -> list[dict]:
    """Page through ERROR/WARNING entries for one app over the last 24h."""
    start = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).isoformat(
        timespec="seconds"
    )
    flt = (
        f'jsonPayload.application="{app}" '
        f"AND severity>=WARNING "
        f'AND timestamp >= "{start}"'
    )
    entries: list[dict] = []
    page_token: str | None = None
    while len(entries) < MAX_ENTRIES_PER_APP:
        body: dict = {
            "resourceNames": [f"projects/{PROJECT}"],
            "filter": flt,
            "orderBy": "timestamp desc",
            "pageSize": PAGE_SIZE,
        }
        if page_token:
            body["pageToken"] = page_token
        req = urllib.request.Request(
            "https://logging.googleapis.com/v2/entries:list",
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            log.error("logging API error for %s: %s — %s", app, e.code, e.read()[:200])
            break
        entries.extend(data.get("entries", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    log.info("scanned %d entries for %s", len(entries), app)
    return entries


# ── Clustering ──────────────────────────────────────────────────────────────

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_NUM_RE = re.compile(r"\b\d+\b")
_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*")
_PATH_PARAM_RE = re.compile(r"/[0-9a-f]{8,}|/\d+")


def normalize_msg(msg: str) -> str:
    if not msg:
        return ""
    s = msg.lower()
    s = _UUID_RE.sub("<uuid>", s)
    s = _TIMESTAMP_RE.sub("<ts>", s)
    s = _NUM_RE.sub("<n>", s)
    return s[:120]


def normalize_endpoint(ep: str) -> str:
    if not ep:
        return ""
    return _PATH_PARAM_RE.sub("/<id>", ep)


def cluster_key(jp: dict) -> tuple[str, str, str]:
    exc = jp.get("exceptionClass") or "<no-exc>"
    endpoint = normalize_endpoint(jp.get("endpoint") or "")
    job = jp.get("jobName") or ""
    target = endpoint or job or "<unknown>"
    return (exc, target, normalize_msg(jp.get("msg") or ""))


def sig_hash(key: tuple) -> str:
    return hashlib.sha1("|".join(key).encode()).hexdigest()[:16]


def build_clusters(entries: list[dict]) -> dict[str, dict]:
    clusters: dict[str, dict] = {}
    for e in entries:
        jp = e.get("jsonPayload") or {}
        if not isinstance(jp, dict):
            continue
        key = cluster_key(jp)
        sig = sig_hash(key)
        ts = e.get("timestamp") or ""
        sev = e.get("severity") or jp.get("severity") or "ERROR"
        c = clusters.get(sig)
        if not c:
            clusters[sig] = {
                "sig": sig,
                "exception_class": jp.get("exceptionClass") or "",
                "endpoint": jp.get("endpoint") or "",
                "job_name": jp.get("jobName") or "",
                "http_status": jp.get("httpStatus"),
                "severity": sev,
                "sample_msg": (jp.get("msg") or "")[:200],
                "sample_exc": (jp.get("exc") or "")[:500],
                "first_seen": ts,
                "last_seen": ts,
                "count": 1,
                "apps": {jp.get("application") or "?"},
            }
        else:
            c["count"] += 1
            if ts < c["first_seen"]:
                c["first_seen"] = ts
            if ts > c["last_seen"]:
                c["last_seen"] = ts
            c["apps"].add(jp.get("application") or "?")
            if sev == "CRITICAL":
                c["severity"] = "CRITICAL"
            if not c["sample_exc"] and jp.get("exc"):
                c["sample_exc"] = jp["exc"][:500]
    # Filter noise
    keep = {
        s: c
        for s, c in clusters.items()
        if c["count"] >= MIN_CLUSTER_COUNT
        or c["severity"] == "CRITICAL"
        or c["exception_class"]
    }
    return keep


# ── Backlog parsing ─────────────────────────────────────────────────────────

_SIG_RE = re.compile(r"<!--\s*sig:\s*([0-9a-f]+)\s*-->")


def existing_sigs(repo_root: Path) -> set[str]:
    p = repo_root / BACKLOG_PATH
    if not p.is_file():
        return set()
    return set(_SIG_RE.findall(p.read_text()))


# ── Code-context gathering ──────────────────────────────────────────────────

def grep_locations(repo_root: Path, pattern: str, max_hits: int = 5) -> list[tuple[str, int, str]]:
    """Return (rel_path, line_no, line_text) tuples for grep hits inside backend/."""
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", pattern, "backend/"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return []
    hits: list[tuple[str, int, str]] = []
    for line in result.stdout.splitlines()[:max_hits]:
        m = re.match(r"^([^:]+):(\d+):(.*)$", line)
        if m:
            hits.append((m.group(1), int(m.group(2)), m.group(3).strip()[:200]))
    return hits


def read_context(repo_root: Path, rel_path: str, line: int, ctx: int = 8) -> str:
    p = repo_root / rel_path
    if not p.is_file():
        return ""
    try:
        lines = p.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    lo = max(0, line - ctx)
    hi = min(len(lines), line + ctx)
    return "\n".join(f"{i+1:4d}  {lines[i]}" for i in range(lo, hi))


def gather_code_context(repo_root: Path, c: dict) -> tuple[str, list[tuple[str, int]]]:
    """Return (formatted snippets, [(path, line), ...]) for the LLM + the backlog."""
    snippets: list[str] = []
    refs: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()

    def add(path: str, line: int, header: str) -> None:
        key = (path, line)
        if key in seen:
            return
        seen.add(key)
        ctx = read_context(repo_root, path, line)
        if ctx:
            snippets.append(f"--- {header}: {path}:{line}\n{ctx}")
            refs.append(key)

    if c["exception_class"]:
        for path, line, _ in grep_locations(repo_root, f"raise {c['exception_class']}", 3):
            add(path, line, "raise site")
        for path, line, _ in grep_locations(repo_root, f"class {c['exception_class']}", 1):
            add(path, line, "class def")
    if c["endpoint"]:
        # /api/foo/bar/<x> → grep "/foo/bar"
        ep = c["endpoint"].split("?", 1)[0]
        parts = [p for p in ep.strip("/").split("/") if p and not re.match(r"^[0-9a-f-]+$", p)]
        if len(parts) >= 2:
            quoted = "/" + "/".join(parts[-2:])
            for path, line, _ in grep_locations(repo_root, quoted, 3):
                add(path, line, "route handler")
    if c["job_name"]:
        # Common path: backend/nidp/services/<job>/
        candidate = repo_root / "backend" / "nidp" / "services" / c["job_name"]
        if candidate.is_dir():
            main = candidate / "__main__.py"
            if main.is_file():
                add(f"backend/nidp/services/{c['job_name']}/__main__.py", 1, "job entrypoint")
    # Fallback: distinctive phrase from the message
    if not snippets and c["sample_msg"]:
        words = [w for w in re.findall(r"\w{6,}", c["sample_msg"])]
        if words:
            for path, line, _ in grep_locations(repo_root, words[0], 2):
                add(path, line, "msg match")
    return "\n\n".join(snippets[:6]), refs[:6]


# ── OpenAI root-cause call ──────────────────────────────────────────────────

_RC_PROMPT = """You are a senior backend engineer triaging a production error. \
Given the error details and relevant code snippets, write:

1. SUSPECTED_ROOT_CAUSE: One sentence — the most likely cause given the evidence.
2. SUGGESTED_FIX: One or two sentences — concrete next step a developer should take.

Be specific. Reference file paths or function names if the snippets make them obvious. \
Do not invent details not supported by the input. \
If the snippets are insufficient, say "Insufficient context — needs investigation" \
in SUSPECTED_ROOT_CAUSE.

Respond as JSON: {"root_cause": "...", "fix": "..."}"""


def llm_analyze(openai_key: str, c: dict, code_ctx: str) -> tuple[str, str]:
    payload = {
        "model": OPENAI_MODEL,
        "max_tokens": OPENAI_MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _RC_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Application: {','.join(sorted(c['apps']))}\n"
                    f"Exception class: {c['exception_class'] or '-'}\n"
                    f"Endpoint: {c['endpoint'] or '-'}\n"
                    f"Job: {c['job_name'] or '-'}\n"
                    f"HTTP status: {c['http_status']}\n"
                    f"Severity: {c['severity']}\n"
                    f"Frequency (24h): {c['count']}\n\n"
                    f"Sample message:\n{c['sample_msg']}\n\n"
                    f"Sample traceback:\n{c['sample_exc'] or '(none)'}\n\n"
                    f"Relevant code snippets:\n{code_ctx or '(no code matched)'}\n"
                ),
            },
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {openai_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read()[:200].decode(errors="replace")
        log.warning("OpenAI HTTP %s — %s", e.code, body)
        return ("LLM analysis unavailable.", "Investigate manually.")
    except Exception as e:
        log.warning("OpenAI call failed: %s", e)
        return ("LLM analysis unavailable.", "Investigate manually.")
    content = resp["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
        return (
            (parsed.get("root_cause") or "").strip()[:400],
            (parsed.get("fix") or "").strip()[:400],
        )
    except json.JSONDecodeError:
        return (content[:200].replace("\n", " "), "")


# ── Backlog entry formatter ─────────────────────────────────────────────────

def format_entry(c: dict, root_cause: str, fix: str, refs: list[tuple[str, int]]) -> str:
    title_target = c["exception_class"] or "Error"
    where = c["endpoint"] or c["job_name"] or "(unknown)"
    title = f"{title_target} at {where}"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    apps = ", ".join(f"`{a}`" for a in sorted(c["apps"]))
    refs_md = "\n".join(
        f"- [{path}#L{max(1,line-5)}-L{line+5}]({path}#L{max(1,line-5)}-L{line+5})"
        for path, line in refs
    ) or "- _no obvious match in repo_"
    exc_block = c["sample_exc"] or "(none)"
    return f"""## {today}  {title}
<!-- sig: {c['sig']} -->

- **First seen:** `{c['first_seen']}`
- **Last seen:** `{c['last_seen']}`
- **Frequency (last 24h):** {c['count']} events
- **Applications:** {apps}
- **Severity:** {c['severity']}
- **Exception class:** `{c['exception_class'] or '-'}`
- **Endpoint / job:** `{c['endpoint'] or c['job_name'] or '-'}`
- **HTTP status:** {c['http_status'] if c['http_status'] is not None else '-'}

**Sample message:**
```
{c['sample_msg']}
```

**Sample traceback:**
```
{exc_block}
```

**Suspected root cause:** {root_cause}

**Suggested fix:** {fix}

**Code references:**
{refs_md}

---

"""


# ── Git / PR ────────────────────────────────────────────────────────────────

def run_git(args: list[str], cwd: Path, env: dict | None = None) -> str:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    out = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=full_env,
    )
    return out.stdout.strip()


def clone_repo(gh_token: str, work_root: Path) -> Path:
    repo_dir = work_root / REPO_NAME
    auth_url = (
        f"https://x-access-token:{gh_token}@github.com/{REPO_OWNER}/{REPO_NAME}.git"
    )
    subprocess.run(
        ["git", "clone", "--depth=1", "--branch=main", auth_url, str(repo_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    return repo_dir


def push_and_pr(
    repo_dir: Path, branch: str, gh_token: str, new_count: int
) -> tuple[str, bool]:
    run_git(["config", "user.email", "error-triage@niveshcopilot.com"], repo_dir)
    run_git(["config", "user.name", "Nivesh Error Triage"], repo_dir)
    run_git(["checkout", "-b", branch], repo_dir)
    run_git(["add", BACKLOG_PATH], repo_dir)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_git(
        ["commit", "-m", f"chore(triage): error backlog {today} (+{new_count})"],
        repo_dir,
    )
    auth_url = (
        f"https://x-access-token:{gh_token}@github.com/{REPO_OWNER}/{REPO_NAME}.git"
    )
    run_git(["push", auth_url, branch], repo_dir)
    # Try PR creation; fall back to manual URL
    pr_body = {
        "title": f"chore(triage): error backlog {today} (+{new_count})",
        "head": branch,
        "base": "main",
        "body": (
            f"Adds {new_count} new error cluster(s) from the last "
            f"{LOOKBACK_HOURS}h of Cloud Logging. "
            f"See `{BACKLOG_PATH}`. _Generated by error_triage.py on nivesh-app-vm._"
        ),
    }
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls",
        data=json.dumps(pr_body).encode(),
        headers={
            "Authorization": f"Bearer {gh_token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            return (data.get("html_url", ""), True)
    except urllib.error.HTTPError as e:
        log.warning("PR creation HTTP %s — branch pushed, open manually", e.code)
        return (
            f"https://github.com/{REPO_OWNER}/{REPO_NAME}/pull/new/{branch}",
            False,
        )


# ── Work dashboard ingest ────────────────────────────────────────────────────

def ingest_to_work_dashboard(clusters: dict[str, dict], rca_map: dict[str, tuple[str, str]]) -> None:
    """
    POST all clusters (with their RCA) to the work dashboard ingest endpoint.
    Non-fatal — a failure here must not abort the backlog/PR pipeline.
    """
    if not WORK_INGEST_URL:
        return
    payload_clusters = []
    for sig, c in clusters.items():
        entry = dict(c)
        entry["apps"] = list(c.get("apps", set()))
        root_cause, fix_suggestion = rca_map.get(sig, ("", ""))
        entry["root_cause"] = root_cause
        entry["fix_suggestion"] = fix_suggestion
        payload_clusters.append(entry)

    body = json.dumps({"clusters": payload_clusters}).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if WORK_INGEST_SECRET:
        headers["X-Ingest-Secret"] = WORK_INGEST_SECRET

    req = urllib.request.Request(
        WORK_INGEST_URL, data=body, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            log.info("work dashboard ingest: created=%s updated=%s", result.get("created"), result.get("updated"))
    except Exception as exc:
        log.warning("work dashboard ingest failed (non-fatal): %s", exc)


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    gh_token = read_secret("GH_TOKEN", GH_TOKEN_FILE)
    openai_key = read_secret("OPENAI_API_KEY", OPENAI_KEY_FILE)
    if not gh_token:
        log.error("missing GitHub token (env GH_TOKEN or %s)", GH_TOKEN_FILE)
        return 2
    if not openai_key:
        log.error("missing OpenAI key (env OPENAI_API_KEY or %s)", OPENAI_KEY_FILE)
        return 2

    try:
        gcp_token = get_gcp_token()
    except Exception as e:
        log.error("could not get GCP metadata token: %s", e)
        return 2

    all_clusters: dict[str, dict] = {}
    per_app_counts: dict[str, int] = {}
    for app in APPS:
        entries = query_logging(gcp_token, app)
        per_app_counts[app] = len(entries)
        for sig, c in build_clusters(entries).items():
            if sig in all_clusters:
                # Merge across apps
                ex = all_clusters[sig]
                ex["count"] += c["count"]
                ex["apps"] |= c["apps"]
                if c["first_seen"] < ex["first_seen"]:
                    ex["first_seen"] = c["first_seen"]
                if c["last_seen"] > ex["last_seen"]:
                    ex["last_seen"] = c["last_seen"]
            else:
                all_clusters[sig] = c
    log.info("formed %d clusters across all apps", len(all_clusters))

    with tempfile.TemporaryDirectory(prefix="error-triage-") as tmp:
        work_root = Path(tmp)
        try:
            repo_dir = clone_repo(gh_token, work_root)
        except subprocess.CalledProcessError as e:
            log.error("git clone failed: %s", e.stderr.strip()[:200] if e.stderr else e)
            return 1
        seen = existing_sigs(repo_dir)
        new_clusters = {s: c for s, c in all_clusters.items() if s not in seen}
        log.info("%d new clusters (after dedup against existing backlog)", len(new_clusters))
        if not new_clusters:
            print(f"summary  scanned={per_app_counts}  clusters={len(all_clusters)}  new=0  no-op")
            return 0

        # Ensure backlog file exists
        backlog = repo_dir / BACKLOG_PATH
        backlog.parent.mkdir(parents=True, exist_ok=True)
        if not backlog.is_file():
            backlog.write_text(
                "# Error backlog\n\n"
                "Automatically maintained by `backend/scripts/error_triage.py` on "
                "nivesh-app-vm. New error clusters from Cloud Logging are appended "
                "here hourly. Each entry includes a `<!-- sig: ... -->` marker that "
                "the script uses to dedupe across runs — do not remove these markers "
                "if you want to keep an entry from re-appearing.\n\n"
                "---\n\n"
            )

        # Sort new clusters by count desc, then enrich + append
        ordered = sorted(new_clusters.values(), key=lambda c: -c["count"])
        appended_blocks: list[str] = []
        for c in ordered:
            code_ctx, refs = gather_code_context(repo_dir, c)
            root_cause, fix = llm_analyze(openai_key, c, code_ctx)
            appended_blocks.append(format_entry(c, root_cause, fix, refs))
        with backlog.open("a") as f:
            f.write("".join(appended_blocks))

        branch = (
            f"chore/error-triage-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        )
        try:
            pr_url, ok = push_and_pr(repo_dir, branch, gh_token, len(ordered))
        except subprocess.CalledProcessError as e:
            log.error("git push failed: %s", (e.stderr or "").strip()[:200])
            return 1

        print(
            f"summary  scanned={per_app_counts}  clusters={len(all_clusters)}  "
            f"new={len(ordered)}  branch={branch}  pr={pr_url}  pr_created={ok}"
        )
        # Top 3 by count
        top = ordered[:3]
        for c in top:
            print(
                f"  • [{c['count']:4d}] {c['exception_class'] or '-'} @ "
                f"{c['endpoint'] or c['job_name'] or '-'}: "
                f"{(c['sample_msg'] or '')[:80]}"
            )

        # Persist ALL clusters (new + recurring) to work dashboard
        rca_map = {c["sig"]: llm_analyze(openai_key, c, "") for c in ordered}
        ingest_to_work_dashboard(all_clusters, rca_map)

        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        log.exception("fatal: %s", e)
        sys.exit(1)
