"""HTTP transport for the source routes: one cookie jar per transport, a user-agent policy per route, an optional
secondary egress (the app-vm proxy, CIE_SECONDARY_PROXY) and a granular classification of what came back — so a
403 from CloudFront, an abuse-detection apology page, a captcha form, an expired session and a plain outage are
recorded as different things and never collapse into a permanent "blocked"."""
from __future__ import annotations

import http.cookiejar
import os
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Optional

UA = {
    "browser": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "plain": "NiveshCopilot-CIE/0.1 (+https://niveshcopilot.com)",           # www.fda.gov's Akamai policy flags the browser UA, not this one
    "sec": "NiveshCopilot-CIE/0.1 (+https://niveshcopilot.com; research use)",  # SEC fair-access: descriptive UA
}
SECONDARY_PROXY_ENV = "CIE_SECONDARY_PROXY"
DEFAULT_SECONDARY_PROXY = "http://10.160.0.5:3128"       # tinyproxy on nivesh-app-vm (used for NSE since PR #127)

_WAF_SERVERS = ("cloudfront", "akamai", "cloudflare", "imperva", "incapsula", "sucuri", "aws")
_WAF_BODY = re.compile(r"access denied|request blocked|cloudfront|akamai|attention required|just a moment", re.I)
_ABUSE = re.compile(r"abuse-detection|excessive-requests|apology_objects|too many requests|rate limit", re.I)
_SESSION = re.compile(r"session[^.<]{0,60}(expired|time[d ]?out)", re.I)


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict = field(default_factory=dict)
    url: str = ""
    egress: str = "primary"

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def classify(r) -> str:
    """Observed outcome of one request. 'ok' means the body is worth parsing; anything else names the obstacle."""
    if isinstance(r, BaseException):
        return "unreachable"
    server = str(r.headers.get("server", "")).lower()
    head = r.body[:4000].decode("utf-8", errors="replace")
    if _ABUSE.search(r.url or "") or _ABUSE.search(head):
        return "blocked_temporary"
    if r.status in (401, 403):
        if any(w in server for w in _WAF_SERVERS) or _WAF_BODY.search(head) or "cloudfront" in str(r.headers.get("x-cache", "")).lower():
            return "waf_blocked"
        return "forbidden" if r.status == 403 else "unauthorized"
    if r.status in (429, 503):
        return "blocked_temporary"
    if r.status == 404:
        return "not_found"
    if r.status >= 500:
        return "server_error"
    if r.status >= 400:
        return "http_error"
    if not r.body.strip():
        return "empty_response"
    low = head.lower()
    if "<html" in low or "<!doctype" in low:
        full = r.body.decode("utf-8", errors="replace") if len(r.body) < 400_000 else head
        if _SESSION.search(full):
            return "session_required"
    return "ok"


def captcha_gated(body: bytes, events: list) -> bool:
    """A captcha decides the outcome only when the adapter found nothing: ministry and ratings pages carry a search
    captcha next to a perfectly readable listing (heavy_industries, GLEIF, ICRA on 2026-09-16)."""
    return not events and b"captcha" in body[:400_000].lower()


def multipart(fields: dict) -> tuple[bytes, str]:
    """A multipart/form-data body the way a browser's FormData sends it (NHAI's API rejects urlencoded bodies)."""
    boundary = "----CIEFormBoundary" + uuid.uuid4().hex[:16]
    out = bytearray()
    for k, v in fields.items():
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


class HttpTransport:
    """request(route, url, data=None, headers=None) → Response. HTTP errors come back as Responses (status + body) so
    the caller can classify them; only network-level failures raise."""

    def __init__(self, secondary_proxy: Optional[str] = None, timeout: int = 60):
        self.timeout = timeout
        self.secondary_proxy = secondary_proxy if secondary_proxy is not None else os.environ.get(SECONDARY_PROXY_ENV, DEFAULT_SECONDARY_PROXY)
        self._openers: dict[str, urllib.request.OpenerDirector] = {}

    def _opener(self, egress: str):
        if egress not in self._openers:
            handlers = [urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())]
            if egress == "secondary":
                if not self.secondary_proxy:
                    raise ConnectionError("no secondary egress configured (CIE_SECONDARY_PROXY)")
                handlers.append(urllib.request.ProxyHandler({"http": self.secondary_proxy, "https": self.secondary_proxy}))
            self._openers[egress] = urllib.request.build_opener(*handlers)
        return self._openers[egress]

    def request(self, route, url: str, data: Optional[bytes] = None, headers: Optional[dict] = None, timeout: Optional[int] = None) -> Response:
        h = {"User-Agent": UA.get(getattr(route, "ua", "browser"), UA["browser"]), "Accept": "application/json, application/xml, text/xml, text/html;q=0.9, */*;q=0.8"}
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
        egress = getattr(route, "egress", "primary")
        try:
            with self._opener(egress).open(req, timeout=timeout or self.timeout) as r:
                return Response(r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}, r.geturl(), egress)
        except urllib.error.HTTPError as e:
            body = e.read() if hasattr(e, "read") else b""
            return Response(e.code, body, {k.lower(): v for k, v in (e.headers or {}).items()}, getattr(e, "url", url) or url, egress)
        except urllib.error.URLError as e:
            raise ConnectionError(str(e.reason)) from e
        except (TimeoutError, OSError) as e:
            raise ConnectionError(str(e)) from e
