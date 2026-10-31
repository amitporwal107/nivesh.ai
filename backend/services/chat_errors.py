"""What the chat tells the user when an answer could not be finished (owner, 31 Oct 2026).

The staging Copilot's language model runs through a gateway (`/opt/claude-gateway`) under one Claude login, whose 5-hour usage
limit the development sessions share. When it is spent the gateway answers 502 "You've hit your 5-hour limit · resets 10:50am
(Asia/Kolkata)", and the chat said only "trouble connecting". It now says what happened and when it should be back; the raw
error stays in the log. Every other error keeps the generic text.
"""
from __future__ import annotations

import re

GENERIC = "I'm having trouble connecting right now. Please try again."
_LIMIT = re.compile(r"5-hour limit|usage limit|hit your .{0,30}limit", re.I)
_RESET = re.compile(r"resets\s+(\d{1,2})(?::(\d{2}))?\s*([ap])m\s*\(([^)]+)\)", re.I)
_IST_NAMES = {"asia/kolkata", "asia/calcutta", "ist"}


def friendly_error(e: BaseException) -> str:
    """The text for the user for an error that ended an answer."""
    text = str(e)
    if not _LIMIT.search(text):
        return GENERIC
    when = None
    m = _RESET.search(text)
    if m and m.group(4).strip().lower() in _IST_NAMES:                       # a time in another zone is not claimed as IST
        when = f"{int(m.group(1))}:{m.group(2) or '00'} {m.group(3).upper()}M IST"
    return ("The AI assistant has reached its usage limit, so it cannot write an explanation right now"
            + (f"; it should be back around {when}" if when else "")
            + ". The figures and charts on your screen are not affected. Please try again later.")
