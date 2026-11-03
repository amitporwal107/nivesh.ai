"""The Mongo query and update semantics the in-memory test fakes share (Phase 1 risk reservation).

The risk reservation (services/paper_account.reserve_entry) is ONE conditional update whose filter uses dotted paths
into arrays (`reservations.id`), `$ne`, and an aggregation `$expr` with `$and` / `$add` / `$subtract` / `$ifNull` /
comparisons over dotted field paths, and whose update uses `$inc` on dotted paths, `$push`, `$pull` and `$max`. The
fakes in tests/test_desk_trading.py, tests/test_paper_account.py, tests/test_risk_gate.py and the AI-trader suite
evaluate filters and updates through here, so they all read the same documents the same way. Anything else fails
loudly: a fake that silently matched an expression it cannot read would pass a refusal it never checked.

This is NOT a substitute for the real-Mongo concurrency test (tests/test_risk_reservation_mongo.py), which runs the
same update against mongo:7.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

_MISSING = object()


def get_path(doc: Any, path: str) -> List[Any]:
    """Every value at a dotted path, descending into arrays the way Mongo does. [] when absent."""
    values = [doc]
    for part in path.split("."):
        nxt: List[Any] = []
        for v in values:
            if isinstance(v, dict):
                if part in v:
                    nxt.append(v[part])
            elif isinstance(v, list):
                if part.isdigit() and int(part) < len(v):
                    nxt.append(v[int(part)])
                else:
                    for item in v:
                        if isinstance(item, dict) and part in item:
                            nxt.append(item[part])
        values = nxt
    out: List[Any] = []
    for v in values:
        out.append(v)
    return out


def _candidates(values: List[Any]) -> List[Any]:
    """The values a scalar condition is compared with: each value, and each element of an array value."""
    out: List[Any] = []
    for v in values:
        out.append(v)
        if isinstance(v, list):
            out.extend(v)
    return out


def _cond(values: List[Any], cond: Any) -> bool:
    if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
        for op, arg in cond.items():
            cands = _candidates(values)
            if op == "$ne":
                if any(c == arg for c in cands):
                    return False
            elif op == "$exists":
                if bool(values) != bool(arg):
                    return False
            elif op == "$in":
                if not any(c in arg for c in cands) and not (None in arg and not values):
                    return False
            elif op == "$nin":
                if any(c in arg for c in cands):
                    return False
            elif op in ("$gt", "$gte", "$lt", "$lte"):
                ok = False
                for c in cands:
                    if isinstance(c, (int, float)) and not isinstance(c, bool) and isinstance(arg, (int, float)) \
                            or isinstance(c, str) and isinstance(arg, str):
                        ok = ok or {"$gt": c > arg, "$gte": c >= arg, "$lt": c < arg, "$lte": c <= arg}[op]
                if not ok:
                    return False
            elif op == "$type":
                assert arg == "string", f"the fake does not know $type {arg!r}"
                if not any(isinstance(c, str) for c in cands):
                    return False
            else:
                raise AssertionError(f"the fake does not know the query operator {op}")
        return True
    if cond is None:
        return not values or any(v is None for v in values)
    return any(c == cond for c in _candidates(values))


def expr(doc: Dict[str, Any], e: Any) -> Any:
    """An aggregation expression over one document."""
    if isinstance(e, str) and e.startswith("$"):
        vals = get_path(doc, e[1:])
        return vals[0] if vals else None
    if e is None or isinstance(e, (bool, int, float, str)):
        return e
    assert isinstance(e, dict) and len(e) == 1, f"the fake does not know the expression {e!r}"
    [(op, args)] = e.items()
    if op == "$and":
        return all(expr(doc, a) for a in args)
    if op == "$or":
        return any(expr(doc, a) for a in args)
    vals = [expr(doc, a) for a in args]
    if op == "$ifNull":
        return vals[0] if vals[0] is not None else vals[1]
    if op == "$add":
        return sum(vals)
    if op == "$subtract":
        return vals[0] - vals[1]
    a, b = vals
    if op == "$gte":
        return a >= b
    if op == "$gt":
        return a > b
    if op == "$lte":
        return a <= b
    if op == "$lt":
        return a < b
    if op == "$eq":
        return a == b
    raise AssertionError(f"the fake does not know {op}")


def match(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for key, cond in query.items():
        if key == "$expr":
            if not expr(doc, cond):
                return False
            continue
        if key == "$or":
            if not any(match(doc, q) for q in cond):
                return False
            continue
        assert not key.startswith("$"), f"the fake does not know the top-level operator {key}"
        if not _cond(get_path(doc, key), cond):
            return False
    return True


def _set_path(doc: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _get_one(doc: Dict[str, Any], path: str) -> Any:
    cur: Any = doc
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


KNOWN_UPDATES = {"$set", "$inc", "$setOnInsert", "$push", "$pull", "$max", "$unset", "$addToSet"}


def apply(doc: Dict[str, Any], update: Dict[str, Any], *, inserting: bool = False) -> None:
    assert set(update) <= KNOWN_UPDATES, f"the fake does not know {set(update) - KNOWN_UPDATES}"
    if inserting:
        for k, v in (update.get("$setOnInsert") or {}).items():
            _set_path(doc, k, copy.deepcopy(v))
    for k, v in (update.get("$set") or {}).items():
        _set_path(doc, k, copy.deepcopy(v))
    for k in (update.get("$unset") or {}):
        parts = k.split(".")
        cur = doc
        for p in parts[:-1]:
            cur = cur.get(p) if isinstance(cur, dict) else None
        if isinstance(cur, dict):
            cur.pop(parts[-1], None)
    for k, delta in (update.get("$inc") or {}).items():
        _set_path(doc, k, (_get_one(doc, k) or 0) + delta)
    for k, v in (update.get("$max") or {}).items():
        have = _get_one(doc, k)
        if have is None or v > have:
            _set_path(doc, k, v)
    for k, v in (update.get("$push") or {}).items():
        arr = _get_one(doc, k)
        if arr is None:
            arr = []
            _set_path(doc, k, arr)
        items = v["$each"] if isinstance(v, dict) and set(v) == {"$each"} else [v]
        arr.extend(copy.deepcopy(items))
    for k, v in (update.get("$addToSet") or {}).items():
        arr = _get_one(doc, k)
        if arr is None:
            arr = []
            _set_path(doc, k, arr)
        for item in (v["$each"] if isinstance(v, dict) and set(v) == {"$each"} else [v]):
            if item not in arr:
                arr.append(copy.deepcopy(item))
    for k, cond in (update.get("$pull") or {}).items():
        arr = _get_one(doc, k)
        if not isinstance(arr, list):
            continue
        if isinstance(cond, dict):
            arr[:] = [x for x in arr if not (isinstance(x, dict) and match(x, cond))]
        else:
            arr[:] = [x for x in arr if x != cond]
