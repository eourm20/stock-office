"""오늘 피드백 for the closing report: why the day went the way it did, in two or three plain lines.

Owner, 2026-11-06: "the closing report should say 'it looks like this happened because of that
news', like the breaking news did; that is the feedback I wanted". The closing report itself is
built from numbers only (`kiwoom_mock/closing.py`). Shortly after it is filed, the news desk gives
the cheap "quick" model the report's own lines (account, index, trades, holdings, each meeting's
conclusion and the stock's move) and the news the company collected in the last day (market
briefings and breaking news, already written), and asks for two or three sentences connecting
them. The model may only point at that news, and must say "~인 것 같아요" — a day's move has many
causes and this is a guess, not an analysis. The cited news titles are kept only if they are among
the ones given. The lines go first in the report as "오늘 피드백 (AI 추정)". Tokens count in the
monthly budget; a failure leaves the report as it was, noted.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from stock_office.db import transaction
from stock_office.events.sanitize import redact_text

log = logging.getLogger("stock_office.closing_feedback")

WINDOW = timedelta(hours=6)        # reports this recent get feedback
NEWS_SINCE = timedelta(hours=26)   # news from about a day before the close


class FeedbackDraft(BaseModel):
    lines: list[str] = Field(description="오늘 결과를 그날 소식과 연결한 쉬운 문장 2~3개")
    cited: list[str] = Field(default_factory=list,
                             description="근거로 삼은 소식 제목 (입력의 제목 그대로)")


PROMPT = """너는 투자회사 사장님께 장 마감 보고를 하는 비서다. 아래는 오늘 {desk} 계좌의 마감 숫자와
오늘 회의 결과, 그리고 회사가 오늘 모은 시장 소식(브리핑·속보)이다.

오늘 계좌와 종목이 왜 이렇게 움직였는지, 소식과 연결해서 2~3문장으로 쉽게 말하라.
- 반드시 아래 소식 중에서만 이유를 찾고, 쓴 소식의 제목을 cited에 그대로 적어라.
- 원인은 확실하지 않으니 "~때문인 것 같아요", "~의 영향으로 보여요"처럼 추정으로 말하라.
- 연결할 소식이 없으면 "오늘 움직임을 설명할 만한 소식은 따로 없었어요"라고 솔직히 말하라.
- 숫자는 입력에 있는 것만. 쉬운 존댓말(~요), 전문 용어 없이. 투자 권유는 하지 마라.

오늘 마감 숫자와 회의:
{report}

오늘 모은 소식:
{news}
"""


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def news_since(conn: sqlite3.Connection, since: datetime) -> list[dict[str, str]]:
    """Market briefing stories and breaking news written since `since` (title, why)."""
    out: list[dict[str, str]] = []
    for r in conn.execute(
            "SELECT title, summary, payload FROM inbox_items WHERE created_at >= ? AND "
            "(dedupe_key LIKE 'market-briefing:%' OR dedupe_key LIKE 'breaking:%') ORDER BY id",
            (_iso(since),)):
        payload = json.loads(r["payload"])
        if payload.get("type") == "breaking":
            card = payload["news"][0]
            out.append({"title": card["title"], "why": card.get("why", ""), "kind": "속보"})
        elif payload.get("briefing_status") == "OK":
            out += [{"title": n["title"], "why": n.get("why", ""), "kind": "브리핑"}
                    for n in payload.get("news", [])]
    return out


def due(conn: sqlite3.Connection, now: datetime) -> list[sqlite3.Row]:
    return [r for r in conn.execute(
        "SELECT id, title, payload, created_at FROM inbox_items WHERE kind='closing' "
        "AND created_at >= ? ORDER BY id", (_iso(now - WINDOW),))
        if "feedback" not in json.loads(r["payload"])]


def write(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime, writer: Any) -> None:
    """Add 오늘 피드백 to one closing report (or note why not). Never raises."""
    payload = json.loads(row["payload"])
    news = news_since(conn, datetime.fromisoformat(row["created_at"]) - NEWS_SINCE)
    feedback: dict[str, Any] = {"at": _iso(now)}
    if writer is None:
        feedback["note"] = "AI를 쓸 수 없어 피드백을 쓰지 않았어요 (엔진 미설정 또는 예산 부족)."
    else:
        desk = "국내장" if payload.get("market") == "KR" else "해외장"
        report = "\n".join(f"[{s['title']}] " + " / ".join(s["lines"])
                           for s in payload.get("sections", []))
        try:
            draft, usage = writer(PROMPT.format(
                desk=desk, report=report,
                news="\n".join(f"- ({n['kind']}) {n['title']}: {n['why']}" for n in news)
                or "(오늘 모은 소식 없음)"))
            titles = {n["title"] for n in news}
            feedback.update({
                "lines": [redact_text(" ".join(x.split()), limit=220)
                          for x in draft.lines if x.strip()][:3],
                "cited": [t for t in dict.fromkeys(draft.cited) if t in titles][:4],
                "token_usage": usage, "model": getattr(writer, "model", ""),
            })
        except Exception as exc:
            log.exception("closing feedback #%s failed", row["id"])
            feedback["note"] = f"AI 피드백 실패 ({type(exc).__name__})"
    if feedback.get("lines"):
        lines = list(feedback["lines"])
        if feedback["cited"]:
            lines.append("근거로 본 소식: " + " · ".join(feedback["cited"]))
        payload["sections"] = [{"title": "오늘 피드백 (AI 추정)", "lines": lines},
                               *payload.get("sections", [])]
    payload["feedback"] = feedback
    with transaction(conn):
        conn.execute("UPDATE inbox_items SET payload=? WHERE id=?",
                     (json.dumps(payload, ensure_ascii=False), row["id"]))


def usages(conn: sqlite3.Connection, month: str) -> list[dict[str, Any]]:
    from stock_office.budget import month_key

    out = []
    for r in conn.execute("SELECT payload, created_at FROM inbox_items WHERE kind='closing'"):
        usage = (json.loads(r["payload"]).get("feedback") or {}).get("token_usage")
        if usage and month_key(datetime.fromisoformat(r["created_at"])) == month:
            out.append(usage)
    return out


def tick(service: Any, settings: Any, now: datetime) -> None:
    """Worker (briefing thread): feedback for closing reports filed in the last hours."""
    if service.inbox is None:
        return
    rows = due(service.inbox.conn, now)
    if not rows:
        return
    from stock_office.engine.adapter import EngineNotConfiguredError
    from stock_office.market_news import QuickModelWriter, _budget_ok

    writer = None
    engine = service.engines("tradingagents")
    try:
        engine.check_ready()
        if _budget_ok(service):
            writer = QuickModelWriter(engine.build_config(settings.data_dir / "closing_feedback"),
                                      FeedbackDraft)
    except EngineNotConfiguredError:
        pass
    for row in rows:
        write(service.inbox.conn, row, now, writer)
