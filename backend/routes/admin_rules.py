"""Admin routes for V2 Rules Config + LLM Prompts management.

All endpoints require admin (session cookie + is_admin=true).
"""
from fastapi import APIRouter, HTTPException, Request
from typing import Any, Dict
import logging

from deps import require_admin
from services import rules_config, prompts_manager
from services.rules_dsl import safe_eval, validate_expression, SafeEvalError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin")


# ── Rules Config ─────────────────────────────────────────────────────────

@router.get("/rules-config")
async def get_rules_config(request: Request) -> Dict[str, Any]:
    """Return effective rules config + defaults for diff display."""
    await require_admin(request)
    cfg = await rules_config.get_config(refresh=True)
    return {"config": cfg, "defaults": rules_config.DEFAULTS}


@router.put("/rules-config")
async def update_rules_config(request: Request) -> Dict[str, Any]:
    """Replace the rules-config overrides with the posted payload."""
    admin = await require_admin(request)
    body = await request.json()
    cfg = await rules_config.save_overrides(body, updated_by=admin.get("email"))
    return {"ok": True, "config": cfg}


@router.post("/rules-config/reset")
async def reset_rules_config(request: Request) -> Dict[str, Any]:
    admin = await require_admin(request)
    cfg = await rules_config.reset_to_defaults(updated_by=admin.get("email"))
    return {"ok": True, "config": cfg}


# ── Custom Rules (Phase 2) ───────────────────────────────────────────────

_ALLOWED_CONTEXT_KEYS = [
    "portfolio_score", "confidence_score", "total_value",
    "equity_pct", "debt_pct", "gold_pct",
    "max_category_pct", "max_amc_pct", "avg_overlap_pct",
    "mf_count", "stock_count", "fund_count",
]
_ALLOWED_ACTION_TYPES = ["FLAG_ONLY", "ADD_DEBT_FUND", "EXIT_HIGHEST_EXIT_SCORE"]


@router.get("/rules-config/custom")
async def list_custom_rules(request: Request) -> Dict[str, Any]:
    await require_admin(request)
    cfg = await rules_config.get_config(refresh=True)
    return {
        "custom_rules": cfg.get("custom_rules", []),
        "allowed_context_keys": _ALLOWED_CONTEXT_KEYS,
        "allowed_action_types": _ALLOWED_ACTION_TYPES,
    }


@router.post("/rules-config/custom")
async def upsert_custom_rule(request: Request) -> Dict[str, Any]:
    """Add a new custom rule or update an existing one (by id)."""
    admin = await require_admin(request)
    body = await request.json()
    rule_id = (body.get("id") or "").strip()
    name = (body.get("name") or "").strip()
    expression = (body.get("expression") or "").strip()
    action_type = (body.get("action_type") or "").strip()

    if not name or not expression or not action_type:
        raise HTTPException(status_code=400, detail="name, expression, action_type required")
    if action_type not in _ALLOWED_ACTION_TYPES:
        raise HTTPException(status_code=400, detail=f"action_type must be one of {_ALLOWED_ACTION_TYPES}")

    validation = validate_expression(expression)
    if not validation["ok"]:
        raise HTTPException(status_code=400, detail=f"expression: {validation['error']}")
    unknown = [n for n in validation["names_used"] if n not in _ALLOWED_CONTEXT_KEYS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown context keys: {unknown}. Allowed: {_ALLOWED_CONTEXT_KEYS}")

    if not rule_id:
        from uuid import uuid4
        rule_id = f"r_{uuid4().hex[:10]}"

    entry = {
        "id": rule_id,
        "name": name,
        "description": body.get("description", ""),
        "enabled": bool(body.get("enabled", True)),
        "expression": expression,
        "action_type": action_type,
        "reason_code": (body.get("reason_code") or f"CUSTOM_{rule_id.upper()}")[:80],
        "reason_text": (body.get("reason_text") or name)[:400],
        "target": body.get("target") or {},
    }

    cfg = await rules_config.get_config(refresh=True)
    customs = list(cfg.get("custom_rules", []) or [])
    idx = next((i for i, r in enumerate(customs) if r.get("id") == rule_id), None)
    if idx is None:
        customs.append(entry)
    else:
        customs[idx] = entry

    new_cfg = await rules_config.save_overrides(
        {"rules": cfg["rules"], "plan_limits": cfg["plan_limits"], "custom_rules": customs},
        updated_by=admin.get("email"),
    )
    return {"ok": True, "rule": entry, "config": new_cfg}


@router.delete("/rules-config/custom/{rule_id}")
async def delete_custom_rule(rule_id: str, request: Request) -> Dict[str, Any]:
    admin = await require_admin(request)
    cfg = await rules_config.get_config(refresh=True)
    customs = [r for r in (cfg.get("custom_rules") or []) if r.get("id") != rule_id]
    new_cfg = await rules_config.save_overrides(
        {"rules": cfg["rules"], "plan_limits": cfg["plan_limits"], "custom_rules": customs},
        updated_by=admin.get("email"),
    )
    return {"ok": True, "config": new_cfg}


@router.post("/rules-config/custom/validate")
async def validate_custom_rule(request: Request) -> Dict[str, Any]:
    """Validate an expression + optionally evaluate against a sample context."""
    await require_admin(request)
    body = await request.json()
    expr = (body.get("expression") or "").strip()
    sample = body.get("sample_context") or {}
    v = validate_expression(expr)
    out: Dict[str, Any] = {
        "ok": v["ok"],
        "error": v["error"],
        "names_used": v["names_used"],
        "allowed_context_keys": _ALLOWED_CONTEXT_KEYS,
    }
    if v["ok"] and sample:
        # Fill missing keys with 0 to avoid SafeEvalError for undefined names
        ctx = {k: sample.get(k, 0) for k in _ALLOWED_CONTEXT_KEYS}
        try:
            out["evaluated"] = bool(safe_eval(expr, ctx))
        except SafeEvalError as e:
            out["ok"] = False
            out["error"] = str(e)
    return out


# ── Prompts Manager ──────────────────────────────────────────────────────

@router.get("/prompts")
async def list_prompts(request: Request) -> Dict[str, Any]:
    await require_admin(request)
    return {"prompts": await prompts_manager.list_all()}


@router.get("/prompts/{name}")
async def get_prompt(name: str, request: Request) -> Dict[str, Any]:
    await require_admin(request)
    prompts = await prompts_manager.list_all()
    for p in prompts:
        if p["name"] == name:
            return p
    raise HTTPException(status_code=404, detail=f"Unknown prompt: {name}")


@router.put("/prompts/{name}")
async def update_prompt(name: str, request: Request) -> Dict[str, Any]:
    admin = await require_admin(request)
    body = await request.json()
    text = body.get("text") or ""
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="Prompt text required")
    try:
        res = await prompts_manager.save_override(name, text, updated_by=admin.get("email"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, **res}


@router.post("/prompts/{name}/reset")
async def reset_prompt(name: str, request: Request) -> Dict[str, Any]:
    admin = await require_admin(request)
    try:
        res = await prompts_manager.reset_override(name, updated_by=admin.get("email"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, **res}


@router.post("/prompts/{name}/test")
async def test_prompt(name: str, request: Request) -> Dict[str, Any]:
    """Run the prompt against a sample user message and return the LLM response.
    
    Uses gpt-4o-mini. Timeout 15s. Returns {system, user, response, error}.
    """
    await require_admin(request)
    body = await request.json()
    user_text = (body.get("user_text") or "Test message — summarize what you do in 2 lines.").strip()
    format_kwargs = body.get("format_kwargs") or {}

    # Safe fill for common template vars
    defaults = {"portfolio_context": "(no portfolio context provided in test)"}
    defaults.update(format_kwargs)

    system = await prompts_manager.get(name, **defaults)
    if not system:
        raise HTTPException(status_code=404, detail=f"Unknown prompt: {name}")

    try:
        from helpers import secrets as _secrets
        key = _secrets.get("OPENAI_API_KEY") or _secrets.get("EMERGENT_LLM_KEY")
        if not key:
            return {"system": system[:2000], "user": user_text,
                    "response": None, "error": "No LLM key configured"}
        from openai import AsyncOpenAI
        import asyncio
        client = AsyncOpenAI(api_key=key) if _secrets.get("OPENAI_API_KEY") else None
        if client is None:
            # Emergent key route — use emergentintegrations
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            chat = LlmChat(api_key=key, session_id=f"admin-test-{name}",
                           system_message=system).with_model("openai", "gpt-4o-mini")
            try:
                resp = await asyncio.wait_for(chat.send_message(UserMessage(text=user_text)), timeout=20)
            except asyncio.TimeoutError:
                return {"system": system[:2000], "user": user_text,
                        "response": None, "error": "LLM timeout after 20s"}
            return {"system": system[:2000], "user": user_text,
                    "response": str(resp)[:4000], "error": None}
        else:
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_text},
                    ],
                    max_tokens=500,
                    temperature=0.7,
                ), timeout=20,
            )
            return {"system": system[:2000], "user": user_text,
                    "response": resp.choices[0].message.content, "error": None}
    except Exception as e:  # noqa: BLE001
        logger.warning("prompt test failed: %s", e)
        return {"system": system[:2000], "user": user_text, "response": None, "error": str(e)}
