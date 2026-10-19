"""GET /api/filings/feed — the Market intelligence additions (routes/filings.py): `provenance=1` (PRD §6.3: both the
publication and the ingestion time, the issuer, the sector with its source, peers and every source record) and
`family=calls|ownership|exchange` (PRD §6.2 categories read from the exchange's own subject line).

No network: `daas_client.get_raw` answers DaaS /v1/desk/event-sources and /v1/desk/filings with fixture bodies in
the shape nidp/services/daas_api/routers/desk_market.py sends, and `_feed` / `_insights_for` are replaced, so the
route's own work runs for real: what is asked for, the merge, and the honest failure states.
MOCK — not real data.
"""
from __future__ import annotations

import copy
from typing import Any, List, Optional, Tuple

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import filings, markets
from services.copilot_tools import daas_client

ARTICLES = [
    {"id": "n1", "symbol": "FIXA", "company": "Fix A Ltd", "when": "2026-10-13T14:30:00+05:30", "source": "NSE_ANN",
     "title": "Outcome of Board Meeting", "category": "Earnings", "impact": "high", "sentiment": "positive",
     "url": "https://nsearchives.nseindia.com/n1.pdf"},
    {"id": "b1", "symbol": None, "company": "Fix A Ltd", "when": "2026-10-13T14:32:00+05:30", "source": "BSE_ANN",
     "title": "Board Meeting Outcome", "category": "Markets", "impact": None, "sentiment": None,
     "url": "https://www.bseindia.com/b1.pdf"},
    {"id": "x1", "symbol": "FIXZ", "company": "Fix Z Ltd", "when": "2026-10-13T09:00:00+05:30", "source": "NSE_ANN",
     "title": "Press Release", "category": "Orders", "impact": "medium", "sentiment": "neutral", "url": None},
]
PEERS = [{"symbol": "PEER1", "name": "Peer One Ltd.", "largest_index": "Nifty 50"}]
EVENTS = {"source": "fixture", "peer_index": "Nifty Total Market", "events": {
    "n1": {"nse_symbol": "FIXA", "resolution": "exchange_symbol", "timing_type": "intraday", "known_at_open_session": "2026-10-14",
           "known_by_close_session": "2026-10-13", "primary_row": True, "ts_basis": "dissemination", "sector": "Healthcare",
           "sector_source": "NSE index list (Nifty Total Market, 2026-10-13)", "peers": PEERS,
           "records": [{"announcement_id": "n1", "source": "NSE_ANN", "company": "Fix A Ltd", "subject": "Outcome of Board Meeting",
                        "url": "https://nsearchives.nseindia.com/n1.pdf", "published_at": "2026-10-13T09:00:00+00:00",
                        "broadcast_at": "2026-10-13T08:59:59+00:00", "ingested_at": "2026-10-13T09:15:02+00:00",
                        "classified_at": "2026-10-13T09:20:00+00:00", "classifier_version": "v3"}]},
    "b1": {"nse_symbol": "FIXA", "resolution": "bse_scrip_isin_bridge", "timing_type": "intraday", "known_at_open_session": "2026-10-14",
           "known_by_close_session": "2026-10-13", "primary_row": False, "ts_basis": "dissemination", "sector": "Healthcare",
           "sector_source": "NSE index list (Nifty Total Market, 2026-10-13)", "peers": PEERS,
           "records": [{"announcement_id": "b1", "source": "BSE_ANN", "company": "Fix A Ltd", "subject": "Board Meeting Outcome",
                        "url": "https://www.bseindia.com/b1.pdf", "published_at": "2026-10-13T09:02:00+00:00",
                        "broadcast_at": None, "ingested_at": "2026-10-13T09:40:00+00:00", "classified_at": None,
                        "classifier_version": None}]},
}}
FAMILY = {"family": "calls", "patterns": ["%Con. Call%"], "days": 7, "source": "fixture", "total": 1, "categories": {},
          "articles": [{"id": "c1", "title": "Analysts/Institutional Investor Meet/Con. Call Updates", "company": "Fix C Ltd",
                        "symbol": "FIXC", "category": "Regulatory", "impact": "low", "sentiment": "neutral",
                        "when": "2026-10-13T08:00:00+00:00", "source": "NSE_ANN", "url": None, "ingested_at": "2026-10-13T08:15:00+00:00"}]}

Calls = List[Tuple[str, Optional[dict]]]


@pytest.fixture
def client(monkeypatch):
    calls: Calls = []
    replies = {"/desk/event-sources": (200, EVENTS), "/desk/filings": (200, FAMILY)}

    async def get_raw(path: str, params: Optional[dict] = None, timeout: float = 10.0):
        calls.append((path, params))
        r = replies[path]
        if isinstance(r, Exception):
            raise r
        return copy.deepcopy(r)

    async def fake_feed(*a, **k):
        return {"articles": copy.deepcopy(ARTICLES), "total": 40, "categories": {"earnings": 5}}

    async def no_insights(ids):
        return {}

    async def fake_user(request: Request):
        return {"user_id": "u1"}

    monkeypatch.setattr(markets, "_AUX_CACHE", {})
    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    monkeypatch.setattr(daas_client, "is_configured", lambda: True)
    monkeypatch.setattr(filings, "_feed", fake_feed)
    monkeypatch.setattr(filings, "_insights_for", no_insights)
    monkeypatch.setattr(filings, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(filings.router)
    return TestClient(app), calls, replies


def test_without_the_flag_the_rows_are_unchanged_and_nothing_more_is_read(client):
    c, calls, _ = client
    body = c.get("/api/filings/feed?days=7&sort=latest").json()
    assert "ingested_at" not in body["rows"][0] and "provenance" not in body
    assert calls == []


def test_provenance_rows_carry_both_times_the_issuer_sector_peers_and_every_record(client):
    c, calls, _ = client
    body = c.get("/api/filings/feed?days=7&sort=latest&provenance=1").json()
    assert calls == [("/desk/event-sources", {"ids": "b1,n1,x1"})]
    by = {r["id"]: r for r in body["rows"]}
    n1 = by["n1"]
    assert (n1["published_at"], n1["ingested_at"], n1["broadcast_at"]) == (
        "2026-10-13T09:00:00+00:00", "2026-10-13T09:15:02+00:00", "2026-10-13T08:59:59+00:00")
    assert (n1["nse_symbol"], n1["sector"], n1["sector_source"]) == ("FIXA", "Healthcare", "NSE index list (Nifty Total Market, 2026-10-13)")
    assert (n1["timing_type"], n1["known_at_open_session"], n1["primary_row"]) == ("intraday", "2026-10-14", True)
    assert n1["peers"] == PEERS and n1["classifier_version"] == "v3" and len(n1["records"]) == 1
    # the BSE copy resolves to the same NSE symbol through the scrip bridge, and is not the primary row
    assert (by["b1"]["nse_symbol"], by["b1"]["resolution"], by["b1"]["primary_row"]) == ("FIXA", "bse_scrip_isin_bridge", False)
    # a filing the store does not know keeps the row, with every provenance field null
    assert by["x1"]["ingested_at"] is None and by["x1"]["records"] is None and by["x1"]["exchange"] == "NSE"
    assert body["provenance"] == {"source": "fixture", "error": None}
    # the feed's own fields are untouched
    assert (n1["exchange"], n1["docLabel"], n1["date"]) == ("NSE", "Outcome of Board Meeting", "2026-10-13T14:30:00+05:30")


def test_a_failed_provenance_read_keeps_the_rows_and_says_so(client):
    c, _, replies = client
    replies["/desk/event-sources"] = daas_client.DaasError("unreachable")
    body = c.get("/api/filings/feed?days=7&provenance=1").json()
    assert len(body["rows"]) == 3 and all(r["ingested_at"] is None for r in body["rows"])
    assert body["provenance"] == {"source": None, "error": "upstream_unavailable"}


def test_a_family_reads_the_exchange_subject_family_instead_of_the_classified_articles(client):
    c, calls, _ = client
    body = c.get("/api/filings/feed?days=7&family=calls&limit=40").json()
    assert calls == [("/desk/filings", {"family": "calls", "days": 7, "limit": 40, "offset": 0})]
    assert [r["id"] for r in body["rows"]] == ["c1"] and body["total"] == 1
    assert body["family"] == {"key": "calls", "patterns": ["%Con. Call%"], "source": "fixture"}
    assert body["rows"][0]["docLabel"] == "Analysts/Institutional Investor Meet/Con. Call Updates"


def test_an_unknown_family_is_400_and_a_failed_family_read_is_502_not_an_empty_list(client):
    c, calls, replies = client
    assert c.get("/api/filings/feed?family=gossip").status_code == 400
    assert calls == []
    replies["/desk/filings"] = daas_client.DaasError("unreachable")
    r = c.get("/api/filings/feed?family=ownership")
    assert (r.status_code, r.json()["detail"]) == (502, "upstream_unavailable")
