"""Tests for `services.cas_transactions` — txn extraction + SIP detection."""
from datetime import date, timedelta

import pytest

from services import cas_transactions as ct


# ── Fixtures ─────────────────────────────────────────────────────────────
def _cas_payload(scheme="HDFC Flexi Cap Fund", folio="123456789", txns=None):
    return {
        "mutual_funds": [{
            "amc": "HDFC Mutual Fund",
            "folio_number": folio,
            "schemes": [{
                "scheme_name": scheme,
                "isin": "INF179K01YV8",
                "transactions": txns or [],
            }],
        }],
    }


def _monthly_sip_dates(months=12, start=date(2024, 4, 1)):
    return [(start.replace(day=1) + timedelta(days=30 * i)).isoformat() for i in range(months)]


# ── _classify_txn ────────────────────────────────────────────────────────
@pytest.mark.parametrize("desc,expected", [
    ("SIP - Purchase",                     ct.TXN_TYPE_SIP_PURCHASE),
    ("Systematic Investment Plan - Apr",   ct.TXN_TYPE_SIP_PURCHASE),
    ("Purchase - Lumpsum",                 ct.TXN_TYPE_PURCHASE),
    ("SUBSCRIPTION",                        ct.TXN_TYPE_PURCHASE),
    ("Redemption",                          ct.TXN_TYPE_REDEMPTION),
    ("Switch Out (Reg to Direct)",          ct.TXN_TYPE_SWITCH_OUT),
    ("Switch In - Direct Plan",             ct.TXN_TYPE_SWITCH_IN),
    ("IDCW Payout",                         ct.TXN_TYPE_DIVIDEND),
    ("Dividend Reinvest",                   ct.TXN_TYPE_DIVIDEND),
    ("Stamp Duty",                          ct.TXN_TYPE_CHARGE),
    ("STT",                                 ct.TXN_TYPE_CHARGE),
])
def test_classify_txn(desc, expected):
    units = -10.0 if "Switch Out" in desc else 10.0
    assert ct._classify_txn({"description": desc, "units": units}) == expected


def test_classify_unknown_falls_back_on_sign():
    # Positive units + amount → assume purchase
    assert ct._classify_txn({"description": "Unknown line", "units": 5, "amount": 5000}) == ct.TXN_TYPE_PURCHASE
    # Negative units + amount → redemption
    assert ct._classify_txn({"description": "Unknown line", "units": -5, "amount": -5000}) == ct.TXN_TYPE_REDEMPTION
    assert ct._classify_txn({"description": "", "units": 0, "amount": 0}) == ct.TXN_TYPE_OTHER


# ── _norm_date ──────────────────────────────────────────────────────────
def test_norm_date_iso_pass_through():
    assert ct._norm_date("2024-04-01") == "2024-04-01"


def test_norm_date_dd_mm_yyyy():
    assert ct._norm_date("01-04-2024") == "2024-04-01"
    assert ct._norm_date("01/04/2024") == "2024-04-01"


def test_norm_date_invalid_returns_none():
    assert ct._norm_date("garbage") is None
    assert ct._norm_date(None) is None
    assert ct._norm_date("") is None


# ── extract_transactions ─────────────────────────────────────────────────
def test_extract_transactions_basic():
    payload = _cas_payload(txns=[
        {"date": "2024-04-01", "description": "SIP - Purchase",
         "amount": 5000, "units": 100.5, "nav": 49.75, "balance": 100.5},
        {"date": "2024-05-01", "description": "SIP - Purchase",
         "amount": 5000, "units": 99.0, "nav": 50.50, "balance": 199.5},
    ])
    txns = ct.extract_transactions(payload)
    assert len(txns) == 2
    t = txns[0]
    assert t["scheme_name"] == "HDFC Flexi Cap Fund"
    assert t["folio"] == "123456789"
    assert t["amc"] == "HDFC Mutual Fund"
    assert t["isin"] == "INF179K01YV8"
    assert t["type"] == ct.TXN_TYPE_SIP_PURCHASE
    assert t["amount"] == 5000.0
    assert t["nav"] == 49.75


def test_extract_transactions_skips_zero_amounts():
    payload = _cas_payload(txns=[
        {"date": "2024-04-01", "description": "SIP - Purchase", "amount": 0, "units": 0},
        {"date": "2024-05-01", "description": "Purchase", "amount": 5000, "units": 100},
    ])
    txns = ct.extract_transactions(payload)
    assert len(txns) == 1


def test_extract_transactions_handles_invalid_dates():
    payload = _cas_payload(txns=[
        {"date": "garbage", "description": "Purchase", "amount": 5000, "units": 100},
        {"date": "2024-04-01", "description": "Purchase", "amount": 1000, "units": 20},
    ])
    txns = ct.extract_transactions(payload)
    # Garbage date → dropped silently
    assert len(txns) == 1


def test_extract_transactions_empty_payload():
    assert ct.extract_transactions({}) == []
    assert ct.extract_transactions({"mutual_funds": []}) == []


# ── detect_sip_patterns ─────────────────────────────────────────────────
def test_detect_monthly_sip_12_instalments():
    txns = [
        {"date": d, "scheme_name": "HDFC Flexi Cap", "isin": "INF1", "folio": "F1",
         "amc": "HDFC", "type": ct.TXN_TYPE_SIP_PURCHASE,
         "amount": 5000, "units": 100, "nav": 50, "balance": 100, "raw_description": "SIP"}
        for d in _monthly_sip_dates(12)
    ]
    sips = ct.detect_sip_patterns(txns)
    assert len(sips) == 1
    s = sips[0]
    assert s["cadence"] == "MONTHLY"
    assert s["amount"] == 5000.0
    assert s["instalment_count"] == 12
    assert s["total_invested"] == 60000.0
    # Started Apr 2024, last instalment was 12 × 30 days later — definitely > 60d ago
    assert s["status"] == "PAUSED"


def test_detect_active_sip_recent_instalment():
    """Last instalment within 2× cadence → ACTIVE."""
    today = date.today()
    dates = [(today - timedelta(days=30 * i)).isoformat() for i in range(5)]
    txns = [
        {"date": d, "scheme_name": "Parag Parikh Flexi", "isin": "INF2", "folio": "F2",
         "amc": "PPFAS", "type": ct.TXN_TYPE_SIP_PURCHASE,
         "amount": 10_000, "units": 50, "nav": 200, "balance": 50, "raw_description": "SIP"}
        for d in dates
    ]
    sips = ct.detect_sip_patterns(txns)
    assert len(sips) == 1
    assert sips[0]["status"] == "ACTIVE"


def test_detect_quarterly_sip():
    today = date.today()
    dates = [(today - timedelta(days=90 * i)).isoformat() for i in range(4)]
    txns = [
        {"date": d, "scheme_name": "Quarterly Fund", "isin": "INF3", "folio": "F3",
         "amc": "X", "type": ct.TXN_TYPE_PURCHASE,
         "amount": 50_000, "units": 100, "nav": 500, "balance": 100, "raw_description": "Purchase"}
        for d in dates
    ]
    sips = ct.detect_sip_patterns(txns)
    assert len(sips) == 1
    assert sips[0]["cadence"] == "QUARTERLY"
    assert sips[0]["status"] == "ACTIVE"


def test_no_sip_when_under_3_instalments():
    txns = [
        {"date": "2024-04-01", "scheme_name": "X", "isin": "I", "folio": "F",
         "amc": "A", "type": ct.TXN_TYPE_PURCHASE,
         "amount": 5000, "units": 100, "nav": 50, "balance": 100, "raw_description": ""},
        {"date": "2024-05-01", "scheme_name": "X", "isin": "I", "folio": "F",
         "amc": "A", "type": ct.TXN_TYPE_PURCHASE,
         "amount": 5000, "units": 100, "nav": 50, "balance": 100, "raw_description": ""},
    ]
    assert ct.detect_sip_patterns(txns) == []


def test_no_sip_when_amounts_drift_too_much():
    """Amounts that drift > 5% with no consistent pattern → not a SIP."""
    txns = [
        {"date": d, "scheme_name": "X", "isin": "I", "folio": "F",
         "amc": "A", "type": ct.TXN_TYPE_PURCHASE,
         "amount": amt, "units": 100, "nav": 50, "balance": 100, "raw_description": ""}
        for d, amt in zip(_monthly_sip_dates(5), [5000, 7000, 3000, 12000, 2000])
    ]
    assert ct.detect_sip_patterns(txns) == []


def test_no_sip_when_cadence_irregular():
    """Random gaps → not a recognisable cadence."""
    txns = [
        {"date": d, "scheme_name": "X", "isin": "I", "folio": "F",
         "amc": "A", "type": ct.TXN_TYPE_PURCHASE,
         "amount": 5000, "units": 100, "nav": 50, "balance": 100, "raw_description": ""}
        for d in ["2024-04-01", "2024-04-15", "2024-07-01", "2024-12-01"]
    ]
    assert ct.detect_sip_patterns(txns) == []


def test_redemptions_excluded_from_sip_detection():
    today = date.today()
    txns = [
        {"date": (today - timedelta(days=30 * i)).isoformat(),
         "scheme_name": "X", "isin": "I", "folio": "F",
         "amc": "A", "type": ct.TXN_TYPE_REDEMPTION,
         "amount": -5000, "units": -100, "nav": 50, "balance": -100, "raw_description": ""}
        for i in range(4)
    ]
    assert ct.detect_sip_patterns(txns) == []


def test_multiple_funds_detected_independently():
    today = date.today()
    txns = []
    for sch, isin, folio, amt in [("Fund A", "I1", "F1", 5000),
                                   ("Fund B", "I2", "F2", 10_000)]:
        for i in range(4):
            txns.append({
                "date": (today - timedelta(days=30 * i)).isoformat(),
                "scheme_name": sch, "isin": isin, "folio": folio,
                "amc": "A", "type": ct.TXN_TYPE_SIP_PURCHASE,
                "amount": amt, "units": 100, "nav": 50, "balance": 100,
                "raw_description": "SIP",
            })
    sips = ct.detect_sip_patterns(txns)
    assert len(sips) == 2
    by_isin = {s["isin"]: s for s in sips}
    assert by_isin["I1"]["amount"] == 5000.0
    assert by_isin["I2"]["amount"] == 10_000.0
