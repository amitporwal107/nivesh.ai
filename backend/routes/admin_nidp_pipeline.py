"""Admin surface for the 6-stage announcement -> RAG pipeline.

A thin proxy over the NIDP query API's /pipeline/stages. The stage semantics and
every SQL rule live there, next to the DB — this layer only enforces admin auth
and degrades gracefully, matching /api/admin/nidp/feeds/live.

Why a separate router rather than another endpoint on admin_nidp.py: that module
is ~1.1k lines and mixes gcloud control-plane calls with read surfaces. This is a
read-only monitoring surface with one dependency; keeping it separate matches the
newer admin_nidp_backfill / admin_nidp_replay split.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Request

from deps import require_admin
from services import nidp_query_client as _nq

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/nidp/pipeline", tags=["admin-nidp-pipeline"])


@router.get("/stages")
async def pipeline_stages(request: Request) -> Dict[str, Any]:
    """Six stages with counts + per-stage freshness.

    Returns db_error rather than raising when the query API is unreachable: the
    panel then renders a visible error instead of a blank page. A monitoring
    surface that goes blank when its backend dies is the failure it exists to
    report.
    """
    await require_admin(request)

    try:
        data = await _nq.get_pipeline_stages()
    except _nq.NidpQueryClientError as e:
        logger.warning("admin/nidp/pipeline/stages: query api unavailable: %s", e.detail)
        return {
            "generated_at": None,
            "stages": [],
            "summary": {"total": 0, "healthy": 0, "backlog": 0,
                        "lagging": 0, "stale": 0, "never": 0},
            "db_error": e.detail,
        }

    # Worst-first, so a lagging stage cannot hide below six healthy ones. Order
    # is otherwise pipeline order, which is what you want when reading it as a flow.
    _RANK = {"stale": 0, "never": 1, "lagging": 2, "backlog": 3, "healthy": 4}
    stages = data.get("stages") or []
    data["worst_state"] = (
        sorted((s.get("state", "never") for s in stages), key=lambda x: _RANK.get(x, 9))[0]
        if stages else "never"
    )
    return data
