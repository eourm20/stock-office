from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from stock_office.api.app import create_app
from stock_office.config import Settings
from stock_office.domain.models import (
    AnalysisRun,
    DecisionAction,
    InvestmentDecision,
    RunStatus,
)
from stock_office.runs.repository import RunRepository
from stock_office.runs.summary import build_summary

T0 = datetime(2026, 10, 16, 7, 0, tzinfo=UTC)


def _run(repo: RunRepository, rid: str, inst: str, status: RunStatus, minutes: int,
         demo: bool = False, action: DecisionAction | None = None) -> None:
    at = T0 + timedelta(minutes=minutes)
    repo.save_run(AnalysisRun(id=rid, instrument_id=inst, requested_at=at, as_of=at,
                              engine="demo" if demo else "tradingagents", status=status,
                              engine_version="v", config_hash="h", demo=demo))
    if action:
        repo.save_decision(InvestmentDecision(run_id=rid, action=action, engine_rating="Hold",
                                              rationale="r", model_version="m",
                                              created_at=at, demo=demo))


def test_latest_real_decision_ignores_demo_and_failed(tmp_path: Path) -> None:
    repo = RunRepository(tmp_path)
    _run(repo, "old", "US:NASDAQ:NVDA", RunStatus.COMPLETED, 0, action=DecisionAction.SELL)
    _run(repo, "new", "US:NASDAQ:NVDA", RunStatus.COMPLETED, 10, action=DecisionAction.BUY)
    _run(repo, "demo", "US:NASDAQ:NVDA", RunStatus.COMPLETED, 20, demo=True,
         action=DecisionAction.HOLD)
    _run(repo, "failed", "US:NASDAQ:NVDA", RunStatus.FAILED, 30)
    _run(repo, "live", "KR:KRX:005930", RunStatus.RUNNING, 40)
    s = {i.instrument_id: i for i in build_summary(repo).instruments}
    nvda, samsung = s["US:NASDAQ:NVDA"], s["KR:KRX:005930"]
    assert nvda.latest is not None and nvda.latest.run_id == "new"
    assert nvda.latest.action is DecisionAction.BUY
    assert nvda.active_run_id is None
    assert samsung.latest is None
    assert (samsung.active_run_id, samsung.active_status) == ("live", RunStatus.RUNNING)


def test_summary_endpoint(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path, _env_file=None)))  # type: ignore[call-arg]
    body = client.get("/api/v1/office/summary").json()
    assert [i["instrument_id"] for i in body["instruments"]] == ["US:NASDAQ:NVDA", "KR:KRX:005930"]
    assert all(i["latest"] is None for i in body["instruments"])
