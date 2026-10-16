"""Default engine/provider wiring from Settings."""

from __future__ import annotations

from collections.abc import Sequence

from stock_office.config import Settings
from stock_office.domain.models import EngineName
from stock_office.engine.adapter import AnalysisEngine
from stock_office.engine.demo_engine import DemoEngine
from stock_office.engine.tradingagents_engine import TradingAgentsEngine
from stock_office.providers.base import MarketDataProvider
from stock_office.providers.dart import DartDisclosureProvider
from stock_office.providers.fixture import FixtureProvider
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
        return [YahooPriceProvider(), DartDisclosureProvider(api_key=key)]

    return RunService(RunRepository(settings.data_dir), engines, providers)
