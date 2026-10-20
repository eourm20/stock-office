"""Default engine/provider wiring from Settings."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from stock_office.briefing import BriefingWriter, DemoBriefingWriter, QuickModelBriefingWriter
from stock_office.config import Settings
from stock_office.db import connect
from stock_office.domain.models import AnalysisRun, EngineName
from stock_office.engine.adapter import AnalysisEngine
from stock_office.engine.demo_engine import DemoEngine
from stock_office.engine.tradingagents_engine import TradingAgentsEngine
from stock_office.inbox import Inbox
from stock_office.paper.book import Book
from stock_office.paper.costs import Costs
from stock_office.paper.settle import Settler
from stock_office.providers.base import MarketDataProvider
from stock_office.providers.dart import DartDisclosureProvider
from stock_office.providers.fixture import FixtureProvider
from stock_office.providers.naver import NaverNewsProvider
from stock_office.providers.yahoo import YahooPriceProvider
from stock_office.runs.repository import RunRepository
from stock_office.runs.service import RunService


def build_service(settings: Settings) -> RunService:
    def engines(name: EngineName) -> AnalysisEngine:
        if name == "demo":
            return DemoEngine()
        return TradingAgentsEngine(settings)

    def providers(name: EngineName) -> Sequence[MarketDataProvider]:
        if name == "demo":
            return [FixtureProvider()]
        key = settings.dart_api_key.get_secret_value() if settings.dart_api_key else None
        naver = NaverNewsProvider(
            settings.naver_client_id.get_secret_value() if settings.naver_client_id else None,
            settings.naver_client_secret.get_secret_value()
            if settings.naver_client_secret
            else None,
        )
        return [YahooPriceProvider(), DartDisclosureProvider(api_key=key), naver]

    repo = RunRepository(settings.data_dir)

    def briefers(run: AnalysisRun) -> BriefingWriter:
        if run.demo:
            return DemoBriefingWriter()
        engine = TradingAgentsEngine(settings)
        return QuickModelBriefingWriter(engine.build_config(repo.root / run.id))

    service = RunService(repo, engines, providers,
                         max_paid_runs_per_day=settings.max_paid_runs_per_day, briefers=briefers,
                         monthly_budget_usd=settings.monthly_budget_usd)
    service.inbox = build_inbox(settings, repo)
    service.reporter = lambda run: service.inbox.file_run(run, service.clock())
    return service


def costs_from(settings: Settings) -> Costs:
    return Costs(
        kr_commission=settings.paper_kr_commission,
        kr_sell_tax=settings.paper_kr_sell_tax,
        us_commission=settings.paper_us_commission,
        fx_spread=settings.paper_fx_spread,
        slippage=settings.paper_slippage,
    )


def build_inbox(settings: Settings, repo: RunRepository) -> Inbox:
    from stock_office.kiwoom_mock.desks import build_desks
    from stock_office.kiwoom_mock.link import build_link
    from stock_office.providers.yahoo import usd_krw_rate

    conn = connect(settings.data_dir)
    link = build_link(settings)

    def accounts(market: str) -> dict[str, Any] | None:
        acc: dict[str, Any] | None = link.status()["accounts"].get(market)
        return acc

    return Inbox(conn, repo, fx=usd_krw_rate, book=Book(conn, costs=costs_from(settings)),
                 desks=build_desks(settings, conn), accounts=accounts)


def build_settler(inbox: Inbox) -> Settler:
    from stock_office.providers.yahoo import daily_bar, usd_krw_rate

    return Settler(inbox.book, daily_bar, usd_krw_rate)
