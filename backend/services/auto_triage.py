"""auto_triage — optional automation on top of the human-gated issue pipeline.

Two independently-flagged behaviours, run as a background task when an error issue
is first filed (services.issue_intake schedules it):

  1. AUTO-RCA ON FILING  (flag: AUTO_RCA_ENABLED — default ON off-production):
     generate a short RCA (root cause + fix suggestion) via the LLM and attach it,
     and auto-classify OBVIOUS non-code errors (delisted symbol, upstream/data/
     timeout) as `business_validation` so they don't clutter the human queue.

  2. AUTO-FIX HIGH-CONFIDENCE CODING BUGS  (admin feature flag: `auto_fix_agent`,
     default OFF; env AUTO_FIX_ENABLED overrides as an ops kill-switch):
     only when explicitly enabled, if the LLM is confident the issue is a
     genuine CODING bug (not data/delisted/vendor), mark it `valid` and spawn the
     PR-only fix agent. Everything uncertain is left `unclassified` for a human.

Nothing here ever auto-merges — the fix agent only ever opens a PR. Safe no-op when
the flags are off or no LLM key is available.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from deps import db
from helpers import secrets as _secrets
from helpers import gsm as _gsm

logger = logging.getLogger(__name__)
_COLLECTION = "work_issues"
OPENAI_MODEL = os.environ.get("AUTO_TRIAGE_OPENAI_MODEL", "gpt-4o-mini")
_FIX_CONFIDENCE = 0.75

_bg_tasks: set = set()

# Signatures of NON-code (data / external / vendor) errors — never auto-fixed.
_DATA_ERROR_RE = re.compile(
    r"delisted|no price data|no data found|symbol may be|yahoo|rate.?limit|"
    r"timed out|timeout|connection (refused|reset|error)|temporarily unavailable|"
    r"upstream|bad gateway|gateway time|\b50[234]\b|dns|name resolution|quota",
    re.IGNORECASE,
)


def _flag(name: str, default_non_prod: bool = False) -> bool:
    """Explicit env flag wins; else `default_non_prod` on non-production, off on prod."""
    v = os.environ.get(name)
    if v not in (None, ""):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return default_non_prod and _secrets.current_env() != "production"


def _auto_rca_enabled() -> bool:
    return _flag("AUTO_RCA_ENABLED", default_non_prod=True)


async def _auto_fix_enabled() -> bool:
    """Opt-in, default OFF. Toggled by admins via the `auto_fix_agent` feature flag
    (Admin → Feature Flags, set mode = everyone). Read straight from Mongo (the
    persisted source of truth) rather than feature_flags' process-local in-memory
    cache, which can be stale across uvicorn workers. An AUTO_FIX_ENABLED env var,
    if set, overrides the flag (ops kill-switch / force-enable)."""
    v = os.environ.get("AUTO_FIX_ENABLED")
    if v not in (None, ""):
        return v.strip().lower() in ("1", "true", "yes", "on")
    try:
        doc = await db.system_config.find_one({"key": "feature_flags"}, {"_id": 0, "flags": 1})
        mode = (((doc or {}).get("flags") or {}).get("auto_fix_agent") or {}).get("mode", "off")
        return mode == "everyone"
    except Exception:  # noqa: BLE001
        return False


def _llm_key() -> Optional[str]:
    return (
        _gsm.get_for_env("OPENAI_API_KEY")
        or (_secrets.get("OPENAI_API_KEY") or None)
        or (os.environ.get("OPENAI_API_KEY") or None)
    )


def _heuristic_business_validation(text: str, http_status: Optional[int]) -> bool:
    if _DATA_ERROR_RE.search(text or ""):
        return True
    # Expected client-validation errors (4xx) are not code bugs to auto-fix.
    return bool(http_status and 400 <= int(http_status) < 500 and int(http_status) != 500)


def _openai_triage(issue: dict, key: str) -> dict:
    system = (
        "You triage a production backend error. Return JSON with keys: "
        "root_cause (1 sentence), fix_suggestion (1 sentence), "
        "classification (one of: valid | business_validation | tbd), "
        "is_coding_bug (boolean), confidence (0..1). "
        "'valid' = a genuine code defect we can fix in this repo. "
        "'business_validation' = expected/validation/data/vendor error (e.g. a "
        "delisted symbol, upstream/rate-limit/timeout) — NOT a code bug. "
        "'tbd' = needs human clarification. Be conservative: if unsure, use 'tbd' "
        "with low confidence. Do not invent details."
    )
    user = (
        f"Exception: {issue.get('exception_class') or '-'}\n"
        f"Endpoint: {issue.get('endpoint') or '-'}\n"
        f"HTTP status: {issue.get('http_status')}\n"
        f"Message:\n{issue.get('sample_message') or '-'}\n\n"
        f"Traceback:\n{(issue.get('sample_traceback') or '(none)')[:1200]}\n"
    )
    payload = {
        "model": OPENAI_MODEL,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        resp = json.loads(r.read())
    return json.loads(resp["choices"][0]["message"]["content"])


async def _enrich(issue_id: str) -> None:
    """Generate RCA + (conservatively) classify; optionally auto-fix. Never raises."""
    try:
        if not _auto_rca_enabled():
            return
        issue = await db[_COLLECTION].find_one({"issue_id": issue_id}, {"_id": 0})
        if not issue or issue.get("rca"):  # already enriched (or gone)
            return
        key = _llm_key()
        if not key:
            return

        text = f"{issue.get('exception_class','')} {issue.get('sample_message','')} {issue.get('sample_traceback','')}"
        heuristic_bv = _heuristic_business_validation(text, issue.get("http_status"))
        auto_fix = await _auto_fix_enabled()

        try:
            j = await asyncio.get_event_loop().run_in_executor(None, _openai_triage, issue, key)
        except Exception as e:  # noqa: BLE001
            logger.warning("auto_triage LLM failed for %s: %s", issue_id, e)
            return

        rca = {
            "root_cause": str(j.get("root_cause", ""))[:400],
            "fix_suggestion": str(j.get("fix_suggestion", ""))[:400],
            "confidence": float(j.get("confidence", 0.5) or 0.5),
            "source": "openai",
            "fix_file": None,
            "fix_description": None,
        }
        # Decide classification conservatively.
        classification = None
        llm_class = str(j.get("classification", "")).strip().lower()
        is_coding = bool(j.get("is_coding_bug"))
        if heuristic_bv or llm_class == "business_validation":
            classification = "business_validation"
        elif auto_fix and llm_class == "valid" and is_coding and rca["confidence"] >= _FIX_CONFIDENCE:
            classification = "valid"
        elif llm_class == "tbd":
            classification = "tbd"
        # else: leave unclassified for a human.

        update: dict = {"rca": rca, "updated_at": datetime.now(timezone.utc)}
        if classification:
            update["classification"] = classification
        await db[_COLLECTION].update_one({"issue_id": issue_id}, {"$set": update})
        logger.info("auto_triage enriched %s (class=%s, conf=%.2f)", issue_id, classification, rca["confidence"])

        # Opt-in auto-fix: only for confidently-coding 'valid' issues.
        if classification == "valid" and auto_fix:
            now = datetime.now(timezone.utc)
            await db[_COLLECTION].update_one(
                {"issue_id": issue_id},
                {"$set": {
                    "status": "in_progress",
                    "remediation": {"status": "queued", "started_at": now, "finished_at": None,
                                    "branch": None, "pr_url": None, "run_id": None,
                                    "detail": "Queued for the VM fix-agent runner"},
                    "updated_at": now,
                },
                 "$push": {"comments": {"author": "auto_triage",
                                        "body": "Auto-classified valid (high-confidence coding bug) → queued for the VM fix-agent runner.",
                                        "created_at": now.isoformat()}}},
            )
            # The fix executes out-of-process on the VM (fix_agent_runner.py, cron),
            # which polls the queue and reports back — the app container has no git.
    except Exception as e:  # noqa: BLE001 — background task must never raise
        logger.warning("auto_triage._enrich failed for %s: %s", issue_id, e)


def schedule(issue_id: str) -> None:
    """Fire-and-forget enrichment for a newly-filed issue (retains task ref)."""
    if not issue_id or not _auto_rca_enabled():
        return
    try:
        task = asyncio.create_task(_enrich(issue_id))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
    except RuntimeError:
        # No running loop (e.g. called from sync context) — skip silently.
        pass
