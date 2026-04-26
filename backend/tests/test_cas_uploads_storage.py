"""Raw CAS PDF storage + MFD-side selective re-parse coverage.

Exercises the full lifecycle:
  1. MFD creates an invite for a profile
  2. Client (public, no auth) submits PAN + consents
  3. Client uploads a tiny PDF directly via /upload-pdf
  4. MFD lists CAS uploads for the profile + workspace-wide
  5. MFD re-parses with a custom password (pw hint reflects override)
  6. MFD downloads the original PDF (Content-Type: application/pdf)
  7. MFD deletes the stored copy (file vanishes, list empty)
"""
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://portfolio-pro-985.preview.emergentagent.com").rstrip("/")
PROFILE_ID = "1755a697-d386-4cf4-98ea-327961d823d3"  # AMIT PORWAL
SESSION_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"  # priyankamantri@gmail.com (MFD)


@pytest.fixture(scope="module")
def mfd():
    s = requests.Session()
    s.cookies.set("session_token", SESSION_TOKEN)
    return s


@pytest.fixture(scope="module")
def anon():
    return requests.Session()


@pytest.fixture(scope="module")
def fresh_invite(mfd):
    r = mfd.post(
        f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invite",
        json={"client_name": f"Storage Test {uuid.uuid4().hex[:6]}", "regenerate": True},
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text[:300]
    return r.json()["invite_token"]


@pytest.fixture(scope="module")
def details_submitted(anon, fresh_invite):
    r = anon.post(
        f"{BASE_URL}/api/public/cas-invite/{fresh_invite}/client-details",
        json={
            "name": "Storage Tester",
            "mobile": "9876543210",
            "email": "store-test@example.com",
            "pan": "ABCDE1234F",
            "consent_cas_access": True,
            "consent_gmail_access": False,
            "consent_advisor_access": True,
        },
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text[:300]
    return fresh_invite


@pytest.fixture(scope="module")
def uploaded_file_id(anon, details_submitted):
    """Upload a tiny dummy PDF via the public direct-upload route."""
    r = anon.post(
        f"{BASE_URL}/api/public/cas-invite/{details_submitted}/upload-pdf",
        files={"file": ("dummy.pdf", b"%PDF-1.4\nstub", "application/pdf")},
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["queued"] is True
    assert body["file_id"]
    # Wait a beat for the background parse to fail (it's a dummy PDF) so the
    # row settles into status=error before we exercise re-parse.
    time.sleep(2.5)
    return body["file_id"]


class TestPublicUpload:
    def test_upload_rejects_without_details(self, anon, mfd):
        # Issue a brand-new invite that has NO details captured yet
        r = mfd.post(
            f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-invite",
            json={"regenerate": True},
            headers={"Content-Type": "application/json"},
        )
        tok = r.json()["invite_token"]
        u = anon.post(
            f"{BASE_URL}/api/public/cas-invite/{tok}/upload-pdf",
            files={"file": ("x.pdf", b"%PDF-1.4\nx", "application/pdf")},
        )
        assert u.status_code == 400
        assert "PAN" in u.text

    def test_upload_rejects_non_pdf(self, anon, details_submitted):
        r = anon.post(
            f"{BASE_URL}/api/public/cas-invite/{details_submitted}/upload-pdf",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert r.status_code == 400
        assert "PDF" in r.text

    def test_upload_rejects_empty_file(self, anon, details_submitted):
        r = anon.post(
            f"{BASE_URL}/api/public/cas-invite/{details_submitted}/upload-pdf",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert r.status_code == 400


class TestMfdListUploads:
    def test_list_for_profile_includes_uploaded_file(self, mfd, uploaded_file_id):
        r = mfd.get(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-uploads")
        assert r.status_code == 200
        files = r.json()["files"]
        ids = [f["file_id"] for f in files]
        assert uploaded_file_id in ids
        row = next(f for f in files if f["file_id"] == uploaded_file_id)
        assert row["source"] == "upload"
        assert row["filename"] == "dummy.pdf"
        assert row["is_downloadable"] is True
        assert row["client_pan"] == "ABCDE1234F"
        # Server should never leak the file_path
        assert "file_path" not in row

    def test_list_workspace_wide(self, mfd, uploaded_file_id):
        r = mfd.get(f"{BASE_URL}/api/mfd/cas-uploads")
        assert r.status_code == 200
        ids = [f["file_id"] for f in r.json()["files"]]
        assert uploaded_file_id in ids

    def test_list_requires_auth(self, anon):
        r = anon.get(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-uploads")
        assert r.status_code == 401


class TestMfdReparseAndDownload:
    def test_reparse_with_custom_password_records_hint(self, mfd, uploaded_file_id):
        r = mfd.post(
            f"{BASE_URL}/api/mfd/cas-uploads/{uploaded_file_id}/reparse",
            json={"password": "MYCUSTOMPW"},
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200, r.text[:300]
        assert r.json()["status"] == "queued"
        time.sleep(2.5)

        r2 = mfd.get(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-uploads")
        row = next(f for f in r2.json()["files"] if f["file_id"] == uploaded_file_id)
        assert row["reparsed_by_mfd"] is True
        assert (row.get("reparse_count") or 0) >= 1
        # Hint must be a privacy-safe shortened form (first 2 + *** + last 1)
        assert row["last_password_hint"] and "***" in row["last_password_hint"]
        assert "MYCUSTOMPW" not in row["last_password_hint"]

    def test_reparse_unknown_file_returns_404(self, mfd):
        r = mfd.post(
            f"{BASE_URL}/api/mfd/cas-uploads/does-not-exist-xyz/reparse",
            json={"password": "anything"},
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 404

    def test_download_returns_pdf_content(self, mfd, uploaded_file_id):
        r = mfd.get(f"{BASE_URL}/api/mfd/cas-uploads/{uploaded_file_id}/download")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content.startswith(b"%PDF")

    def test_download_requires_auth(self, anon, uploaded_file_id):
        r = anon.get(f"{BASE_URL}/api/mfd/cas-uploads/{uploaded_file_id}/download")
        assert r.status_code == 401

    def test_delete_removes_row_and_file(self, mfd, uploaded_file_id):
        r = mfd.delete(f"{BASE_URL}/api/mfd/cas-uploads/{uploaded_file_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"
        # After delete, list should no longer include this file_id
        r2 = mfd.get(f"{BASE_URL}/api/mfd/profiles/{PROFILE_ID}/cas-uploads")
        ids = [f["file_id"] for f in r2.json()["files"]]
        assert uploaded_file_id not in ids
        # Download must now 404 (file gone, row gone)
        d = mfd.get(f"{BASE_URL}/api/mfd/cas-uploads/{uploaded_file_id}/download")
        assert d.status_code == 404
