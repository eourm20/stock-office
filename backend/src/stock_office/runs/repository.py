"""File-backed run storage for Sprint 0 (PostgreSQL arrives in Sprint 1).

Layout: <data_dir>/runs/<run_id>/{run.json, events.jsonl, decision.json, outputs.json,
snapshots/<id>.json, .claim}
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from stock_office.domain.models import (
    AgentResult,
    AnalysisRun,
    InvestmentDecision,
    MarketSnapshot,
    RunStatus,
)
from stock_office.events.store import EventStore

_RESULTS = TypeAdapter(list[AgentResult])


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _dump(model: BaseModel) -> str:
    return model.model_dump_json(indent=2)


class RunRepository:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.events = EventStore(self.root)

    def _dir(self, run_id: str) -> Path:
        return self.root / run_id

    def save_run(self, run: AnalysisRun) -> None:
        _atomic_write(self._dir(run.id) / "run.json", _dump(run))

    def get_run(self, run_id: str) -> AnalysisRun | None:
        path = self._dir(run_id) / "run.json"
        if not path.exists():
            return None
        return AnalysisRun.model_validate_json(path.read_text(encoding="utf-8"))

    def list_runs(self) -> list[AnalysisRun]:
        runs = [self.get_run(p.name) for p in self.root.iterdir() if p.is_dir()]
        return sorted((r for r in runs if r), key=lambda r: r.requested_at, reverse=True)

    def queued_run_ids(self) -> list[str]:
        return [r.id for r in reversed(self.list_runs()) if r.status is RunStatus.QUEUED]

    def claim(self, run_id: str) -> bool:
        """Atomically claim a run for one worker (O_EXCL). False if someone else owns it."""
        try:
            fd = os.open(self._dir(run_id) / ".claim", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True

    def save_decision(self, decision: InvestmentDecision) -> None:
        _atomic_write(self._dir(decision.run_id) / "decision.json", _dump(decision))

    def get_decision(self, run_id: str) -> InvestmentDecision | None:
        path = self._dir(run_id) / "decision.json"
        if not path.exists():
            return None
        return InvestmentDecision.model_validate_json(path.read_text(encoding="utf-8"))

    def save_outputs(self, run_id: str, results: list[AgentResult]) -> None:
        _atomic_write(
            self._dir(run_id) / "outputs.json", _RESULTS.dump_json(results, indent=2).decode()
        )

    def get_outputs(self, run_id: str) -> list[AgentResult]:
        path = self._dir(run_id) / "outputs.json"
        if not path.exists():
            return []
        return _RESULTS.validate_json(path.read_text(encoding="utf-8"))

    def save_snapshot(self, run_id: str, snapshot: MarketSnapshot) -> None:
        _atomic_write(self._dir(run_id) / "snapshots" / f"{snapshot.id}.json", _dump(snapshot))

    def get_snapshots(self, run_id: str) -> list[MarketSnapshot]:
        folder = self._dir(run_id) / "snapshots"
        if not folder.exists():
            return []
        return [
            MarketSnapshot.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted(folder.glob("*.json"))
        ]

    def get_briefing(self, run_id: str) -> dict[str, object] | None:
        path = self._dir(run_id) / "briefing.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None

    def get_tool_results(self, run_id: str) -> list[dict[str, object]] | None:
        path = self._dir(run_id) / "tool_results.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else None

    def get_reports(self, run_id: str) -> dict[str, str] | None:
        path = self._dir(run_id) / "reports.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else None

    def write_json(self, run_id: str, name: str, data: object) -> None:
        _atomic_write(self._dir(run_id) / name, json.dumps(data, indent=2, ensure_ascii=False))
