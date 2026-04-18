"""Feature-flag allowlists.

Keeps features hidden from general users until battle-tested.
"""
from __future__ import annotations

# AI Copilot (scenario engine) — hidden until fully tested
COPILOT_ALLOWLIST: set[str] = {
    "aporwal107@gmail.com",
}


def is_copilot_enabled(email: str | None) -> bool:
    if not email:
        return False
    return email.lower().strip() in {e.lower() for e in COPILOT_ALLOWLIST}
