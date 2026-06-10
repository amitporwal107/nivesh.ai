"""Periodic Gmail ECAS auto-import.

For every Gmail-connected user with a saved CAS password (the PAN they
typed during their first manual import — see `routes.gmail`), scan their
inbox for new NSDL/CDSL/CAMS/KFintech statements and import any not yet
processed. Gmail tokens (access + refresh) are saved at OAuth time and
refreshed automatically here so credentials persist across sessions.

Scheduled: 1st of each month at 06:30 IST via `services.mf_scheduler`.
ECAS providers (NSDL priority, then CDSL) email monthly statements in
the first few days of the month; running on the 1st at 06:30 IST catches
same-day delivery for most users. On-demand sync is available via
`/api/gmail/auto-import/run` (Dashboard "Sync Gmail" button).

The actual parse uses the same casparser SDK-flow as the onboarding
orchestrator (`services.cas_api_client.parse_cas_via_sdk_flow_with_error`)
and persists with `helpers.parsing.save_holdings`, so the data shape is
identical to a manual import — auto-imported statements populate live
holdings and contribute to transactions / SIP detection on equal footing.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def auto_import_for_user(db, user_id: str) -> Dict[str, Any]:
    """Scan one user's Gmail and import the latest not-yet-imported CAS.
    Returns a small status dict for logging.

    Parses via the same casparser SDK-flow the onboarding orchestrator uses
    (`services.cas_api_client`) and persists with `save_holdings` — the old
    `_persist_gmail_pdf` / `_process_gmail_cas_background` helpers were removed
    when CAS parsing moved fully server-side, which left this path raising
    ImportError on every run (scheduler + Dashboard 'Sync Gmail')."""
    # Lazy imports to avoid circular import at module load.
    from services.gmail_service import (
        get_gmail_credentials, build_gmail_service,
        scan_for_cas_emails, download_attachment,
    )
    from services import cas_api_client
    from helpers.parsing import save_holdings

    token_doc = await db.gmail_tokens.find_one({"user_id": user_id}, {"_id": 0})
    if not token_doc:
        return {"status": "skipped", "reason": "no_tokens"}
    if token_doc.get("auto_import_enabled") is False:
        return {"status": "skipped", "reason": "disabled"}

    # PAN unlocks the PAN-locked CAS PDF. Prefer the saved gmail_tokens value,
    # then fall back to the profile PAN (the onboarding /pan path writes there).
    pwd = token_doc.get("cas_password", "")
    if not pwd:
        profile = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0}) or {}
        pwd = profile.get("cas_password") or profile.get("pan") or ""
    if not pwd:
        return {"status": "skipped", "reason": "no_saved_password"}

    try:
        creds = get_gmail_credentials(token_doc)
        service = build_gmail_service(creds)
        # Persist refreshed access token if it rotated
        if creds.token != token_doc.get("access_token"):
            await db.gmail_tokens.update_one(
                {"user_id": user_id},
                {"$set": {
                    "access_token": creds.token,
                    "expires_at": (
                        creds.expiry.replace(tzinfo=timezone.utc).isoformat()
                        if creds.expiry else None
                    ),
                }},
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("auto_import: creds failed for %s: %s", user_id, e)
        return {"status": "error", "reason": "creds_failed", "error": str(e)}

    try:
        emails = scan_for_cas_emails(service, max_results=20)
    except Exception as e:  # noqa: BLE001
        logger.warning("auto_import: scan failed for %s: %s", user_id, e)
        return {"status": "error", "reason": "scan_failed", "error": str(e)}

    # Dedupe against statements already imported (completed). Emails come back
    # sorted by source priority, so the first not-yet-imported one is the best.
    existing = await db.gmail_imports.find(
        {"user_id": user_id},
        {"_id": 0, "message_id": 1, "attachment_id": 1, "status": 1},
    ).to_list(500)
    done_keys = {
        (e["message_id"], e.get("attachment_id"))
        for e in existing if e.get("status") == "completed"
    }

    def _att_id(em: Dict[str, Any]):
        return em.get("attachment_id") or (em.get("attachments") or [{}])[0].get("attachment_id")

    fresh = [e for e in emails if (e["message_id"], _att_id(e)) not in done_keys]
    if not fresh:
        await db.gmail_tokens.update_one(
            {"user_id": user_id},
            {"$set": {"last_auto_import_at": datetime.now(timezone.utc).isoformat()}},
        )
        return {"status": "no_new_emails", "scanned": len(emails)}

    email = fresh[0]
    message_id = email["message_id"]
    attachment_id = _att_id(email)
    filename = (
        email.get("filename")
        or (email.get("attachments") or [{}])[0].get("filename")
        or "cas.pdf"
    )
    if not attachment_id:
        return {"status": "error", "reason": "no_attachment", "scanned": len(emails)}

    try:
        content = download_attachment(service, message_id, attachment_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("auto_import: download failed for %s/%s: %s", user_id, message_id, e)
        return {"status": "error", "reason": "download_failed", "error": str(e)}

    try:
        holdings, _raw, _norm, parse_err = cas_api_client.parse_cas_via_sdk_flow_with_error(
            content, password=pwd,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("auto_import: parse crashed for %s/%s: %s", user_id, filename, e)
        return {"status": "error", "reason": "parse_failed", "error": str(e)}

    if not holdings:
        kind = (parse_err or {}).get("kind", "parse")
        logger.warning(
            "auto_import: parse failed for %s (%s) kind=%s detail=%s",
            filename, user_id, kind, (parse_err or {}).get("detail"),
        )
        return {
            "status": "error", "reason": "parse_failed",
            "error_kind": kind, "error": (parse_err or {}).get("message"),
            "scanned": len(emails),
        }

    task_id = f"gmail_auto_{uuid.uuid4().hex[:12]}"
    await save_holdings(user_id, holdings, file_type="gmail_cas", task_id=task_id)

    now = datetime.now(timezone.utc).isoformat()
    await db.gmail_imports.update_one(
        {"user_id": user_id, "message_id": message_id, "attachment_id": attachment_id},
        {"$set": {
            "user_id": user_id, "message_id": message_id, "attachment_id": attachment_id,
            "filename": filename, "count": len(holdings), "task_id": task_id,
            "status": "completed", "source": "gmail_auto", "trigger": "auto",
            "imported_at": now,
        }},
        upsert=True,
    )
    await db.gmail_tokens.update_one(
        {"user_id": user_id},
        {"$set": {"last_auto_import_at": now, "auto_import_enabled": True}},
    )
    logger.info("auto_import: imported %s holdings for %s (%s)", len(holdings), user_id, filename)
    return {"status": "ok", "scanned": len(emails), "imported": 1, "holdings": len(holdings)}


async def auto_import_all_users() -> Dict[str, Any]:
    """Scheduler entrypoint — sweep every Gmail-connected user with a
    saved CAS password. Designed to be called from APScheduler."""
    from deps import db  # lazy

    cursor = db.gmail_tokens.find(
        {
            "cas_password": {"$exists": True, "$ne": ""},
            # Either auto_import_enabled is True or the field doesn't
            # exist yet (legacy rows from before this feature)
            "$or": [
                {"auto_import_enabled": True},
                {"auto_import_enabled": {"$exists": False}},
            ],
        },
        {"_id": 0, "user_id": 1},
    )
    users = await cursor.to_list(2000)
    summary = {"users": len(users), "imported": 0, "failed": 0, "errors": 0, "skipped": 0}
    for u in users:
        try:
            res = await auto_import_for_user(db, u["user_id"])
            summary["imported"] += res.get("imported", 0)
            summary["failed"] += res.get("failed", 0)
            if res.get("status") == "error":
                summary["errors"] += 1
            elif res.get("status") in ("skipped", "no_new_emails"):
                summary["skipped"] += 1
        except Exception as e:  # noqa: BLE001
            logger.error("auto_import: user %s crashed: %s", u.get("user_id"), e)
            summary["errors"] += 1
    logger.info("auto_import sweep complete: %s", summary)
    return summary
