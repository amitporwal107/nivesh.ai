"""The order-path guard (test_reports/fno_risk_foundation_TESTCASES.md, G-1 to G-5).

Two properties of backend/ (tests excluded), checked on the AST so a comment or a docstring cannot trip them:

  * no call to an order method — place_order, modify_order, cancel_order, place_gtt, modify_gtt, cancel_gtt —
    directly or through getattr(obj, "<name>"), outside `services/oms/adapters/`. That directory need not exist yet:
    when live execution is built (Kite Connect, in the user's own session) the adapter lives there, behind the risk
    gate, and nowhere else.
  * no pass-through catch-all route: an `api_route` / `add_api_route` registration (several methods, the proxy shape)
    whose path has a `{...:path}` segment, or any route whose path IS a catch-all from the router's root
    ("/{x:path}"). The OpenAlgo reverse proxy was one: an unauthenticated pass-through to a trading engine. The
    existing entries are admin-only proxies to the data platform's admin API; each is named below with its reason,
    and its handler must begin with `await require_admin(...)`. A new one fails here.
    A single-method route with a trailing file-name parameter (GET .../{target_date}/{filename:path}) is not a
    pass-through and is not flagged.
"""
from __future__ import annotations

import ast
import functools
import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

BACKEND = Path(__file__).resolve().parents[1]
ORDER_METHODS = {"place_order", "modify_order", "cancel_order", "place_gtt", "modify_gtt", "cancel_gtt"}
ADAPTERS_DIR = ("services", "oms", "adapters")
ROUTE_CALLS = {"api_route", "route", "get", "post", "put", "patch", "delete", "head", "options", "websocket",
               "add_api_route", "add_api_websocket_route"}
MULTI_METHOD = {"api_route", "route", "add_api_route"}
CATCH_ALL = re.compile(r"\{[^{}]*:path\}")
ROOT_CATCH_ALL = re.compile(r"^/?\{[^{}]*:path\}$")
SKIP_PARTS = {"tests", "__pycache__", "node_modules", ".venv", "venv"}

#: (file relative to backend/, handler name) → why it is allowed.
CATCH_ALL_ALLOWED: Dict[Tuple[str, str], str] = {
    ("routes/admin_nidp.py", "grafana_proxy"): "admin-only Grafana UI proxy (observability)",
    ("routes/admin_nidp.py", "dq_proxy"): "admin-only proxy to the data platform's /v1/dq/* (data quality)",
    ("routes/admin_nidp_replay.py", "replay_proxy"): "admin-only proxy to the data platform's /v1/replay/*",
    ("routes/admin_nidp_backfill.py", "backfill_proxy"): "admin-only proxy to the data platform's /v1/backfill/*",
}


def python_files(root: Path = BACKEND) -> Iterator[Tuple[str, Path]]:
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if SKIP_PARTS & set(rel.parts) or rel.name.startswith("test_"):
            continue
        yield rel.as_posix(), path


def in_adapters(rel: str) -> bool:
    parts = tuple(rel.split("/"))
    return parts[:len(ADAPTERS_DIR)] == ADAPTERS_DIR


def _call_name(node: ast.Call) -> Optional[str]:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def order_calls(tree: ast.AST) -> List[Tuple[int, str]]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name in ORDER_METHODS:
            found.append((node.lineno, name))
        elif (name == "getattr" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
              and node.args[1].value in ORDER_METHODS):
            found.append((node.lineno, f"getattr:{node.args[1].value}"))
    return found


def _route_path(node: ast.Call) -> Optional[str]:
    candidates = list(node.args[:1]) + [k.value for k in node.keywords if k.arg == "path"]
    for arg in candidates:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _is_catch_all(call: str, path: str) -> bool:
    return bool(ROOT_CATCH_ALL.match(path)) or (call in MULTI_METHOD and bool(CATCH_ALL.search(path)))


def catch_alls(tree: ast.AST) -> List[Tuple[int, str, str]]:
    """(line, handler name or "<call>", path) for every pass-through catch-all route registration."""
    return [(line, name, path) for line, name, path, _ in _catch_all_nodes(tree)]


def _catch_all_nodes(tree: ast.AST):
    handler_of: Dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                handler_of[id(dec)] = node
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ROUTE_CALLS:
            path = _route_path(node)
            if path is not None and _is_catch_all(node.func.attr, path):
                handler = handler_of.get(id(node))
                found.append((node.lineno, getattr(handler, "name", "<call>"), path, handler))
    return found


def starts_with_require_admin(handler: Optional[ast.AST]) -> bool:
    """True when the handler's first statement (after a docstring) is `await require_admin(...)`."""
    body = list(getattr(handler, "body", []))
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    first = body[0] if body else None
    return (isinstance(first, ast.Expr) and isinstance(first.value, ast.Await)
            and isinstance(first.value.value, ast.Call) and _call_name(first.value.value) == "require_admin")


@functools.lru_cache(maxsize=1)
def _scan() -> Tuple[List[str], List[str], List[str], List[Tuple[str, str]]]:
    scanned, orders, routes, allowed_seen = [], [], [], []
    for rel, path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        scanned.append(rel)
        if not in_adapters(rel):
            orders += [f"{rel}:{line} {name}" for line, name in order_calls(tree)]
        for line, handler, route, node in _catch_all_nodes(tree):
            if (rel, handler) in CATCH_ALL_ALLOWED and starts_with_require_admin(node):
                allowed_seen.append((rel, handler))
            else:
                routes.append(f"{rel}:{line} {handler} {route}")
    return scanned, orders, routes, allowed_seen


# ── the scanners themselves (so a pass means something) ──────────────────────
def test_the_order_scanner_finds_a_direct_call_and_one_through_getattr():
    tree = ast.parse("kite.place_order(variety='regular')\nx = getattr(k, 'cancel_gtt')(1)\n"
                     "# place_order in a comment\ns = 'modify_order'\n")
    assert order_calls(tree) == [(1, "place_order"), (2, "getattr:cancel_gtt")]


def test_only_the_adapters_directory_is_exempt():
    assert in_adapters("services/oms/adapters/kite.py")
    assert not in_adapters("services/oms/kite.py")
    assert not in_adapters("routes/services/oms/adapters/x.py")


def test_the_catch_all_scanner_finds_proxies_and_root_catch_alls_but_not_file_names():
    tree = ast.parse(
        "@router.api_route('/c/{account_id}/{path:path}', methods=['GET', 'POST'])\nasync def proxy(path): ...\n"
        "@router.get('/{rest:path}')\nasync def root(rest): ...\n"
        "router.add_api_route(path='/x/{p:path}', endpoint=f)\n"
        "@router.get('/archive/{day}/{filename:path}')\nasync def download(day, filename): ...\n"
        "@router.get('/{symbol}/expiries')\nasync def fine(symbol): ...\n")
    assert catch_alls(tree) == [(1, "proxy", "/c/{account_id}/{path:path}"), (3, "root", "/{rest:path}"),
                                (5, "<call>", "/x/{p:path}")]


def test_an_allowlisted_proxy_must_begin_by_requiring_an_admin():
    guarded = ast.parse("async def p(tail, request):\n    'doc'\n    await require_admin(request)\n    return 1\n")
    late = ast.parse("async def p(tail, request):\n    x = 1\n    await require_admin(request)\n")
    assert starts_with_require_admin(guarded.body[0]) and not starts_with_require_admin(late.body[0])


# ── the repository ───────────────────────────────────────────────────────────
def test_the_scan_covers_the_backend_it_claims_to():
    scanned, _, _, _ = _scan()
    # A path typo must fail the test, not quietly scan nothing.
    assert {"routes/desk_trading.py", "routes/admin_nidp.py", "services/risk_controls.py",
            "services/brokers/zerodha.py", "server.py"} <= set(scanned)
    assert len(scanned) > 300
    assert not any(rel.startswith("tests/") for rel in scanned)


def test_no_order_method_is_called_outside_the_oms_adapters():
    _, orders, _, _ = _scan()
    assert orders == []


def test_no_router_has_a_catch_all_route_except_the_named_admin_proxy():
    _, _, routes, allowed_seen = _scan()
    assert routes == []
    # A stale allowlist entry is noticed instead of silently allowing a future handler of that name.
    assert sorted(allowed_seen) == sorted(CATCH_ALL_ALLOWED)


def test_the_openalgo_proxy_is_gone():
    assert not (BACKEND / "routes" / "openalgo_proxy.py").exists()
    server = (BACKEND / "server.py").read_text(encoding="utf-8")
    assert "openalgo_proxy" not in server and "/api/openalgo" not in server
