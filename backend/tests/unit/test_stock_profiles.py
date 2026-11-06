"""Stock profiles: made once from the public profile, cached, budgeted (no model, no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from stock_office.db import connect
from stock_office.market_news import usages_in_month
from stock_office.stock_profiles import ProfileDraft, profile

NOW = datetime(2026, 11, 6, 7, 0, tzinfo=UTC)
USAGE = {"gpt-6-luna": {"input_tokens": 600, "output_tokens": 80}}


class Writer:
    model = "gpt-6-luna"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> tuple[ProfileDraft, dict[str, Any]]:
        self.prompts.append(prompt)
        return ProfileDraft(kind="회사", what="스마트폰과 반도체를 만드는 전자 회사예요.",
                            themes=["반도체", "스마트폰", " ", "가전", "AI", "다섯째"]), USAGE


def info(symbol: str) -> dict[str, Any]:
    return {"quoteType": "EQUITY", "longName": "Samsung Electronics Co., Ltd.",
            "industry": "Consumer Electronics", "longBusinessSummary": "x" * 5000}


def test_made_once_then_cached_and_counted(tmp_path: Path) -> None:
    conn, writer = connect(tmp_path), Writer()
    body = profile(conn, "KR:KRX:005930", NOW, writer, info)
    assert body["name"] == "삼성전자" and body["kind"] == "회사"
    assert body["themes"] == ["반도체", "스마트폰", "가전", "AI"]
    assert '"korean_name": "삼성전자"' in writer.prompts[0] and "x" * 1501 not in writer.prompts[0]
    assert profile(conn, "KR:KRX:005930", NOW + timedelta(days=30), None, info) == body
    assert len(writer.prompts) == 1                                     # cached
    assert usages_in_month(conn, "2026-11") == [USAGE]
    with pytest.raises(RuntimeError):                                  # stale, no engine
        profile(conn, "KR:KRX:005930", NOW + timedelta(days=91), None, info)
    with pytest.raises(LookupError):
        profile(conn, "KR:KRX:999999", NOW, writer, info)
    with pytest.raises(RuntimeError):
        profile(conn, "US:NASDAQ:NVDA", NOW, writer, lambda s: {})    # no public profile
