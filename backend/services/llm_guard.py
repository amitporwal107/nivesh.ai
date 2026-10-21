"""Nothing personal reaches a model provider, from any call site.

The rule (user, 2026-10-22): PAN, Aadhaar, mobile, address and date of birth are not sent to an LLM
"in any case", and not "in plain text or encrypted form" — so not as a hash or any other derivative
of the value either. `llm_safety` does the masking; this module makes it unskippable.

WHY A PATCH AND NOT A WRAPPER AT EACH CALL SITE
There are twelve independent client constructions across services/ and routes/ and no shared
factory, so a per-call-site edit protects only the sites that exist today: the next one someone adds
leaks silently, which is the failure this is meant to make impossible. `install()` therefore wraps
the SDK's own request methods once, at startup, so every present and future call goes through it:

    openai.resources.chat.completions.Completions.create   (and AsyncCompletions)
    anthropic.resources.messages.Messages.create           (and AsyncMessages)

FAIL CLOSED
After redaction the payload is scanned again. If anything personal survived, the call RAISES
(`PiiWouldLeak`) instead of being sent. A false positive costs one failed request and a loud log; a
false negative sends a user's PAN to a third party. The trade is deliberate.

WHAT THIS CANNOT DO, stated because it bounds the promise
  * Images and PDFs sent as base64 blocks are passed through untouched. A CAS page photographed or
    attached still shows whatever it shows. Redaction is a text operation.
  * `llm_safety.redact_pii` matches date of birth and address only where the text labels them. Prose
    like "I was born in March 1980" is not a pattern; `llm_safety.redact_values` covers that for
    values the product already holds, and callers that hold them should pass them.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from services import llm_safety

logger = logging.getLogger(__name__)

_installed = False

#: Kwargs whose text is redacted before a request leaves the process.
_TEXT_KWARGS = ("system", "prompt", "instructions")


class PiiWouldLeak(RuntimeError):
    """A request still contained a personal detail after redaction; it was not sent."""


def _clean_text(value: Any) -> Any:
    return llm_safety.redact_pii(value) if isinstance(value, str) else value


def _clean_content(content: Any) -> Any:
    """Message content is either a string or a list of blocks. Text blocks are redacted; image and
    document blocks are left alone and reported by `describe_unscannable`."""
    if isinstance(content, str):
        return llm_safety.redact_pii(content)
    if isinstance(content, list):
        out: List[Any] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                block = {**block, "text": llm_safety.redact_pii(block["text"])}
            out.append(block)
        return out
    return content


def _clean_messages(messages: Any) -> Any:
    if not isinstance(messages, list):
        return messages
    out = []
    for m in messages:
        if isinstance(m, dict) and "content" in m:
            m = {**m, "content": _clean_content(m["content"])}
        out.append(m)
    return out


def _scannable_text(kwargs: Dict[str, Any]) -> str:
    """Every piece of text in the request, concatenated, for the fail-closed check."""
    parts: List[str] = []
    for key in _TEXT_KWARGS:
        v = kwargs.get(key)
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(b["text"] for b in v if isinstance(b, dict) and isinstance(b.get("text"), str))
    for m in kwargs.get("messages") or []:
        if not isinstance(m, dict):
            continue
        c = m.get("content")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            parts.extend(b["text"] for b in c if isinstance(b, dict) and isinstance(b.get("text"), str))
    return "\n".join(parts)


def describe_unscannable(kwargs: Dict[str, Any]) -> List[str]:
    """Block types in the request that redaction cannot read (images, documents)."""
    kinds = set()
    for m in kwargs.get("messages") or []:
        for block in (m.get("content") if isinstance(m, dict) else None) or []:
            if isinstance(block, dict):
                t = block.get("type")
                if t and t != "text":
                    kinds.add(str(t))
    return sorted(kinds)


def sanitize(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Redact every text field, then refuse the call if anything personal survived."""
    cleaned = dict(kwargs)
    if "messages" in cleaned:
        cleaned["messages"] = _clean_messages(cleaned["messages"])
    for key in _TEXT_KWARGS:
        if key in cleaned:
            cleaned[key] = _clean_content(cleaned[key]) if isinstance(cleaned[key], list) else _clean_text(cleaned[key])

    remaining = llm_safety.scan(_scannable_text(cleaned))
    if remaining:
        # Deliberately does not log the text: that would move the secret into the log file.
        raise PiiWouldLeak(
            "the request still contains " + ", ".join(sorted(remaining)) +
            " after redaction, so it was not sent. This is a bug in llm_safety.redact_pii; "
            "fix the pattern rather than relaxing this check."
        )
    unscannable = describe_unscannable(cleaned)
    if unscannable:
        logger.info("llm_guard: request carries non-text blocks that cannot be redacted: %s",
                    ", ".join(unscannable))
    return cleaned


def _wrap(owner: type, name: str = "create") -> bool:
    original = getattr(owner, name, None)
    if original is None or getattr(original, "_pii_guarded", False):
        return False

    import functools
    import inspect

    if inspect.iscoroutinefunction(original):
        @functools.wraps(original)
        async def guarded(self, *args, **kwargs):
            return await original(self, *args, **sanitize(kwargs))
    else:
        @functools.wraps(original)
        def guarded(self, *args, **kwargs):
            return original(self, *args, **sanitize(kwargs))

    guarded._pii_guarded = True          # type: ignore[attr-defined]
    setattr(owner, name, guarded)
    return True


def install() -> List[str]:
    """Patch the provider SDKs once. Returns the targets actually wrapped, for the startup log.

    Import failures are not fatal: a provider that is not installed cannot leak through. A target
    that moves in a future SDK release WOULD silently stop being guarded, so the startup log names
    what was wrapped and `installed_targets()` lets a test assert the expected set.
    """
    global _installed
    wrapped: List[str] = []
    targets = [
        ("openai.resources.chat.completions", "Completions"),
        ("openai.resources.chat.completions", "AsyncCompletions"),
        ("anthropic.resources.messages", "Messages"),
        ("anthropic.resources.messages", "AsyncMessages"),
    ]
    import importlib

    for module_name, class_name in targets:
        try:
            owner = getattr(importlib.import_module(module_name), class_name)
        except Exception as e:  # noqa: BLE001 — a missing provider is not an error
            logger.info("llm_guard: %s.%s not available (%s)", module_name, class_name, type(e).__name__)
            continue
        if _wrap(owner):
            wrapped.append(f"{module_name}.{class_name}.create")
    _installed = True
    if wrapped:
        logger.warning("llm_guard: PII guard installed on %s", ", ".join(wrapped))
    else:
        logger.warning("llm_guard: nothing was wrapped — provider calls are NOT guarded")
    return wrapped


def installed_targets() -> List[str]:
    """Which of the expected targets currently carry the guard."""
    import importlib

    live = []
    for module_name, class_name in [
        ("openai.resources.chat.completions", "Completions"),
        ("openai.resources.chat.completions", "AsyncCompletions"),
        ("anthropic.resources.messages", "Messages"),
        ("anthropic.resources.messages", "AsyncMessages"),
    ]:
        try:
            owner = getattr(importlib.import_module(module_name), class_name)
        except Exception:  # noqa: BLE001
            continue
        if getattr(getattr(owner, "create", None), "_pii_guarded", False):
            live.append(f"{module_name}.{class_name}.create")
    return live
