"""Probe (scratch, not part of the repo): behaviour of the position-creating paths with the F&O gate OFF (staging's value).
Uses the repo's own fakes. MOCK — not real data: FIXA and its prices are the suites' fixtures."""
from tests.test_risk_gate_desk_journal import jh, _trade, U1, FILL, JOURNAL  # noqa: F401
from tests.test_desk_trading import api, world, trade_body, TRADES_URL, A  # noqa: F401
from tests.test_risk_gate import run
from services import risk_controls as rc


def test_journal_entry_fill_with_kill_switch_on_and_gate_off(jh):
    db, state, client = jh
    db["trade_journal"].docs.append(_trade())
    run(rc.set_control(db, "u1", field="kill_switch", value=True, reason="probe", actor="u1"))
    created = client.post(JOURNAL, json={"nse_symbol": "FIXA", "capital_alloc_rs": 50000}, headers=U1)
    fill = client.post(f"{JOURNAL}/t1/fill", json=dict(FILL, qty=100000, price=100), headers=U1)
    print("\nPROBE journal create with kill switch ON, gate OFF ->", created.status_code)
    print("PROBE journal ENTRY fill qty=100000 @100 (Rs 1 crore) with kill switch ON, gate OFF ->", fill.status_code,
          "fills now:", len(db["trade_journal"].docs[0]["fills"]), "decision rows:", len(db[rc.DECISIONS].docs))


def test_desk_same_trade_twice_and_no_governor(api, world):
    body = trade_body()
    r1 = api.post(TRADES_URL, json=body, headers=A)
    r2 = api.post(TRADES_URL, json=body, headers=A)
    big = dict(body, quantity=int(900_000 // body["entry_price"]))
    r3 = api.post(TRADES_URL, json=big, headers=A)
    print("\nPROBE desk body:", {k: body[k] for k in ("symbol", "quantity", "entry_price", "stop_price")})
    print("PROBE desk identical POST twice ->", r1.status_code, r2.status_code, "| a third at qty", big["quantity"], "->", r3.status_code,
          r3.json().get("detail", {}).get("code") if r3.status_code != 201 else "created")
    opened = [d for d in world.db.cols["desk_paper_trades"].docs if d["status"] == "open"]
    print("PROBE open trades for the same symbol:", sum(1 for d in opened if d["symbol"] == body["symbol"]))
