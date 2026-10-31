"""Auto-suggestions & smart queries (owner brief, 30 Oct 2026; docs/daily_trader_copilot/audits/E_suggestions.md).

Four tabs (For you, Market, My trades, F&O Lab) of suggestion cards, each a question that opens the same visual answer
as typing it. Every card comes from a rule over real data with its as-of date, carries one class (informational /
validated_signal / risk_alert) with its own wording, and can be dismissed, marked useful or not relevant, refreshed,
and explained ("Why am I seeing this?"). A source that is stale or missing produces no card; the tab says so.

    catalog.py  tabs, classes and their wording, query templates, rules (the seed for the Mongo stores)
    inputs.py   the sources a rule reads, with their as-of dates (market cached, personal per user); read-only
    rules.py    one pure evaluator per trigger
    engine.py   gate → evaluate → rank → dedupe → persist; tab view; "why"; the scheduled pass
    store.py    the five stores: suggestion_rules, query_templates, suggestion_events, suggestion_instances,
                suggestion_feedback

Ideas to review, not advice: nothing here places an order or tells the user to buy, sell, exit or hold.
"""
from . import catalog, engine, store

__all__ = ["catalog", "engine", "store"]
