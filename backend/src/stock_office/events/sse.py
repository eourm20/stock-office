"""Server-Sent Events framing and resume-point parsing."""

from __future__ import annotations

import json

from stock_office.domain.models import RunEvent


def format_sse(event: RunEvent) -> str:
    data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
    # `id` is the seq so a browser's automatic Last-Event-ID resumes exactly after it.
    return f"id: {event.seq}\nevent: {event.type.value}\ndata: {data}\n\n"


def resume_after(last_event_id: str | None, after_seq: int | None) -> int:
    """Resume point: explicit `after_seq` query wins, else the `Last-Event-ID` header, else 0."""
    if after_seq is not None:
        return max(after_seq, 0)
    if last_event_id:
        try:
            return max(int(last_event_id.strip()), 0)
        except ValueError:
            return 0
    return 0
