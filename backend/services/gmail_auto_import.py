"""Periodic Gmail CAS auto-import.

For every Gmail-connected user with a saved CAS password (the PAN they
typed during their first manual import — see `routes.gmail`), scan their
inbox once a day for new NSDL/CDSL/CAMS/KFintech statements and import
any not yet processed. Wired into the AsyncIO scheduler in
`services.mf_scheduler` to run at 06:30 IST daily, which is a few hours
after CAS providers typically email statements (early-morning IST batch).

The actual parse + snapshot creation reuses `_process_gmail_cas_background`
from the routes module so the data shape is identical to a manual
import — meaning auto-imported statements show up in Time-Machine,
populate live holdings if they're the latest, and contribute to
transactions / SIP detection on equal footing.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def auto_import_for_user(db, user_id: str) -> Dict[str, Any]:
    """Scan one user's Gmail and import any CAS attachments that
    haven't been imported yet. Returns a small status dict for logging."""
    # Lazy imports to avoid circular import at module load (mf_scheduler
    # imports this module before `routes.gmail` is registered).
    from services.gmail_service import (
        get_gmail_credentials, build_gmail_service,
        scan_for_cas_emails, download_attachment,
    )
    from routes.gmail import _persist_gmail_pdf, _process_gmail_cas_background

    token_doc = await db.gmail_tokens.find_one({"user_id": user_id}, {"_id": 0})
    if not token_doc:
        return {"status": "skipped", "reason": "no_tokens"}
    if token_doc.get("auto_import_enabled") is False:
        return {"status": "skipped", "reason": "disabled"}
    pwd = token_doc.get("cas_password", "")
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

    # Already-processed dedupe: skip rows that are completed OR currently
    # in-flight. We re-try ones that previously errored out — the user may
    # have updated their password since the last attempt.
    existing = await db.gmail_imports.find(
        {"user_id": user_id},
        {"_id": 0, "message_id": 1, "attachment_id": 1, "status": 1},
    ).to_list(500)
    skip_keys = {
        (e["message_id"], e.get("attachment_id"))
        for e in existing
        if e.get("status") in ("completed", "processing")
    }
    fresh = [
        e for e in emails
        if (e["message_id"], e.get("attachment_id")) not in skip_keys
    ]
    if not fresh:
        await db.gmail_tokens.update_one(
            {"user_id": user_id},
            {"$set": {"last_auto_import_at": datetime.now(timezone.utc).isoformat()}},
        )
        return {"status": "no_new_emails", "scanned": len(emails)}

    imported_ok = 0
    imported_fail = 0
    for email in fresh:
        attachment_id = email.get("attachment_id")
        message_id = email["message_id"]
        filename = email.get("filename") or "cas.pdf"
        if not attachment_id:
            continue
        try:
            content = download_attachment(service, message_id, attachment_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "auto_import: download failed for %s/%s: %s",
                user_id, message_id, e,
            )
            imported_fail += 1
            continue

        task_id = f"gmail_auto_{uuid.uuid4().hex[:12]}"
        await db.upload_tasks.insert_one({
            "task_id": task_id,
            "user_id": user_id,
            "status": "processing",
            "message": f"Auto-importing {filename}...",
            "count": 0,
            "holdings": [],
            "source": "gmail_auto",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await db.gmail_imports.update_one(
            {"user_id": user_id, "message_id": message_id, "attachment_id": attachment_id},
            {"$set": {
                "user_id": user_id,
                "message_id": message_id,
                "attachment_id": attachment_id,
                "filename": filename,
                "task_id": task_id,
                "status": "processing",
                "trigger": "auto",
                "imported_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )

        # Persist raw PDF to disk first (so a parse failure can be
        # diagnosed later without re-pulling from Gmail).
        try:
            file_id, file_path, file_sha256 = _persist_gmail_pdf(user_id, content, filename)
        except Exception as e:  # noqa: BLE001
            logger.warning("auto_import: persist failed for %s: %s", user_id, e)
            await db.upload_tasks.update_one(
                {"task_id": task_id},
                {"$set": {"status": "error", "message": f"persist failed: {e}"}},
            )
            imported_fail += 1
            continue
        await db.gmail_imports.update_one(
            {"user_id": user_id, "message_id": message_id, "attachment_id": attachment_id},
            {"$set": {
                "file_id": file_id, "file_path": file_path, "file_sha256": file_sha256,
            }},
        )

        # Parse + snapshot synchronously inside this scheduler tick.
        # Each CAS takes ~10-30s; serializing per user is fine because
        # the scheduler runs once a day and most users have 0-1 new
        # statements per run.
        try:
            await _process_gmail_cas_background(
                content, user_id, task_id, "", pwd,
                message_id, attachment_id, file_id, filename,
            )
            # Re-read the gmail_imports row to see the final status
            row = await db.gmail_imports.find_one(
                {"user_id": user_id, "message_id": message_id, "attachment_id": attachment_id},
                {"_id": 0, "status": 1},
            )
            if row and row.get("status") == "completed":
                imported_ok += 1
                logger.info(
                    "auto_import: imported %s for %s (%s)",
                    filename, user_id, file_id[:8],
                )
            else:
                imported_fail += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("auto_import: parse failed for %s/%s: %s", user_id, filename, e)
            imported_fail += 1

    await db.gmail_tokens.update_one(
        {"user_id": user_id},
        {"$set": {"last_auto_import_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {
        "status": "ok",
        "scanned": len(emails),
        "imported": imported_ok,
        "failed": imported_fail,
    }


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
