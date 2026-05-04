"""Retrieval-driven Copilot pipeline.

Replaces the "dump everything into the system prompt" pattern that was
making gpt-4o-mini hallucinate fund names from training data. New flow:

    user message
        │
        ▼
  intent_router  ──► one of: ranking | concentration | overlap | tax |
        │              goals | holding_lookup | generic | empty_portfolio
        ▼
   retrievers     ──► deterministic SQL/Mongo query, returns a SMALL
        │              structured payload (~500 chars max)
        ▼
   chart_specs    ──► (when applicable) deterministic chart JSON
        │              computed server-side — never asked from LLM
        ▼
   orchestrator   ──► assembles tight LLM context + chart specs +
        │              suggested follow-ups
        ▼
   ai_engine.chat ──► LLM reasons over the small precise payload
                     and ONLY writes prose; charts ride along separately

Public surface is just `answer(user_id, message)` — everything else is
internal. The chat endpoint wraps this and adds session/history glue.
"""
from .orchestrator import answer  # noqa: F401
from .intent_router import classify_intent  # noqa: F401
