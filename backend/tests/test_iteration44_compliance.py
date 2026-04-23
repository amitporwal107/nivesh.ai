"""Iteration 44 — DPDP compliance + category rank backend tests."""
import os, base64, requests, pytest, asyncio

BASE = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
COOKIE = {"session_token": "370eff71-fda1-46d8-b506-b81b894d634f"}


def _c():
    s = requests.Session(); s.cookies.update(COOKIE); return s


class TestConsents:
    def test_list_5_purposes(self):
        r = _c().get(f"{BASE}/api/compliance/consents"); assert r.status_code == 200
        items = r.json()["consents"]
        purposes = {i["purpose"] for i in items}
        assert purposes == {"data_processing","advice_ai","scraping_fetch","marketing_comms","partner_sharing"}
        req = [i for i in items if i["required"]]
        assert len(req) == 1 and req[0]["purpose"] == "data_processing"

    def test_grant_data_processing_then_marketing(self):
        s = _c()
        r1 = s.post(f"{BASE}/api/compliance/consents/data_processing"); assert r1.status_code == 200
        r2 = s.post(f"{BASE}/api/compliance/consents/marketing_comms"); assert r2.status_code == 200
        lst = s.get(f"{BASE}/api/compliance/consents").json()["consents"]
        mc = next(i for i in lst if i["purpose"] == "marketing_comms")
        assert mc["status"] == "granted"

    def test_withdraw_marketing_then_required_blocked(self):
        s = _c()
        s.post(f"{BASE}/api/compliance/consents/marketing_comms")
        r = s.delete(f"{BASE}/api/compliance/consents/marketing_comms"); assert r.status_code == 200
        lst = s.get(f"{BASE}/api/compliance/consents").json()["consents"]
        mc = next(i for i in lst if i["purpose"] == "marketing_comms")
        assert mc["status"] == "withdrawn"
        rbad = s.delete(f"{BASE}/api/compliance/consents/data_processing")
        assert rbad.status_code == 400 and "cannot_withdraw_required" in rbad.json()["detail"]


class TestPAN:
    def test_invalid_pan(self):
        s = _c(); s.post(f"{BASE}/api/compliance/consents/data_processing")
        r = s.put(f"{BASE}/api/compliance/pan", json={"pan": "BADPAN"})
        assert r.status_code == 400 and "invalid_pan" in r.json()["detail"]

    def test_set_get_delete_pan(self):
        s = _c(); s.post(f"{BASE}/api/compliance/consents/data_processing")
        r = s.put(f"{BASE}/api/compliance/pan", json={"pan": "ABCDE1234F", "password": "abc"})
        assert r.status_code == 200
        j = r.json(); assert j["ok"] is True and j["masked"] == "XXXXX1234X"
        g = s.get(f"{BASE}/api/compliance/pan").json()
        assert g["has_pan"] is True and g["masked"] == "XXXXX1234X"
        assert "pan" not in g and "plaintext" not in str(g).lower()
        # Delete
        d = s.delete(f"{BASE}/api/compliance/pan"); assert d.status_code == 200
        g2 = s.get(f"{BASE}/api/compliance/pan").json()
        assert g2["has_pan"] is False


class TestEncryptRoundtrip:
    def test_roundtrip(self):
        import sys; sys.path.insert(0, "/app/backend")
        from services import pii_security as p
        assert p.decrypt(p.encrypt("ABCDE1234F")) == "ABCDE1234F"
        assert p.encrypt(None) == ""
        assert p.decrypt("") is None
        assert p.decrypt(p.encrypt("!@#$%^&*()")) == "!@#$%^&*()"


class TestDBEncryption:
    def test_db_stores_ciphertext_not_plain(self):
        import sys; sys.path.insert(0, "/app/backend")
        from deps import db
        s = _c(); s.post(f"{BASE}/api/compliance/consents/data_processing")
        s.put(f"{BASE}/api/compliance/pan", json={"pan": "ABCDE1234F"})

        async def check():
            return await db.users.find_one({"user_id": "user_f087c6332922"}, {"_id": 0})

        doc = asyncio.run(check())
        assert doc is not None
        assert "ABCDE1234F" not in str(doc)
        assert doc.get("pan_encrypted") and len(doc["pan_encrypted"]) >= 30
        assert doc.get("pan_last4") == "1234"


class TestAudit:
    def test_audit_trail_has_actions(self):
        s = _c()
        s.post(f"{BASE}/api/compliance/consents/data_processing")
        s.put(f"{BASE}/api/compliance/pan", json={"pan": "ABCDE1234F", "password": "secret"})
        s.get(f"{BASE}/api/compliance/pan")
        r = s.get(f"{BASE}/api/compliance/audit"); assert r.status_code == 200
        rows = r.json()["rows"]
        actions = {row["action"] for row in rows}
        assert {"consent_grant", "pan_update", "pan_view"}.issubset(actions)
        # Audit sanitisation: find any pan_update row and check details don't contain plaintext
        pan_updates = [r for r in rows if r["action"] == "pan_update"]
        for row in pan_updates:
            assert "ABCDE1234F" not in str(row)
            # if password key present, must be redacted
            det = row.get("details") or {}
            if "password" in det:
                assert det["password"] == "[REDACTED]"


class TestExport:
    def test_export_masks_pan(self):
        s = _c(); s.post(f"{BASE}/api/compliance/consents/data_processing")
        s.put(f"{BASE}/api/compliance/pan", json={"pan": "ABCDE1234F"})
        r = s.get(f"{BASE}/api/compliance/export"); assert r.status_code == 200
        data = r.json()
        assert "user" in data and "holdings" in data and "consents" in data
        u = data["user"]
        assert u.get("pan_masked") == "XXXXX1234X"
        assert "pan_encrypted" not in u
        assert "ABCDE1234F" not in str(data)


class TestConsentWithdrawFix:
    """Iteration 45: verify the consent grant/withdraw/regrant read-consistency
    fix in services/consents.py::current_for_user."""

    @staticmethod
    def _pym():
        import os
        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
        db_name = os.environ.get("DB_NAME") or "nivesh"
        return MongoClient(mongo_url)[db_name]

    def test_grant_withdraw_regrant_partner_sharing(self):
        pdb = self._pym()
        s = _c()
        s.post(f"{BASE}/api/compliance/consents/data_processing")

        def count_rows():
            return pdb.consent_records.count_documents(
                {"user_id": "user_f087c6332922", "purpose": "partner_sharing"}
            )

        base = count_rows()
        # Grant 1
        r1 = s.post(f"{BASE}/api/compliance/consents/partner_sharing"); assert r1.status_code == 200
        lst = s.get(f"{BASE}/api/compliance/consents").json()["consents"]
        ps = next(i for i in lst if i["purpose"] == "partner_sharing")
        assert ps["status"] == "granted", f"expected granted got {ps}"
        assert count_rows() == base + 1

        # Withdraw → read should immediately flip to withdrawn
        r2 = s.delete(f"{BASE}/api/compliance/consents/partner_sharing"); assert r2.status_code == 200
        lst = s.get(f"{BASE}/api/compliance/consents").json()["consents"]
        ps = next(i for i in lst if i["purpose"] == "partner_sharing")
        assert ps["status"] == "withdrawn", f"expected withdrawn got {ps}"
        assert count_rows() == base + 2

        # Regrant → flips back to granted
        r3 = s.post(f"{BASE}/api/compliance/consents/partner_sharing"); assert r3.status_code == 200
        lst = s.get(f"{BASE}/api/compliance/consents").json()["consents"]
        ps = next(i for i in lst if i["purpose"] == "partner_sharing")
        assert ps["status"] == "granted"
        assert count_rows() == base + 3

    def test_event_ts_populated_on_both_paths(self):
        """New rows must carry event_ts on both grant and withdraw."""
        pdb = self._pym()
        s = _c()
        s.post(f"{BASE}/api/compliance/consents/marketing_comms")
        s.delete(f"{BASE}/api/compliance/consents/marketing_comms")

        rows = list(
            pdb.consent_records.find(
                {"user_id": "user_f087c6332922", "purpose": "marketing_comms"},
                {"_id": 0},
            ).sort("event_ts", -1).limit(2)
        )
        assert len(rows) >= 2
        for r in rows:
            assert r.get("event_ts"), f"event_ts missing in row {r}"

    def test_legacy_row_coalesce_fallback(self):
        """Insert a legacy-shaped row WITHOUT event_ts, ensure reader still
        picks the right latest status via coalesce(granted_at/withdrawn_at).
        Uses pymongo seed + API GET to avoid motor event-loop issues."""
        import uuid
        pdb = self._pym()
        s = _c()
        # Pick a non-required purpose; purge priyanka's rows for it, seed 2
        # legacy rows (no event_ts), call API, then restore.
        user_id = "user_f087c6332922"
        purpose = "scraping_fetch"
        # Save existing rows to restore afterwards
        saved = list(pdb.consent_records.find(
            {"user_id": user_id, "purpose": purpose}
        ))
        try:
            pdb.consent_records.delete_many({"user_id": user_id, "purpose": purpose})
            # Legacy grant (older) — no event_ts
            pdb.consent_records.insert_one({
                "consent_id": f"cns_{uuid.uuid4().hex[:12]}",
                "user_id": user_id,
                "purpose": purpose,
                "version": "1.0",
                "status": "granted",
                "granted_at": "2025-01-01T00:00:00+00:00",
                "withdrawn_at": None,
            })
            # Legacy withdraw (newer) — no event_ts
            pdb.consent_records.insert_one({
                "consent_id": f"cns_{uuid.uuid4().hex[:12]}",
                "user_id": user_id,
                "purpose": purpose,
                "version": "1.0",
                "status": "withdrawn",
                "granted_at": None,
                "withdrawn_at": "2025-06-01T00:00:00+00:00",
            })
            lst = s.get(f"{BASE}/api/compliance/consents").json()["consents"]
            row = next(i for i in lst if i["purpose"] == purpose)
            assert row["status"] == "withdrawn", (
                f"coalesce fallback failed — expected withdrawn, got {row}"
            )
        finally:
            pdb.consent_records.delete_many({"user_id": user_id, "purpose": purpose})
            if saved:
                for doc in saved:
                    doc.pop("_id", None)
                pdb.consent_records.insert_many(saved)


class TestCategoryRank:
    def test_holdings_enriched_has_cat_rank(self):
        r = _c().get(f"{BASE}/api/portfolio/holdings-enriched"); assert r.status_code == 200
        mf = [h for h in r.json()["holdings"] if h.get("asset_type") in ("mutual_fund", "etf")]
        ranked = [h for h in mf if h.get("category_rank") is not None and h.get("category_rank_total") is not None]
        assert len(ranked) >= 1
        for h in ranked:
            assert isinstance(h["category_rank"], int) and h["category_rank"] >= 1
            assert isinstance(h["category_rank_total"], int)
            assert h["category_rank"] <= h["category_rank_total"]
