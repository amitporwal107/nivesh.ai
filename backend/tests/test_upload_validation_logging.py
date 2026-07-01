"""Regression test for the upload-validation logging crash (prod 500 on upload).

Root cause: the malware-scan step of ``validate_upload_async`` logged with
``extra={"filename": ...}``. ``filename`` is a *reserved* attribute on Python's
``logging.LogRecord``, so ``logging.makeRecord`` raised
``KeyError: "Attempt to overwrite 'filename' in LogRecord"``. Because one of the
three scan-branch log calls runs on EVERY upload (step 4), every request to
``/api/portfolio/upload`` returned an unhandled 500 — for all users, all file
types. Observed in prod (nivesh-app-vm) 2026-07-01 06:48:02 UTC.

These tests exercise all three scan branches (unavailable / clean / rejected)
and assert the logging call no longer raises. They deliberately do NOT require a
running ClamAV daemon or a live server — the scanner is stubbed.
"""
import asyncio
import os
import sys

import pytest

# Make ``helpers.*`` and ``services.*`` importable (backend/ is the import root,
# matching how the app runs: `from services.malware_scanner import scan`).
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from helpers import upload_validation  # noqa: E402
from services.malware_scanner import ScanResult  # noqa: E402

# A minimal, valid CSV so size/extension/magic checks (steps 1-3) pass and we
# reach the malware-scan log calls (step 4) that used to crash.
_CSV = b"symbol,qty\nRELIANCE,10\n"


def _stub_scan(result: ScanResult):
    async def _scan(content: bytes) -> ScanResult:
        return result
    return _scan


@pytest.mark.parametrize(
    "result",
    [
        # The exact prod condition: ClamAV not reachable -> MALWARE_SCAN_SKIP branch.
        ScanResult(clean=True, threat=None, scanner_available=False, bytes_scanned=len(_CSV)),
        # Clean scan -> MALWARE_SCAN_CLEAN branch (also passed "filename" in extra).
        ScanResult(clean=True, threat=None, scanner_available=True, bytes_scanned=len(_CSV)),
    ],
    ids=["clamav_unavailable", "clean_scan"],
)
def test_validate_upload_async_logs_without_crashing(monkeypatch, result):
    monkeypatch.setattr("services.malware_scanner.scan", _stub_scan(result))
    ext, mime = asyncio.run(upload_validation.validate_upload_async(_CSV, "portfolio.csv"))
    assert ext == ".csv"


def test_validate_upload_async_malware_rejected_is_422_not_500(monkeypatch):
    """Malware branch must log (without crashing) then raise a clean 422."""
    from fastapi import HTTPException

    bad = ScanResult(clean=False, threat="Eicar-Test-Signature",
                     scanner_available=True, bytes_scanned=len(_CSV))
    monkeypatch.setattr("services.malware_scanner.scan", _stub_scan(bad))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload_validation.validate_upload_async(_CSV, "portfolio.csv"))
    assert exc.value.status_code == 422
