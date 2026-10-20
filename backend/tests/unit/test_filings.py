"""Only important filings reach the CEO; routine ones are checked but not reported."""

from __future__ import annotations

from datetime import date

import httpx

from stock_office.filings import kr_topic
from stock_office.providers.sec import SecFilings


def test_kr_important_filings_by_name() -> None:
    assert kr_topic("연결재무제표기준영업(잠정)실적(공정공시)") == "실적"
    assert kr_topic("주요사항보고서(자기주식취득결정)") == "자사주 취득"
    assert kr_topic("단일판매ㆍ공급계약체결") == "대규모 공급계약"
    assert kr_topic("임원ㆍ주요주주특정증권등소유상황보고서") is None
    assert kr_topic("기업설명회(IR)개최(안내공시)") is None
    assert kr_topic("[기재정정]주요사항보고서(유상증자결정)") is None


def test_us_routine_8k_and_6k_are_not_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("company_tickers.json"):
            return httpx.Response(200, json={"0": {"cik_str": 1, "ticker": "ASML"}})
        return httpx.Response(200, json={"filings": {"recent": {
            "form": ["8-K", "8-K", "6-K", "8-K/A"],
            "filingDate": ["2026-10-20"] * 4,
            "accessionNumber": ["a", "b", "c", "d"],
            "items": ["7.01,9.01", "5.02", "", "2.02"],
            "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm"],
        }}})

    sec = SecFilings("ops@example.com", httpx.Client(transport=httpx.MockTransport(handler)))
    assert [(a, t) for a, t, _ in sec.recent("ASML", date(2026, 10, 20))] == [
        ("b", "8-K 수시 공시 · 임원·이사 변경")]
