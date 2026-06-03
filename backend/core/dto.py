"""DTO (Data Transfer Object) filtering helpers.

Strips internal/system fields from MongoDB documents before they are sent
to API clients. All routes should pass raw Mongo dicts through ``clean``
(or ``clean_list``) rather than returning them directly.

Internal fields stripped by default
-------------------------------------
``_id``         MongoDB ObjectId — never useful to clients, can leak internals.
``__v``         Mongoose version key (only present in legacy documents).

Fields that are intentionally kept
-------------------------------------
``user_id``     Kept so admin/advisor routes can return cross-user data properly.
                Client routes don't expose this in practice because the frontend
                already knows its own user_id from the session.
``created_at``  Audit timestamp — useful for display ("added 3 days ago").
``updated_at``  Same.

Usage::

    from core.dto import clean, clean_list

    doc = await db.portfolios.find_one({"portfolio_id": pid})
    return clean(doc)

    docs = await db.holdings.find({"user_id": uid}).to_list(2000)
    return clean_list(docs)
"""
from __future__ import annotations

from typing import Any

# Fields stripped from every MongoDB document before it reaches the client.
_STRIP = frozenset({"_id", "__v"})


def clean(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a copy of *doc* with internal fields removed.

    Returns ``None`` if *doc* is ``None`` (pass-through for find_one → 404 paths).
    """
    if doc is None:
        return None
    return {k: v for k, v in doc.items() if k not in _STRIP}


def clean_list(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply :func:`clean` to every document in *docs*."""
    return [clean(d) for d in docs]  # type: ignore[misc]
