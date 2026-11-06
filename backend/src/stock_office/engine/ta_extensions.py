"""Stock Office extensions to TradingAgents, registered at runtime (no upstream file is edited).

1. `stockoffice_kr_news` news vendor: for KRX stocks Yahoo often has no company news (observed
   for 005930.KS on 2026-10-16). This vendor serves Korean press headlines from the official
   Naver Search API (title + summary only) and official OpenDART disclosures for the same window,
   each clearly labelled. It runs before Yahoo for KRX stocks. Upstream `get_news` already
   clamps the window to the run's trade date (point-in-time).
2. `stockoffice_global_news` / `stockoffice_kr_global_news` vendors for `get_global_news`
   (owner, 2026-11-06: the company reads the news the CEO cannot). Upstream searches its
   queries in order and stops once the limit is filled, so in practice only the first (Fed)
   query was read. These take headlines topic by topic over Stock Office's own queries
   (tech/AI policy, US politics, chips, ...); for KRX stocks Korean market-wide headlines
   (KOSPI, foreign selling, FX) from Naver come first.
3. `UpstreamDataGapCollector`: upstream logs vendor failures (e.g. Polymarket HTTP 451, Yahoo
   "no news") as warnings and carries on. The collector turns them into run coverage gaps.

Guarded by tests/contract/test_upstream_graph.py against the pinned upstream version.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Hashable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, TypeVar

from stock_office.domain.instruments import REGISTRY
from stock_office.domain.models import Instrument, Market, MarketSnapshot
from stock_office.engine.upstream import import_tradingagents
from stock_office.events.sanitize import redact_text
from stock_office.providers.dart import DartDisclosureProvider
from stock_office.providers.naver import NaverNewsProvider

KR_NEWS_VENDOR = "stockoffice_kr_news"
GLOBAL_NEWS_VENDOR = "stockoffice_global_news"
KR_GLOBAL_NEWS_VENDOR = "stockoffice_kr_global_news"
PREDICTION_OFF_VENDOR = "stockoffice_off"
MAX_GAPS = 10

# Market-wide topics for both desks (Yahoo search, English). Order is only a tie-break: every
# topic gets a headline before any gets a second.
GLOBAL_NEWS_QUERIES = (
    "stock market today",
    "Federal Reserve interest rates inflation",
    "AI data center spending regulation",
    "US Congress legislation election market impact",
    "semiconductor chips export controls",
    "tariffs trade war geopolitical risk",
    "oil energy commodities prices",
)
# Korean market mood (Naver news, newest first), read before the global headlines for KRX stocks.
KR_MARKET_QUERIES = ("코스피 증시", "코스닥 증시", "외국인 순매도", "원달러 환율")
KR_MARKET_LIMIT = 10
KR_MARKET_SUBJECT = "KR:MARKET"

logger = logging.getLogger("tradingagents.stockoffice")   # collected as gaps with upstream's

T = TypeVar("T")


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


def format_news(symbol: str, start: str, end: str, news: list[MarketSnapshot]) -> str:
    lines = [
        f"## Korean press headlines for {symbol}, {start} to {end}",
        "Source: Naver News search (title and the publisher's summary only; full articles were "
        "not read). Secondary sources: weigh them against filings and prices.",
        "",
    ]
    for snap in sorted(news, key=lambda s: s.observed_at, reverse=True):
        p = snap.payload
        when = snap.observed_at.strftime("%Y-%m-%d %H:%M")
        lines.append(f"- {when} | {p['title']} - {p['description']} | {p['link']}")
    return "\n".join(lines)


def make_kr_news_vendor(
    dart_factory: Callable[[], DartDisclosureProvider],
    naver_factory: Callable[[], NaverNewsProvider] | None = None,
) -> Callable[[str, str, str], str]:
    def kr_news(ticker: str, start_date: str, end_date: str) -> str:
        import_tradingagents()
        from tradingagents.dataflows.errors import NoMarketDataError

        instrument = instrument_for_provider_symbol(ticker)
        if instrument is None or instrument.market is not Market.KR:
            raise NoMarketDataError(ticker, detail="Korean news covers KRX-listed companies only")
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        sections: list[str] = []
        gaps: list[str] = []
        naver = naver_factory() if naver_factory else None
        if naver is not None and naver.supports(instrument):
            got = naver.fetch_range(instrument, start, end)
            if got.snapshots:
                sections.append(format_news(ticker, start_date, end_date, got.snapshots))
            gaps.extend(got.coverage_gaps)
        dart = dart_factory()
        if dart.supports(instrument):
            got = dart.fetch_range(instrument, start, end)
            if got.snapshots:
                sections.append(format_disclosures(ticker, start_date, end_date, got.snapshots))
            gaps.extend(got.coverage_gaps)
        if not sections:
            raise NoMarketDataError(ticker, detail="; ".join(gaps) or "no news or disclosures")
        return "\n\n".join(sections)

    return kr_news


def register_kr_news_vendor(
    dart_factory: Callable[[], DartDisclosureProvider],
    naver_factory: Callable[[], NaverNewsProvider] | None = None,
) -> None:
    import_tradingagents()
    from tradingagents.dataflows.router import VENDOR_METHODS

    VENDOR_METHODS["get_news"][KR_NEWS_VENDOR] = make_kr_news_vendor(dart_factory, naver_factory)


def interleave(groups: Sequence[Sequence[T]], limit: int, key: Callable[[T], Hashable]
               ) -> list[T]:
    """Round-robin over groups (first of each, then second of each, ...), deduplicated."""
    out: list[T] = []
    seen: set[Hashable] = set()
    for rank in range(max((len(g) for g in groups), default=0)):
        for group in groups:
            if rank >= len(group) or len(out) >= limit:
                continue
            k = key(group[rank])
            if k not in seen:
                seen.add(k)
                out.append(group[rank])
    return out


YahooSearch = Callable[[str, int], list[dict[str, Any]]]


def _yahoo_search(query: str, count: int) -> list[dict[str, Any]]:
    import yfinance as yf
    from tradingagents.dataflows.vendors.yahoo.common import yf_retry

    found = yf_retry(lambda: yf.Search(query=query, news_count=count,
                                       enable_fuzzy_query=True).news)
    return list(found or [])


def yahoo_global_articles(as_of: str, look_back_days: int, limit: int,
                          queries: Sequence[str], search: YahooSearch) -> list[dict[str, Any]]:
    """Yahoo articles in the window (none after `as_of`), topic by topic, deduplicated by title.
    Each: title, summary, publisher, link, pub_date."""
    import_tradingagents()
    from tradingagents.dataflows.date_window import in_window
    from tradingagents.dataflows.vendors.yahoo.news import _extract_article_data

    end = datetime.strptime(as_of, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    groups: list[list[dict[str, Any]]] = []
    for query in queries:
        try:
            found = search(query, limit)
        except Exception as exc:
            logger.warning("Yahoo global news search failed for %r: %s", query,
                           type(exc).__name__)
            continue
        articles = [_extract_article_data(a) for a in found]
        groups.append([a for a in articles
                       if a["title"] and in_window(a["pub_date"], start, end)])
    return interleave(groups, limit, key=lambda a: a["title"])


def yahoo_global_section(as_of: str, look_back_days: int, limit: int,
                         queries: Sequence[str], search: YahooSearch) -> str | None:
    from tradingagents.dataflows.vendors.yahoo.news import _format_articles

    picked = yahoo_global_articles(as_of, look_back_days, limit, queries, search)
    if not picked:
        return None
    start = datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=look_back_days)
    return (f"## Global market news, {start:%Y-%m-%d} to {as_of}\n"
            f"Source: Yahoo Finance search, headlines spread over these topics: "
            f"{'; '.join(queries)}.\n\n{_format_articles(picked)}")


def kr_market_headlines(naver: NaverNewsProvider, as_of: str, look_back_days: int,
                        queries: Sequence[str] = KR_MARKET_QUERIES,
                        limit: int = KR_MARKET_LIMIT) -> list[MarketSnapshot]:
    """Naver headlines for market-wide queries, query by query, deduplicated by link."""
    end = date.fromisoformat(as_of)
    start = end - timedelta(days=look_back_days)
    groups: list[list[MarketSnapshot]] = []
    for query in queries:
        try:
            got = naver.search(query, KR_MARKET_SUBJECT, start, end, limit=limit)
        except Exception as exc:
            logger.warning("Naver market news failed for %r: %s", query, type(exc).__name__)
            continue
        groups.append(sorted(got.snapshots, key=lambda s: s.observed_at, reverse=True))
    return interleave(groups, limit, key=lambda s: s.payload["link"] or s.payload["title"])


def kr_market_section(naver: NaverNewsProvider, as_of: str, look_back_days: int) -> str | None:
    picked = kr_market_headlines(naver, as_of, look_back_days)
    if not picked:
        return None
    start = date.fromisoformat(as_of) - timedelta(days=look_back_days)
    lines = [
        f"## Korean stock market headlines, {start} to {as_of}",
        "Source: Naver News search for the Korean market as a whole "
        f"({', '.join(KR_MARKET_QUERIES)}); title and the publisher's summary only. "
        "Market mood, not news about this company.",
        "",
    ]
    for snap in sorted(picked, key=lambda s: s.observed_at, reverse=True):
        p = snap.payload
        lines.append(f"- {snap.observed_at:%Y-%m-%d %H:%M} | {p['title']} - {p['description']} "
                     f"| {p['link']}")
    return "\n".join(lines)


def make_global_news_vendor(
    naver_factory: Callable[[], NaverNewsProvider] | None = None,
    search: YahooSearch = _yahoo_search,
) -> Callable[..., str]:
    """`naver_factory` given: Korean market headlines first (the KRX desk's vendor)."""
    def global_news(curr_date: str, look_back_days: int | None = None,
                    limit: int | None = None) -> str:
        import_tradingagents()
        from tradingagents.dataflows.config import get_config
        from tradingagents.dataflows.errors import VendorUnavailableError

        config = get_config()
        days = look_back_days or config["global_news_lookback_days"]
        sections: list[str] = []
        naver = naver_factory() if naver_factory else None
        if naver is not None and naver.configured:
            kr = kr_market_section(naver, curr_date, days)
            if kr:
                sections.append(kr)
        world = yahoo_global_section(curr_date, days, limit or config["global_news_article_limit"],
                                     config["global_news_queries"], search)
        if world:
            sections.append(world)
        if not sections:
            raise VendorUnavailableError("no market-wide headlines in the window")
        return "\n\n".join(sections)

    return global_news


def register_global_news_vendors(
    naver_factory: Callable[[], NaverNewsProvider] | None = None,
    search: YahooSearch = _yahoo_search,
) -> None:
    import_tradingagents()
    from tradingagents.dataflows.router import VENDOR_METHODS

    VENDOR_METHODS["get_global_news"][GLOBAL_NEWS_VENDOR] = make_global_news_vendor(None, search)
    VENDOR_METHODS["get_global_news"][KR_GLOBAL_NEWS_VENDOR] = make_global_news_vendor(
        naver_factory, search)


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
