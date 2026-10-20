"""FastAPI surface. PAPER ONLY: nothing here reaches a securities firm or any order service."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Protocol

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from stock_office import __version__
from stock_office.config import TRADINGAGENTS_COMMIT, TRADINGAGENTS_VERSION, Settings, get_settings
from stock_office.db import transaction
from stock_office.domain.instruments import (
    InvalidInstrumentIdError,
    UnknownInstrumentError,
    display_name,
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
    MarketSnapshot,
)
from stock_office.events.sse import format_sse, resume_after
from stock_office.inbox import DecisionError, Inbox, InboxItem
from stock_office.kiwoom_mock.link import build_link
from stock_office.logging_setup import install_log_redaction
from stock_office.notify import build_notifier
from stock_office.paper.settle import next_settle_times as settle_times
from stock_office.runs.service import BudgetExceededError, FutureAsOfError, RunService
from stock_office.runs.summary import OfficeSummary, build_summary
from stock_office.schedule import next_slots
from stock_office.wiring import build_inbox, build_service
from stock_office.worker import ThreadDispatcher


class DecisionBody(BaseModel):
    """CEO decision on an inbox document. `client_request_id` makes repeated taps harmless."""

    action: str
    comment: str = ""
    client_request_id: str


class AutoApproveBody(BaseModel):
    enabled: bool


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class PushSubscriptionBody(BaseModel):
    """A browser PushSubscription as JSON (endpoint at a known push service)."""

    endpoint: str = Field(min_length=1, max_length=1000)
    keys: PushKeys


class UnsubscribeBody(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1000)


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
    # Thread-mode runs call providers inside the API process, so its logs need the same hygiene.
    install_log_redaction(*(logging.getLogger(n) for n in ("uvicorn", "uvicorn.error")))
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
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type", "Last-Event-ID"])

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
        except BudgetExceededError as exc:
            raise HTTPException(429, str(exc)) from None
        active.submit(run.id)
        return CreateRunResponse(run_id=run.id, status=run.status)

    inbox: Inbox = service.inbox or build_inbox(settings, service.repo)

    @app.get("/api/v1/inbox")
    def list_inbox() -> list[InboxItem]:
        inbox.expire_due(service.clock())
        return inbox.list()

    @app.get("/api/v1/inbox/{item_id}")
    def get_inbox_item(item_id: int) -> InboxItem:
        inbox.expire_due(service.clock())
        item = inbox.get(item_id)
        if item is None:
            raise HTTPException(404, "document not found")
        return item

    @app.post("/api/v1/inbox/{item_id}/decision")
    def decide(item_id: int, body: DecisionBody) -> InboxItem:
        """CEO decision. An approval books a simulated order in the local paper book only."""
        try:
            return inbox.decide(item_id, body.action, body.comment, body.client_request_id,
                                service.clock())
        except DecisionError as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @app.post("/api/v1/inbox/{item_id}/read")
    def mark_read(item_id: int) -> dict[str, bool]:
        inbox.mark_read(item_id, service.clock())
        return {"ok": True}

    @app.get("/api/v1/records")
    def records() -> list[dict[str, object]]:
        """Meeting minutes list: every run with its decision, headline and approval outcome."""
        outcome = inbox.by_run()
        none: dict[str, object] = {}
        rows: list[dict[str, object]] = []
        for run in service.repo.list_runs():
            decision = service.repo.get_decision(run.id)
            briefing = service.repo.get_briefing(run.id) or {}
            rows.append({
                "run_id": run.id, "instrument_id": run.instrument_id,
                "name": display_name(run.instrument_id), "status": run.status.value,
                "demo": run.demo, "trigger": run.trigger, "requested_at": run.requested_at,
                "action": decision.action.value if decision else None,
                "rating": decision.engine_rating if decision else None,
                "headline": briefing.get("headline") if briefing.get("status") == "OK" else None,
                "approval": outcome.get(run.id, none).get("status"),
                "approval_auto": outcome.get(run.id, none).get("auto", False),
                "paper": outcome.get(run.id, none).get("paper"),
                "ceo_opinion": outcome.get(run.id, none).get("opinion"),
            })
        return rows

    @app.get("/api/v1/portfolio")
    def portfolio() -> dict[str, object]:
        """Paper book: KRW cash, holdings marked at the last settled close, NAV, return."""
        return inbox.book.portfolio()

    @app.get("/api/v1/portfolio/activity")
    def portfolio_activity(limit: Annotated[int, Query(ge=1, le=500)] = 100
                           ) -> list[dict[str, object]]:
        """Simulated orders and their fills, newest first."""
        return inbox.book.activity(limit)

    @app.get("/api/v1/company/settings")
    def company_settings() -> dict[str, object]:
        return {"auto_approve": inbox.book.auto_approve(),
                "costs": inbox.book.costs.describe(),
                "policy_version": inbox.book.policy.version,
                "initial_krw": str(inbox.book.policy.initial_equity_krw)}

    notifier = build_notifier(settings, inbox.conn, service.repo)
    mock_link = build_link(settings)

    @app.get("/api/v1/kiwoom-mock/activity")
    def kiwoom_mock_activity(market: str | None = None) -> list[dict[str, object]]:
        """Orders the desks placed on the Kiwoom mock accounts (newest first)."""
        if inbox.desks is None or market not in (None, "KR", "US"):
            return []
        rows: list[dict[str, object]] = inbox.desks.orders(market=market)
        return rows

    @app.get("/api/v1/kiwoom-mock/performance")
    def kiwoom_mock_performance(market: str = "KR") -> dict[str, object]:
        """Evaluation basis per desk: starting equity and one value per closed session."""
        if inbox.desks is None or market not in ("KR", "US"):
            return {"start": None, "history": []}
        start = inbox.desks.start_equity(market)
        return {"start": str(start) if start is not None else None,
                "history": inbox.desks.nav_history(market)}

    @app.get("/api/v1/kiwoom-mock")
    def kiwoom_mock_status(refresh: bool = False) -> dict[str, object]:
        """Kiwoom 모의투자 accounts, read-only (step K1): deposits, holdings, today's fills.
        Cached; `refresh` is throttled. Keys and tokens never leave the server."""
        return mock_link.status(refresh=refresh)

    @app.get("/api/v1/notify/status")
    def notify_status() -> dict[str, object]:
        """Phone notifications: whether the server can send, how many phones, quiet hours."""
        return {"enabled": notifier.sender is not None,
                "public_key": settings.vapid_public_key if notifier.sender else None,
                "subscriptions": notifier.subscriptions(),
                "quiet": f"{settings.notify_quiet_start:02d}:00–{settings.notify_quiet_end:02d}:00",
                "categories": ["회의 시작 (정기 회의, 예산 한도로 못 열면 그 사실)",
                               "회의 끝 (결론 또는 실패)", "결재 요청 (회의 끝 알림 대신)",
                               "주문 (키움 모의: 주문 접수·체결·청산·미체결·거절)"]}

    @app.post("/api/v1/notify/subscribe")
    def notify_subscribe(body: PushSubscriptionBody) -> dict[str, object]:
        try:
            with transaction(inbox.conn):
                notifier.subscribe(body.endpoint, body.keys.p256dh, body.keys.auth,
                                   service.clock())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"subscriptions": notifier.subscriptions()}

    @app.post("/api/v1/notify/unsubscribe")
    def notify_unsubscribe(body: UnsubscribeBody) -> dict[str, object]:
        with transaction(inbox.conn):
            notifier.unsubscribe(body.endpoint)
        return {"subscriptions": notifier.subscriptions()}

    @app.post("/api/v1/notify/test")
    def notify_test() -> dict[str, object]:
        """Send one test notification now (ignores quiet hours)."""
        if notifier.sender is None:
            raise HTTPException(409, "push keys are not configured on the server")
        with transaction(inbox.conn):
            sent = notifier.send({"title": "Stock Office 알림 테스트",
                                  "body": ("이 휴대폰으로 회의 시작·끝, 결재 요청, "
                                           "주문 알림을 받습니다."),
                                  "url": "/settings", "tag": "test"}, service.clock())
        return {"sent": sent}

    @app.post("/api/v1/company/auto-approve")
    def set_auto_approve(body: AutoApproveBody) -> dict[str, object]:
        """Paper-trading period switch: approve every request as it is filed (local setting)."""
        with transaction(inbox.conn):
            inbox.book.set_auto_approve(body.enabled, service.clock())
        return {"auto_approve": inbox.book.auto_approve()}

    @app.get("/api/v1/office/now")
    def office_now() -> dict[str, object]:
        """What the company is doing now and next (CCTV header, inbox summary)."""
        now = service.clock()
        runs = service.repo.list_runs()
        active = next((r for r in runs if r.status.value in ("QUEUED", "RUNNING")), None)
        slots = sorted(next_slots(now), key=lambda s: s.scheduled_at)
        upcoming: list[dict[str, object]] = [
            {"instrument_id": s.rule.instrument_id, "name": display_name(s.rule.instrument_id),
             "market": s.rule.instrument_id.split(":")[0], "at": s.scheduled_at,
             "kind": "committee"} for s in slots]
        if inbox.book.started_at() is not None:
            upcoming += [{"instrument_id": None,
                          "name": "국내 장 마감 정산" if m is Market.KR else "미국 장 마감 정산",
                          "market": m.value, "at": at, "kind": "settle"}
                         for m, at in settle_times(now)]
            upcoming.sort(key=lambda u: u["at"])  # type: ignore[arg-type,return-value]
        status = service.budget()
        return {
            "now": now,
            "active": {"run_id": active.id, "instrument_id": active.instrument_id,
                       "name": display_name(active.instrument_id), "status": active.status.value,
                       "demo": active.demo} if active else None,
            "next": upcoming,
            "budget": status.model_dump(mode="json") if status else None,
            "pending_approvals": sum(1 for i in inbox.list()
                                     if i.status in ("PENDING", "DEFERRED")),
        }

    @app.get("/api/v1/budget")
    def get_budget() -> dict[str, object]:
        """This month's LLM spend, reservations and what is left of the budget."""
        status = service.budget()
        return {"configured": status is not None,
                "budget": status.model_dump(mode="json") if status else None}

    @app.get("/api/v1/office/summary")
    def office_summary() -> OfficeSummary:
        return build_summary(service.repo)

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

    @app.get("/api/v1/analysis-runs/{run_id}/snapshots")
    def get_snapshots(run_id: str) -> list[MarketSnapshot]:
        """Source data the run was given, with observed/available/ingested times (evidence)."""
        _run_or_404(run_id)
        return sorted(service.repo.get_snapshots(run_id),
                      key=lambda s: (s.kind, s.observed_at, s.id))

    @app.get("/api/v1/analysis-runs/{run_id}/reports")
    def get_reports(run_id: str) -> dict[str, object]:
        """Full sanitized reports. Runs stored before this existed have only event summaries."""
        _run_or_404(run_id)
        reports = service.repo.get_reports(run_id)
        return {"available": reports is not None, "reports": reports or {}}

    @app.get("/api/v1/analysis-runs/{run_id}/briefing")
    def get_briefing(run_id: str) -> dict[str, object]:
        """One-page AI summary of the stored reports, when it exists."""
        _run_or_404(run_id)
        briefing = service.repo.get_briefing(run_id)
        return {"available": briefing is not None, "briefing": briefing}

    @app.get("/api/v1/analysis-runs/{run_id}/tool-results")
    def get_tool_results(run_id: str) -> dict[str, object]:
        """What the analysts' tools returned (redacted). Older runs did not store them."""
        _run_or_404(run_id)
        results = service.repo.get_tool_results(run_id)
        return {"available": results is not None, "results": results or []}

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
