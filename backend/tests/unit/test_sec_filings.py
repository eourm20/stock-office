"""SEC EDGAR filings: ticker → CIK, report-worthy forms of the last few days, no network."""

from __future__ import annotations

from datetime import date

import httpx

from stock_office.providers.sec import SecFilings


def test_recent_filings_are_titled_in_korean_and_linked() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        if request.url.path.endswith("company_tickers.json"):
            return httpx.Response(200, json={"0": {"cik_str": 1045810, "ticker": "NVDA"}})
        return httpx.Response(200, json={"filings": {"recent": {
            "form": ["8-K", "4", "10-Q", "8-K"],
            "filingDate": ["2026-10-20", "2026-10-20", "2026-10-17", "2026-10-01"],
            "accessionNumber": ["0001045810-26-000101", "x", "0001045810-26-000099", "old"],
            "items": ["2.02,9.01", "", "", "5.02"],
            "primaryDocument": ["nvda-8k.htm", "", "nvda-10q.htm", "a.htm"],
        }}})

    sec = SecFilings("Stock Office ops@example.com",
                     httpx.Client(transport=httpx.MockTransport(handler)))
    found = sec.recent("NVDA", date(2026, 10, 20))
    assert [(acc, title) for acc, title, _ in found] == [
        ("0001045810-26-000099", "10-Q 분기 보고서"),
        ("0001045810-26-000101", "8-K 수시 공시 · 실적 발표")]
    assert found[1][2] == ("https://www.sec.gov/Archives/edgar/data/1045810/"
                           "000104581026000101/nvda-8k.htm")
    assert set(seen) == {"Stock Office ops@example.com"}
    assert sec.recent("ZZZZ", date(2026, 10, 20)) == []      # unknown ticker; map cached
    assert len(seen) == 2
