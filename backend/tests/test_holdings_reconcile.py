"""Broker wins: how holdings from a CAS statement, a broker connection and a
broker export are reconciled (helpers.holdings_reconcile), and how the central
import path (helpers.parsing.save_holdings) applies it."""
import asyncio
import re

import pytest

from helpers import holdings_reconcile as hr
from helpers import parsing

INFY, TCS, HDFC = "INE009A01021", "INE467B01029", "INE040A01034"
MF = "INF879O01019"


# ── A small in-memory stand-in for the Mongo calls these modules make ────
def _match(doc, query):
    for key, cond in query.items():
        if key == "$or":
            if not any(_match(doc, q) for q in cond):
                return False
            continue
        value = doc.get(key)  # a missing field reads as None, as in Mongo's null match
        if isinstance(cond, dict) and all(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                if op == "$in":
                    ok = value in arg
                elif op == "$nin":
                    ok = value not in arg
                elif op == "$ne":
                    ok = value != arg
                elif op == "$regex":
                    flags = re.I if "i" in cond.get("$options", "") else 0
                    ok = isinstance(value, str) and re.search(arg, value, flags) is not None
                elif op == "$options":
                    ok = True                      # read with `$regex`
                else:
                    raise NotImplementedError(op)
                if not ok:
                    return False
        elif value != cond:
            return False
    return True


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, length=None):
        return [dict(r) for r in self._rows]


class _Deleted:
    def __init__(self, n):
        self.deleted_count = n


class _Holdings:
    def __init__(self, rows=()):
        self.rows = [dict(r) for r in rows]

    def find(self, query, _projection=None):
        return _Cursor([r for r in self.rows if _match(r, query)])

    async def count_documents(self, query):
        return sum(1 for r in self.rows if _match(r, query))

    async def delete_many(self, query):
        before = len(self.rows)
        self.rows = [r for r in self.rows if not _match(r, query)]
        return _Deleted(before - len(self.rows))

    async def insert_one(self, doc):
        self.rows.append(doc)


class _Sink:
    async def delete_one(self, *_a, **_k):
        return _Deleted(0)

    async def delete_many(self, *_a, **_k):
        return _Deleted(0)

    async def update_one(self, *_a, **_k):
        return None


class _Db:
    def __init__(self, rows=()):
        self.holdings = _Holdings(rows)
        self.mfd_profile_signal_cache = _Sink()
        self.fund_performance_cache = _Sink()
        self.upload_tasks = _Sink()


def _cas(isin, user="u1", **extra):
    return {"user_id": user, "ticker": isin, "source": "cas", "quantity": 10, **extra}


def _live(isin, user="u1", broker="zerodha", account="ba_1", **extra):
    return {"user_id": user, "ticker": "SYM", "isin": isin, "source": "broker_native",
            "broker": broker, "broker_account_id": account, "quantity": 10, **extra}


def _export(isin, user="u1", broker="zerodha", **extra):
    return {"user_id": user, "ticker": "SYM", "isin": isin, "source": "broker_export",
            "broker": broker, "quantity": 10, **extra}


def _isins(db, **where):
    return sorted(hr.row_isin(r) for r in db.holdings.rows if _match(r, where))


@pytest.fixture(autouse=True)
def symbol_index(monkeypatch):
    monkeypatch.setattr(hr, "_symbol_index", {"INFY": INFY, "TCS": TCS, "EMBASSY": "INE041025011"})


# ── ISIN resolution ──────────────────────────────────────────────────────
@pytest.mark.parametrize("row, expected", [
    ({"isin": " ine009a01021 "}, INFY),
    ({"ticker": INFY}, INFY),                      # statement rows keep the ISIN in ticker
    ({"isin": "", "ticker": "INFY"}, ""),          # a symbol is not an ISIN
    ({"ticker": "INDIGO"}, ""),                    # starts with IN but is not 12 characters
    ({}, ""),
])
def test_row_isin_reads_only_a_stated_isin(row, expected):
    assert hr.row_isin(row) == expected


@pytest.mark.parametrize("ticker, expected", [
    ("INFY", INFY),
    ("infy", INFY),
    ("NSE:INFY", INFY),
    ("INFY-EQ", INFY),                             # series suffix
    ("EMBASSY-RR", "INE041025011"),
    ("BAJAJ-AUTO", ""),                            # the hyphen is part of the symbol; not in the index
    ("UNLISTEDCO", ""),
    ("", ""),
])
def test_resolve_isin_falls_back_to_the_trading_symbol(ticker, expected):
    assert hr.resolve_isin({"ticker": ticker}) == expected


def test_resolve_isin_prefers_the_stated_isin_over_the_symbol():
    assert hr.resolve_isin({"isin": TCS, "ticker": "INFY"}) == TCS


def test_missing_masterdata_resolves_nothing_instead_of_failing(monkeypatch):
    monkeypatch.setattr(hr, "_symbol_index", None)

    def _boom():
        raise OSError("masterdata volume not mounted")

    from services import masterdata
    monkeypatch.setattr(masterdata, "_load_equity_master", _boom)
    assert hr.resolve_isin({"ticker": "INFY"}) == ""


# ── Classification ───────────────────────────────────────────────────────
@pytest.mark.parametrize("row, sourced", [
    (_live(INFY), True),
    (_export(INFY), True),
    (_cas(INFY), False),
    ({"user_id": "u1", "ticker": "INFY"}, False),                 # hand-added, no source at all
    ({"user_id": "u1", "source": "manual", "broker_account_id": ""}, False),
    ({"user_id": "u1", "source": "openalgo", "broker_account_id": "ba_9"}, True),
])
def test_broker_sourced_rows_and_both_filters_agree(row, sourced):
    assert hr.is_broker_sourced(row) is sourced
    assert _match(row, hr.broker_sourced_filter()) is sourced
    assert _match(row, hr.not_broker_sourced_filter()) is (not sourced)


# ── Statement import helpers ─────────────────────────────────────────────
def test_broker_held_isins_covers_connections_and_exports_of_this_user_only():
    db = _Db([_live(INFY), _export(TCS), _cas(HDFC), _live(MF, user="u2"),
              {"user_id": "u1", "ticker": "TCS", "source": "broker_native", "broker_account_id": "ba_2"}])
    assert asyncio.run(hr.broker_held_isins(db, "u1")) == {INFY, TCS}


def test_drop_broker_held_leaves_out_only_matching_isins():
    rows = [_cas(INFY), _cas(MF), {"ticker": "UNLISTEDCO"}]
    kept, left_out = hr.drop_broker_held(rows, {INFY})
    assert [r["ticker"] for r in kept] == [MF, "UNLISTEDCO"]
    assert left_out == 1
    assert hr.drop_broker_held(rows, set()) == (rows, 0)


# ── Broker export upload ─────────────────────────────────────────────────
def test_a_new_export_replaces_that_brokers_earlier_export_only():
    db = _Db([_export(INFY), _export(TCS, broker="groww"), _live(HDFC, broker="upstox"), _cas(MF)])
    incoming = [_export(TCS)]
    kept = asyncio.run(hr.replace_broker_export(db, "u1", incoming))
    assert kept == incoming
    assert _isins(db, source="broker_export") == [TCS]          # groww's export stays, zerodha's went
    assert _isins(db, source="broker_native") == [HDFC]
    assert _isins(db, source="cas") == [MF]


def test_an_export_leaves_out_what_a_live_connection_to_the_same_broker_holds():
    db = _Db([_live(INFY, broker="zerodha"), _live(TCS, broker="upstox")])
    kept = asyncio.run(hr.replace_broker_export(db, "u1", [_export(INFY), _export(TCS), _export(HDFC)]))
    assert sorted(r["isin"] for r in kept) == [HDFC, TCS]       # TCS is live at another broker: kept


def test_rows_that_are_not_a_broker_export_pass_through_and_delete_nothing():
    db = _Db([_export(INFY), _cas(TCS)])
    generic = [{"name": "Infosys", "ticker": "INFY", "quantity": 5}]
    assert asyncio.run(hr.replace_broker_export(db, "u1", generic)) == generic
    assert len(db.holdings.rows) == 2


# ── After broker rows are stored ─────────────────────────────────────────
def test_a_live_sync_removes_statement_copies_and_that_brokers_export_copies():
    db = _Db([
        _cas(INFY), _cas(MF), _cas(INFY, user="u2"),
        {"user_id": "u1", "ticker": INFY, "source": "snapshot_load"},
        {"user_id": "u1", "ticker": INFY, "source": "manual"},     # the user's own entry is not touched
        _export(INFY), _export(INFY, broker="groww"), _live(INFY),
    ])
    out = asyncio.run(hr.apply_broker_wins(db, "u1", [_live(INFY)], broker="zerodha", live=True))
    assert out == {"statement_rows_removed": 2, "export_rows_removed": 1}
    left = [(r["user_id"], r.get("source"), r.get("broker")) for r in db.holdings.rows]
    assert left == [("u1", "cas", None), ("u2", "cas", None), ("u1", "manual", None),
                    ("u1", "broker_export", "groww"), ("u1", "broker_native", "zerodha")]


def test_an_export_removes_statement_copies_but_never_another_export():
    db = _Db([_cas(INFY), _export(INFY, broker="groww")])
    out = asyncio.run(hr.apply_broker_wins(db, "u1", [_export(INFY)], broker="zerodha", live=False))
    assert out == {"statement_rows_removed": 1, "export_rows_removed": 0}
    assert _isins(db, source="broker_export") == [INFY]


def test_a_broker_row_matched_by_symbol_supersedes_the_statement_row():
    db = _Db([_cas(TCS)])
    synced = [{"ticker": "TCS-EQ", "source": "broker_native", "broker_account_id": "ba_1"}]
    out = asyncio.run(hr.apply_broker_wins(db, "u1", synced, broker="angel", live=True))
    assert out["statement_rows_removed"] == 1


def test_rows_without_an_establishable_isin_remove_nothing():
    db = _Db([_cas(INFY)])
    out = asyncio.run(hr.apply_broker_wins(db, "u1", [{"ticker": "UNLISTEDCO"}], broker="zerodha", live=True))
    assert out == {"statement_rows_removed": 0, "export_rows_removed": 0}
    assert len(db.holdings.rows) == 1


# ── A live sync and the same broker's export: also matched by ticker ─────
def _file_row(ticker, broker="zerodha", user="u1", **extra):
    """An uploaded export row. No `isin` unless given: many exports carry only the symbol."""
    return {"user_id": user, "ticker": ticker, "source": "broker_export", "broker": broker, "quantity": 10, **extra}


def _synced(ticker, isin=None, account="ba_1", broker="zerodha"):
    row = {"user_id": "u1", "ticker": ticker, "source": "broker_native", "broker": broker,
           "broker_account_id": account, "quantity": 10}
    return {**row, "isin": isin} if isin else row


def _tickers(db, **where):
    return sorted(r["ticker"] for r in db.holdings.rows if _match(r, where))


def test_an_export_row_without_an_isin_is_matched_by_the_same_ticker():
    # UNLISTEDCO is in no masterdata index, so nothing but the ticker can tie the two rows together.
    db = _Db([_file_row("UNLISTEDCO"), _file_row("OTHERCO"), _synced("UNLISTEDCO", isin=HDFC)])
    out = asyncio.run(hr.apply_broker_wins(db, "u1", [_synced("UNLISTEDCO", isin=HDFC)], broker="zerodha", live=True))
    assert out == {"statement_rows_removed": 0, "export_rows_removed": 1}
    assert _tickers(db, source="broker_export") == ["OTHERCO"]


def test_a_synced_row_without_an_isin_matches_the_export_row_by_ticker_even_when_that_has_one():
    db = _Db([_file_row("UNLISTEDCO", isin=HDFC), _file_row("OTHERCO", isin=MF)])
    out = asyncio.run(hr.apply_broker_wins(db, "u1", [_synced("UNLISTEDCO")], broker="zerodha", live=True))
    assert out == {"statement_rows_removed": 0, "export_rows_removed": 1}
    assert _tickers(db, source="broker_export") == ["OTHERCO"]


@pytest.mark.parametrize("stored, synced", [
    ("unlistedco", "UNLISTEDCO"), ("UnlistedCo", "unlistedco"), ("M&M", "m&m"), ("BAJAJ-AUTO", "bajaj-auto"),
])
def test_the_ticker_match_ignores_case(stored, synced):
    db = _Db([_file_row(stored)])
    out = asyncio.run(hr.apply_broker_wins(db, "u1", [_synced(synced)], broker="zerodha", live=True))
    assert out["export_rows_removed"] == 1 and db.holdings.rows == []


@pytest.mark.parametrize("stored", ["UNLISTEDCO2", "XUNLISTEDCO", "UNLISTED", "UNLISTEDCO-BE", "NSE:UNLISTEDCO", ""])
def test_the_ticker_match_is_exact_not_partial(stored):
    db = _Db([_file_row(stored)])
    out = asyncio.run(hr.apply_broker_wins(db, "u1", [_synced("UNLISTEDCO")], broker="zerodha", live=True))
    assert out["export_rows_removed"] == 0 and len(db.holdings.rows) == 1


def test_two_rows_that_both_state_an_isin_are_matched_by_isin_never_by_ticker():
    # The same symbol under two different ISINs is two instruments: the export row stays.
    db = _Db([_file_row("UNLISTEDCO", isin=HDFC)])
    out = asyncio.run(hr.apply_broker_wins(db, "u1", [_synced("UNLISTEDCO", isin=MF)], broker="zerodha", live=True))
    assert out["export_rows_removed"] == 0 and len(db.holdings.rows) == 1


def test_the_ticker_match_is_for_the_same_brokers_export_only():
    other_rows = [
        _file_row("UNLISTEDCO", broker="groww"),                                    # another broker's export
        _file_row("UNLISTEDCO", user="u2"),                                         # another user's export
        {"user_id": "u1", "ticker": "UNLISTEDCO", "source": "cas", "quantity": 10},              # a statement row
        {"user_id": "u1", "ticker": "UNLISTEDCO", "source": "snapshot_load", "quantity": 10},    # a statement row
        {"user_id": "u1", "ticker": "UNLISTEDCO", "source": "manual", "quantity": 10},           # the user's own entry
        _synced("UNLISTEDCO", account="ba_2"),                                      # another login at this broker
        _synced("UNLISTEDCO", account="ba_9", broker="groww"),                      # a connection to another broker
    ]
    db = _Db(other_rows + [_file_row("UNLISTEDCO")])
    out = asyncio.run(hr.apply_broker_wins(db, "u1", [_synced("UNLISTEDCO")], broker="zerodha", live=True))
    assert out == {"statement_rows_removed": 0, "export_rows_removed": 1}
    assert db.holdings.rows == other_rows                # a statement row is never removed on a symbol


def test_an_uploaded_export_does_not_use_the_ticker_match():
    # `live=False` is the upload path: it never removes export rows at all, by ISIN or by ticker.
    db = _Db([_file_row("UNLISTEDCO", broker="zerodha"), _file_row("UNLISTEDCO", broker="groww")])
    out = asyncio.run(hr.apply_broker_wins(db, "u1", [_file_row("UNLISTEDCO")], broker="zerodha", live=False))
    assert out == {"statement_rows_removed": 0, "export_rows_removed": 0} and len(db.holdings.rows) == 2


def test_an_isin_match_and_a_ticker_match_on_one_row_count_once():
    db = _Db([_file_row("INFY", isin=INFY), _file_row("TCS")])
    synced = [_synced("INFY", isin=INFY), _synced("TCS", isin=TCS)]
    out = asyncio.run(hr.apply_broker_wins(db, "u1", synced, broker="zerodha", live=True))
    assert out == {"statement_rows_removed": 0, "export_rows_removed": 2} and db.holdings.rows == []


# ── save_holdings ────────────────────────────────────────────────────────
@pytest.fixture
def save(monkeypatch):
    async def _no_enrichment(*_a, **_k):
        return None

    from services import equity_sectors, masterdata
    monkeypatch.setattr(parsing, "_enrich_after_upload", _no_enrichment)
    monkeypatch.setattr(masterdata, "validate_and_enrich_holdings", lambda rows: rows)
    monkeypatch.setattr(equity_sectors, "enrich_holdings_with_sectors", lambda rows: rows)

    def _run(db, rows, file_type):
        monkeypatch.setattr(parsing, "db", db)

        async def _go():
            added = await parsing.save_holdings("u1", rows, file_type)
            await asyncio.sleep(0)  # let the fire-and-forget enrichment task finish
            return added

        return asyncio.run(_go())

    return _run


def _parsed(ticker, **extra):
    return {"name": ticker, "ticker": ticker, "asset_type": "equity", "quantity": 5,
            "buy_price": 100, "current_price": 110, **extra}


def test_cas_import_keeps_broker_rows_and_leaves_out_what_they_hold(save):
    db = _Db([_cas(HDFC), {"user_id": "u1", "ticker": "OLD", "source": "manual"},
              _live(INFY), _export(TCS, broker="groww"), _cas(HDFC, user="u2")])
    added = save(db, [_parsed(INFY), _parsed(TCS), _parsed(MF, asset_type="mutual_fund")], "gmail_cas")

    assert [a["name"] for a in added] == [MF]                    # INFY and TCS are broker-held
    mine = [r for r in db.holdings.rows if r["user_id"] == "u1"]
    assert sorted((r["source"], hr.row_isin(r)) for r in mine) == [
        ("broker_export", TCS), ("broker_native", INFY), ("cas", MF),
    ]                                                            # old CAS and manual rows replaced, as before
    assert [r for r in db.holdings.rows if r["user_id"] == "u2"] == [_cas(HDFC, user="u2")]


def test_cas_import_without_any_broker_source_behaves_as_before(save):
    db = _Db([_cas(HDFC), {"user_id": "u1", "ticker": "OLD", "source": "manual"}])
    added = save(db, [_parsed(INFY), _parsed(MF, asset_type="mutual_fund")], "cas_pdf")
    assert len(added) == 2
    assert sorted(r["ticker"] for r in db.holdings.rows) == [INFY, MF]
    assert all(r["source"] == "cas" and "isin" not in r and "broker" not in r for r in db.holdings.rows)


def test_broker_export_upload_replaces_the_earlier_one_and_supersedes_cas(save):
    db = _Db([_export(HDFC), _cas(INFY), _cas(MF), _live(TCS, broker="upstox")])
    rows = [_parsed("INFY", isin=INFY, source="broker_export", broker="zerodha"),
            _parsed("TCS", isin=TCS, source="broker_export", broker="zerodha")]
    added = save(db, rows, "Excel")

    assert len(added) == 2
    stored = [r for r in db.holdings.rows if r.get("source") == "broker_export"]
    assert sorted((r["broker"], r["isin"], r["ticker"]) for r in stored) == [
        ("zerodha", INFY, "INFY"), ("zerodha", TCS, "TCS"),
    ]                                                            # the earlier HDFC export row is gone
    assert _isins(db, source="cas") == [MF]                      # the CAS copy of INFY was superseded
    assert _isins(db, source="broker_native") == [TCS]           # another broker's live row is untouched


def test_generic_upload_still_adds_rows_and_deletes_nothing(save):
    db = _Db([_cas(INFY), _export(TCS), _live(HDFC)])
    added = save(db, [_parsed("INFY"), _parsed("WIPRO")], "CSV")
    assert len(added) == 2
    assert len(db.holdings.rows) == 5
    new = [r for r in db.holdings.rows if r.get("source") == "manual"]
    assert len(new) == 2 and all("isin" not in r and "broker" not in r for r in new)
