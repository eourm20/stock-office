"""Closing report: the plain "오늘 한눈에" lines (no model, no network)."""

from __future__ import annotations

from decimal import Decimal as D

from stock_office.kiwoom_mock.closing import Meeting, compose, glance


def test_the_day_at_a_glance_in_plain_words() -> None:
    meetings = [Meeting("삼성전자", "BUY", False, D("1.2"), "50,000원", "매수 19주 체결"),
                Meeting("한화오션", "HOLD", False, D("8.5"), "90,000원"),
                Meeting("NAVER", "HOLD", True, D("-0.5"), "200,000원")]
    lines = glance(D("0.40"), D("-1.20"), meetings, "AI 규제 우려로 반도체가 약한 하루")
    assert lines == [
        "오늘 계좌는 +0.40%, 시장(지수)은 -1.20%로 시장보다 잘 버텼어요.",
        "오늘 시장 분위기: AI 규제 우려로 반도체가 약한 하루",
        "오늘 회의 3건(매수 1 · 유지 2). 주문으로 이어진 건 삼성전자예요. "
        "사지 않은 한화오션은(는) 오늘 +8.50% 올랐어요.",
    ]
    assert glance(None, None, [], None) == []


def test_the_glance_comes_first_in_the_closing_report() -> None:
    _, _, sections = compose("KR", "2026-11-06", "10,040,000원", D(10_040_000), D(10_000_000),
                             D(10_000_000), D("-1.2"), [], [], [], [], mood=None)
    assert [s["title"] for s in sections][:2] == ["오늘 한눈에", "계좌"]
