"""Route inventory: no route can create a position without the universal risk service (Phase 1 item 1.7; TESTCASES
U-1, U-2 in test_reports/p1_universal_risk_TESTCASES.md). Modelled on tests/test_order_path_guard.py: an AST check, so a
comment or a docstring cannot satisfy it.

For every route handler in backend/routes/*.py (a function decorated with `<router>.post/put/patch/delete/get`), the
module-local functions it calls are followed transitively. If that call graph WRITES A POSITION — an `insert_one` /
`insert_many` / `replace_one` / `bulk_write` into `desk_paper_trades`, `trade_journal`, `ai_trader_tickets` or
`oms_orders`, or an `update_one` that `$push`es a fill — the same call graph must call `risk_service.enforce(...)` or
`risk_service.enter(...)` (services/risk_gate/service.py). Writes that only close, cancel, reject or expire are not
position-creating and are not in scope.

The collection is resolved from the subscript text: `db[svc.TRADES]`, `db[desk.TRADES]`, `db[base.TRADES]` ->
desk_paper_trades; `db[execution.TICKETS]` -> ai_trader_tickets; `db[COL]` in routes/positional_journal.py and
`db["trade_journal"]` -> trade_journal; `db["oms_orders"]` / `db[oms.ORDERS]` -> oms_orders.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

BACKEND = Path(__file__).resolve().parents[1]
ROUTES = BACKEND / "routes"
STORES = {"desk_paper_trades", "trade_journal", "ai_trader_tickets", "oms_orders"}
STORE_EXPRS = {
    "svc.TRADES": "desk_paper_trades", "desk.TRADES": "desk_paper_trades", "base.TRADES": "desk_paper_trades",
    "TRADES": "desk_paper_trades", "execution.TICKETS": "ai_trader_tickets", "TICKETS": "ai_trader_tickets",
    "oms.ORDERS": "oms_orders", "ORDERS": "oms_orders",
}
CREATE_CALLS = {"insert_one", "insert_many", "replace_one", "bulk_write"}
SERVICE_CALLS = {"enforce", "enter"}
SERVICE_MODULES = {"risk_service"}
ROUTE_DECORATORS = {"post", "put", "patch", "delete", "get", "api_route"}

#: Every position-creating route that exists today: the inventory must find exactly these (U-2), so a path that slips
#: out of the scan (renamed, moved) fails here instead of passing unseen.
EXPECTED_PATHS = {
    ("routes/desk_trading.py", "create_paper_trade"),            # P1 cash, P2 strategy
    ("routes/desk_trading.py", "roll_paper_trade"),              # P7 the F&O roll's new structure (#362)
    ("routes/positional_journal.py", "create_trade"),            # P3
    ("routes/positional_journal.py", "add_fill"),                # P4
    ("routes/ai_trader.py", "strategy_signals"),                 # P5
    ("routes/ai_trader.py", "confirm_ticket"),                   # P6
}


def _src(node: ast.AST) -> str:
    return ast.unparse(node)


def _store(subscript: ast.Subscript, module_consts: Dict[str, str], rel: str) -> Optional[str]:
    key = subscript.slice
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return key.value if key.value in STORES else None
    text = _src(key)
    if text in module_consts:
        return module_consts[text] if module_consts[text] in STORES else None
    return STORE_EXPRS.get(text)


def _module_consts(tree: ast.Module) -> Dict[str, str]:
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def _pushes_a_fill(call: ast.Call) -> bool:
    for arg in list(call.args[1:2]) + [k.value for k in call.keywords if k.arg == "update"]:
        if isinstance(arg, ast.Dict):
            for k, v in zip(arg.keys, arg.values):
                if isinstance(k, ast.Constant) and k.value == "$push" and "fills" in _src(v):
                    return True
    return False


def scan(source: str, rel: str) -> Dict[str, Dict[str, object]]:
    """{handler: {"writes": {stores}, "service": bool, "route": bool}} for every function in one module, with the
    module-local call graph folded in."""
    tree = ast.parse(source)
    consts = _module_consts(tree)
    funcs: Dict[str, ast.AST] = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    direct: Dict[str, Tuple[Set[str], bool, Set[str]]] = {}
    for name, fn in funcs.items():
        writes: Set[str] = set()
        service = False
        calls: Set[str] = set()
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute):
                if f.attr in SERVICE_CALLS and isinstance(f.value, ast.Name) and f.value.id in SERVICE_MODULES:
                    service = True
                if isinstance(f.value, ast.Subscript):
                    store = _store(f.value, consts, rel)
                    if store and (f.attr in CREATE_CALLS or (f.attr == "update_one" and _pushes_a_fill(node))):
                        writes.add(store)
            elif isinstance(f, ast.Name) and f.id in funcs:
                calls.add(f.id)
        direct[name] = (writes, service, calls)

    def fold(name: str, seen: Set[str]) -> Tuple[Set[str], bool]:
        writes, service, calls = direct[name]
        writes, service = set(writes), service
        for c in calls - seen:
            w, s = fold(c, seen | {c})
            writes |= w
            service = service or s
        return writes, service

    out: Dict[str, Dict[str, object]] = {}
    for name, fn in funcs.items():
        route = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ROUTE_DECORATORS
                    for d in getattr(fn, "decorator_list", []))
        writes, service = fold(name, {name})
        out[name] = {"writes": writes, "service": service, "route": route}
    return out


def inventory() -> List[Tuple[str, str, Set[str], bool]]:
    rows = []
    for path in sorted(ROUTES.glob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        for name, info in scan(path.read_text(), rel).items():
            if info["route"] and info["writes"]:
                rows.append((rel, name, info["writes"], info["service"]))
    return rows


def test_u1_every_position_creating_route_calls_the_risk_service():
    missing = [(rel, name, sorted(writes)) for rel, name, writes, service in inventory() if not service]
    assert missing == [], f"routes that create a position without risk_service.enforce/enter: {missing}"


def test_u2_the_inventory_finds_all_six_paths_and_nothing_unexpected():
    found = {(rel, name) for rel, name, _w, _s in inventory()}
    assert found == EXPECTED_PATHS, f"found {sorted(found)}"


def test_the_check_can_fail_a_route_that_writes_without_the_service():
    bad = '''
from fastapi import APIRouter
router = APIRouter()
TRADES = "desk_paper_trades"

async def _write(doc):
    await db[TRADES].insert_one(doc)

@router.post("/sneaky")
async def sneaky(request):
    await _write({"symbol": "X"})

@router.post("/fill")
async def fill(request):
    await db["trade_journal"].update_one({"_id": 1}, {"$push": {"fills": {}}})

@router.post("/ok")
async def ok(request):
    await risk_service.enforce(db, req)
    await db[TRADES].insert_one({})
'''
    info = scan(bad, "routes/bad.py")
    assert info["sneaky"]["writes"] == {"desk_paper_trades"} and info["sneaky"]["service"] is False
    assert info["fill"]["writes"] == {"trade_journal"} and info["fill"]["service"] is False
    assert info["ok"]["service"] is True


def test_no_route_reaches_the_oms_order_store_without_the_service():
    """services/oms/orders.create_order writes oms_orders; no route may call it without the service."""
    callers = []
    for path in sorted(ROUTES.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "create_order":
                callers.append(path.name)
    assert callers == []
