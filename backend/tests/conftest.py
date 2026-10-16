from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stock_office.api.app import create_app
from stock_office.config import Settings
from stock_office.domain.models import EngineName
from stock_office.engine.adapter import AnalysisEngine
from stock_office.engine.demo_engine import DemoEngine
from stock_office.engine.tradingagents_engine import TradingAgentsEngine
from stock_office.providers.base import MarketDataProvider
from stock_office.providers.fixture import FixtureProvider
from stock_office.runs.repository import RunRepository
from stock_office.runs.service import RunService

AS_OF = "2026-10-16T00:00:00Z"


class InlineDispatcher:
    """Executes synchronously so tests are deterministic (production uses a worker)."""

    def __init__(self, service: RunService) -> None:
        self.service = service

    def submit(self, run_id: str) -> None:
        self.service.execute(run_id)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, sse_poll_interval_s=0.01, _env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def make_service(settings: Settings) -> Callable[..., RunService]:
    def factory(
        demo_engine: DemoEngine | None = None,
        providers: Sequence[MarketDataProvider] | None = None,
    ) -> RunService:
        def engines(name: EngineName) -> AnalysisEngine:
            return demo_engine or DemoEngine() if name == "demo" else TradingAgentsEngine(settings)

        def provs(name: EngineName) -> Sequence[MarketDataProvider]:
            return providers if providers is not None else [FixtureProvider()]

        return RunService(RunRepository(settings.data_dir), engines, provs)

    return factory


@pytest.fixture
def make_client(settings: Settings, make_service: Callable[..., RunService]
                ) -> Callable[..., TestClient]:
    def factory(**kwargs: object) -> TestClient:
        service = make_service(**kwargs)
        return TestClient(create_app(settings, service, InlineDispatcher(service)))

    return factory


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


def parse_sse(body: str) -> list[dict[str, str]]:
    frames = []
    for block in body.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith(":") or ":" not in line:
                continue
            key, _, value = line.partition(":")
            fields[key] = value.lstrip()
        if "data" in fields:
            frames.append(fields)
    return frames


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
