"""Naver news provider: parsing, point-in-time window, dedupe, not-configured (no network)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from stock_office.domain.instruments import get_instrument
from stock_office.providers.naver import NaverNewsProvider

ITEMS = {
    "items": [
        {
            "title": "삼성전자 &quot;<b>HBM</b>&quot; 확대",
            "description": "<b>요약</b> 문장",
            "originallink": "https://a.example/1",
            "link": "https://n.news/1",
            "pubDate": "Wed, 14 Oct 2026 09:00:00 +0900",
        },
        {
            "title": "중복 기사",
            "description": "",
            "originallink": "https://a.example/1",
            "pubDate": "Wed, 14 Oct 2026 10:00:00 +0900",
        },
        {
            "title": "창 밖의 기사",
            "description": "",
            "originallink": "https://a.example/2",
            "pubDate": "Mon, 05 Oct 2026 09:00:00 +0900",
        },
        {
            "title": "날짜 깨짐",
            "description": "",
            "originallink": "https://a.example/3",
            "pubDate": "?",
        },
    ]
}


def test_parses_cleans_dedupes_and_keeps_the_window() -> None:
    calls: list[dict[str, object]] = []

    def api(_url: str, params: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
        calls.append(params)
        assert headers["X-Naver-Client-Id"] == "id"
        return ITEMS

    p = NaverNewsProvider("id", "secret", http_get=api)
    got = p.fetch_range(get_instrument("KR:KRX:005930"), date(2026, 10, 9), date(2026, 10, 16))
    assert calls[0]["query"] == "삼성전자" and calls[0]["sort"] == "date"
    assert len(got.snapshots) == 1
    snap = got.snapshots[0]
    assert (
        snap.payload["title"] == '삼성전자 "HBM" 확대'
        and snap.payload["description"] == "요약 문장"
    )
    assert snap.kind == "news" and snap.source_url == "https://a.example/1"
    assert snap.available_at == datetime(2026, 10, 14, 0, 0, tzinfo=UTC)  # published time


def test_not_configured_or_us_stock_does_not_apply() -> None:
    assert not NaverNewsProvider(None, None).supports(get_instrument("KR:KRX:005930"))
    assert not NaverNewsProvider("id", "s").supports(get_instrument("US:NASDAQ:NVDA"))
    empty = NaverNewsProvider("id", "s", http_get=lambda *_: {"items": []})
    got = empty.fetch_range(get_instrument("KR:KRX:005930"), date(2026, 10, 9), date(2026, 10, 16))
    assert got.snapshots == [] and got.coverage_gaps
