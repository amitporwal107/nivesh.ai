"""Streaming helpers for the copilot graph.

`emit_widget` lets a specialist node push its widget to the SSE stream the
moment the widget DATA is ready — which is right after the tools run and BEFORE
the LLM writes the narrative. The widget is deterministic from the tool results
(the LLM only writes the explanation), so emitting it early means the client
renders the chart/table first and then streams the text underneath it, instead
of the widget popping in at the very end.

It dispatches a LangChain custom event that surfaces in `graph.astream_events`
as `on_custom_event` (name=``copilot_widget``). Outside a streaming run (e.g.
the blocking /chat/send path) or on any error it is a harmless no-op — the
widget still rides on the final AgentResponse.
"""
from __future__ import annotations

from typing import Any


async def emit_widget(widget_type: Any, widget_data: Any) -> None:
    try:
        wt = widget_type.value if hasattr(widget_type, "value") else str(widget_type)
    except Exception:  # noqa: BLE001
        wt = str(widget_type)
    if not widget_data or not wt or wt in ("none", "WidgetType.NONE"):
        return
    try:
        from langchain_core.callbacks.manager import adispatch_custom_event
        await adispatch_custom_event(
            "copilot_widget", {"widget_type": wt, "widget_data": widget_data}
        )
    except Exception:  # noqa: BLE001 — not in a stream, or dispatch unsupported
        pass
