"""Safe expression evaluator for V2 custom rules.

Design goals:
- NEVER use eval()/exec()/compile(). Parse with `ast` and walk a whitelisted
  node set. Any unknown node → raises SafeEvalError.
- Whitelisted nodes: constants, names (context lookup), comparisons, boolean
  ops, arithmetic, unary minus, subscripts, attribute access on dicts.
- Whitelisted callables: `min, max, abs, len, sum, round`.
- Evaluates against a context dict provided by the rule engine.

Example expressions:
    "portfolio_score < 50"
    "any(c.pct > 40 for c in categories)"          # comprehensions allowed
    "debt_pct < 15 and equity_pct > 85"
    "max_amc_pct > 20"

For the first cut we keep it simple — no comprehensions, just scalar
conditions over a flat context. That covers 95% of custom-rule needs.
"""
from __future__ import annotations
import ast
import operator as op
from typing import Any, Dict


class SafeEvalError(Exception):
    pass


_BIN_OPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
}
_CMP_OPS = {
    ast.Eq: op.eq, ast.NotEq: op.ne,
    ast.Lt: op.lt, ast.LtE: op.le,
    ast.Gt: op.gt, ast.GtE: op.ge,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}
_BOOL_OPS = {ast.And: all, ast.Or: any}
_UNARY_OPS = {ast.USub: op.neg, ast.UAdd: op.pos, ast.Not: op.not_}

_SAFE_FUNCS = {"min": min, "max": max, "abs": abs, "len": len, "sum": sum, "round": round}


def _eval(node: ast.AST, ctx: Dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, ctx)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in _SAFE_FUNCS:
            return _SAFE_FUNCS[node.id]
        if node.id not in ctx:
            raise SafeEvalError(f"Unknown name: {node.id}")
        return ctx[node.id]
    if isinstance(node, ast.Attribute):
        base = _eval(node.value, ctx)
        if isinstance(base, dict):
            if node.attr not in base:
                raise SafeEvalError(f"Unknown attribute: {node.attr}")
            return base[node.attr]
        raise SafeEvalError("Attribute access only allowed on dict")
    if isinstance(node, ast.Subscript):
        base = _eval(node.value, ctx)
        key = _eval(node.slice, ctx) if not isinstance(node.slice, ast.Constant) else node.slice.value
        return base[key]
    if isinstance(node, ast.BinOp):
        fn = _BIN_OPS.get(type(node.op))
        if not fn:
            raise SafeEvalError(f"Operator not allowed: {type(node.op).__name__}")
        return fn(_eval(node.left, ctx), _eval(node.right, ctx))
    if isinstance(node, ast.UnaryOp):
        fn = _UNARY_OPS.get(type(node.op))
        if not fn:
            raise SafeEvalError("Unary op not allowed")
        return fn(_eval(node.operand, ctx))
    if isinstance(node, ast.BoolOp):
        fn = _BOOL_OPS.get(type(node.op))
        if not fn:
            raise SafeEvalError("Bool op not allowed")
        return fn(_eval(v, ctx) for v in node.values)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        for op_node, comparator in zip(node.ops, node.comparators):
            cmp = _CMP_OPS.get(type(op_node))
            if not cmp:
                raise SafeEvalError(f"Comparison not allowed: {type(op_node).__name__}")
            right = _eval(comparator, ctx)
            if not cmp(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        func = _eval(node.func, ctx)
        if func not in _SAFE_FUNCS.values():
            raise SafeEvalError("Function calls restricted to safe builtins")
        args = [_eval(a, ctx) for a in node.args]
        return func(*args)
    raise SafeEvalError(f"Expression node not allowed: {type(node).__name__}")


def safe_eval(expr: str, ctx: Dict[str, Any]) -> Any:
    """Evaluate a whitelisted expression against ctx. Raises SafeEvalError on
    any unsupported construct or lookup failure.

    >>> safe_eval("a > 5 and b < 10", {"a": 6, "b": 3})
    True
    """
    if not isinstance(expr, str) or not expr.strip():
        raise SafeEvalError("Empty expression")
    if len(expr) > 500:
        raise SafeEvalError("Expression too long (>500 chars)")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise SafeEvalError(f"Syntax error: {e}")
    return _eval(tree, ctx)


def validate_expression(expr: str) -> Dict[str, Any]:
    """Validate without a real context — returns {ok, error, names_used}."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return {"ok": False, "error": f"Syntax error: {e}", "names_used": []}
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        if isinstance(node, (ast.Call,)) and not (
            isinstance(node.func, ast.Name) and node.func.id in _SAFE_FUNCS
        ):
            return {"ok": False, "error": "Only safe builtins allowed as functions", "names_used": list(names)}
    return {"ok": True, "error": None, "names_used": sorted(names - set(_SAFE_FUNCS))}
