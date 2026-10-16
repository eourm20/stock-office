from pathlib import Path

import pytest

from stock_office.domain.models import EventType
from stock_office.events.sanitize import sanitize_payload
from stock_office.events.sse import format_sse, resume_after
from stock_office.events.store import CorruptEventLogError, EventStore


def test_seq_is_monotonic_and_gap_free(tmp_path: Path) -> None:
    store = EventStore(tmp_path)
    for t in (EventType.RUN_CREATED, EventType.RUN_STARTED, EventType.RUN_COMPLETED):
        store.append("r1", t)
    assert [e.seq for e in store.read("r1")] == [1, 2, 3]
    assert [e.seq for e in store.read("r1", after_seq=2)] == [3]


def test_dedupe_key_makes_append_idempotent(tmp_path: Path) -> None:
    store = EventStore(tmp_path)
    first = store.append("r1", EventType.AGENT_STARTED, agent_id="a", dedupe_key="task:1:start")
    again = store.append("r1", EventType.AGENT_STARTED, agent_id="a", dedupe_key="task:1:start")
    assert first == again
    assert len(store.read("r1")) == 1


def test_duplicate_seq_on_disk_is_detected(tmp_path: Path) -> None:
    store = EventStore(tmp_path)
    store.append("r1", EventType.RUN_CREATED)
    path = tmp_path / "r1" / "events.jsonl"
    line = path.read_text(encoding="utf-8")
    path.write_text(line + line, encoding="utf-8")
    with pytest.raises(CorruptEventLogError):
        store.read("r1")


def test_interrupted_trailing_write_is_ignored(tmp_path: Path) -> None:
    store = EventStore(tmp_path)
    store.append("r1", EventType.RUN_CREATED)
    with (tmp_path / "r1" / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"event": {"seq": 2')  # crash mid-write
    assert len(store.read("r1")) == 1
    assert store.append("r1", EventType.RUN_STARTED).seq == 2
    assert [e.type for e in store.read("r1")] == [EventType.RUN_CREATED, EventType.RUN_STARTED]


def test_payload_sanitized_on_write(tmp_path: Path) -> None:
    store = EventStore(tmp_path)
    event = store.append("r1", EventType.AGENT_COMPLETED, payload={
        "summary": "key api_key=abc123 and sk-ABCDEFGHIJKLMNOPQRST",
        "messages": ["raw prompt"], "nested": {"prompt": "secret prompt", "ok": 1},
    })
    assert "abc123" not in event.payload["summary"] and "sk-ABC" not in event.payload["summary"]
    assert "messages" not in event.payload
    assert event.payload["nested"] == {"ok": 1}


def test_long_text_truncated() -> None:
    assert sanitize_payload({"t": "x" * 5000})["t"].endswith("…[truncated]")


def test_sse_framing_and_resume(tmp_path: Path) -> None:
    event = EventStore(tmp_path).append("r1", EventType.RUN_CREATED)
    frame = format_sse(event)
    assert frame.startswith("id: 1\nevent: run.created\ndata: {") and frame.endswith("\n\n")
    assert resume_after("7", None) == 7
    assert resume_after("7", 3) == 3  # explicit query wins
    assert resume_after("garbage", None) == 0
