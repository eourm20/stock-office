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
from pathlib import Path
from typing import Any, TypeVar

from stock_office.domain.instruments import REGISTRY, display_name
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
    "South Korea economy exports won",
    "China economy government policy stimulus",
    "ECB Bank of Japan central bank policy",
)
# Korean market mood and Korean economy/policy (owner, 2026-11-06: "우리나라 경제랑 정치는 안봐?"),
# Naver news, newest first, read before the global headlines for KRX stocks.
KR_MARKET_QUERIES = ("코스피 증시", "코스닥 증시", "외국인 순매도", "원달러 환율",
                     "한국은행 기준금리", "정부 증시 정책")
KR_MARKET_LIMIT = 10
KR_MARKET_SUBJECT = "KR:MARKET"

# The meeting stock's own industry (owner, 2026-11-06: meetings should also read the news of the
# stock's sector/theme). Yahoo's industry label, with a Korean press query for KRX stocks written
# for how Korean press names that industry (Yahoo files shipbuilders under Aerospace & Defense,
# batteries under Electrical Equipment, Samsung Electronics under Consumer Electronics).
THEME_KEY = "stockoffice_theme"
THEME_HEADLINES = 4
INDUSTRY_KO = {
    "Semiconductors": "반도체 업황", "Semiconductor Equipment & Materials": "반도체 장비 업황",
    "Consumer Electronics": "반도체 전자 업황", "Electronic Components": "전자부품 업황",
    "Electrical Equipment & Parts": "2차전지 전력기기", "Solar": "태양광 업계",
    "Auto Manufacturers": "자동차 업계", "Auto Parts": "자동차 부품 업계",
    "Aerospace & Defense": "방산 조선 수주", "Specialty Industrial Machinery": "조선 기계 수주",
    "Farm & Heavy Construction Machinery": "건설기계 업황",
    "Chemicals": "석유화학 업황", "Specialty Chemicals": "화학 소재 업황",
    "Steel": "철강 업황", "Other Industrial Metals & Mining": "비철금속 업황",
    "Metal Fabrication": "비철금속 업황", "Building Materials": "시멘트 건자재",
    "Engineering & Construction": "건설 수주", "Oil & Gas Refining & Marketing": "정유 업황",
    "Banks - Regional": "은행 금융지주", "Banks - Diversified": "은행 금융지주",
    "Capital Markets": "증권사 업황", "Insurance - Life": "보험 업계",
    "Insurance - Property & Casualty": "보험 업계", "Credit Services": "카드사 업계",
    "Asset Management": "지주회사 주가", "Conglomerates": "지주회사 주가",
    "Drug Manufacturers - General": "제약 업계",
    "Drug Manufacturers - Specialty & Generic": "제약 업계", "Biotechnology": "바이오 업계",
    "Medical Devices": "의료기기 업계", "Medical Distribution": "바이오 업계",
    "Household & Personal Products": "화장품 업계", "Apparel Manufacturing": "의류 패션 업계",
    "Textile Manufacturing": "섬유 업계", "Packaged Foods": "식품 업계",
    "Confectioners": "식품 업계", "Food Distribution": "식품 유통",
    "Beverages - Non-Alcoholic": "식품 음료 업계",
    "Beverages - Wineries & Distilleries": "주류 업계",
    "Tobacco": "담배 업계", "Department Stores": "유통 업계", "Discount Stores": "유통 업계",
    "Grocery Stores": "편의점 유통", "Specialty Retail": "면세점 업계",
    "Information Technology Services": "IT서비스 업계",
    "Software - Infrastructure": "IT서비스 업계", "Internet Content & Information": "인터넷 플랫폼",
    "Electronic Gaming & Multimedia": "게임 업계", "Entertainment": "엔터 업계",
    "Advertising Agencies": "광고 업계", "Telecom Services": "통신 업계",
    "Marine Shipping": "해운 업황", "Integrated Freight & Logistics": "물류 택배",
    "Airlines": "항공 업계", "Railroads": "철도 업계", "Resorts & Casinos": "카지노 여행",
    "Leisure": "여행 레저", "Utilities - Regulated Electric": "전기요금 한전",
    "Utilities - Regulated Gas": "가스요금", "Utilities - Renewable": "재생에너지",
    "Real Estate Services": "부동산 업계",
}
SECTOR_KO = {
    "Technology": "IT 업종", "Healthcare": "제약 바이오", "Financial Services": "금융주",
    "Consumer Cyclical": "소비 업종", "Consumer Defensive": "식품 생활용품",
    "Industrials": "산업재 업종", "Energy": "에너지 업종", "Basic Materials": "소재 업종",
    "Communication Services": "통신 미디어", "Utilities": "유틸리티 업종",
    "Real Estate": "부동산 업계",
}

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


ProfileFetch = Callable[[str], dict[str, Any]]   # yahoo symbol -> {"sector", "industry"}
PROFILE_DAYS = 30


def _yahoo_profile(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    info = yf.Ticker(symbol).info or {}
    return {"sector": info.get("sector"), "industry": info.get("industry")}


def theme_for(instrument: Instrument, cache: Path, now: datetime,
              fetch: ProfileFetch = _yahoo_profile) -> dict[str, Any] | None:
    """The stock's industry for the meeting's theme news (cached per stock for 30 days).
    None when Yahoo has no industry for it."""
    import json

    try:
        known: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    entry = known.get(instrument.id)
    fresh = entry and now - datetime.fromisoformat(entry["at"]) < timedelta(days=PROFILE_DAYS)
    if not fresh:
        try:
            entry = {**fetch(instrument.provider_symbols["yahoo"]), "at": now.isoformat()}
        except Exception as exc:
            logger.warning("industry lookup failed for %s: %s", instrument.id,
                           type(exc).__name__)
            return None
        known[instrument.id] = entry
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(known, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    industry, sector = (entry or {}).get("industry"), (entry or {}).get("sector")
    if not industry:
        return None
    return {"instrument_id": instrument.id, "name": display_name(instrument.id),
            "market": instrument.market.value, "industry": industry, "sector": sector,
            "kr_query": INDUSTRY_KO.get(industry) or SECTOR_KO.get(sector or "")}


def theme_section(theme: dict[str, Any], as_of: str, look_back_days: int,
                  naver: NaverNewsProvider | None, search: YahooSearch) -> str | None:
    """Headlines about the meeting stock's industry: Korean press for KRX stocks, and the global
    industry (peers, demand, regulation) from Yahoo for both markets."""
    lines: list[str] = []
    if theme["market"] == "KR" and theme.get("kr_query") and naver is not None \
            and naver.configured:
        for s in kr_market_headlines(naver, as_of, look_back_days, [theme["kr_query"]],
                                     limit=THEME_HEADLINES):
            p = s.payload
            lines.append(f"- {s.observed_at:%Y-%m-%d %H:%M} | {p['title']} - {p['description']} "
                         f"| {p['link']}")
    for a in yahoo_global_articles(as_of, look_back_days, THEME_HEADLINES,
                                   [f"{theme['industry']} stocks"], search):
        when = f"{a['pub_date']:%Y-%m-%d %H:%M}" if a.get("pub_date") else "undated"
        lines.append(f"- {when} | {a['title']} ({a['publisher']}) - {a['summary']} "
                     f"| {a['link']}")
    if not lines:
        return None
    kr = f" / Korean press query '{theme['kr_query']}'" if theme["market"] == "KR" else ""
    return "\n".join([
        f"## Industry and theme news for {theme['name']} ({theme['industry']}), up to {as_of}",
        f"Source: Yahoo Finance search '{theme['industry']} stocks'{kr}. News about the "
        "industry this company is in (peers, demand, prices, regulation); not about the company "
        "itself unless it is named. Industry label from Yahoo, which can be approximate.",
        "", *lines])


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
        theme = config.get(THEME_KEY)
        if theme:
            industry = theme_section(theme, curr_date, days, naver, search)
            if industry:
                sections.append(industry)
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
