"""Upload validation: size cap + MIME magic-byte sniffing + malware scan.

PRD references:
    FR-UPLOAD-001 — All uploads must pass MIME validation.
    FR-UPLOAD-005 — File size limits enforced.
    FR-UPLOAD-007 — Uploaded files must be scanned for malware before processing.

Pipeline (in order):
    1. Size cap (413)
    2. Extension allow-list (415)
    3. Magic-byte MIME check (415)
    4. ClamAV malware scan (422) — async; skipped with warning when ClamAV unavailable

We avoid pulling in libmagic / python-magic and instead inline the magic-byte
checks for the 3 file types the upload pipeline accepts (PDF, XLSX, CSV).
The magic-byte check happens before any parser touches the bytes — so a
`.pdf`-named file that's actually a renamed `.exe` or `.zip` is rejected
with 415 before pdfplumber ever sees it.

Use :func:`validate_upload_async` in async route handlers (runs malware scan).
Use :func:`validate_upload` for synchronous contexts (skips malware scan).
"""
from __future__ import annotations

import logging
import os
from typing import Tuple

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# 50 MB cap — CAS PDFs are typically 200KB-3MB; XLSX rarely > 5MB. 50MB
# leaves generous headroom for advisor batch sheets without enabling DoS.
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 50 * 1024 * 1024))

# Extension -> (expected MIME, magic-byte prefix tuple). We allow multiple
# prefixes per type (e.g. XLSX is OOXML/zip but legacy .xls is OLE2).
_MAGIC_TABLE: dict[str, tuple[str, tuple[bytes, ...]]] = {
    ".pdf": ("application/pdf", (b"%PDF-",)),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        (b"PK\x03\x04",),  # OOXML is a zip
    ),
    ".xls": (
        "application/vnd.ms-excel",
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),  # OLE2 compound document
    ),
    ".csv": ("text/csv", ()),  # CSV has no magic; sniff for printable text
}


def _ext(filename: str) -> str:
    """Return lowercased extension including the dot, or '' if none."""
    f = (filename or "").lower()
    idx = f.rfind(".")
    return f[idx:] if idx != -1 else ""


def _looks_like_text(blob: bytes, sample: int = 4096) -> bool:
    """Heuristic for CSV: first N bytes are mostly printable / UTF-8 decodable."""
    head = blob[:sample]
    if not head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        try:
            head.decode("latin-1")
        except UnicodeDecodeError:
            return False
    # Reject if too many control chars (anything < 0x20 except tab/lf/cr)
    bad = sum(1 for b in head if b < 0x20 and b not in (0x09, 0x0A, 0x0D))
    return bad / max(len(head), 1) < 0.05


def validate_upload(
    content: bytes,
    filename: str,
    *,
    allowed_exts: tuple[str, ...] = (".pdf", ".xlsx", ".xls", ".csv"),
) -> Tuple[str, str]:
    """Validate size and MIME magic. Returns (extension, sniffed_mime).

    Raises 413 if oversized, 415 if extension not allowed or magic mismatch.
    """
    size = len(content)
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size} bytes; cap {MAX_UPLOAD_BYTES}).",
        )

    ext = _ext(filename)
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {ext or 'no extension'}. "
                   f"Allowed: {', '.join(allowed_exts)}.",
        )

    expected_mime, prefixes = _MAGIC_TABLE.get(ext, ("", ()))

    if prefixes:
        if not any(content.startswith(p) for p in prefixes):
            logger.warning(
                "upload_mime_mismatch ext=%s declared=%s first_bytes=%s",
                ext, expected_mime, content[:8].hex(),
            )
            raise HTTPException(
                status_code=415,
                detail=f"File contents do not match {ext} signature.",
            )
    elif ext == ".csv":
        if not _looks_like_text(content):
            raise HTTPException(
                status_code=415,
                detail="CSV upload is not valid UTF-8 / latin-1 text.",
            )

    return ext, expected_mime


async def validate_upload_async(
    content: bytes,
    filename: str,
    *,
    allowed_exts: tuple[str, ...] = (".pdf", ".xlsx", ".xls", ".csv"),
) -> Tuple[str, str]:
    """Async version of :func:`validate_upload` that also runs a ClamAV scan.

    Call this from async route handlers instead of ``validate_upload`` to get
    malware scanning. Falls back gracefully when ClamAV is not installed.

    Raises:
        413 — file too large
        415 — bad extension or MIME mismatch
        422 — malware detected
    """
    # Step 1-3: size + extension + magic bytes (sync, fast)
    ext, mime = validate_upload(content, filename, allowed_exts=allowed_exts)

    # Step 4: malware scan (async, ClamAV)
    from services.malware_scanner import scan as _scan
    result = await _scan(content)

    if not result.scanner_available:
        logger.warning(
            "Malware scan skipped — ClamAV unavailable",
            extra={
                "eventType": "MALWARE_SCAN_SKIP",
                # NB: key must not be "filename" — that's a reserved LogRecord
                # attribute and passing it in extra raises KeyError, which turned
                # this benign warning into an unhandled 500 on every upload.
                "upload_filename": filename,
                "bytes": len(content),
            },
        )
    elif not result.clean:
        logger.error(
            "Upload rejected — malware detected: %s in %s",
            result.threat, filename,
            extra={
                "eventType": "MALWARE_REJECTED",
                "upload_filename": filename,
                "threat": result.threat,
                "bytes": len(content),
            },
        )
        raise HTTPException(
            status_code=422,
            detail=f"File rejected: malware detected ({result.threat}). "
                   "Do not retry with the same file.",
        )
    else:
        logger.info(
            "Malware scan clean: %s (%d bytes)",
            filename, len(content),
            extra={"eventType": "MALWARE_SCAN_CLEAN", "upload_filename": filename, "bytes": len(content)},
        )

    return ext, mime
