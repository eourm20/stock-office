"""Append-only JSONL event log per run with a monotonic, gap-free `seq`.

Single-writer per run: the API writes `run.created`, then exactly one worker owns the run.
Within a process, appends are serialized by a per-run lock.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stock_office.domain.models import EventType, RunEvent

from .sanitize import sanitize_payload


class CorruptEventLogError(RuntimeError):
    pass


class EventStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        self._guard = threading.Lock()

    def _path(self, run_id: str) -> Path:
        return self.root / run_id / "events.jsonl"

    def _lock(self, run_id: str) -> threading.Lock:
        with self._guard:
            return self._locks[run_id]

    def _read_records(self, run_id: str) -> list[dict[str, Any]]:
        path = self._path(run_id)
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        # A trailing fragment without "\n" is an interrupted write; it was never acknowledged.
        complete = lines[:-1]
        records = [json.loads(line) for line in complete if line.strip()]
        for expected, record in enumerate(records, start=1):
            if record["event"]["seq"] != expected:
                found = record["event"]["seq"]
                raise CorruptEventLogError(f"run {run_id}: seq {found} != {expected}")
        return records

    def append(
        self,
        run_id: str,
        type: EventType,
        *,
        agent_id: str | None = None,
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        occurred_at: datetime | None = None,
    ) -> RunEvent:
        """Append an event; re-sending the same `dedupe_key` returns the stored one (idempotent)."""
        with self._lock(run_id):
            records = self._read_records(run_id)
            if dedupe_key is not None:
                for record in records:
                    if record.get("dedupe_key") == dedupe_key:
                        return RunEvent.model_validate(record["event"])
            seq = len(records) + 1
            event = RunEvent(
                event_id=f"{run_id}-{seq:06d}",
                run_id=run_id,
                seq=seq,
                type=type,
                agent_id=agent_id,
                occurred_at=occurred_at or datetime.now(UTC),
                payload=sanitize_payload(payload or {}),
            )
            line = json.dumps(
                {"event": event.model_dump(mode="json"), "dedupe_key": dedupe_key},
                ensure_ascii=False,
            )
            path = self._path(run_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._drop_unterminated_tail(path)
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
                fh.flush()
            return event

    @staticmethod
    def _drop_unterminated_tail(path: Path) -> None:
        """Truncate an interrupted, never-acknowledged trailing fragment before appending."""
        if not path.exists():
            return
        data = path.read_bytes()
        if data and not data.endswith(b"\n"):
            with path.open("r+b") as fh:
                fh.truncate(data.rfind(b"\n") + 1)

    def read(self, run_id: str, after_seq: int = 0) -> list[RunEvent]:
        return [
            RunEvent.model_validate(r["event"])
            for r in self._read_records(run_id)
            if r["event"]["seq"] > after_seq
        ]
