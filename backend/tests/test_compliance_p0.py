"""Compliance P0 (test_reports/compliance_p0_TESTCASES.md).

TC-4/5  the 5paisa adapter refuses a password/TOTP sign-in and stays off the connectable list.
TC-6/7/8 services.cas_secrets: encryption, unlock precedence, the backfill update.
TC-9..12, 14 the onboarding / Gmail routes store the PAN and statement password encrypted, never in the clear.
TC-15   with no encryption key outside dev, nothing is stored (and nothing in the clear).

The backfill script and the daily sweep's selection run against a real MongoDB in
tests/compliance_p0_mongo_check.py (TC-13, TC-16), not here.
"""
from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest
from starlette.datastructures import UploadFile

from routes import gmail as gmail_route
from routes import onboarding_gmail as route
from services import cas_secrets, pii_security
from services.brokers import fivepaisa, registry
from tests.test_cas_import_all_fakes import FakeDb

UID = "user_compliance_p0"
PAN = "ABCDE1234F"
PLAINTEXT = ("pan", "cas_password", "cas_pdf_password")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(route, "db", fake)

    async def current_user(_request):
        return {"user_id": UID}

    monkeypatch.setattr(route, "get_current_user", current_user)
    return fake


def _profile(db):
    return next(d for d in db.user_profiles.docs if d.get("user_id") == UID)


def _token(db):
    return next(d for d in db.gmail_tokens.docs if d.get("user_id") == UID)


def _no_plaintext(doc):
    leaked = [k for k in PLAINTEXT if k in doc]
    assert not leaked, f"plaintext fields stored: {leaked}"
    assert PAN not in repr(doc), "the PAN appears in clear text in the stored row"


# ── TC-4 / TC-5: 5paisa ──────────────────────────────────────────────────
def test_tc4_fivepaisa_refuses_password_and_totp(monkeypatch):
    called = []
    monkeypatch.setattr(fivepaisa, "require_sdk", lambda *a, **k: called.append("sdk") or SimpleNamespace())
    code = '{"client_code": "12345678", "password": "hunter2", "totp": "123456"}'
    with pytest.raises(RuntimeError) as err:
        run(fivepaisa.exchange_code(code=code, state="s", redirect_uri="https://x/cb"))
    assert "never accepts broker credentials" in str(err.value)
    assert "hunter2" not in str(err.value) and "123456" not in str(err.value)
    assert called == [], "the 5paisa SDK must not be touched"


def test_tc5_fivepaisa_is_not_connectable_even_when_configured(monkeypatch):
    monkeypatch.setattr(registry, "missing_secrets", lambda slug: [])
    row = next(r for r in registry.list_supported() if r["slug"] == "fivepaisa")
    assert row["auth_style"] == "form" and row["connectable"] is False


# ── TC-6: encryption ─────────────────────────────────────────────────────
def test_tc6_pan_and_password_fields_are_ciphertext():
    f = cas_secrets.pan_fields(" abcde1234f ")
    assert set(f) == {"pan_encrypted", "pan_last4"} and f["pan_last4"] == "1234"
    assert PAN not in f["pan_encrypted"] and pii_security.decrypt(f["pan_encrypted"]) == PAN
    # a non-PAN-shaped legacy value is still encrypted, but no last-4 is derived from it
    assert set(cas_secrets.pan_fields("short")) == {"pan_encrypted"}
    p = cas_secrets.pdf_password_fields("Custom-Pw-1")
    assert set(p) == {"cas_pdf_password_encrypted"}
    assert pii_security.decrypt(p["cas_pdf_password_encrypted"]) == "Custom-Pw-1"  # verbatim, case kept
    for bad in ("", "   "):
        with pytest.raises(ValueError):
            cas_secrets.pan_fields(bad)
        with pytest.raises(ValueError):
            cas_secrets.pdf_password_fields(bad)


# ── TC-7: unlock precedence ──────────────────────────────────────────────
def test_tc7_unlock_password_precedence():
    enc_pan = cas_secrets.pan_fields(PAN)
    enc_pw = cas_secrets.pdf_password_fields("Custom-Pw-1")
    assert cas_secrets.unlock_password({**enc_pan, **enc_pw}) == "Custom-Pw-1"       # custom beats PAN
    assert cas_secrets.unlock_password(enc_pan, {"cas_pdf_password": "Legacy-Pw"}) == "Legacy-Pw"  # in any row
    assert cas_secrets.unlock_password(enc_pan, {"pan": "ZZZZZ9999Z"}) == PAN          # first row's PAN wins
    assert cas_secrets.unlock_password({"cas_password": "abcde1234f"}) == PAN          # legacy mirror, upper-cased
    assert cas_secrets.unlock_password({}, None) == ""
    # an undecryptable value does not crash and is treated as absent, so the next row's PAN is used
    assert cas_secrets.unlock_password({"pan_encrypted": "not-a-ciphertext"}, {"pan": PAN}) == PAN


# ── TC-8: the backfill update ────────────────────────────────────────────
def test_tc8_legacy_update():
    upd = cas_secrets.legacy_update({"pan": PAN, "cas_password": PAN, "cas_pdf_password": "Custom-Pw-1"})
    assert set(upd["$unset"]) == {"pan", "cas_password", "cas_pdf_password"}
    assert pii_security.decrypt(upd["$set"]["pan_encrypted"]) == PAN
    assert pii_security.decrypt(upd["$set"]["cas_pdf_password_encrypted"]) == "Custom-Pw-1"
    keep = cas_secrets.pan_fields(PAN)
    upd2 = cas_secrets.legacy_update({**keep, "cas_password": "ZZZZZ9999Z"})
    assert upd2 == {"$unset": {"cas_password": ""}}, "an existing encrypted value is kept, the copy only removed"
    assert cas_secrets.legacy_update({**keep}) is None
    assert cas_secrets.legacy_update({"user_id": "u"}) is None


# ── TC-9: POST /api/onboarding/pan ───────────────────────────────────────
def test_tc9_save_pan_stores_ciphertext_only(db):
    db.user_profiles.docs.append({"user_id": UID, "pan": "OLDPN0000X", "cas_password": "OLDPN0000X"})
    db.gmail_tokens.docs.append({"user_id": UID, "cas_password": "OLDPN0000X"})
    out = run(route.save_pan(route.PanInput(pan="abcde1234f"), request=None))
    assert out == {"ok": True}
    for doc in (_profile(db), _token(db)):
        _no_plaintext(doc)
        assert "OLDPN0000X" not in repr(doc)
        assert pii_security.decrypt(doc["pan_encrypted"]) == PAN and doc["pan_last4"] == "1234"


# ── TC-10: POST /api/onboarding/cas-password ─────────────────────────────
def test_tc10_save_statement_password_stores_ciphertext_only(db):
    db.gmail_tokens.docs.append({"user_id": UID, "cas_pdf_password": "Old-Pw"})
    run(route.save_cas_password(route.CasPasswordInput(password="Custom-Pw-1"), request=None))
    for doc in (_profile(db), _token(db)):
        assert "cas_pdf_password" not in doc and "Custom-Pw-1" not in repr(doc) and "Old-Pw" not in repr(doc)
        assert pii_security.decrypt(doc["cas_pdf_password_encrypted"]) == "Custom-Pw-1"


# ── TC-11: CAS upload with an inline secret ──────────────────────────────
@pytest.mark.parametrize("supplied, expected_unlock, field", [
    ("abcde1234f", PAN, "pan_encrypted"),
    ("Custom-Pw-1", "Custom-Pw-1", "cas_pdf_password_encrypted"),
])
def test_tc11_upload_inline_secret_is_encrypted_and_still_unlocks(db, monkeypatch, supplied, expected_unlock, field):
    seen = {}

    async def fake_import(user_id, content, pan, filename):
        seen["unlock"] = pan
        return {"ok": True}

    monkeypatch.setattr(route, "import_cas_pdf_for_user", fake_import)
    monkeypatch.setattr(route, "validate_upload", lambda content, filename: None)
    upload = UploadFile(file=io.BytesIO(b"%PDF-1.4 test"), filename="cas.pdf")
    run(route.upload_cas_pdf(request=None, file=upload, password=supplied))
    assert seen["unlock"] == expected_unlock
    doc = _profile(db)
    _no_plaintext(doc)
    assert supplied not in repr(doc) and expected_unlock not in repr(doc)
    assert pii_security.decrypt(doc[field]) == expected_unlock


# ── TC-12 / TC-14: presence flags read the encrypted fields ──────────────
def test_tc12_pan_on_file_and_tc14_auto_import_ready():
    enc = cas_secrets.pan_fields(PAN)
    assert cas_secrets.has_pan(enc) and cas_secrets.has_pan({"cas_password": PAN}) and cas_secrets.has_pan({"pan": PAN})
    assert not cas_secrets.has_pan({}) and not cas_secrets.has_pan(cas_secrets.pdf_password_fields("x"))
    src = open(route.__file__).read() + open(gmail_route.__file__).read()
    assert '"pan_on_file": cas_secrets.has_pan(profile)' in src
    assert '"auto_import_ready": cas_secrets.has_pan(token_doc)' in src


# ── TC-15: no key outside dev → nothing stored ───────────────────────────
def test_tc15_no_key_outside_dev_stores_nothing(db, monkeypatch):
    monkeypatch.setattr(pii_security, "_cached_key", None)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("PII_ENCRYPTION_KEY", raising=False)
    from helpers import secrets as app_secrets
    monkeypatch.setattr(app_secrets, "get", lambda *a, **k: None, raising=False)
    with pytest.raises(RuntimeError):
        run(route.save_pan(route.PanInput(pan=PAN), request=None))
    assert db.user_profiles.docs == [] and db.gmail_tokens.docs == []
