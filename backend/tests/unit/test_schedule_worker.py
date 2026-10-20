"""Scheduled runs through the real service with a DEMO-like engine standing in for the paid one."""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stock_office.domain.models import EngineName, RunStatus
from stock_office.engine.adapter import AnalysisEngine
from stock_office.engine.demo_engine import DemoEngine
from stock_office.providers.base import MarketDataProvider
from stock_office.providers.fixture import FixtureProvider
from stock_office.runs.repository import RunRepository
from stock_office.runs.service import BudgetExceededError, RunService
from stock_office.schedule import MILESTONE_RULES
from stock_office.worker import schedule_tick


class PaidLikeEngine(DemoEngine):
    """Behaves like the real engine for accounting (not DEMO), runs the scripted trace."""
    demo = False


def service(tmp_path: Path, limit: int | None = None) -> RunService:
    def engines(_: EngineName) -> AnalysisEngine:
        return PaidLikeEngine()

    def providers(_: EngineName) -> Sequence[MarketDataProvider]:
        return [FixtureProvider()]

    return RunService(RunRepository(tmp_path), engines, providers,
                      clock=lambda: datetime(2026, 10, 16, 8, 0, tzinfo=UTC),
                      max_paid_runs_per_day=limit)


def test_tick_runs_each_due_slot_once(tmp_path: Path) -> None:
    svc = service(tmp_path)
    now = datetime.fromisoformat("2026-10-16T07:45:00+09:00")       # before KRX open
    first = schedule_tick(svc, now, rules=MILESTONE_RULES)
    assert [(r.instrument_id, r.trigger, r.schedule_slot) for r in first] == [
        ("US:NASDAQ:NVDA", "schedule", "US:NASDAQ:NVDA@2026-10-15"),
        ("KR:KRX:005930", "schedule", "KR:KRX:005930@2026-10-16"),
    ]
    assert all(r.status is RunStatus.COMPLETED for r in first)
    assert schedule_tick(svc, now, rules=MILESTONE_RULES) == []  # never twice


def test_budget_blocks_paid_runs(tmp_path: Path) -> None:
    svc = service(tmp_path, limit=1)
    started = schedule_tick(svc, datetime.fromisoformat("2026-10-16T07:45:00+09:00"),
                            rules=MILESTONE_RULES)
    assert len(started) == 1                                          # second slot skipped
    from stock_office.domain.models import CreateRunRequest
    with pytest.raises(BudgetExceededError):
        svc.create_run(CreateRunRequest(instrument_id="US:NASDAQ:NVDA", engine="tradingagents"))


def test_engine_not_ready_does_not_burn_the_slot(tmp_path: Path) -> None:
    from stock_office.engine.adapter import EngineNotConfiguredError

    class NotReady(PaidLikeEngine):
        def check_ready(self) -> None:
            raise EngineNotConfiguredError("OPENAI_API_KEY is not set")

    svc = service(tmp_path)
    svc.engines = lambda _: NotReady()  # type: ignore[method-assign,assignment]
    now = datetime.fromisoformat("2026-10-16T07:45:00+09:00")
    assert schedule_tick(svc, now, rules=MILESTONE_RULES) == []
    assert svc.repo.list_runs() == []                                 # nothing recorded
    svc.engines = lambda _: PaidLikeEngine()  # type: ignore[method-assign,assignment]
    assert len(schedule_tick(svc, now, rules=MILESTONE_RULES)) == 2  # runs once fixed
