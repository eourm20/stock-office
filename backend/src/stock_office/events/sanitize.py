"""Redaction for anything published as an event or log line.

Events carry sanitized summaries only: no raw prompts, tool-call internals or secrets.
"""

from __future__ import annotations

import re
from typing import Any

MAX_TEXT_CHARS = 1200
_FORBIDDEN_KEYS = frozenset({"messages", "prompt", "prompts", "tool_calls", "api_key", "crtfc_key"})
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|crtfc_key|token|secret|password)\s*[=:]\s*[^\s&\"']+"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
]


def redact_text(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if len(text) > limit:
        text = text[:limit].rstrip() + " …[truncated]"
    return text


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: sanitize_payload(v)
            for k, v in value.items()
            if str(k).lower() not in _FORBIDDEN_KEYS
        }
    if isinstance(value, list):
        return [sanitize_payload(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
