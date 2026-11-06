"""[시장 브리핑]: slot timing, collection, source-checked picks, failures filed, budget.

No network."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from stock_office.budget import budget_status
from stock_office.db import connect
from stock_office.market_news import (
    MarketBriefingDraft,
    NewsPick,
    due,
    finalize,
    usages_in_month,
    write,
)
from stock_office.providers.naver import NaverNewsProvider
from stock_office.runs.repository import RunRepository

pytest.importorskip("tradingagents")

NOW = datetime(2026, 11, 5, 22, 30, tzinfo=UTC)   # Fri 11/6 07:30 KST, before the KRX open
USAGE = {"gpt-6-luna": {"input_tokens": 6000, "output_tokens": 3000}}


def article(title: str, when: str) -> dict[str, Any]:
    return {"content": {"title": title, "summary": f"{title} summary",
                        "provider": {"displayName": "Reuters"},
                        "canonicalUrl": {"url": f"https://y.example/{title}"}, "pubDate": when}}


def yahoo(query: str, count: int) -> list[dict[str, Any]]:
    return [article(f"{query[:12]} now", "2026-11-05T20:00:00Z"),
            article(f"{query[:12]} future", "2026-11-09T20:00:00Z")]


def naver() -> NaverNewsProvider:
    def api(_url: str, params: dict[str, object], _h: dict[str, str]) -> dict[str, object]:
        return {"items": [{"title": f"{params['query']} 소식", "description": "요약",
                           "originallink": f"https://n.example/{params['query']}",
                           "pubDate": "Thu, 05 Nov 2026 16:00:00 +0900"}]}
    return NaverNewsProvider("id", "secret", http_get=api)


class Writer:
    model = "gpt-6-luna"

    def __init__(self, picks: list[NewsPick] | None = None, fail: bool = False) -> None:
        self.picks, self.fail, self.prompts = picks, fail, []

    def __call__(self, prompt: str) -> tuple[MarketBriefingDraft, dict[str, Any]]:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("model down")
        picks = self.picks if self.picks is not None else [
            NewsPick(source_ids=["e3", "k1"], title="AI 데이터센터 규제 우려",
                     summary="미국에서 데이터센터 규제 법안이 논의된다는 보도가 있어요.",
                     story="비유하자면 마을이 새 공장 짓기를 막겠다고 하는 것과 같아요.",
                     why="반도체 수요가 줄 수 있다는 우려예요.", markets=["KR", "US"],
                     sectors=["반도체", "엔비디아"], direction="나쁨"),
            NewsPick(source_ids=["zz9"], title="출처 없는 소식", summary="지어낸 이야기",
                     story="", why="", markets=["US"], direction="좋음"),
        ]
        return MarketBriefingDraft(mood="반도체 걱정이 큰 하루", picks=picks), USAGE


def test_slots_are_before_each_open() -> None:
    assert due("KR", NOW) == date(2026, 11, 6)                                # 07:30 KST
    assert due("KR", datetime(2026, 11, 5, 21, 0, tzinfo=UTC)) is None        # 06:00 KST
    assert due("KR", datetime(2026, 11, 6, 0, 30, tzinfo=UTC)) is None        # market open
    # NYSE opens 14:30 UTC (23:30 KST) after DST: slot from 13:00 UTC (22:00 KST)
    assert due("US", datetime(2026, 11, 6, 13, 10, tzinfo=UTC)) == date(2026, 11, 6)
    assert due("US", datetime(2026, 11, 6, 12, 50, tzinfo=UTC)) is None
    assert due("US", datetime(2026, 11, 7, 13, 10, tzinfo=UTC)) is None       # Saturday


def test_writes_one_briefing_with_sources_from_the_collected_list(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    writer = Writer()
    item_id = write(conn, "KR", date(2026, 11, 6), NOW, naver(), writer, search=yahoo)
    assert item_id is not None
    row = conn.execute("SELECT * FROM inbox_items WHERE id=?", (item_id,)).fetchone()
    payload = json.loads(row["payload"])
    assert row["kind"] == "daily" and row["status"] == "INFO"
    assert row["title"] == "[시장 브리핑] 11/6(금) 아침 · 국내장 개장 전"
    assert row["summary"] == "반도체 걱정이 큰 하루"
    assert payload["type"] == "market_briefing" and payload["briefing_status"] == "OK"
    [news] = payload["news"]                                    # the uncited pick was dropped
    assert news["rank"] == 1 and news["markets"] == ["KR", "US"]
    assert [s["lang"] for s in news["sources"]] == ["en", "ko"]
    assert news["sources"][0]["url"].startswith("https://y.example/")
    # point in time: nothing published after now reached the model; Korean headlines did
    assert "future" not in writer.prompts[0] and "코스피 증시 소식" in writer.prompts[0]
    assert write(conn, "KR", date(2026, 11, 6), NOW, naver(), writer, search=yahoo) is None
    assert len(writer.prompts) == 1


def test_failures_are_filed_not_hidden(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    write(conn, "KR", date(2026, 11, 6), NOW, naver(), Writer(fail=True), search=yahoo)
    write(conn, "US", date(2026, 11, 6), NOW, None, Writer(), search=lambda q, n: [])
    write(conn, "KR", date(2026, 11, 9), NOW, naver(), Writer(), lambda: False, search=yahoo)
    rows = {r["dedupe_key"]: (r["title"], json.loads(r["payload"]))
            for r in conn.execute("SELECT * FROM inbox_items")}
    assert rows["market-briefing:KR:2026-11-06"][1]["briefing_status"] == "FAILED"
    assert rows["market-briefing:US:2026-11-06"][1]["briefing_status"] == "INSUFFICIENT_DATA"
    assert rows["market-briefing:KR:2026-11-09"][1]["briefing_status"] == "SKIPPED_BUDGET"
    assert all(title.endswith("작성 못 함") for title, _ in rows.values())


def test_briefing_tokens_count_against_the_budget(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    write(conn, "KR", date(2026, 11, 6), NOW, naver(), Writer(), search=yahoo)
    assert usages_in_month(conn, "2026-11") == [USAGE] and usages_in_month(conn, "2026-12") == []
    repo = RunRepository(tmp_path / "runs")
    plain = budget_status(repo, NOW, Decimal("7"))
    with_news = budget_status(repo, NOW, Decimal("7"),
                              extra_usages=lambda m: usages_in_month(conn, m))
    assert plain.spent_usd == 0
    assert with_news.spent_usd == Decimal("0.0021")   # 6000×0.10 + 3000×0.50 per 1M


def test_finalize_caps_picks_and_never_reuses_a_source() -> None:
    cands = [{"id": f"e{i}", "lang": "en", "publisher": "P", "published": "", "title": f"t{i}",
              "summary": "", "url": f"u{i}"} for i in range(1, 15)]
    picks = [NewsPick(source_ids=[f"e{i}", "e1"], title=f"뉴스{i}", summary="s", story="",
                      why="", markets=["US"], direction="엇갈림") for i in range(1, 15)]
    _, news = finalize(MarketBriefingDraft(mood="m", picks=picks), cands)
    assert len(news) == 10
    assert [s["url"] for s in news[1]["sources"]] == ["u2"]    # e1 already used by the first
