"""Read-only Korean news headlines from the official Naver Search API (news).

Only what the API returns is used: title, short description, links and publication time. Article
bodies are never fetched. Each item becomes a `news` snapshot whose observed/available time is the
publication time, so the point-in-time guard applies as for any other source. The query is the
company's Korean name. Without credentials the provider reports that it does not apply.

API: GET https://openapi.naver.com/v1/search/news.json (X-Naver-Client-Id / -Secret headers).
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

from stock_office.domain.instruments import display_name
from stock_office.domain.models import Instrument, Market, MarketSnapshot

from .base import ProviderError, ProviderResult, payload_hash, utcnow

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
_TAG = re.compile(r"<[^>]+>")

HttpGet = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


def _clean(text: str) -> str:
    return html.unescape(_TAG.sub("", text or "")).strip()


def _http_get(url: str, params: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    import httpx

    resp = httpx.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data


class NaverNewsProvider:
    name = "naver-news"

    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        lookback_days: int = 7,
        http_get: HttpGet = _http_get,
    ) -> None:
        self.client_id, self.client_secret = client_id or "", client_secret or ""
        self.lookback_days = lookback_days
        self.http_get = http_get

    @property
    def configured(self) -> bool:
        return bool(self.client_id.strip() and self.client_secret.strip())

    def supports(self, instrument: Instrument) -> bool:
        return self.configured and instrument.market is Market.KR

    def fetch(self, instrument: Instrument, as_of: datetime) -> ProviderResult:
        end = as_of.date()
        return self.fetch_range(instrument, end - timedelta(days=self.lookback_days), end)

    def fetch_range(
        self, instrument: Instrument, start: date, end: date, limit: int = 30
    ) -> ProviderResult:
        if not self.supports(instrument):
            return ProviderResult(
                coverage_gaps=[f"{self.name}: not configured for {instrument.id}"]
            )
        query = display_name(instrument.id)
        try:
            data = self.http_get(
                NAVER_NEWS_URL,
                {"query": query, "display": min(limit, 100), "sort": "date"},
                {"X-Naver-Client-Id": self.client_id, "X-Naver-Client-Secret": self.client_secret},
            )
        except Exception as exc:
            raise ProviderError("PROVIDER_REQUEST_FAILED", type(exc).__name__) from exc
        ingested = utcnow()
        snapshots: list[MarketSnapshot] = []
        seen: set[str] = set()
        for item in data.get("items", []):
            try:
                published = parsedate_to_datetime(str(item.get("pubDate", "")))
            except (TypeError, ValueError):
                continue
            if published.tzinfo is None or not start <= published.date() <= end:
                continue
            link = str(item.get("originallink") or item.get("link") or "")
            title = _clean(str(item.get("title", "")))
            key = link or title
            if not title or key in seen:
                continue
            seen.add(key)
            payload = {
                "query": query,
                "title": title,
                "description": _clean(str(item.get("description", ""))),
                "link": link,
                "naver_link": str(item.get("link") or ""),
            }
            snapshots.append(
                MarketSnapshot(
                    id=f"naver-{hashlib.sha256(key.encode()).hexdigest()[:16]}",
                    instrument_id=instrument.id,
                    source=self.name,
                    kind="news",
                    observed_at=published,
                    available_at=published,
                    ingested_at=ingested,
                    payload=payload,
                    payload_hash=payload_hash(payload),
                    source_url=link or None,
                )
            )
        if not snapshots:
            return ProviderResult(
                coverage_gaps=[f"{self.name}: no news for {query} {start}..{end}"]
            )
        return ProviderResult(snapshots=snapshots)
