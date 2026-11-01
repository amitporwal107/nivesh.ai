"""Compliance P0 data check against a REAL MongoDB (TC-13, TC-16). Not collected by pytest.

Seeds synthetic rows in the old (plaintext) and new (encrypted) shapes, then checks with real Mongo
queries: the daily Gmail sweep's selection, the backfill's dry run, its apply, its idempotence, and
that every secret still unlocks. Synthetic values only; prints counts and pass/fail, never a value.

  docker network create cp0 && docker run -d --name cp0-mongo --network cp0 mongo:7
  docker run --rm --network cp0 -v <worktree>:/work:ro -w /work/backend \
      -e MONGO_URL=mongodb://cp0-mongo:27017 -e DB_NAME=compliance_p0_check -e OPENAI_API_KEY=x \
      nivesh/backend:staging python tests/compliance_p0_mongo_check.py
"""
from __future__ import annotations

import asyncio
import copy
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deps import db  # noqa: E402  (MONGO_URL / DB_NAME from the environment)
from scripts.encrypt_cas_secrets import backfill  # noqa: E402
from services import cas_secrets, gmail_auto_import, pii_security  # noqa: E402

PAN_A, PAN_B, PAN_C, PAN_D = "AAAAA1111A", "BBBBB2222B", "CCCCC3333C", "DDDDD4444D"
results = []


def check(name, ok):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name)


async def seed():
    await db.user_profiles.delete_many({})
    await db.gmail_tokens.delete_many({})
    new_c = cas_secrets.pan_fields(PAN_C)
    await db.user_profiles.insert_many([
        {"user_id": "u1", "pan": PAN_A, "cas_password": PAN_A},              # legacy PAN
        {"user_id": "u2", "cas_pdf_password": "Custom-Pw-2"},                # legacy statement password only
        {"user_id": "u3", **new_c, "cas_password": "ZZZZZ9999Z"},            # new + stale legacy copy
        {"user_id": "u4", "name": "no secrets"},
        {"user_id": "u5", "pan": PAN_B, "cas_pdf_password": "Custom-Pw-5"},  # legacy both
    ])
    await db.gmail_tokens.insert_many([
        {"user_id": "u1", "cas_password": PAN_A, "auto_import_enabled": True},
        {"user_id": "u2", "cas_pdf_password": "Custom-Pw-2", "auto_import_enabled": True},  # no PAN → not swept (as before)
        {"user_id": "u5", "cas_password": PAN_B, "auto_import_enabled": False},              # disabled
        {"user_id": "u6", **cas_secrets.pan_fields(PAN_D)},                                  # new shape, flag absent
    ])


async def swept_users():
    seen = []

    async def record(_db, user_id):
        seen.append(user_id)
        return {"status": "skipped"}

    real = gmail_auto_import.auto_import_for_user
    gmail_auto_import.auto_import_for_user = record
    try:
        await gmail_auto_import.auto_import_all_users()
    finally:
        gmail_auto_import.auto_import_for_user = real
    return sorted(seen)


async def snapshot():
    out = []
    for name in ("user_profiles", "gmail_tokens"):
        out.append(await db[name].find({}, {"_id": 0}).sort("user_id", 1).to_list(100))
    return out


async def main():
    await seed()
    check("TC-13 sweep selects legacy-PAN and encrypted-PAN rows, skips disabled / no-PAN (before backfill)",
          await swept_users() == ["u1", "u6"])

    before = await snapshot()
    dry = await backfill(db, apply=False)
    check("TC-16 dry run finds 4 profile rows and 3 token rows with plaintext",
          dry["user_profiles"]["plaintext_rows"] == 4 and dry["gmail_tokens"]["plaintext_rows"] == 3)
    check("TC-16 dry run writes nothing", await snapshot() == before and dry["user_profiles"]["updated"] == 0)

    applied = await backfill(db, apply=True)
    check("TC-16 apply updates 4 + 3 rows and leaves 0 plaintext rows",
          applied["user_profiles"]["updated"] == 4 and applied["gmail_tokens"]["updated"] == 3
          and applied["user_profiles"]["plaintext_rows_left"] == 0 and applied["gmail_tokens"]["plaintext_rows_left"] == 0)

    leaked = await db.user_profiles.count_documents({"$or": [{f: {"$exists": True}} for f in cas_secrets.LEGACY_FIELDS]})
    leaked += await db.gmail_tokens.count_documents({"$or": [{f: {"$exists": True}} for f in cas_secrets.LEGACY_FIELDS]})
    check("TC-16 a direct Mongo count finds 0 plaintext fields in both collections", leaked == 0)

    rows = {d["user_id"]: d for d in await db.user_profiles.find({}, {"_id": 0}).to_list(100)}
    toks = {d["user_id"]: d for d in await db.gmail_tokens.find({}, {"_id": 0}).to_list(100)}
    raw = repr(rows) + repr(toks)
    check("TC-16 no synthetic secret appears in clear text anywhere",
          not any(v in raw for v in (PAN_A, PAN_B, PAN_C, PAN_D, "ZZZZZ9999Z", "Custom-Pw-2", "Custom-Pw-5")))
    check("TC-16 ciphertexts decrypt to the originals",
          pii_security.decrypt(rows["u1"]["pan_encrypted"]) == PAN_A
          and pii_security.decrypt(rows["u2"]["cas_pdf_password_encrypted"]) == "Custom-Pw-2"
          and pii_security.decrypt(rows["u5"]["pan_encrypted"]) == PAN_B
          and pii_security.decrypt(rows["u5"]["cas_pdf_password_encrypted"]) == "Custom-Pw-5"
          and pii_security.decrypt(toks["u1"]["pan_encrypted"]) == PAN_A)
    check("TC-16 an existing encrypted value is kept over a stale plaintext copy",
          pii_security.decrypt(rows["u3"]["pan_encrypted"]) == PAN_C)
    check("TC-16 unlock passwords after backfill: custom beats PAN, PAN otherwise",
          cas_secrets.unlock_password(toks.get("u1"), rows["u1"]) == PAN_A
          and cas_secrets.unlock_password(toks.get("u2"), rows["u2"]) == "Custom-Pw-2"
          and cas_secrets.unlock_password(toks.get("u5"), rows["u5"]) == "Custom-Pw-5"
          and cas_secrets.unlock_password(rows["u4"]) == "")
    check("TC-13 sweep selection unchanged after backfill", await swept_users() == ["u1", "u6"])

    again = await backfill(db, apply=True)
    check("TC-16 second apply is a no-op", again["user_profiles"]["plaintext_rows"] == 0
          and again["gmail_tokens"]["plaintext_rows"] == 0)

    passed = sum(ok for _, ok in results)
    print(f"{passed}/{len(results)} checks passed")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
