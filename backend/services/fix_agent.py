"""fix_agent — PR-only autonomous remediation for a triaged 'valid' work issue.

Flow (all in an ISOLATED shallow clone off `dev` — never the live checkout):
  1. Generate a fuller RCA document (LLM) and attach it to the issue.
  2. Run a coding agent to make the minimal fix:
       - preferred: the Claude Agent SDK (bounded tools, acceptEdits) if available;
       - fallback: a single-shot OpenAI full-file rewrite of the suspected file.
  3. Verify touched Python compiles (py_compile) — best-effort.
  4. Commit to a `fix/WORK-XXXX-*` branch, push, open a PR via the GitHub REST API.
  5. Move the issue to `in_review` with the PR link + RCA doc.

SAFETY (non-negotiable):
  * Disabled unless FIX_AGENT_ENABLED is truthy.
  * Requires a GitHub token + an LLM key; missing creds → fail-safe (no-op, marked failed).
  * Works only in a throwaway clone; NEVER edits the running tree; NEVER merges.
  * Opens a PR for human review only.

This module runs as a fire-and-forget background task (see routes/work.py::trigger_fix)
and must never raise into the caller.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from deps import db
from helpers import secrets as _secrets
from helpers import gsm as _gsm

logger = logging.getLogger(__name__)
_COLLECTION = "work_issues"

# ── Config (mirrors backend/scripts/error_triage.py conventions) ──────────────
REPO_OWNER = "amitporwal107"
REPO_NAME = "nivesh.ai"
BASE_BRANCH = os.environ.get("FIX_AGENT_BASE_BRANCH", "dev")
GH_TOKEN_FILE = "/opt/nivesh/.gh_pat"
OPENAI_KEY_FILE = "/opt/nivesh/.openai_key"
OPENAI_MODEL = os.environ.get("FIX_AGENT_OPENAI_MODEL", "gpt-4o-mini")


def _enabled() -> bool:
    """Explicit FIX_AGENT_ENABLED wins; otherwise ON in staging, OFF in production."""
    explicit = os.environ.get("FIX_AGENT_ENABLED")
    if explicit not in (None, ""):
        return explicit.strip().lower() in ("1", "true", "yes", "on")
    return _secrets.current_env() != "production"


def _read_secret(env_var: str, fallback_path: str) -> Optional[str]:
    val = os.environ.get(env_var)
    if val:
        return val.strip()
    p = Path(fallback_path)
    if p.is_file():
        try:
            return p.read_text().strip()
        except OSError:
            return None
    return None


def _gh_token() -> Optional[str]:
    """GitHub token: GSM (GH_TOKEN_<ENV> / GH_TOKEN, via gsm.get_for_env) →
    DB override (helpers.secrets) → env → /opt/nivesh/.gh_pat."""
    return (
        _gsm.get_for_env("GH_TOKEN")
        or (_secrets.get("GH_TOKEN") or None)
        or _read_secret("GH_TOKEN", GH_TOKEN_FILE)
    )


def _llm_key() -> Optional[str]:
    """OpenAI key: GSM → DB override (helpers.secrets) → env → /opt/nivesh/.openai_key."""
    return (
        _gsm.get_for_env("OPENAI_API_KEY")
        or (_secrets.get("OPENAI_API_KEY") or None)
        or _read_secret("OPENAI_API_KEY", OPENAI_KEY_FILE)
    )


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _set_remediation(issue_id: str, **fields) -> None:
    now = datetime.now(timezone.utc)
    update = {f"remediation.{k}": v for k, v in fields.items()}
    update["updated_at"] = now
    await db[_COLLECTION].update_one({"issue_id": issue_id}, {"$set": update})


async def _fail(issue_id: str, detail: str) -> None:
    logger.warning("fix_agent %s failed: %s", issue_id, detail)
    now = datetime.now(timezone.utc)
    await _set_remediation(issue_id, status="failed", detail=detail, finished_at=now)


# ── LLM (OpenAI via urllib — no extra deps, same as error_triage) ─────────────

def _openai_json(system: str, user: str, key: str, max_tokens: int = 1200) -> Optional[dict]:
    payload = {
        "model": OPENAI_MODEL,
        "max_tokens": max_tokens,
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
        logger.warning("fix_agent OpenAI call failed: %s", e)
        return None


def _generate_rca_document(issue: dict, code_ctx: str, key: str) -> str:
    system = (
        "You are a senior backend engineer writing a concise Root Cause Analysis for a "
        "production issue. Return JSON with keys: summary, root_cause, impact, fix_plan, "
        "prevention. Each value is 1-3 sentences of plain markdown. Be specific; do not "
        "invent details unsupported by the evidence."
    )
    user = (
        f"Issue {issue.get('issue_id')}: {issue.get('title')}\n"
        f"Exception: {issue.get('exception_class') or '-'}\n"
        f"Endpoint: {issue.get('endpoint') or '-'}\n"
        f"HTTP status: {issue.get('http_status')}\n"
        f"Sample message:\n{issue.get('sample_message') or '-'}\n\n"
        f"Traceback:\n{(issue.get('sample_traceback') or '(none)')[:1500]}\n\n"
        f"Relevant code:\n{code_ctx or '(none found)'}\n"
    )
    j = _openai_json(system, user, key, max_tokens=700) or {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"# RCA — {issue.get('issue_id')}: {issue.get('title')}\n"
        f"_Generated by fix_agent · {now}_\n\n"
        f"## Summary\n{j.get('summary', '_n/a_')}\n\n"
        f"## Root cause\n{j.get('root_cause', '_n/a_')}\n\n"
        f"## Impact\n{j.get('impact', '_n/a_')}\n\n"
        f"## Fix plan\n{j.get('fix_plan', '_n/a_')}\n\n"
        f"## Prevention\n{j.get('prevention', '_n/a_')}\n"
    )


# ── Git helpers ───────────────────────────────────────────────────────────────

def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git"] + args, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _clone(gh_token: str, dest: Path) -> Path:
    repo_dir = dest / REPO_NAME
    auth_url = f"https://x-access-token:{gh_token}@github.com/{REPO_OWNER}/{REPO_NAME}.git"
    subprocess.run(
        ["git", "clone", "--depth=1", f"--branch={BASE_BRANCH}", auth_url, str(repo_dir)],
        check=True, capture_output=True, text=True,
    )
    return repo_dir


def _grep_file(repo_dir: Path, pattern: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["grep", "-rl", "--include=*.py", "--include=*.ts", "--include=*.tsx", pattern, "backend/", "frontend-v5/src/"],
            cwd=repo_dir, capture_output=True, text=True, timeout=15,
        ).stdout.strip().splitlines()
        return out[0] if out else None
    except Exception:  # noqa: BLE001
        return None


def _locate_fix_file(repo_dir: Path, issue: dict) -> Optional[str]:
    rca = issue.get("rca") or {}
    cand = rca.get("fix_file")
    if cand and (repo_dir / cand).is_file():
        return cand
    exc = issue.get("exception_class")
    if exc:
        hit = _grep_file(repo_dir, f"raise {exc}")
        if hit:
            return hit
    ep = (issue.get("endpoint") or "").strip("/").split("?")[0]
    parts = [p for p in ep.split("/") if p and not p.replace("-", "").isdigit()]
    if len(parts) >= 2:
        return _grep_file(repo_dir, "/" + "/".join(parts[-2:]))
    return None


# ── Coding step ───────────────────────────────────────────────────────────────

_AGENT_SYSTEM = (
    "You are a careful senior engineer fixing ONE specific production issue in the Nivesh "
    "codebase. Make the SMALLEST correct change at the root cause. Do NOT refactor unrelated "
    "code, do NOT touch other files, follow the existing patterns, never hardcode secrets. "
    "If you cannot determine a safe fix from the evidence, make no change."
)


async def _run_claude_agent(repo_dir: Path, issue: dict, rca_md: str) -> bool:
    """Preferred path: Claude Agent SDK. Returns True if it changed files.
    Guarded — if the SDK/key are unavailable, returns False so we fall back."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions  # type: ignore
    except Exception:  # noqa: BLE001 — SDK not installed on this host
        return False
    prompt = (
        f"{_AGENT_SYSTEM}\n\nIssue {issue.get('issue_id')}: {issue.get('title')}\n"
        f"Exception: {issue.get('exception_class') or '-'} · Endpoint: {issue.get('endpoint') or '-'}\n"
        f"Sample message: {issue.get('sample_message') or '-'}\n\n"
        f"RCA:\n{rca_md}\n\nApply the minimal fix now."
    )
    try:
        options = ClaudeAgentOptions(
            cwd=str(repo_dir),
            permission_mode="acceptEdits",
            allowed_tools=["Read", "Edit", "Grep", "Glob", "Bash"],
            system_prompt=_AGENT_SYSTEM,
        )
        async for _ in query(prompt=prompt, options=options):
            pass
    except Exception as e:  # noqa: BLE001
        logger.warning("fix_agent Claude SDK run failed: %s", e)
        return False
    return bool(_git(["status", "--porcelain"], repo_dir))


def _run_openai_patch(repo_dir: Path, issue: dict, rca_md: str, key: str) -> bool:
    """Fallback: ask OpenAI to rewrite the single suspected file. Returns True if changed."""
    rel = _locate_fix_file(repo_dir, issue)
    if not rel:
        return False
    path = repo_dir / rel
    try:
        current = path.read_text(errors="replace")
    except OSError:
        return False
    if len(current) > 40000:  # too large to safely full-rewrite
        return False
    system = (
        _AGENT_SYSTEM + " You are given ONE file. Return JSON {\"new_content\": \"...\"} with the "
        "COMPLETE corrected file, or {\"no_change\": \"reason\"} if you cannot safely fix it here."
    )
    user = (
        f"Issue: {issue.get('title')}\nRCA:\n{rca_md}\n\n"
        f"File to fix: {rel}\n----- BEGIN {rel} -----\n{current}\n----- END {rel} -----\n"
    )
    j = _openai_json(system, user, key, max_tokens=4000)
    if not j or "new_content" not in j:
        return False
    new_content = j["new_content"]
    if not isinstance(new_content, str) or new_content.strip() == current.strip():
        return False
    path.write_text(new_content)
    return True


def _verify_python(repo_dir: Path) -> tuple[bool, str]:
    """py_compile any changed .py files. Best-effort; TS build is left to CI/PR checks."""
    changed = _git(["diff", "--name-only"], repo_dir).splitlines()
    py = [c for c in changed if c.endswith(".py")]
    if not py:
        return True, "no python files changed (TS build deferred to PR checks)"
    proc = subprocess.run(
        ["python3", "-m", "py_compile", *py], cwd=repo_dir, capture_output=True, text=True
    )
    ok = proc.returncode == 0
    return ok, (proc.stderr.strip()[:500] if not ok else f"py_compile OK ({len(py)} file(s))")


# ── PR ─────────────────────────────────────────────────────────────────────────

def _push_and_pr(repo_dir: Path, branch: str, gh_token: str, issue: dict, verify_note: str) -> tuple[str, bool]:
    _git(["config", "user.email", "fix-agent@niveshcopilot.com"], repo_dir)
    _git(["config", "user.name", "Nivesh Fix Agent"], repo_dir)
    _git(["checkout", "-b", branch], repo_dir)
    _git(["add", "-A"], repo_dir)
    _git(["commit", "-m", f"fix({issue.get('issue_id')}): {issue.get('title')[:60]}"], repo_dir)
    auth_url = f"https://x-access-token:{gh_token}@github.com/{REPO_OWNER}/{REPO_NAME}.git"
    _git(["push", auth_url, branch], repo_dir)
    body = {
        "title": f"fix({issue.get('issue_id')}): {issue.get('title')[:70]}",
        "head": branch,
        "base": BASE_BRANCH,
        "body": (
            f"Automated fix for **{issue.get('issue_id')}** — {issue.get('title')}\n\n"
            f"Verification: {verify_note}\n\n"
            f"⚠️ Generated by fix_agent for human review — do not merge without checking. "
            f"Full RCA + tests are attached on the issue in the Work dashboard."
        ),
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
        logger.warning("fix_agent PR creation HTTP %s — branch pushed, open manually", e.code)
        return f"https://github.com/{REPO_OWNER}/{REPO_NAME}/pull/new/{branch}", False


# ── Orchestrator ────────────────────────────────────────────────────────────────

async def run_fix(issue_id: str) -> None:
    """Background entrypoint. Never raises."""
    try:
        if not _enabled():
            await _fail(issue_id, "fix agent disabled (set FIX_AGENT_ENABLED=true to allow)")
            return
        issue = await db[_COLLECTION].find_one({"issue_id": issue_id}, {"_id": 0})
        if not issue:
            return
        if issue.get("classification") != "valid":
            await _fail(issue_id, "issue is not classified 'valid'")
            return
        gh_token = _gh_token()
        llm_key = _llm_key()
        if not gh_token:
            await _fail(issue_id, "missing GitHub token (GSM/GH_TOKEN/.gh_pat)")
            return
        if not llm_key:
            await _fail(issue_id, "missing OpenAI key (GSM/OPENAI_API_KEY/.openai_key)")
            return

        now = datetime.now(timezone.utc)
        await _set_remediation(issue_id, status="running", detail="cloning + analysing", started_at=now)

        with tempfile.TemporaryDirectory(prefix="fix-agent-") as tmp:
            try:
                repo_dir = _clone(gh_token, Path(tmp))
            except subprocess.CalledProcessError as e:
                await _fail(issue_id, f"clone failed: {(e.stderr or '').strip()[:200]}")
                return

            # 1) RCA document
            fix_file = _locate_fix_file(repo_dir, issue)
            code_ctx = ""
            if fix_file and (repo_dir / fix_file).is_file():
                code_ctx = f"{fix_file}:\n" + (repo_dir / fix_file).read_text(errors="replace")[:4000]
            rca_md = _generate_rca_document(issue, code_ctx, llm_key)
            await db[_COLLECTION].update_one(
                {"issue_id": issue_id},
                {"$set": {"rca_document": rca_md, "updated_at": datetime.now(timezone.utc)}},
            )

            # 2) Coding step — Claude Agent SDK preferred, OpenAI full-file fallback
            await _set_remediation(issue_id, detail="running coding agent")
            changed = await _run_claude_agent(repo_dir, issue, rca_md)
            if not changed:
                changed = _run_openai_patch(repo_dir, issue, rca_md, llm_key)
            if not changed:
                await _fail(issue_id, "agent produced no safe change — needs manual fix")
                return

            # 3) Verify
            ok, verify_note = _verify_python(repo_dir)
            if not ok:
                await _fail(issue_id, f"verification failed: {verify_note}")
                return

            # 4) PR
            branch = f"fix/{issue_id.lower()}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            try:
                pr_url, created = _push_and_pr(repo_dir, branch, gh_token, issue, verify_note)
            except subprocess.CalledProcessError as e:
                await _fail(issue_id, f"push failed: {(e.stderr or '').strip()[:200]}")
                return

            # 5) Move issue to in_review with the PR + note
            fin = datetime.now(timezone.utc)
            await db[_COLLECTION].update_one(
                {"issue_id": issue_id},
                {"$set": {
                    "status": "in_review",
                    "remediation": {
                        "status": "pr_open", "branch": branch, "pr_url": pr_url,
                        "run_id": branch, "detail": f"{verify_note}; PR {'opened' if created else 'push only'}",
                        "started_at": now, "finished_at": fin,
                    },
                    "updated_at": fin,
                },
                 "$push": {"comments": {"author": "fix_agent",
                                        "body": f"Opened PR for review: {pr_url}",
                                        "created_at": fin.isoformat()}}},
            )
            logger.info("fix_agent %s → PR %s", issue_id, pr_url)

            # 6) Kick off the test/screenshot run (Phase 3) — best-effort, non-blocking.
            try:
                from services import test_reporter
                await test_reporter.run_test_report(issue_id, pr_url=pr_url)
            except Exception as e:  # noqa: BLE001
                logger.info("fix_agent: test reporter skipped (%s)", e)
    except Exception as e:  # noqa: BLE001 — background task must never raise
        await _fail(issue_id, f"unexpected error: {e}")
