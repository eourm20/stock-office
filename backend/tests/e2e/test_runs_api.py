"""End-to-end through the HTTP API with the DEMO engine and DEMO fixtures (no network)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from stock_office.engine.demo_engine import DemoEngine
from stock_office.providers.base import ProviderError, ProviderResult
from tests.conftest import AS_OF, parse_sse

TERMINAL = {"run.completed", "run.failed"}


def create(client: TestClient, instrument: str, **kw: object) -> str:
    body = {"instrument_id": instrument, "as_of": AS_OF, "engine": "demo", **kw}
    resp = client.post("/api/v1/analysis-runs", json=body)
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "QUEUED"
    return str(resp.json()["run_id"])


def sse_events(client: TestClient, run_id: str, **kw: object) -> list[dict[str, object]]:
    headers = kw.pop("headers", None)
    resp = client.get(f"/api/v1/analysis-runs/{run_id}/events", params=kw, headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    frames = parse_sse(resp.text)
    for f in frames:
        assert int(f["id"]) == json.loads(f["data"])["seq"]
    return [json.loads(f["data"]) for f in frames]


def test_nvda_demo_run_full_lifecycle(client: TestClient) -> None:
    run_id = create(client, "US:NASDAQ:NVDA")
    run = client.get(f"/api/v1/analysis-runs/{run_id}").json()
    assert run["status"] == "COMPLETED" and run["demo"] is True
    assert run["latency_ms"] is not None and len(run["snapshot_ids"]) == 4

    events = sse_events(client, run_id)
    types = [e["type"] for e in events]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert types[:2] == ["run.created", "run.started"]
    assert types[-2:] == ["decision.created", "run.completed"]
    assert all(e["payload"]["demo"] is True for e in events)
    started = [e["agent_id"] for e in events if e["type"] == "agent.started"]
    assert started[0] == "data_collector"
    assert started[1:5] == ["market_analyst", "news_analyst", "fundamentals_analyst", "memory_log"]
    assert started[-1] == "portfolio_manager"
    debate = [e["payload"]["stance"] for e in events if e["type"] == "debate.message"]
    assert debate == ["bull", "bear", "aggressive", "conservative", "neutral"]
    # every started agent finishes (none left RUNNING)
    assert len(started) == len([e for e in events if e["type"] == "agent.completed"])
    # analysts' lookups arrive as tool.called with names only, between their start and finish
    tools = [e for e in events if e["type"] == "tool.called"]
    assert [(e["agent_id"], e["payload"]["round"]) for e in tools] == [
        ("market_analyst", 1), ("market_analyst", 2), ("news_analyst", 1),
        ("fundamentals_analyst", 1), ("fundamentals_analyst", 2)]
    assert set(tools[0]["payload"]) == {"role", "turn", "round", "tools", "demo"}
    assert tools[0]["payload"]["tools"] == ["get_stock_data", "get_indicators"]

    decision = client.get(f"/api/v1/analysis-runs/{run_id}/decision").json()
    assert decision["action"] == "HOLD" and decision["engine_rating"] == "Hold"

    snapshots = client.get(f"/api/v1/analysis-runs/{run_id}/snapshots").json()
    assert sorted(s["id"] for s in snapshots) == sorted(run["snapshot_ids"])
    for snap in snapshots:
        observed = datetime.fromisoformat(snap["observed_at"])
        assert observed <= datetime.fromisoformat(snap["available_at"]) and snap["demo"] is True
    assert client.get("/api/v1/analysis-runs/nope/snapshots").status_code == 404

    reports = client.get(f"/api/v1/analysis-runs/{run_id}/reports").json()
    assert reports["available"] is True
    assert {"market_analyst", "news_analyst", "fundamentals_analyst", "research_manager",
            "trader", "portfolio_manager"} <= set(reports["reports"])
    assert reports["reports"]["portfolio_manager"].endswith("Rating: Hold")
    assert decision["execution"] == "PROPOSED_ONLY" and decision["demo"] is True
    assert "DEMO_NOT_ANALYSIS" in decision["risk_flags"]
    assert set(decision["evidence_snapshot_ids"]) == set(run["snapshot_ids"])
    outputs = client.get(f"/api/v1/analysis-runs/{run_id}/outputs").json()
    assert {o["agent_id"] for o in outputs} >= {"market_analyst", "portfolio_manager"}


class _KrOnlyProvider:
    name = "kr-only"

    def supports(self, instrument: object) -> bool:
        return False

    def fetch(self, instrument: object, as_of: datetime) -> ProviderResult:
        raise AssertionError("must not be called for an unsupported instrument")


def test_not_applicable_provider_is_not_a_coverage_gap(
    make_client: Callable[..., TestClient]
) -> None:
    from stock_office.providers.fixture import FixtureProvider

    client = make_client(providers=[FixtureProvider(), _KrOnlyProvider()])
    run_id = create(client, "US:NASDAQ:NVDA")
    run = client.get(f"/api/v1/analysis-runs/{run_id}").json()
    assert run["status"] == "COMPLETED" and run["coverage_gaps"] == []
    decision = client.get(f"/api/v1/analysis-runs/{run_id}/decision").json()
    assert "COVERAGE_GAP" not in decision["risk_flags"]


def test_samsung_demo_run_reports_coverage_gap(client: TestClient) -> None:
    run_id = create(client, "KR:KRX:005930")
    run = client.get(f"/api/v1/analysis-runs/{run_id}").json()
    assert run["status"] == "COMPLETED" and run["coverage_gaps"]
    decision = client.get(f"/api/v1/analysis-runs/{run_id}/decision").json()
    assert "COVERAGE_GAP" in decision["risk_flags"]


def test_sse_resume_with_last_event_id_and_after_seq(client: TestClient) -> None:
    run_id = create(client, "US:NASDAQ:NVDA")
    full = sse_events(client, run_id)
    resumed = sse_events(client, run_id, headers={"Last-Event-ID": "5"})
    assert resumed == full[5:]
    assert sse_events(client, run_id, after_seq=10) == full[10:]
    # Replay is stable: two full reads are identical.
    assert sse_events(client, run_id) == full
    # Resuming after the terminal event closes immediately with nothing.
    assert sse_events(client, run_id, headers={"Last-Event-ID": str(len(full))}) == []


def test_live_sse_while_external_worker_runs(
    make_service: Callable[..., object], settings: object
) -> None:
    """API only enqueues; a separate worker executes while a client is streaming."""
    import threading
    import time

    from stock_office.api.app import create_app
    from stock_office.runs.service import RunService

    service = make_service()
    assert isinstance(service, RunService)

    class Deferred:
        def submit(self, run_id: str) -> None:
            def later() -> None:
                time.sleep(0.2)
                service.execute(run_id)
            threading.Thread(target=later, daemon=True).start()

    client = TestClient(create_app(settings, service, Deferred()))  # type: ignore[arg-type]
    run_id = create(client, "US:NASDAQ:NVDA")
    assert client.get(f"/api/v1/analysis-runs/{run_id}").json()["status"] in {"QUEUED", "RUNNING"}
    events = sse_events(client, run_id)  # blocks until the terminal event, then closes
    assert events[0]["type"] == "run.created" and events[-1]["type"] == "run.completed"
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))


def test_execute_is_idempotent(make_service: Callable[..., object]) -> None:
    from stock_office.domain.models import CreateRunRequest
    from stock_office.runs.service import RunService

    service = make_service()
    assert isinstance(service, RunService)
    run = service.create_run(CreateRunRequest(instrument_id="US:NASDAQ:NVDA"))
    service.execute(run.id)
    n = len(service.repo.events.read(run.id))
    service.execute(run.id)  # duplicate delivery from a queue
    assert len(service.repo.events.read(run.id)) == n


def test_engine_failure_is_explicit(make_client: Callable[..., TestClient]) -> None:
    client = make_client(demo_engine=DemoEngine(fail_at="News Analyst"))
    run_id = create(client, "US:NASDAQ:NVDA")
    run = client.get(f"/api/v1/analysis-runs/{run_id}").json()
    assert run["status"] == "FAILED" and run["error_code"] == "ENGINE_ERROR"
    events = sse_events(client, run_id)
    assert events[-1]["type"] == "run.failed"
    failed = {e["agent_id"] for e in events if e["type"] == "agent.failed"}
    assert failed == {"news_analyst", "fundamentals_analyst", "memory_log"}
    assert "decision.created" not in {e["type"] for e in events}
    assert client.get(f"/api/v1/analysis-runs/{run_id}/decision").status_code == 404


class _GappyEngine(DemoEngine):
    """Engine that, like real TradingAgents, reports data it could not obtain."""

    def run(self, ctx):  # type: ignore[no-untyped-def]
        outcome = super().run(ctx)
        outcome.coverage_gaps = ["tradingagents: Polymarket search failed for 'Fed': 451"]
        return outcome


def test_engine_data_gaps_are_recorded(make_client: Callable[..., TestClient]) -> None:
    client = make_client(demo_engine=_GappyEngine())
    run_id = create(client, "US:NASDAQ:NVDA")
    run = client.get(f"/api/v1/analysis-runs/{run_id}").json()
    assert run["coverage_gaps"] == ["tradingagents: Polymarket search failed for 'Fed': 451"]
    decision = client.get(f"/api/v1/analysis-runs/{run_id}/decision").json()
    assert "COVERAGE_GAP" in decision["risk_flags"]


def test_unparseable_rating_becomes_review(make_client: Callable[..., TestClient]) -> None:
    client = make_client(demo_engine=DemoEngine(rating=None))
    run_id = create(client, "US:NASDAQ:NVDA")
    decision = client.get(f"/api/v1/analysis-runs/{run_id}/decision").json()
    assert decision["action"] == "REVIEW"
    assert "UNPARSEABLE_OR_REVIEW_RATING" in decision["risk_flags"]


class _EmptyProvider:
    name = "empty"

    def supports(self, instrument: object) -> bool:
        return True

    def fetch(self, instrument: object, as_of: datetime) -> ProviderResult:
        return ProviderResult(coverage_gaps=["empty: nothing"])


class _BrokenProvider(_EmptyProvider):
    name = "broken"

    def fetch(self, instrument: object, as_of: datetime) -> ProviderResult:
        raise ProviderError("PROVIDER_REQUEST_FAILED", "timeout")


@pytest.mark.parametrize("provider", [_EmptyProvider(), _BrokenProvider()])
def test_missing_data_blocks_analysis(make_client: Callable[..., TestClient],
                                      provider: object) -> None:
    client = make_client(providers=[provider])
    run_id = create(client, "US:NASDAQ:NVDA")
    run = client.get(f"/api/v1/analysis-runs/{run_id}").json()
    assert run["status"] == "INSUFFICIENT_DATA" and run["coverage_gaps"]
    decision = client.get(f"/api/v1/analysis-runs/{run_id}/decision").json()
    assert decision["action"] == "REVIEW" and decision["evidence_snapshot_ids"] == []
    assert {"INSUFFICIENT_DATA", "NO_GROUNDED_EVIDENCE"} <= set(decision["risk_flags"])
    events = sse_events(client, run_id)
    assert events[-1]["type"] == "run.failed"
    assert events[-1]["payload"]["status"] == "INSUFFICIENT_DATA"
    # The engine never ran: only the data collector appears as an agent.
    assert {e["agent_id"] for e in events if e["type"].startswith("agent.")} == {"data_collector"}


def test_point_in_time_excludes_future_snapshots(client: TestClient) -> None:
    resp = client.post("/api/v1/analysis-runs", json={
        "instrument_id": "US:NASDAQ:NVDA", "as_of": "2026-10-15T12:00:00Z", "engine": "demo"})
    run_id = resp.json()["run_id"]
    events = sse_events(client, run_id)
    collected = next(e for e in events if e["type"] == "agent.completed"
                     and e["agent_id"] == "data_collector")
    assert collected["payload"]["excluded_future_snapshots"] == ["demo-NVDA-3"]
    decision = client.get(f"/api/v1/analysis-runs/{run_id}/decision").json()
    assert "demo-NVDA-3" not in decision["evidence_snapshot_ids"]


def test_tradingagents_without_key_fails_explicitly(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    run_id = create(client, "US:NASDAQ:NVDA", engine="tradingagents")
    run = client.get(f"/api/v1/analysis-runs/{run_id}").json()
    assert run["status"] == "FAILED" and run["error_code"] == "ENGINE_NOT_CONFIGURED"
    assert run["demo"] is False
    assert sse_events(client, run_id)[-1]["type"] == "run.failed"
    assert client.get(f"/api/v1/analysis-runs/{run_id}/decision").status_code == 404


@pytest.mark.parametrize("body,code", [
    ({"instrument_id": "NVDA"}, 422),
    ({"instrument_id": "US:NASDAQ:AAPL"}, 404),
    ({"instrument_id": "US:NASDAQ:NVDA", "as_of": "2099-01-01T00:00:00Z"}, 422),
    ({"instrument_id": "US:NASDAQ:NVDA", "engine": "live-broker"}, 422),
])
def test_bad_requests(client: TestClient, body: dict[str, object], code: int) -> None:
    assert client.post("/api/v1/analysis-runs", json=body).status_code == code


def test_cors_allows_only_the_configured_ui_origin(client: TestClient) -> None:
    ok = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    other = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_unknown_run_404(client: TestClient) -> None:
    for suffix in ("", "/events", "/decision", "/outputs"):
        assert client.get(f"/api/v1/analysis-runs/nope{suffix}").status_code == 404

