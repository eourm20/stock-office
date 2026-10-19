from __future__ import annotations

import contextlib
import socket
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from stock_office.api.app import create_app
from stock_office.briefing import DemoBriefingWriter
from stock_office.config import Settings
from stock_office.db import connect
from stock_office.domain.models import EngineName
from stock_office.engine.adapter import AnalysisEngine
from stock_office.engine.demo_engine import DemoEngine
from stock_office.engine.tradingagents_engine import TradingAgentsEngine
from stock_office.engine.upstream import import_tradingagents
from stock_office.inbox import Inbox
from stock_office.providers.base import MarketDataProvider
from stock_office.providers.fixture import FixtureProvider
from stock_office.runs.repository import RunRepository
from stock_office.runs.service import RunService

AS_OF = "2026-10-16T00:00:00Z"

if sys.platform == "win32":
    # On the development PC, socket.socketpair() fails at random with WinError 10014 (~17% in a
    # 400-try check on 2026-10-19; an environment issue, not Stock Office code). asyncio needs a
    # socket pair for every event loop the test client creates, so retry that one error.
    _socketpair = socket.socketpair

    def _socketpair_retrying(*args: Any, **kwargs: Any) -> tuple[socket.socket, socket.socket]:
        for _ in range(20):
            try:
                return _socketpair(*args, **kwargs)
            except OSError as exc:
                if getattr(exc, "winerror", None) != 10014:
                    raise
        return _socketpair(*args, **kwargs)

    socket.socketpair = _socketpair_retrying

# Import the engine package before any test module does, without upstream's import-time
# `.env` loading: otherwise backend/.env keys leak into os.environ for the whole session and a
# "no key" test can make a real, paid LLM call.
with contextlib.suppress(ImportError):
    import_tradingagents()


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

        # DEMO runs get the model-free DEMO briefing; real-engine runs never reach a model in tests.
        service = RunService(RunRepository(settings.data_dir), engines, provs,
                             briefers=lambda run: DemoBriefingWriter() if run.demo else None)
        # CEO inbox on a temporary database; a fixed USD/KRW rate instead of a network call.
        service.inbox = Inbox(connect(settings.data_dir), service.repo,
                              fx=lambda: (Decimal(1400), datetime(2026, 10, 15, tzinfo=UTC)))
        service.reporter = lambda run: service.inbox.file_run(run, service.clock())
        return service

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
