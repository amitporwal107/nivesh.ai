"""scripts/rotate_data_keys.py — RK-1..RK-4 (test_reports/prod_data_key_rotation_TESTCASES.md).

The Mongo passes (RK-5..RK-9) run against a real mongo:7 in the sandbox rehearsal of
deploy/cloudpe-prod/rotate-data-keys.sh, not here.
"""
from __future__ import annotations

import base64
import os

import pytest

from scripts import rotate_data_keys as rk
from services import pii_security

OLD = os.urandom(32)
NEW = os.urandom(32)
B64 = lambda k: base64.b64encode(k).decode()  # noqa: E731


def _pii_encrypt_with(monkeypatch, key: bytes, text: str) -> str:
    """Encrypt exactly as the backend does, under `key`."""
    monkeypatch.setattr(pii_security, "_cached_key", key)
    return pii_security.encrypt(text)


# RK-1
def test_rk1_round_trip_and_compatibility_with_pii_security(monkeypatch):
    stored = _pii_encrypt_with(monkeypatch, OLD, "ABCDE1234F")
    assert rk.open_with(OLD, stored) == "ABCDE1234F"
    assert rk.open_with(NEW, stored) is None
    moved = rk.rewrap("ABCDE1234F", False, NEW)
    assert moved != stored and rk.open_with(OLD, moved) is None
    monkeypatch.setattr(pii_security, "_cached_key", NEW)
    assert pii_security.decrypt(moved) == "ABCDE1234F"          # the app reads it with the new key


# RK-2
def test_rk2_classify_raw(monkeypatch):
    old_ct = _pii_encrypt_with(monkeypatch, OLD, "tok")
    new_ct = rk.seal_with(NEW, "tok")
    assert rk.classify(old_ct, False, OLD, NEW) == ("old", "tok")
    assert rk.classify(new_ct, False, OLD, NEW) == ("already_new", None)
    assert rk.classify("not-a-ciphertext", False, OLD, NEW) == ("undecryptable", None)
    assert rk.classify(rk.seal_with(os.urandom(32), "x"), False, OLD, NEW) == ("undecryptable", None)
    for v in ("", None, 42):
        assert rk.classify(v, False, OLD, NEW) == ("skipped", None)


# RK-3
def test_rk3_classify_sealed(monkeypatch):
    monkeypatch.setattr(pii_security, "_cached_key", OLD)
    sealed_old = pii_security.seal_field("ya29.refresh")
    assert sealed_old.startswith(rk.SEAL_PREFIX)
    kind, pt = rk.classify(sealed_old, True, OLD, NEW)
    assert (kind, pt) == ("old", "ya29.refresh")
    moved = rk.rewrap(pt, True, NEW)
    assert moved.startswith(rk.SEAL_PREFIX) and rk.classify(moved, True, OLD, NEW) == ("already_new", None)
    monkeypatch.setattr(pii_security, "_cached_key", NEW)
    assert pii_security.unseal_field(moved) == "ya29.refresh"
    assert rk.classify("legacy-plaintext-token", True, OLD, NEW) == ("plaintext", None)


# RK-4
@pytest.mark.parametrize("old, new, reason", [
    (None, B64(NEW), "OLD_PII_KEY is not set"),
    ("%%%not-base64%%%", B64(NEW), "not valid base64"),
    (base64.b64encode(b"short").decode(), B64(NEW), "decodes to 5 bytes"),
    (B64(OLD), B64(OLD), "the same key"),
])
def test_rk4_bad_keys_exit_2_without_printing_keys(monkeypatch, capsys, old, new, reason):
    monkeypatch.delenv("OLD_PII_KEY", raising=False)
    if old is not None:
        monkeypatch.setenv("OLD_PII_KEY", old)
    monkeypatch.setenv("NEW_PII_KEY", new)
    monkeypatch.setenv("MONGO_URL", "mongodb://unused:1")
    monkeypatch.setenv("DB_NAME", "unused")
    assert rk.main([]) == 2
    out = capsys.readouterr()
    assert reason in out.err
    for k in (B64(OLD), B64(NEW)):
        assert k not in out.out + out.err


def test_rk4_missing_mongo_settings_exit_2(monkeypatch, capsys):
    monkeypatch.setenv("OLD_PII_KEY", B64(OLD))
    monkeypatch.setenv("NEW_PII_KEY", B64(NEW))
    monkeypatch.delenv("MONGO_URL", raising=False)
    assert rk.main(["--verify"]) == 2
    assert "MONGO_URL and DB_NAME" in capsys.readouterr().err


# RK-8: compare-and-set — a value replaced between the read and the write is not overwritten.
class _Res:
    def __init__(self, n):
        self.modified_count = n


class _RacyCollection:
    """find() returns the rows; the first update_one finds the row already changed by someone else."""

    def __init__(self, docs, racer):
        self.docs, self.racer, self.raced = docs, racer, False

    def find(self, query, projection):
        field = next(iter(query))
        return [dict(d) for d in self.docs if isinstance(d.get(field), str) and d.get(field)]

    def update_one(self, flt, update):
        if not self.raced:
            self.raced = True
            self.racer(self.docs)
        for d in self.docs:
            if all(d.get(k) == v for k, v in flt.items()):
                d.update(update["$set"])
                return _Res(1)
        return _Res(0)


def test_rk8_compare_and_set_keeps_a_concurrent_write(monkeypatch):
    first = _pii_encrypt_with(monkeypatch, OLD, "t1")
    second = _pii_encrypt_with(monkeypatch, OLD, "t2")
    newer = rk.seal_with(NEW, "written-meanwhile")
    docs = [{"_id": 1, "token_enc": first}, {"_id": 2, "token_enc": second}]
    coll = _RacyCollection(docs, racer=lambda ds: ds[0].update(token_enc=newer))
    report = rk.run({"kite_platform_token": coll}, OLD, NEW, "apply", [("kite_platform_token", "token_enc", False)])
    assert report["kite_platform_token.token_enc"] == {"total": 2, "changed_concurrently": 1, "rotated": 1}
    assert docs[0]["token_enc"] == newer                       # the newer value was not overwritten
    assert rk.open_with(NEW, docs[1]["token_enc"]) == "t2"


def test_targets_cover_every_encrypting_call_site():
    """Every (collection, field) the backend encrypts with pii_security is a rotation target."""
    fields = {f"{c}.{f}" for c, f, _ in rk.TARGETS}
    assert {"users.pan_encrypted", "broker_accounts.api_key_encrypted", "broker_accounts.extras_encrypted",
            "kite_platform_token.token_enc", "gmail_tokens.access_token", "gmail_tokens.refresh_token",
            "user_profiles.pan_encrypted", "user_profiles.cas_pdf_password_encrypted"} <= fields
