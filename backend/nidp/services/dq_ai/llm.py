"""LLM client wrapper used by both diagnostics and expectation_author.

Resolves API key from OPENAI_API_KEY (or EMERGENT_LLM_KEY alias).
Forces structured JSON output via response_format=json_object.
"""
from __future__ import annotations

import json
import logging
import os
from nidp.shared.openai_key import get_openai_api_key
from typing import Any, Dict, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("DQ_AI_MODEL", "gpt-4o")


class LlmClient:
    """Thin wrapper around openai.OpenAI for JSON-structured analysis."""

    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        key = (
            api_key
            or get_openai_api_key()
            or os.environ.get("EMERGENT_LLM_KEY")
        )
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY (or EMERGENT_LLM_KEY) is not set — "
                "dq_ai cannot run without an LLM key"
            )
        self._client = OpenAI(api_key=key)
        self.model = model

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        """Call the model and require strict JSON output.

        Returns a tuple-like dict with keys:
          - ``data``: parsed JSON
          - ``prompt_tokens``: int
          - ``completion_tokens``: int
          - ``model``: model id used
        """
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        choice = resp.choices[0]
        try:
            parsed = json.loads(choice.message.content or "{}")
        except json.JSONDecodeError as e:
            logger.error("LLM returned non-JSON output: %s", e)
            raise
        return {
            "data": parsed,
            "prompt_tokens": (resp.usage.prompt_tokens if resp.usage else None),
            "completion_tokens": (resp.usage.completion_tokens if resp.usage else None),
            "model": resp.model or self.model,
        }
