"""Optional LLM refiner (Phase 3): only candidates go to the model, its output is validated against a contract, it may move
materiality within bounds, and every affected entity it names must resolve in the entity map or is dropped. The key is
read from a file path, never from code, never logged. Tests use a fake client; one live smoke test is opt-in."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from nidp.tests.services.tpd_model.conftest import ist


def _ev(title, summary=None, symbol=None, source_id="nse_announcements_api", category=None, doc_text=None):
    return {"source_id": source_id, "title": title, "summary": summary, "symbol": symbol, "category": category, "doc_text": doc_text, "url": "https://x/y.pdf",
            "published_at": ist(datetime(2026, 9, 14).date(), 21, 2), "first_seen_at": ist(datetime(2026, 9, 14).date(), 21, 15), "hash": "h" + title[:12], "entity_text": None}


def test_candidates_are_the_non_routine_events_with_something_to_refine():
    from nidp.services.catalyst_intel.llm import is_candidate
    from nidp.services.catalyst_intel.rules import classify

    pnc = _ev("PNCINFRA: Action(s) taken or orders passed", "informed the Exchange about Action(s) taken or orders passed", "PNCINFRA", category="Action(s) taken or orders passed", doc_text="NHAI extended the debarment for three years")
    assert is_candidate(pnc, classify(pnc))
    tw = _ev("ACME: Trading Window", "Closure of trading window", "ACME", category="Trading Window")
    assert not is_candidate(tw, classify(tw))
    unk = _ev("ACME: Updates", "The company has informed the Exchange regarding an update", "ACME", category="Updates", doc_text="Sub: Update. The Company wishes to inform that it has commenced trial production at the new unit.")
    assert is_candidate(unk, classify(unk))                                # a generic update with a document the rules could not read: worth a look
    bare = _ev("ACME: Updates", "The company has informed the Exchange regarding an update", "ACME", category="Updates")
    assert not is_candidate(bare, classify(bare))                          # nothing to read: no call
    news = _ev("Markets close flat; Nifty ends at 24,000", source_id="et_stocks")
    assert not is_candidate(news, classify(news))                          # no entity, no rules hit, P2: skip


def test_key_is_read_from_a_file_and_never_echoed(tmp_path, monkeypatch):
    from nidp.services.catalyst_intel.llm import load_key

    kf = tmp_path / "k"; kf.write_text("sk-test-abc\n")
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(kf))
    assert load_key() == "sk-test-abc"
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(tmp_path / "missing"))
    with pytest.raises(FileNotFoundError):
        load_key()


def _fake_client(payload):
    class FakeResp:
        def __init__(self, content): self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]; self.usage = type("U", (), {"prompt_tokens": 500, "completion_tokens": 120})()
    class FakeCompletions:
        def __init__(self): self.calls = []
        def create(self, **kw): self.calls.append(kw); return FakeResp(json.dumps(payload))
    class FakeClient:
        def __init__(self): self.chat = type("Ch", (), {})(); self.chat.completions = FakeCompletions()
    return FakeClient()


def _entities():
    from nidp.services.catalyst_intel.entities import EntityMap
    names = "symbol,isin,company_name,sector,industry\nTATACHEM,INE092A01019,Tata Chemicals Limited,Chemicals,Chemicals\nTATAINVEST,INE672A01026,Tata Investment Corporation Limited,Finance,Financial Services\nPNCINFRA,INE195J01029,PNC Infratech Limited,Construction,Construction\n"
    return EntityMap.from_csv_text(names)


def test_refine_validates_the_contract_bounds_materiality_and_drops_unresolved_entities():
    from nidp.services.catalyst_intel.llm import refine
    from nidp.services.catalyst_intel.rules import classify

    e = _ev("RBI files caveat after rejecting Tata Sons bid to avoid market listing", "The RBI rejected Tata Sons' application to deregister as an NBFC", source_id="bs_companies")
    rules = classify(e)                                                    # regulatory_decision / rejection / negative / 80+
    payload = {"event_type": "REGULATORY", "event_subtype": "rejection", "direction": "positive", "materiality": 40, "novelty": 95, "confidence": 0.9,
               "time_horizon": "months", "economic_mechanism": "value_unlock", "entities": [{"name": "Reserve Bank of India", "role": "regulator"}, {"name": "Tata Sons", "role": "subject"}],
               "affected_listed": [{"name": "Tata Chemicals Limited", "why": "holds 2.53% of Tata Sons"}, {"name": "Unicorn Widgets Ltd", "why": "made up"}],
               "quantities": {}, "rationale": "Rejection keeps a listing on the table; group companies with stakes benefit"}
    client = _fake_client(payload)
    out = refine(e, rules, _entities(), client=client, model="fake-model")
    assert out["classifier"].startswith("llm:") and out["event_type"] == "REGULATORY" and out["event_subtype"] == "rejection" and out["classification_method"] == "RULE+LLM"
    assert out["direction"] == "positive"
    assert out["direction_rules"] == "positive"                            # the forced-listing rule already reads a denied exit from listing as positive for holders
    assert out["materiality"] == rules["materiality"] - 20 and out["materiality_rules"] == rules["materiality"]   # 40 clipped to the rules prior − 20
    assert [a["symbol"] for a in out["affected_listed"]] == ["TATACHEM"] and out["dropped_entities"] == ["Unicorn Widgets Ltd"]
    assert out["usage"]["prompt_tokens"] == 500 and "sk-" not in json.dumps(out)
    kw = client.chat.completions.calls[0]
    assert kw["model"] == "fake-model" and kw["response_format"]["type"] == "json_schema" and "Tata Sons" in kw["messages"][-1]["content"]


def test_refine_rejects_malformed_output_and_keeps_the_rules_result():
    from nidp.services.catalyst_intel.llm import refine
    from nidp.services.catalyst_intel.rules import classify

    e = _ev("PNCINFRA: Action(s) taken or orders passed", "informed the Exchange", "PNCINFRA", category="Action(s) taken or orders passed", doc_text="NHAI extended the debarment for three years")
    rules = classify(e)
    out = refine(e, rules, _entities(), client=_fake_client({"event_type": "not_a_type", "direction": "up"}), model="fake")
    assert out["classifier"].startswith("rules") and out["llm_error"].startswith("contract") and out["event_subtype"] == "debarment"


def test_refinements_are_cached_by_hash(tmp_path):
    from nidp.services.catalyst_intel.llm import RefineCache

    c = RefineCache(tmp_path); assert c.get("h1") is None
    c.put("h1", {"event_type": "order_win"}); assert c.get("h1") == {"event_type": "order_win"} and (tmp_path / "h1.json").exists()


@pytest.mark.skipif(not Path("/app/docs/.OPENAI_API_KEY").exists(), reason="no key file on this host")
def test_live_smoke_one_call_on_the_pnc_filing():
    """One real call (a few hundred tokens) proving the key, the schema and the bounds on the PNC benchmark."""
    from nidp.services.catalyst_intel.llm import make_client, refine
    from nidp.services.catalyst_intel.rules import classify

    e = _ev("PNCINFRA: Action(s) taken or orders passed", "PNC Infratech Limited has informed the Exchange about Action(s) taken or orders passed", "PNCINFRA", category="Action(s) taken or orders passed",
            doc_text="PNC Infratech Limited received a letter from NHAI on 11.09.2026, extending the debarment of Awadh Expressway Private Limited for a period of three years, to the Company being Promoter of the Concessionaire. "
                     "Company will not be able to participate in any bid of MoRTH/NHAI and their executing agencies for a period of three years.")
    out = refine(e, classify(e), _entities(), client=make_client(), model="gpt-4o-mini")
    assert out["classifier"].startswith("llm:"), out.get("llm_error")
    assert out["direction"] == "negative" and out["event_type"] == "REGULATORY" and out["materiality"] >= 70
    assert [a["symbol"] for a in out["affected_listed"]] == ["PNCINFRA"] and out["usage"]["prompt_tokens"] > 0
