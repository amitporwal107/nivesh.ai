"""The notifier: events in, Slack posts out. It never raises and never blocks a desk verdict."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from . import alerts
from .transport import SendResult, SlackWebhookTransport, Transport

log = logging.getLogger("autodesk.notify")
ENV_URL = "AUTODESK_SLACK_WEBHOOK_URL"


@dataclass(frozen=True)
class Outcome:
    seq: int
    status: str                  # SENT | FAILED | SUPPRESSED
    reason: Optional[str] = None
    key: Optional[str] = None


class Notifier:
    def __init__(self, transport: Optional[Transport], *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, dedupe_window: float = 900.0, per_minute: int = 10,
                 max_attempts: int = 3):
        self.transport = transport
        self.enabled = transport is not None
        self._clock, self._sleep = clock, sleep
        self._window, self._per_minute, self._attempts = dedupe_window, per_minute, max_attempts
        self._open: dict[str, dict] = {}        # key -> {"last": t, "skipped": n}
        self._sent_at: list[float] = []

    def __repr__(self) -> str:
        return f"Notifier(enabled={self.enabled})"

    def _deliver(self, text: str) -> SendResult:
        res = SendResult(ok=False, reason="not_sent")
        for attempt in range(self._attempts):
            try:
                res = self.transport.send(text)
            except Exception as e:
                res = SendResult(ok=False, reason=f"error:{type(e).__name__}")
            if res.ok or res.permanent:
                return res
            if attempt < self._attempts - 1:
                self._sleep(min(res.retry_after, 60.0) if res.retry_after else float(2 ** attempt))
        return res

    def process(self, events: list[dict[str, Any]]) -> list[Outcome]:
        """Post the support alerts among `events` (critical first). Returns one Outcome per alert. Never raises."""
        if not self.enabled:
            return []
        out: list[Outcome] = []
        try:
            found = [(e, a) for e in events if (a := alerts.classify(e)) is not None]
            found.sort(key=lambda ea: (alerts.RANK[ea[1].severity], ea[1].seq))
            overflow = 0
            for _, a in found:
                now = self._clock()
                self._sent_at = [t for t in self._sent_at if now - t < 60]
                st = self._open.get(a.key)
                repeated = 0
                if a.resolves is None and st is not None and now - st["last"] < self._window:
                    st["skipped"] += 1
                    out.append(Outcome(a.seq, "SUPPRESSED", "duplicate", a.key))
                    continue
                if st is not None and a.resolves is None:
                    repeated = st["skipped"]
                if len(self._sent_at) >= self._per_minute:
                    overflow += 1
                    out.append(Outcome(a.seq, "SUPPRESSED", "burst", a.key))
                    continue
                res = self._deliver(alerts.render(a, repeated=repeated))
                if res.ok:
                    self._sent_at.append(self._clock())
                    if a.resolves is not None:
                        self._open.pop(a.resolves, None)
                    else:
                        self._open[a.key] = {"last": self._clock(), "skipped": 0}
                    out.append(Outcome(a.seq, "SENT", None, a.key))
                else:
                    out.append(Outcome(a.seq, "FAILED", res.reason, a.key))
                    log.warning("alert not delivered: %s (seq %s)", res.reason, a.seq)
            if overflow:
                res = self._deliver(f"{overflow} more support alerts in the last minute were not posted one by one. "
                                    "Open the desk to see them all.")
                if not res.ok:
                    log.warning("burst summary not delivered: %s", res.reason)
        except Exception:        # last resort: the desk must never feel a notifier fault
            log.exception("notifier fault (ignored)")
        return out


_warned = False


def from_env(env: Mapping[str, str]) -> Notifier:
    """A Notifier from the environment. Without the webhook URL it is disabled: it sends nothing and says so once."""
    global _warned
    url = (env.get(ENV_URL) or "").strip()
    if not url:
        if not _warned:
            log.warning("Slack notifications DISABLED: %s is not set", ENV_URL)
            _warned = True
        return Notifier(None)
    return Notifier(SlackWebhookTransport(url))
