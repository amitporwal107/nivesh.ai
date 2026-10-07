"""POST /api/internal/event-ai-analysis/bulk — auth, validation, idempotent upsert, stats.

deps.db is replaced by an in-memory fake, so these run without Mongo."""
import sys, types
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeCol:
    def __init__(self):
        self.docs, self.indexes = {}, []

    async def bulk_write(self, ops, ordered=False):
        up = mod = mat = 0
        for op in ops:
            _id = op._filter["_id"]
            if _id in self.docs:
                mat += 1; mod += int(self.docs[_id] != op._doc)
            else:
                up += 1
            self.docs[_id] = op._doc
        return types.SimpleNamespace(upserted_count=up, modified_count=mod, matched_count=mat)

    async def create_index(self, keys):
        self.indexes.append(keys)

    async def count_documents(self, q):
        return len(self.docs)

    def aggregate(self, pipeline):
        from collections import Counter
        c = Counter((d.get("mode"), d.get("model_tag"), d.get("net_band")) for d in self.docs.values())
        rows = [{"_id": {"mode": m, "model": t, "band": b}, "n": n} for (m, t, b), n in c.items()]

        class Cur:
            async def to_list(self, n):
                return rows
        return Cur()


@pytest.fixture
def env(monkeypatch):
    col = FakeCol()
    fake_deps = types.ModuleType("deps"); fake_deps.db = {"event_ai_analysis": col}
    monkeypatch.setitem(sys.modules, "deps", fake_deps)
    sys.modules.pop("routes.event_ai_ingest", None)
    import routes.event_ai_ingest as R
    from helpers import secrets as S
    monkeypatch.setattr(S, "get", lambda k: {"EVENT_AI_INGEST_KEY": "test-key"}.get(k, ""))
    app = FastAPI(); app.include_router(R.router)
    return TestClient(app), col, R, S, monkeypatch


def doc(i="NSE_ANN:abc:a52e697b2354:sonnet-5", **kw):
    d = {"_id": i, "announcement_id": "abc", "source": "NSE_ANN", "prompt_sha256": "a52e697b2354ff",
         "symbol": "WELCORP", "event_ts": {"$date": "2026-09-25T08:28:52+05:30"},
         "analyzed_at": "2026-09-29T17:00:00+05:30", "mode": "batch50_compact", "model_tag": "sonnet-5",
         "net_band": "slightly_positive", "analysis": {"t": "ORDER / CONTRACT"}}
    d.update(kw)
    return d


URL = "/api/internal/event-ai-analysis/bulk"
H = {"X-Event-AI-Key": "test-key"}


def test_disabled_when_secret_unset(env):
    client, col, R, S, mp = env
    mp.setattr(S, "get", lambda k: "")
    assert client.post(URL, json={"docs": [doc()]}, headers=H).status_code == 503
    assert col.docs == {}


@pytest.mark.parametrize("headers", [{}, {"X-Event-AI-Key": "wrong"}])
def test_rejects_missing_or_wrong_key(env, headers):
    client, col, *_ = env
    assert client.post(URL, json={"docs": [doc()]}, headers=headers).status_code == 401
    assert col.docs == {}


def test_upsert_is_idempotent_and_dates_become_datetimes(env):
    client, col, *_ = env
    r1 = client.post(URL, json={"docs": [doc()]}, headers=H).json()
    r2 = client.post(URL, json={"docs": [doc()]}, headers=H).json()
    assert (r1["upserted"], r2["upserted"], r2["matched"]) == (1, 0, 1)
    stored = col.docs["NSE_ANN:abc:a52e697b2354:sonnet-5"]
    assert isinstance(stored["event_ts"], datetime) and stored["event_ts"].utcoffset().total_seconds() == 19800
    assert isinstance(stored["analyzed_at"], datetime)


def test_other_model_sits_beside_not_over(env):
    client, col, *_ = env
    client.post(URL, json={"docs": [doc(), doc(i="NSE_ANN:abc:a52e697b2354:opus", model_tag="opus")]}, headers=H)
    assert len(col.docs) == 2


def test_bad_docs_rejected_individually_good_ones_written(env):
    client, col, *_ = env
    bad = doc(i="x"); bad.pop("prompt_sha256")
    r = client.post(URL, json={"docs": [doc(), bad, doc(i="y", **{"$where": "1"})]}, headers=H).json()
    assert r["upserted"] == 1 and not r["ok"]
    assert [x["index"] for x in r["rejected"]] == [1, 2]


def test_batch_size_capped(env):
    client, *_ = env
    docs = [doc(i=f"id{n}") for n in range(201)]
    assert client.post(URL, json={"docs": docs}, headers=H).status_code == 422


def test_stats_counts_what_landed(env):
    client, *_ = env
    client.post(URL, json={"docs": [doc(), doc(i="z", net_band="neutral_mixed")]}, headers=H)
    s = client.get("/api/internal/event-ai-analysis/stats", headers=H).json()
    assert s["total"] == 2 and sum(g["n"] for g in s["groups"]) == 2
