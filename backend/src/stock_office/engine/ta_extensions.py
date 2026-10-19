"""Stock Office extensions to TradingAgents, registered at runtime (no upstream file is edited).

1. `stockoffice_dart` news vendor: for KRX stocks Yahoo often has no company news (observed
   for 005930.KS on 2026-10-16), so the News Analyst got nothing. This vendor serves official
   OpenDART disclosures for the same window, clearly labelled as filings, not press news.
   Upstream `get_news` already clamps the window to the run's trade date (point-in-time).
2. `UpstreamDataGapCollector`: upstream logs vendor failures (e.g. Polymarket HTTP 451, Yahoo
   "no news") as warnings and carries on. The collector turns them into run coverage gaps.

Guarded by tests/contract/test_upstream_graph.py against the pinned upstream version.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date

from stock_office.domain.instruments import REGISTRY
from stock_office.domain.models import Instrument, Market, MarketSnapshot
from stock_office.engine.upstream import import_tradingagents
from stock_office.events.sanitize import redact_text
from stock_office.providers.dart import DartDisclosureProvider

KR_NEWS_VENDOR = "stockoffice_dart"
PREDICTION_OFF_VENDOR = "stockoffice_off"
MAX_GAPS = 10


def instrument_for_provider_symbol(symbol: str) -> Instrument | None:
    return next((i for i in REGISTRY.values() if i.provider_symbols.get("yahoo") == symbol), None)


def format_disclosures(symbol: str, start: str, end: str,
                       disclosures: list[MarketSnapshot]) -> str:
    lines = [
        f"## Official OpenDART disclosures for {symbol}, {start} to {end}",
        "Source: Korea FSS OpenDART regulatory filings. These are company/insider filings, "
        "NOT press news articles; treat them as primary-source events.",
        "",
    ]
    for snap in sorted(disclosures, key=lambda s: s.payload["rcept_dt"], reverse=True):
        p = snap.payload
        filed = f"{p['rcept_dt'][:4]}-{p['rcept_dt'][4:6]}-{p['rcept_dt'][6:]}"
        lines.append(f"- {filed} | {p['report_nm']} | filer: {p.get('flr_nm') or 'n/a'} "
                     f"| {snap.source_url}")
    return "\n".join(lines)


def make_kr_news_vendor(provider_factory: Callable[[], DartDisclosureProvider]
                        ) -> Callable[[str, str, str], str]:
    def kr_dart_news(ticker: str, start_date: str, end_date: str) -> str:
        import_tradingagents()
        from tradingagents.dataflows.errors import NoMarketDataError

        instrument = instrument_for_provider_symbol(ticker)
        provider = provider_factory()
        if instrument is None or instrument.market is not Market.KR \
                or not provider.supports(instrument):
            raise NoMarketDataError(ticker, detail="OpenDART covers Korean listed companies only")
        result = provider.fetch_range(instrument, date.fromisoformat(start_date),
                                      date.fromisoformat(end_date))
        if not result.snapshots:
            detail = "; ".join(result.coverage_gaps) or "no disclosures in window"
            raise NoMarketDataError(ticker, detail=detail)
        return format_disclosures(ticker, start_date, end_date, result.snapshots)

    return kr_dart_news


def register_kr_news_vendor(provider_factory: Callable[[], DartDisclosureProvider]) -> None:
    import_tradingagents()
    from tradingagents.dataflows.router import VENDOR_METHODS

    VENDOR_METHODS["get_news"][KR_NEWS_VENDOR] = make_kr_news_vendor(provider_factory)


def register_prediction_markets_off() -> None:
    """A prediction-markets vendor that is honestly unavailable, without any network call.

    Upstream treats prediction markets as optional: an unavailable vendor degrades to a
    "data unavailable" note for the model and a logged warning (recorded as a coverage gap).
    """
    import_tradingagents()
    from tradingagents.dataflows.errors import VendorUnavailableError
    from tradingagents.dataflows.router import VENDOR_METHODS

    def off(*_args: object, **_kwargs: object) -> str:
        raise VendorUnavailableError("prediction markets disabled in Stock Office "
                                     "(Polymarket blocks this network: HTTP 451)")

    VENDOR_METHODS["get_prediction_markets"][PREDICTION_OFF_VENDOR] = off


NOT_USED = re.compile(r"prediction markets disabled in Stock Office|polymarket|"
                      r"get_prediction_markets", re.IGNORECASE)


class UpstreamDataGapCollector(logging.Handler):
    """Collects upstream data warnings (deduplicated, redacted, capped) during one run."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.gaps: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        # Prediction markets are switched off on purpose (blocked from this network): a tool
        # we do not use is not missing data.
        if NOT_USED.search(message):
            return
        text = redact_text(f"tradingagents: {message}", limit=240)
        if text not in self.gaps and len(self.gaps) < MAX_GAPS:
            self.gaps.append(text)


@contextmanager
def collect_upstream_data_gaps() -> Iterator[UpstreamDataGapCollector]:
    logger = logging.getLogger("tradingagents")
    collector = UpstreamDataGapCollector()
    logger.addHandler(collector)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
