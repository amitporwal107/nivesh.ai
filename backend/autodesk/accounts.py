"""Account and policy helpers shared by the API and the simulator."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from . import contracts as C
from . import store


def default_policy_body() -> dict:
    try:
        from .control.policy import default_policy_body as _d
        body = _d()
    except ImportError:   # control package not present (unit tests of the core alone)
        body = C.PolicyBody()
    return body.model_dump(mode="json") if hasattr(body, "model_dump") else dict(body)


async def ensure_default_policy(c, tenant_id: str, created_by: str) -> dict:
    """The tenant's default policy (scope TENANT), created on first use from the risk-profile defaults."""
    row = await c.fetchrow("""SELECT policy_id FROM autodesk.policies WHERE tenant_id=$1 AND scope_type='TENANT'
                              ORDER BY created_at LIMIT 1""", tenant_id)
    if row is not None:
        return await store.get_policy(c, tenant_id, row["policy_id"])
    created = await store.create_policy(c, tenant_id=tenant_id, name="Desk default", body=default_policy_body(),
                                        created_by=created_by, scope_type="TENANT",
                                        reason="default from the risk-profile defaults")
    return await store.get_policy(c, tenant_id, created["policy_id"])


async def open_account(c, *, tenant_id: str, name: str, kind: C.AccountKind, mode: C.OperatingMode,
                       capital: Decimal, created_by: str, policy_id: Optional[str] = None,
                       simulation_id: Optional[str] = None) -> dict:
    if policy_id is None:
        policy_id = (await ensure_default_policy(c, tenant_id, created_by))["policy_id"]
    else:
        await store.get_policy(c, tenant_id, policy_id)   # tenant check
    return await store.create_account(c, tenant_id=tenant_id, name=name, kind=kind, operating_mode=mode,
                                      starting_capital_rs=capital, policy_id=policy_id, created_by=created_by,
                                      simulation_id=simulation_id)
