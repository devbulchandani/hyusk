"""Web fetch tool.

Fetches the content of a URL as plain text. Uses urllib (no extra
deps) and respects a small per-domain rate limit. Limited to
http:// and https://; local file paths are NOT supported (use
read_file instead).
"""
from __future__ import annotations

import re
import socket
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from ...tools.base import READ, Tool


_MAX_BYTES = 5_000_000  # 5 MB cap
_TIMEOUT = 15.0
_USER_AGENT = "Hyusk/0.6 (+https://github.com/devbulchandani/hyusk)"
_RATE_LIMIT_PER_HOST = 2.0  # seconds between requests to the same host


_last_request_at: dict[str, float] = {}


class _TextExtractor(HTMLParser):
    """Tiny HTML-to-text converter. Strips scripts/styles, keeps
    block-level text separated by blank lines."""

    _BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td"}

    def __init__(self) -> None:
        super().__init__()
        self._text: list[str] = []
        self._skip = 0
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        if tag in self._BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        if tag in self._BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._skip:
            return
        text = data.strip()
        if text:
            self._buf.append(text)

    def _flush(self) -> None:
        if self._buf:
            self._text.append(" ".join(self._buf))
            self._buf = []

    def get_text(self) -> str:
        self._flush()
        return "\n\n".join(self._text)


def _strip_html(html: str) -> str:
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        # If parsing fails, fall back to a regex strip.
        return re.sub(r"<[^>]+>", " ", html)
    return extractor.get_text()


def _fetch(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"error": f"unsupported scheme: {parsed.scheme!r}", "url": url}
    if not parsed.netloc:
        return {"error": "no host in url", "url": url}
    # Per-host rate limit.
    host = parsed.netloc
    now = time.time()
    last = _last_request_at.get(host, 0.0)
    wait = _RATE_LIMIT_PER_HOST - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_at[host] = time.time()

    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read(_MAX_BYTES + 1, )
            truncated = len(raw) > _MAX_BYTES
            if truncated:
                raw = raw[:_MAX_BYTES]
            body = raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "url": url}

    text: str
    if "html" in ctype.lower():
        text = _strip_html(body)
    else:
        # Plain text / json / etc. — return as-is, lightly cleaned.
        text = re.sub(r"[ \t]+", " ", body).strip()

    return {
        "url": url,
        "status": "ok",
        "content_type": ctype,
        "bytes": len(raw),
        "truncated": truncated,
        "text": text,
    }


def web_fetch_tool() -> Tool:
    def execute(args: dict) -> dict:
        url = args.get("url", "").strip()
        if not url:
            return {"error": "url is required"}
        return _fetch(url)
    return Tool(
        name="web_fetch",
        description=(
            "Fetch the content of a URL and return it as plain text. "
            "HTML pages are stripped of tags; JSON / plain text is "
            "returned mostly as-is (with whitespace collapsed). "
            "Capped at 5 MB per response."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "http(s) URL to fetch"},
            },
            "required": ["url"],
        },
        permission=READ,
        execute=execute,
    )


def register_web_tools(registry) -> None:
    registry.register(web_fetch_tool())
