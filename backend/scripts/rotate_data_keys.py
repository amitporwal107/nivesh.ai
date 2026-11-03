"""Re-encrypt every value written by services.pii_security from an OLD key to a NEW key.

Why: production was cloned from staging and kept staging's PII_ENCRYPTION_KEY so the cloned rows stayed
readable (deploy/cloudpe-prod/README.md). The owner asked on 2 Nov 2026 for prod to have its own key.
deploy/cloudpe-prod/rotate-data-keys.sh runs this with the backend STOPPED, so nothing is written with the
old key midway.

Self-contained on purpose: it does not import the backend (no cached key, no app start-up). It reads the
keys from the environment only, never from argv, and never prints a key or a value:

    OLD_PII_KEY, NEW_PII_KEY   base64 of 32 bytes each, exactly as PII_ENCRYPTION_KEY is set
    MONGO_URL, DB_NAME         the backend's own settings

    python rotate_data_keys.py            # dry run: count what would change, write nothing
    python rotate_data_keys.py --apply    # re-encrypt
    python rotate_data_keys.py --verify   # nothing may still open with OLD only

Per field it reports counts: total, already_new, to_rotate / rotated, changed_concurrently (the value changed
between read and write; the newer value is kept), plaintext (a sealed field holding legacy plaintext; left
as is), undecryptable (opens with neither key; left as is).

Exit status: 0 ok · 1 --verify found values still under OLD, or --apply could not finish them · 2 bad keys
or configuration. Idempotent: a second --apply finds everything already under NEW.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import sys
from collections import Counter
from typing import Dict, Iterable, Optional, Tuple

NONCE_BYTES = 12            # services.pii_security._NONCE_BYTES
KEY_BYTES = 32              # AES-256
SEAL_PREFIX = "enc:v1:"     # services.pii_security._SEAL_PREFIX

#: (collection, field, sealed). Every place the backend calls pii_security.encrypt / seal_field
#: (origin/main and origin/dev, 2 Nov 2026). Fields a database does not have are simply counted as 0.
TARGETS: Tuple[Tuple[str, str, bool], ...] = (
    ("users", "pan_encrypted", False),                     # routes/compliance.py
    ("broker_accounts", "api_key_encrypted", False),       # services/brokers/sessions.py
    ("broker_accounts", "extras_encrypted", False),
    ("kite_platform_token", "token_enc", False),           # services/kite_live_feed/platform_token.py
    ("user_profiles", "pan_encrypted", False),             # services/cas_secrets.py
    ("user_profiles", "cas_pdf_password_encrypted", False),
    ("gmail_tokens", "pan_encrypted", False),
    ("gmail_tokens", "cas_pdf_password_encrypted", False),
    ("gmail_tokens", "access_token", True),                # pii_security.seal_field (gmail_service et al.)
    ("gmail_tokens", "refresh_token", True),
)


class ConfigError(Exception):
    pass


def load_key(name: str) -> bytes:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        raise ConfigError(f"{name} is not set")
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise ConfigError(f"{name} is not valid base64") from None
    if len(key) != KEY_BYTES:
        raise ConfigError(f"{name} decodes to {len(key)} bytes, want {KEY_BYTES}")
    return key


def _aesgcm(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key)


def open_with(key: bytes, body: str) -> Optional[str]:
    """Plaintext of a base64(nonce||ct) body under `key`, or None."""
    try:
        blob = base64.b64decode(body, validate=True)
        if len(blob) <= NONCE_BYTES:
            return None
        return _aesgcm(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], None).decode("utf-8")
    except Exception:  # noqa: BLE001 — wrong key, tampered or not a ciphertext: all mean "does not open"
        return None


def seal_with(key: bytes, plaintext: str) -> str:
    nonce = os.urandom(NONCE_BYTES)
    return base64.b64encode(nonce + _aesgcm(key).encrypt(nonce, plaintext.encode("utf-8"), None)).decode("ascii")


def classify(value, sealed: bool, old: bytes, new: bytes) -> Tuple[str, Optional[str]]:
    """(kind, plaintext). kind: skipped | plaintext | already_new | undecryptable | old."""
    if not isinstance(value, str) or not value:
        return "skipped", None
    body = value
    if sealed:
        if not value.startswith(SEAL_PREFIX):
            return "plaintext", None
        body = value[len(SEAL_PREFIX):]
    if open_with(new, body) is not None:
        return "already_new", None
    plaintext = open_with(old, body)
    if plaintext is None:
        return "undecryptable", None
    return "old", plaintext


def rewrap(plaintext: str, sealed: bool, new: bytes) -> str:
    body = seal_with(new, plaintext)
    return SEAL_PREFIX + body if sealed else body


def run(db, old: bytes, new: bytes, mode: str, targets: Iterable[Tuple[str, str, bool]] = TARGETS) -> Dict[str, Dict[str, int]]:
    """mode: dry-run | apply | verify. Returns counts per "collection.field"."""
    report: Dict[str, Dict[str, int]] = {}
    for coll, field, sealed in targets:
        counts: Counter = Counter()
        for doc in db[coll].find({field: {"$type": "string", "$ne": ""}}, {"_id": 1, field: 1}):
            counts["total"] += 1
            kind, plaintext = classify(doc.get(field), sealed, old, new)
            if kind != "old":
                counts[kind] += 1
                continue
            if mode != "apply":
                counts["to_rotate"] += 1
                continue
            res = db[coll].update_one(
                {"_id": doc["_id"], field: doc[field]},          # compare-and-set: only if still the value read
                {"$set": {field: rewrap(plaintext, sealed, new)}},
            )
            counts["rotated" if res.modified_count else "changed_concurrently"] += 1
        report[f"{coll}.{field}"] = dict(counts)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="re-encrypt (default: dry run)")
    group.add_argument("--verify", action="store_true", help="fail if any value still opens with OLD only")
    args = ap.parse_args(argv)
    mode = "apply" if args.apply else "verify" if args.verify else "dry-run"
    try:
        old, new = load_key("OLD_PII_KEY"), load_key("NEW_PII_KEY")
        if old == new:
            raise ConfigError("OLD_PII_KEY and NEW_PII_KEY are the same key")
        url, name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
        if not url or not name:
            raise ConfigError("MONGO_URL and DB_NAME must be set")
    except ConfigError as e:
        print(f"rotate_data_keys: {e}", file=sys.stderr)
        return 2

    from pymongo import MongoClient
    client = MongoClient(url, serverSelectionTimeoutMS=10_000)
    report = run(client[name], old, new, mode)
    left = sum(c.get("to_rotate", 0) for c in report.values()) if mode != "apply" else 0
    print(json.dumps({"mode": mode, "db": name, "fields": report}, sort_keys=True))
    if mode == "verify" and left:
        print(f"rotate_data_keys: {left} value(s) still open with the OLD key only", file=sys.stderr)
        return 1
    if mode == "apply":
        # A value that changed under us is re-read by a second pass; anything still under OLD fails the run.
        again = run(client[name], old, new, "verify")
        left = sum(c.get("to_rotate", 0) for c in again.values())
        if left:
            print(f"rotate_data_keys: {left} value(s) still under OLD after apply — rerun --apply", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
