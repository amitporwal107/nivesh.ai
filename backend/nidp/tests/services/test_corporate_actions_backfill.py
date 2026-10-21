"""Corporate-actions ingester: multi-index daily fetch + historical backfill.

Fixtures are trimmed REAL responses of NSE
/api/corporates-corporateActions (fetched read-only 2026-10-20, ranges
01-10-2025 to 19-10-2026), not mocks. Expected values are computed from the
payload, never typed in.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

from nidp.services.corporate_actions import service as svc
from nidp.services.corporate_actions.parser import parse_corporate_actions

FIX = Path(__file__).resolve().parent.parent / "fixtures"


def _load(name: str) -> bytes:
    return (FIX / f"corporate_actions_nse_{name}_range.json").read_bytes()


def test_range_url_uses_nse_dd_mm_yyyy_params():
    url = svc.range_url("sme", date(2025, 10, 1), date(2025, 10, 31))
    assert url.endswith("/api/corporates-corporateActions?index=sme"
                        "&from_date=01-10-2025&to_date=31-10-2025")


def test_date_chunks_cover_range_without_gaps_or_overlap():
    chunks = svc.date_chunks(date(2025, 10, 1), date(2026, 10, 19), days=31)
    assert chunks[0][0] == date(2025, 10, 1)
    assert chunks[-1][1] == date(2026, 10, 19)
    for (_, e1), (s2, _) in zip(chunks, chunks[1:]):
        assert (s2 - e1).days == 1
    assert all((e - s).days < 31 for s, e in chunks)


def test_date_chunks_rejects_inverted_range():
    with pytest.raises(ValueError):
        svc.date_chunks(date(2026, 1, 2), date(2026, 1, 1))


def test_real_split_and_bonus_purposes_classify_with_factor_inputs():
    rows = parse_corporate_actions(_load("equities"))
    kotak = [r for r in rows if r["symbol"] == "KOTAKBANK" and r["action_type"] == "SPLIT"]
    assert len(kotak) == 1
    assert kotak[0]["ex_date"] == "2026-01-14"
    assert (kotak[0]["face_value_pre"], kotak[0]["face_value_post"]) == (5.0, 1.0)
    # same-day split + bonus for one symbol are two separate rows (unique key has action_type)
    fcl = {r["action_type"] for r in rows if r["symbol"] == "FCL"}
    assert fcl == {"SPLIT", "BONUS"}
    # NCRPS bonus inside a scheme of arrangement is NOT a share bonus
    tvs = [r for r in rows if r["symbol"] == "TVSHLTD"]
    assert tvs and all(r["action_type"] != "BONUS" for r in tvs)


def test_sme_and_mf_indexes_parse_too():
    assert {r["action_type"] for r in parse_corporate_actions(_load("sme"))} == {"BONUS", "SPLIT"}
    mf = parse_corporate_actions(_load("mf"))
    assert [r["action_type"] for r in mf] == ["SPLIT"]


class _FakeFetch:
    def __init__(self, bodies: dict[str, bytes], fail: set[str] | None = None):
        self.bodies, self.fail, self.urls = bodies, fail or set(), []

    async def __call__(self, url, **kw):
        self.urls.append(url)
        idx = url.split("index=")[1].split("&")[0]
        if idx in self.fail:
            raise RuntimeError(f"boom {idx}")
        return self.bodies[idx], 200


def _bodies():
    return {"equities": _load("equities"), "sme": _load("sme"), "mf": _load("mf")}


def test_backfill_fetches_every_index_per_chunk_and_upserts_parsed_rows(monkeypatch):
    fake = _FakeFetch(_bodies())
    saved = []

    async def fake_upsert(rows, run_id):
        saved.append(rows)
        return len(rows)

    monkeypatch.setattr(svc, "fetch_bytes", fake)
    monkeypatch.setattr(svc, "upsert_corporate_actions", fake_upsert)
    monkeypatch.setattr(svc, "_pace_between_calls", lambda: asyncio.sleep(0))

    out = asyncio.run(svc.backfill(date(2025, 10, 1), date(2025, 11, 15)))  # 2 chunks x 3 indexes
    assert len(fake.urls) == 6
    assert {u.split("index=")[1].split("&")[0] for u in fake.urls} == {"equities", "sme", "mf"}
    expected = sum(len(parse_corporate_actions(b)) for b in _bodies().values()) * 2
    assert out["fetched"] == expected
    # the duplicate chunk responses collapse to unique (symbol, type, ex_date) keys
    keys = {(r["symbol"], r["action_type"], r["ex_date"]) for rows in saved for r in rows}
    assert out["unique"] == len(keys)
    assert ("KOTAKBANK", "SPLIT", "2026-01-14") in keys


def test_backfill_fails_loudly_when_an_index_fetch_fails(monkeypatch):
    async def fake_upsert(rows, run_id):
        return len(rows)

    monkeypatch.setattr(svc, "fetch_bytes", _FakeFetch(_bodies(), fail={"sme"}))
    monkeypatch.setattr(svc, "upsert_corporate_actions", fake_upsert)
    monkeypatch.setattr(svc, "_pace_between_calls", lambda: asyncio.sleep(0))
    with pytest.raises(RuntimeError, match="boom sme"):
        asyncio.run(svc.backfill(date(2025, 10, 1), date(2025, 10, 31)))


def test_daily_fetch_merges_all_indexes_into_one_json_array(monkeypatch):
    monkeypatch.setattr(svc, "fetch_bytes", _FakeFetch(_bodies()))
    body, _url, status = asyncio.run(svc.CorporateActionsIngester().fetch(None))
    assert status == 200
    merged = parse_corporate_actions(body)
    assert len(merged) == sum(len(parse_corporate_actions(b)) for b in _bodies().values())


def test_daily_fetch_tolerates_sme_failure_but_not_equities_failure(monkeypatch):
    monkeypatch.setattr(svc, "fetch_bytes", _FakeFetch(_bodies(), fail={"sme"}))
    body, _u, _s = asyncio.run(svc.CorporateActionsIngester().fetch(None))
    assert json.loads(body)  # equities + mf still delivered
    monkeypatch.setattr(svc, "fetch_bytes", _FakeFetch(_bodies(), fail={"equities"}))
    with pytest.raises(RuntimeError):
        asyncio.run(svc.CorporateActionsIngester().fetch(None))
