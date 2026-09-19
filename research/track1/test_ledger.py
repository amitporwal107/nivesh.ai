import json, os, sys
import pytest
sys.path.insert(0, os.path.dirname(__file__))
from ledger import Ledger, LedgerError, verify

def test_lifecycle_and_chain(tmp_path):
    p = tmp_path / "ledger.jsonl"; L = Ledger(str(p))
    L.transition("ABC", "H-B", "WATCHLIST", "evening watchlist")
    L.transition("ABC", "H-B", "TRIGGER_APPROACHING", "gap -4.1% at 09:15")
    L.transition("ABC", "H-B", "ENTRY_CONFIRMED", "09:45 confirmed", {"entry": 101.5})
    L.manual("MANUAL_ENTRY", "ABC", "H-B", 101.8, 10, "2026-09-21T09:46:10+05:30")
    L.transition("ABC", "H-B", "CLOSED", "TIME", {"exit": 103.0})
    assert verify(str(p)) == (True, "ok")
    assert Ledger(str(p)).state[("ABC", "H-B")] == "CLOSED"            # state survives a reload

def test_illegal_transitions_rejected(tmp_path):
    L = Ledger(str(tmp_path / "l.jsonl"))
    with pytest.raises(LedgerError): L.transition("X", "H-A", "ENTRY_CONFIRMED", "no watchlist first")
    L.transition("X", "H-A", "WATCHLIST", "w"); L.transition("X", "H-A", "EXPIRED", "no gap")
    with pytest.raises(LedgerError): L.transition("X", "H-A", "ENTRY_CONFIRMED", "after expiry")

def test_manual_entry_needs_confirmed_signal(tmp_path):
    L = Ledger(str(tmp_path / "l.jsonl")); L.transition("X", "H-A", "WATCHLIST", "w")
    with pytest.raises(LedgerError): L.manual("MANUAL_ENTRY", "X", "H-A", 10.0, 1, "t")

def test_tampering_is_detected(tmp_path):
    p = tmp_path / "l.jsonl"; L = Ledger(str(p))
    L.transition("X", "H-A", "WATCHLIST", "w"); L.transition("X", "H-A", "ENTRY_CONFIRMED", "open", {"entry": 50.0})
    lines = p.read_text().splitlines(); e = json.loads(lines[1]); e["data"]["entry"] = 49.0
    lines[1] = json.dumps(e, sort_keys=True); p.write_text("\n".join(lines) + "\n")
    ok, msg = verify(str(p)); assert not ok and "line 1" in msg
