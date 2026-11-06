"""오늘 피드백: the closing report linked to the day's news (no model, no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from stock_office.closing_feedback import FeedbackDraft, due, write
from stock_office.db import connect
from stock_office.market_news import usages_in_month

CLOSE = datetime(2026, 11, 6, 6, 40, tzinfo=UTC)          # 15:40 KST
USAGE = {"gpt-6-luna": {"input_tokens": 2000, "output_tokens": 200}}


class Writer:
    model = "gpt-6-luna"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> tuple[FeedbackDraft, dict[str, Any]]:
        self.prompts.append(prompt)
        return FeedbackDraft(lines=["반도체 규제 소식 때문에 계좌가 내린 것 같아요.", " "],
                             cited=["美 데이터센터 규제 법안", "지어낸 소식"]), USAGE


def seed(conn: Any) -> int:
    conn.execute(
        "INSERT INTO inbox_items (kind, title, payload, status, dedupe_key, created_at) "
        "VALUES ('adhoc', '[속보] 美 데이터센터 규제 법안', ?, 'INFO', 'breaking:a', ?)",
        (json.dumps({"type": "breaking", "news": [{"title": "美 데이터센터 규제 법안",
                                                     "why": "반도체 수요 우려"}]}),
         (CLOSE - timedelta(hours=5)).isoformat()))
    cur = conn.execute(
        "INSERT INTO inbox_items (kind, title, payload, status, dedupe_key, created_at) "
        "VALUES ('closing', '[마감] 국내장', ?, 'INFO', 'closing:KR:2026-11-06', ?)",
        (json.dumps({"market": "KR", "sections": [{"title": "계좌", "lines": ["오늘 -1.20%"]}]}),
         CLOSE.isoformat()))
    return int(cur.lastrowid)


def test_feedback_links_the_day_to_the_news_it_was_given(tmp_path: Path) -> None:
    conn, writer = connect(tmp_path), Writer()
    item = seed(conn)
    [row] = due(conn, CLOSE + timedelta(minutes=5))
    write(conn, row, CLOSE + timedelta(minutes=5), writer)
    payload = json.loads(conn.execute("SELECT payload FROM inbox_items WHERE id=?",
                                      (item,)).fetchone()["payload"])
    first = payload["sections"][0]
    assert first["title"] == "오늘 피드백 (AI 추정)"
    assert first["lines"] == ["반도체 규제 소식 때문에 계좌가 내린 것 같아요.",
                              "근거로 본 소식: 美 데이터센터 규제 법안"]   # invented title dropped
    assert "(속보) 美 데이터센터 규제 법안: 반도체 수요 우려" in writer.prompts[0]
    assert "오늘 -1.20%" in writer.prompts[0]
    assert due(conn, CLOSE + timedelta(minutes=6)) == []           # once
    assert usages_in_month(conn, "2026-11") == [USAGE]


def test_without_the_engine_the_report_is_left_as_it_was(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    item = seed(conn)
    write(conn, due(conn, CLOSE)[0], CLOSE, None)
    payload = json.loads(conn.execute("SELECT payload FROM inbox_items WHERE id=?",
                                      (item,)).fetchone()["payload"])
    assert payload["sections"][0]["title"] == "계좌" and "note" in payload["feedback"]
    assert due(conn, CLOSE + timedelta(hours=7)) == []
