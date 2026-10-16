"""FastAPI surface for Sprint 0. There are intentionally no order/account endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Protocol

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from stock_office import __version__
from stock_office.config import TRADINGAGENTS_COMMIT, TRADINGAGENTS_VERSION, Settings, get_settings
from stock_office.domain.instruments import (
    InvalidInstrumentIdError,
    UnknownInstrumentError,
    search_instruments,
)
from stock_office.domain.models import (
    TERMINAL_EVENT_TYPES,
    AgentResult,
    AnalysisRun,
    CreateRunRequest,
    CreateRunResponse,
    Instrument,
    InvestmentDecision,
    Market,
)
from stock_office.events.sse import format_sse, resume_after
from stock_office.runs.service import FutureAsOfError, RunService
from stock_office.wiring import build_service
from stock_office.worker import ThreadDispatcher


class Dispatcher(Protocol):
    def submit(self, run_id: str) -> None: ...


class _NoopDispatcher:
    """External worker mode: the API only enqueues."""

    def submit(self, run_id: str) -> None:
        return None


def create_app(
    settings: Settings | None = None,
    service: RunService | None = None,
    dispatcher: Dispatcher | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    service = service or build_service(settings)
    thread_dispatcher: ThreadDispatcher | None = None
    if dispatcher is None:
        if settings.worker_mode == "thread":
            thread_dispatcher = ThreadDispatcher(service)
            dispatcher = thread_dispatcher
        else:
            dispatcher = _NoopDispatcher()
    active: Dispatcher = dispatcher

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if thread_dispatcher is not None:
            thread_dispatcher.shutdown()

    app = FastAPI(title="Stock Office API", version=__version__, lifespan=lifespan)

    def _run_or_404(run_id: str) -> AnalysisRun:
        run = service.repo.get_run(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        return run

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "version": __version__,
            "paper_only": settings.paper_only,
            "live_orders": False,
            "worker_mode": settings.worker_mode,
            "tradingagents": {"version": TRADINGAGENTS_VERSION, "commit": TRADINGAGENTS_COMMIT},
        }

    @app.get("/api/v1/instruments")
    def instruments(q: str = "", market: Market | None = None) -> list[Instrument]:
        return search_instruments(q, market)

    @app.post("/api/v1/analysis-runs", status_code=202)
    def create_run(request: CreateRunRequest) -> CreateRunResponse:
        try:
            run = service.create_run(request)
        except InvalidInstrumentIdError as exc:
            raise HTTPException(422, str(exc)) from None
        except UnknownInstrumentError as exc:
            raise HTTPException(404, str(exc)) from None
        except FutureAsOfError as exc:
            raise HTTPException(422, str(exc)) from None
        active.submit(run.id)
        return CreateRunResponse(run_id=run.id, status=run.status)

    @app.get("/api/v1/analysis-runs")
    def list_runs() -> list[AnalysisRun]:
        return service.repo.list_runs()

    @app.get("/api/v1/analysis-runs/{run_id}")
    def get_run(run_id: str) -> AnalysisRun:
        return _run_or_404(run_id)

    @app.get("/api/v1/analysis-runs/{run_id}/outputs")
    def get_outputs(run_id: str) -> list[AgentResult]:
        _run_or_404(run_id)
        return service.repo.get_outputs(run_id)

    @app.get("/api/v1/analysis-runs/{run_id}/decision")
    def get_decision(run_id: str) -> InvestmentDecision:
        run = _run_or_404(run_id)
        decision = service.repo.get_decision(run_id)
        if decision is None:
            detail = "decision not available" + (
                f" (run {run.status.value}: {run.error_code})" if run.error_code else ""
            )
            raise HTTPException(404, detail)
        return decision

    @app.get("/api/v1/analysis-runs/{run_id}/events")
    async def stream_events(
        run_id: str,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
        after_seq: Annotated[int | None, Query(ge=0)] = None,
    ) -> StreamingResponse:
        _run_or_404(run_id)
        cursor = resume_after(last_event_id, after_seq)

        async def gen() -> AsyncIterator[str]:
            nonlocal cursor
            yield "retry: 2000\n\n"
            if cursor > 0:
                # Resuming after the terminal event: nothing more will ever arrive.
                at_cursor = service.repo.events.read(run_id, after_seq=cursor - 1)[:1]
                if at_cursor and at_cursor[0].type in TERMINAL_EVENT_TYPES:
                    return
            while True:
                for event in service.repo.events.read(run_id, after_seq=cursor):
                    cursor = event.seq
                    yield format_sse(event)
                    # The terminal event is always the last one a run writes.
                    if event.type in TERMINAL_EVENT_TYPES:
                        return
                yield ": keep-alive\n\n"
                await asyncio.sleep(settings.sse_poll_interval_s)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def app_factory() -> FastAPI:
    return create_app()
