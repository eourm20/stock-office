"""[속보]: only new headlines, only important ones, emergency meetings for held stocks, budget.

No network."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from stock_office.breaking import (
    MAX_ALERTS_PER_DAY,
    Alert,
    BreakingDraft,
    alerts_for,
    poll,
)
from stock_office.db import connect
from stock_office.market_news import usages_in_month

pytest.importorskip("tradingagents")

NOW = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)          # 10:00 KST
USAGE = {"gpt-6-luna": {"input_tokens": 3000, "output_tokens": 400}}
SAMSUNG = "KR:KRX:005930"


def article(title: str) -> dict[str, Any]:
    return {"content": {"title": title, "summary": f"{title} summary",
                        "provider": {"displayName": "Reuters"},
                        "canonicalUrl": {"url": f"https://y.example/{title}"},
                        "pubDate": "2026-11-06T00:30:00Z"}}


class Feed:
    """Yahoo search stub whose headlines can change between polls."""

    def __init__(self) -> None:
        self.titles = ["old story"]

    def __call__(self, query: str, count: int) -> list[dict[str, Any]]:
        return [article(t) for t in self.titles]


def alert(score: int, ids: list[str], ours: list[str] | None = None, title: str = "속보") -> Alert:
    return Alert(source_ids=ids, score=score, title=title, summary="요약", story="비유하자면",
                 why="이유", markets=["KR"], direction="나쁨", our_stocks=ours or [])


class Writer:
    model = "gpt-6-luna"

    def __init__(self, alerts: list[Alert]) -> None:
        self.alerts, self.prompts = alerts, []

    def __call__(self, prompt: str) -> tuple[BreakingDraft, dict[str, Any]]:
        self.prompts.append(prompt)
        return BreakingDraft(alerts=self.alerts), USAGE


def test_first_poll_only_records_then_only_new_headlines_reach_the_model(tmp_path: Path) -> None:
    conn, feed = connect(tmp_path), Feed()
    writer = Writer([])
    assert poll(conn, NOW, None, writer, [], search=feed) == []
    assert writer.prompts == []                                   # nothing alerted on day one
    feed.titles = ["old story", "new story"]
    poll(conn, NOW + timedelta(minutes=30), None, writer, [], search=feed)
    assert len(writer.prompts) == 1
    assert "new story" in writer.prompts[0] and "old story" not in writer.prompts[0]
    poll(conn, NOW + timedelta(minutes=60), None, writer, [], search=feed)
    assert len(writer.prompts) == 1                              # nothing new: no model call
    polls = conn.execute("SELECT new_headlines, token_usage FROM news_polls").fetchall()
    assert [p["new_headlines"] for p in polls] == [0, 1, 0]
    assert usages_in_month(conn, "2026-11") == [USAGE]          # counted in the budget


def test_only_market_shocks_or_big_news_on_held_stocks_are_sent(tmp_path: Path) -> None:
    conn, feed = connect(tmp_path), Feed()
    poll(conn, NOW, None, Writer([]), [SAMSUNG], search=feed)
    feed.titles = ["old story", "a", "b", "c", "d"]
    called: list[tuple[str, int]] = []
    writer = Writer([alert(5, ["n1"], title="정책 충격"), alert(4, ["n2"], title="업종 소식"),
                     alert(4, ["n3"], ["삼성전자", "애플"], title="삼성 수주 취소"),
                     alert(5, ["zz"], title="출처 없음"), alert(3, ["n4"], ["삼성전자"])])
    filed = poll(conn, NOW + timedelta(minutes=30), None, writer, [SAMSUNG], search=feed,
                 emergency=lambda iid, item: called.append((iid, item)) or "run1")
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM inbox_items")}
    assert [rows[i]["title"] for i in filed] == ["[속보] 정책 충격", "[속보] 삼성 수주 취소"]
    samsung = json.loads(rows[filed[1]]["payload"])
    assert samsung["held_ids"] == [SAMSUNG] and samsung["news"][0]["our_stocks"] == [
        {"name": "삼성전자", "role": "보유"}]
    assert called == [(SAMSUNG, filed[1])]
    assert samsung["meetings"] == [{"instrument_id": SAMSUNG, "name": "삼성전자",
                                    "run_id": "run1"}]
    assert "보유 종목: 삼성전자" in writer.prompts[0]
    found = alerts_for(conn, SAMSUNG, NOW + timedelta(hours=1))
    assert [a["title"] for a in found] == ["[속보] 삼성 수주 취소"]
    assert alerts_for(conn, SAMSUNG, NOW + timedelta(hours=20)) == []


def test_daily_cap_and_already_sent_events_are_given_to_the_model(tmp_path: Path) -> None:
    conn, feed = connect(tmp_path), Feed()
    poll(conn, NOW, None, Writer([]), [], search=feed)
    for n in range(MAX_ALERTS_PER_DAY + 2):
        feed.titles = [f"story {n}"]
        writer = Writer([alert(5, ["n1"], title=f"충격 {n}")])
        poll(conn, NOW + timedelta(minutes=30 * (n + 1)), None, writer, [], search=feed)
    sent = conn.execute("SELECT title FROM inbox_items").fetchall()
    assert len(sent) == MAX_ALERTS_PER_DAY
    assert "[속보] 충격 0" in writer.prompts[0]                  # told what was already sent


def test_budget_or_engine_trouble_skips_the_model(tmp_path: Path) -> None:
    conn, feed = connect(tmp_path), Feed()
    poll(conn, NOW, None, None, [], search=feed)
    feed.titles = ["x"]
    writer = Writer([alert(5, ["n1"])])
    poll(conn, NOW + timedelta(minutes=30), None, writer, [], lambda: False, search=feed)
    feed.titles = ["y"]
    poll(conn, NOW + timedelta(minutes=60), None, None, [], search=feed)
    notes = [r["note"] for r in conn.execute("SELECT note FROM news_polls ORDER BY id")]
    assert notes[1:] == ["budget below reserve: skipped", "engine not ready"]
    assert writer.prompts == [] and not conn.execute("SELECT 1 FROM inbox_items").fetchone()
