#!/usr/bin/env python3
"""fix_agent_runner.py — VM-side PR-only auto-fix runner.

Runs on nivesh-app-vm (which HAS git) via cron, NOT inside the app container
(which does not). Mirrors backend/scripts/error_triage.py: stdlib-only, talks to
the app over HTTP with the ingest secret — so it needs no app deps (no Motor/gsm).

Flow, per queued issue:
  1. GET  /api/work/fix-queue                 (issues with remediation=queued, classification=valid)
  2. report remediation=running
  3. clone dev → LLM RCA doc → attach it
  4. minimal fix: OpenAI full-file rewrite of the suspected file
  5. verify: py_compile the changed .py files
  6. push a fix/WORK-… branch, open a PR via the GitHub REST API
  7. POST /api/work/issues/{id}/artifacts      (rca_document, remediation=pr_open, status=in_review)
Any failure → report remediation=failed with the reason. Never merges; PR only.

Auth (env var OR file):
  GH_TOKEN         | /opt/nivesh/.gh_pat
  OPENAI_API_KEY   | /opt/nivesh/.openai_key
  WORK_INGEST_SECRET   (shared secret for /api/work/fix-queue + /artifacts)
  WORK_API_BASE        (default http://localhost:8001)

Cron (/etc/cron.d/fix-agent-runner) — mirror the error-triage entry:
  */5 * * * * nivesh WORK_INGEST_SECRET=… python3 /opt/nivesh/app/backend/scripts/fix_agent_runner.py >> /var/log/fix-agent-runner.log 2>&1
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s fix-runner %(levelname)s %(message)s")
log = logging.getLogger("fix-runner")

REPO_OWNER = os.environ.get("FIX_RUNNER_REPO_OWNER", "amitporwal107")
REPO_NAME = os.environ.get("FIX_RUNNER_REPO_NAME", "nivesh.ai")
BASE_BRANCH = os.environ.get("FIX_RUNNER_BASE_BRANCH", "dev")
API_BASE = os.environ.get("WORK_API_BASE", "http://localhost:8001").rstrip("/")
OPENAI_MODEL = os.environ.get("FIX_RUNNER_OPENAI_MODEL", "gpt-4o-mini")
GH_TOKEN_FILE = "/opt/nivesh/.gh_pat"
OPENAI_KEY_FILE = "/opt/nivesh/.openai_key"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_secret(env_var: str, path: str) -> Optional[str]:
    v = os.environ.get(env_var)
    if v:
        return v.strip()
    p = Path(path)
    if p.is_file():
        try:
            return p.read_text().strip()
        except OSError:
            return None
    return None


def _ingest_secret() -> str:
    return os.environ.get("WORK_INGEST_SECRET", "")


# ── App API (ingest-secret auth) ──────────────────────────────────────────────

def _api(method: str, path: str, body: Optional[dict] = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API_BASE + path, data=data, method=method,
        headers={"X-Ingest-Secret": _ingest_secret(), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def fetch_queue() -> list[dict]:
    return _api("GET", "/api/work/fix-queue?limit=10").get("issues", [])


def report(issue_id: str, **fields) -> None:
    """POST an ArtifactsUpdate (rca_document / remediation / status / comment)."""
    try:
        _api("POST", f"/api/work/issues/{issue_id}/artifacts", fields)
    except Exception as e:  # noqa: BLE001
        log.warning("report(%s) failed: %s", issue_id, e)


# ── OpenAI (urllib) ───────────────────────────────────────────────────────────

def _openai_json(system: str, user: str, key: str, max_tokens: int = 1200) -> Optional[dict]:
    payload = {
        "model": OPENAI_MODEL, "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
        return json.loads(resp["choices"][0]["message"]["content"])
    except Exception as e:  # noqa: BLE001
        log.warning("OpenAI call failed: %s", e)
        return None


def generate_rca_document(issue: dict, code_ctx: str, key: str) -> str:
    system = (
        "You are a senior backend engineer writing a concise Root Cause Analysis. "
        "Return JSON with keys: summary, root_cause, impact, fix_plan, prevention "
        "(each 1-3 sentences of plain markdown). Be specific; do not invent details."
    )
    user = (
        f"Issue {issue.get('issue_id')}: {issue.get('title')}\n"
        f"Exception: {issue.get('exception_class') or '-'}\n"
        f"Endpoint: {issue.get('endpoint') or '-'}\n"
        f"Sample message:\n{issue.get('sample_message') or '-'}\n\n"
        f"Traceback:\n{(issue.get('sample_traceback') or '(none)')[:1500]}\n\n"
        f"Relevant code:\n{code_ctx or '(none found)'}\n"
    )
    j = _openai_json(system, user, key, max_tokens=700) or {}
    return (
        f"# RCA — {issue.get('issue_id')}: {issue.get('title')}\n"
        f"_Generated by fix_agent_runner · {_now()}_\n\n"
        f"## Summary\n{j.get('summary', '_n/a_')}\n\n"
        f"## Root cause\n{j.get('root_cause', '_n/a_')}\n\n"
        f"## Impact\n{j.get('impact', '_n/a_')}\n\n"
        f"## Fix plan\n{j.get('fix_plan', '_n/a_')}\n\n"
        f"## Prevention\n{j.get('prevention', '_n/a_')}\n"
    )


# ── Git + fix ─────────────────────────────────────────────────────────────────

def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def clone(gh_token: str, dest: Path) -> Path:
    repo_dir = dest / REPO_NAME
    auth = f"https://x-access-token:{gh_token}@github.com/{REPO_OWNER}/{REPO_NAME}.git"
    subprocess.run(["git", "clone", "--depth=1", f"--branch={BASE_BRANCH}", auth, str(repo_dir)],
                   check=True, capture_output=True, text=True)
    return repo_dir


def _grep_file(repo: Path, pattern: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["grep", "-rl", "--include=*.py", "--include=*.ts", "--include=*.tsx", pattern,
             "backend/", "frontend-v5/src/"],
            cwd=repo, capture_output=True, text=True, timeout=15,
        ).stdout.strip().splitlines()
        return out[0] if out else None
    except Exception:  # noqa: BLE001
        return None


def locate_fix_file(repo: Path, issue: dict) -> Optional[str]:
    rca = issue.get("rca") or {}
    cand = rca.get("fix_file")
    if cand and (repo / cand).is_file():
        return cand
    exc = issue.get("exception_class")
    if exc:
        hit = _grep_file(repo, f"raise {exc}")
        if hit:
            return hit
    ep = (issue.get("endpoint") or "").strip("/").split("?")[0]
    parts = [p for p in ep.split("/") if p and not p.replace("-", "").isdigit()]
    if len(parts) >= 2:
        return _grep_file(repo, "/" + "/".join(parts[-2:]))
    return None


_AGENT_SYSTEM = (
    "You are a careful senior engineer fixing ONE specific production issue. Make the "
    "SMALLEST correct change at the root cause. Do NOT refactor unrelated code, do NOT "
    "touch other files, follow existing patterns, never hardcode secrets. If you cannot "
    "determine a safe fix from the evidence, make no change."
)


def run_openai_patch(repo: Path, issue: dict, rca_md: str, key: str) -> bool:
    rel = locate_fix_file(repo, issue)
    if not rel:
        return False
    path = repo / rel
    try:
        current = path.read_text(errors="replace")
    except OSError:
        return False
    if len(current) > 40000:
        return False
    system = (
        _AGENT_SYSTEM + " You are given ONE file. Return JSON {\"new_content\": \"...\"} with the "
        "COMPLETE corrected file, or {\"no_change\": \"reason\"} if you cannot safely fix it here."
    )
    user = f"Issue: {issue.get('title')}\nRCA:\n{rca_md}\n\nFile: {rel}\n----- BEGIN {rel} -----\n{current}\n----- END {rel} -----\n"
    j = _openai_json(system, user, key, max_tokens=4000)
    if not j or "new_content" not in j:
        return False
    new_content = j["new_content"]
    if not isinstance(new_content, str) or new_content.strip() == current.strip():
        return False
    path.write_text(new_content)
    return True


def verify_python(repo: Path) -> tuple[bool, str]:
    changed = _git(["diff", "--name-only"], repo).splitlines()
    py = [c for c in changed if c.endswith(".py")]
    if not py:
        return True, "no python files changed (TS build deferred to PR checks)"
    proc = subprocess.run(["python3", "-m", "py_compile", *py], cwd=repo, capture_output=True, text=True)
    ok = proc.returncode == 0
    return ok, (proc.stderr.strip()[:500] if not ok else f"py_compile OK ({len(py)} file(s))")


def push_and_pr(repo: Path, branch: str, gh_token: str, issue: dict, verify_note: str) -> tuple[str, bool]:
    _git(["config", "user.email", "fix-agent@niveshcopilot.com"], repo)
    _git(["config", "user.name", "Nivesh Fix Agent"], repo)
    _git(["checkout", "-b", branch], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-m", f"fix({issue.get('issue_id')}): {str(issue.get('title'))[:60]}"], repo)
    auth = f"https://x-access-token:{gh_token}@github.com/{REPO_OWNER}/{REPO_NAME}.git"
    _git(["push", auth, branch], repo)
    body = {
        "title": f"fix({issue.get('issue_id')}): {str(issue.get('title'))[:70]}",
        "head": branch, "base": BASE_BRANCH,
        "body": (f"Automated fix for **{issue.get('issue_id')}** — {issue.get('title')}\n\n"
                 f"Verification: {verify_note}\n\n"
                 f"⚠️ Generated by fix_agent_runner for human review — do not merge without checking."),
    }
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()).get("html_url", ""), True
    except urllib.error.HTTPError as e:
        log.warning("PR creation HTTP %s — branch pushed, open manually", e.code)
        return f"https://github.com/{REPO_OWNER}/{REPO_NAME}/pull/new/{branch}", False


# ── Per-issue processing ──────────────────────────────────────────────────────

def process(issue: dict, gh_token: str, key: str) -> None:
    iid = issue["issue_id"]
    report(iid, remediation={"status": "running", "detail": "cloning + analysing", "started_at": _now()})
    with tempfile.TemporaryDirectory(prefix="fix-runner-") as tmp:
        try:
            repo = clone(gh_token, Path(tmp))
        except subprocess.CalledProcessError as e:
            report(iid, remediation={"status": "failed", "detail": f"clone failed: {(e.stderr or '').strip()[:200]}", "finished_at": _now()})
            return

        rel = locate_fix_file(repo, issue)
        code_ctx = ""
        if rel and (repo / rel).is_file():
            code_ctx = f"{rel}:\n" + (repo / rel).read_text(errors="replace")[:4000]
        rca_md = generate_rca_document(issue, code_ctx, key)
        report(iid, rca_document=rca_md, remediation={"status": "running", "detail": "coding", "started_at": _now()})

        if not run_openai_patch(repo, issue, rca_md, key):
            report(iid, remediation={"status": "failed", "detail": "agent produced no safe change — needs manual fix", "finished_at": _now()})
            return
        ok, note = verify_python(repo)
        if not ok:
            report(iid, remediation={"status": "failed", "detail": f"verification failed: {note}", "finished_at": _now()})
            return
        branch = f"fix/{iid.lower()}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        try:
            url, created = push_and_pr(repo, branch, gh_token, issue, note)
        except subprocess.CalledProcessError as e:
            report(iid, remediation={"status": "failed", "detail": f"push failed: {(e.stderr or '').strip()[:200]}", "finished_at": _now()})
            return
        report(
            iid,
            status="in_review",
            remediation={"status": "pr_open", "branch": branch, "pr_url": url, "run_id": branch,
                         "detail": f"{note}; PR {'opened' if created else 'push only'}", "finished_at": _now()},
            comment=f"Opened PR for review: {url}",
        )
        log.info("%s → PR %s", iid, url)


def main() -> int:
    if not _ingest_secret():
        log.error("WORK_INGEST_SECRET not set — cannot talk to the app"); return 1
    gh = _read_secret("GH_TOKEN", GH_TOKEN_FILE)
    key = _read_secret("OPENAI_API_KEY", OPENAI_KEY_FILE)
    if not gh:
        log.error("missing GitHub token (GH_TOKEN / %s)", GH_TOKEN_FILE); return 1
    if not key:
        log.error("missing OpenAI key (OPENAI_API_KEY / %s)", OPENAI_KEY_FILE); return 1
    try:
        queue = fetch_queue()
    except Exception as e:  # noqa: BLE001
        log.error("fetch queue failed: %s", e); return 1
    log.info("queue: %d issue(s)", len(queue))
    for issue in queue:
        iid = issue.get("issue_id", "?")
        try:
            process(issue, gh, key)
        except Exception as e:  # noqa: BLE001
            log.warning("fix %s failed: %s", iid, e)
            report(iid, remediation={"status": "failed", "detail": f"runner error: {e}"[:200], "finished_at": _now()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
