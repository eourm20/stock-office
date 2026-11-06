"""[속보]: important news as it breaks, and an emergency meeting when it hits a held stock.

Owner, 2026-11-06: "watch the news all the time and pop up what matters" (a twice-daily briefing
learns of a 10:00 story at 22:00), and "fix the limits": news during the day reached the committee
only at the next morning's meeting, and held stocks were guarded by their stop/target alone.

Every 30 minutes, day and night (the US desk trades at night in Korea), the news desk:

1. collects headlines (title and summary only) from the same market-wide sources as the briefing
   and the held stocks' own news, and keeps only those it has not seen before (`news_seen`; the
   first poll only records what is there, so switching it on never floods the phone);
2. if there are new ones, asks the cheap "quick" model which are truly important: 5 = moves a
   whole market (policy shock, war, rate surprise, crash), 4 = a big effect on a held stock or its
   industry. Most polls should find nothing. Events already alerted today are given so they are
   not repeated; at most `MAX_ALERTS_PER_DAY` alerts a day;
3. files each alert ([속보], news tab, phone notification even in quiet hours), sources from the
   collected list only;
4. when an alert hits a held stock, queues an emergency committee meeting for it (trigger
   "breaking"; at most `MAX_EMERGENCY_PER_DAY` a day, none if the stock met in the last 6 hours).
   The meeting is told which alert called it (`Inbox.position_context`). Its result follows the
   normal held-stock rules (sell all, or a stop/target change, through the same risk policy and
   auto-approval). An add-on buy only on good news ("좋음"), at most one a day, under the normal
   add-on rules (20% per stock, 1% loss at the stop, the ±5% pre-order check).

Model usage of every poll is stored (`news_polls`) and counted in the monthly budget; polls stop
while the budget is below the briefing reserve, so meetings come first.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from stock_office.db import transaction
from stock_office.domain.instruments import REGISTRY, display_name
from stock_office.engine.ta_extensions import (
    GLOBAL_NEWS_QUERIES,
    YahooSearch,
    _yahoo_search,
    kr_market_headlines,
    yahoo_global_articles,
)
from stock_office.events.sanitize import redact_text
from stock_office.market_news import (
    KST,
    NAVER_QUERIES,
    _clip,
    _en,
    _ko,
    _numbered,
    held_by,
    naver_from,
    stock_headlines,
    writer_for,
)
from stock_office.providers.naver import NaverNewsProvider

log = logging.getLogger("stock_office.breaking")

EVERY = timedelta(minutes=30)
LOOKBACK_DAYS = 1
YAHOO_POOL = 30
NAVER_POOL = 40
HELD_HEADLINES = 3
MAX_ALERTS_PER_DAY = 5
MAX_EMERGENCY_PER_DAY = 2
EMERGENCY_GAP = timedelta(hours=6)
DEDUPE_PREFIX = "breaking:"
SUMMARY_IN_PROMPT = 240


class Alert(BaseModel):
    source_ids: list[str] = Field(description="근거 기사 id (입력의 id 그대로, 1~3개)")
    score: int = Field(ge=1, le=5,
                       description="5: 시장 전체를 흔듦, 4: 보유 종목·그 업종에 큰 영향")
    title: str = Field(description="한국어 제목 35자 이내 (영어는 번역)")
    summary: str = Field(description="무슨 일인지 2문장, 기사에 있는 사실만")
    story: str = Field(description="주식을 모르는 사람을 위한 일상 비유 2~3문장")
    why: str = Field(description="주가에 왜 중요한지 1~2문장")
    markets: list[Literal["KR", "US"]] = Field(description="영향받는 시장")
    sectors: list[str] = Field(default_factory=list, description="영향받는 업종·기업 최대 4개")
    direction: Literal["좋음", "나쁨", "엇갈림"]
    our_stocks: list[str] = Field(default_factory=list,
                                  description="영향받는 우리 보유 종목 이름 (목록 그대로)")


class BreakingDraft(BaseModel):
    alerts: list[Alert] = Field(default_factory=list,
                                description="정말 중요한 것만 (대부분은 빈 목록)")


PROMPT = """너는 투자회사의 속보 담당이다. 아래는 방금 새로 나온 경제 기사 제목과 짧은 요약이다.
사장님께 지금 당장 알려야 할 만큼 중요한 소식만 골라라. 대부분의 경우 빈 목록이 맞다.

점수:
- 5: 한국이나 미국 시장 전체를 흔들 소식 (정부·의회의 큰 정책 변화, 전쟁·지정학 충격, 예상 밖
  금리 결정, 급락·급등을 부르는 사건, 주요 산업을 겨냥한 규제 등)
- 4: 우리 보유 종목이나 그 업종에 큰 영향 (실적 충격, 대형 수주·계약 취소, 규제, 소송, 사고 등)
- 3 이하는 내지 마라.

규칙:
- 오늘 이미 알린 소식(아래)과 같은 사건은 다시 내지 마라.
- 입력에 없는 사실·숫자·회사 이름을 만들지 마라. 확정되지 않은 것은 "~라는 보도가 있어요"로.
- 같은 사건의 기사는 하나로 묶어 source_ids에 함께 적어라.
- 쉬운 존댓말(~요). story는 동네 가게·마을 같은 일상 비유로, 비유임을 드러내라.
- 투자 권유(사라/팔라)를 하지 마라.

우리 보유 종목: {held}
오늘 이미 알린 소식: {already}

새 기사:
{payload}
"""


def _key(row: dict[str, Any]) -> str:
    return hashlib.sha256((row.get("url") or row["title"]).encode()).hexdigest()[:24]


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def _day_start(now: datetime) -> str:
    kst = now.astimezone(KST)
    return _iso(kst.replace(hour=0, minute=0, second=0, microsecond=0))


def last_poll(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute("SELECT at FROM news_polls ORDER BY id DESC LIMIT 1").fetchone()
    return datetime.fromisoformat(row["at"]) if row else None


def collect(as_of: str, naver: NaverNewsProvider | None, search: YahooSearch,
            held: Sequence[str]) -> list[dict[str, Any]]:
    world = yahoo_global_articles(as_of, LOOKBACK_DAYS, YAHOO_POOL, GLOBAL_NEWS_QUERIES, search)
    korea = (kr_market_headlines(naver, as_of, LOOKBACK_DAYS, NAVER_QUERIES, limit=NAVER_POOL)
             if naver is not None and naver.configured else [])
    ours = stock_headlines([(i, f"보유: {display_name(i)}", HELD_HEADLINES) for i in held],
                           as_of, naver, search)
    return [_en(a) for a in world] + [_ko(s) for s in korea] + ours


def fresh(conn: sqlite3.Connection, rows: list[dict[str, Any]], now: datetime
          ) -> tuple[list[dict[str, Any]], bool]:
    """Rows not seen before (all are recorded as seen now), and whether this was the first poll
    (nothing recorded yet: nothing counts as new)."""
    first = conn.execute("SELECT 1 FROM news_seen LIMIT 1").fetchone() is None
    new: list[dict[str, Any]] = []
    with transaction(conn):
        for row in rows:
            cur = conn.execute("INSERT OR IGNORE INTO news_seen (key, title, seen_at) "
                               "VALUES (?,?,?)", (_key(row), row["title"][:300], _iso(now)))
            if cur.rowcount and not first:
                new.append(row)
    return _numbered(new, "n"), first


def build_prompt(rows: Sequence[dict[str, Any]], held: Sequence[str],
                 already: Sequence[str]) -> str:
    payload = [{"id": r["id"], "lang": r["lang"], "published": r["published"],
                "title": r["title"], "summary": r["summary"][:SUMMARY_IN_PROMPT],
                **({"about": r["about"]} if r.get("about") else {})} for r in rows]
    return PROMPT.format(held=", ".join(display_name(i) for i in held) or "없음",
                         already="; ".join(already) or "없음",
                         payload=json.dumps(payload, ensure_ascii=False, indent=0))


def keep(draft: BreakingDraft, rows: Sequence[dict[str, Any]], held: Sequence[str]
         ) -> list[tuple[Alert, list[dict[str, Any]], list[str]]]:
    """Alerts worth sending: score 5, or 4 touching a held stock; cited sources only."""
    by_id = {r["id"]: r for r in rows}
    names = {display_name(i): i for i in held}
    out = []
    for a in sorted(draft.alerts, key=lambda a: -a.score):
        sources = [by_id[i] for i in dict.fromkeys(a.source_ids) if i in by_id][:3]
        hit = [names[n] for n in dict.fromkeys(a.our_stocks) if n in names]
        if sources and a.title.strip() and (a.score >= 5 or (a.score >= 4 and hit)):
            out.append((a, sources, hit))
    return out


def poll(conn: sqlite3.Connection, now: datetime, naver: NaverNewsProvider | None,
         writer: Any, held: Sequence[str], budget_ok: Callable[[], bool] = lambda: True,
         search: YahooSearch = _yahoo_search,
         emergency: Callable[[str, int], str | None] = lambda iid, alert_id: None) -> list[int]:
    """One look at the news. Returns the inbox ids of the alerts filed."""
    note = ""
    usage: dict[str, Any] | None = None
    filed: list[int] = []
    try:
        rows, first = fresh(conn, collect(now.astimezone(KST).date().isoformat(), naver, search,
                                          held), now)
    except Exception as exc:
        log.exception("breaking news: collecting failed")
        rows, first, note = [], False, f"collect failed: {type(exc).__name__}"
    if first:
        note = "first poll: headlines recorded, none alerted"
    elif rows and writer is None:
        note = "engine not ready"
    elif rows and not budget_ok():
        note = "budget below reserve: skipped"
    elif rows:
        start = _day_start(now)
        sent_today = conn.execute(
            "SELECT title FROM inbox_items WHERE dedupe_key LIKE ? AND created_at >= ?",
            (f"{DEDUPE_PREFIX}%", start)).fetchall()
        room = MAX_ALERTS_PER_DAY - len(sent_today)
        try:
            draft, usage = writer(build_prompt(rows, held, [r["title"] for r in sent_today]))
            for alert, sources, hit in keep(draft, rows, held)[:max(room, 0)]:
                item = _file(conn, alert, sources, hit, now, getattr(writer, "model", ""))
                if item is None:
                    continue
                filed.append(item)
                for iid in hit:
                    run_id = emergency(iid, item)
                    if run_id:
                        _note_meeting(conn, item, iid, run_id)
        except Exception as exc:
            log.exception("breaking news: model failed")
            note = f"model failed: {type(exc).__name__}"
    with transaction(conn):
        conn.execute("INSERT INTO news_polls (at, new_headlines, alerts, token_usage, note) "
                     "VALUES (?,?,?,?,?)", (_iso(now), len(rows), len(filed),
                                            json.dumps(usage) if usage else None, note or None))
    return filed


def _file(conn: sqlite3.Connection, a: Alert, sources: list[dict[str, Any]], hit: list[str],
          now: datetime, model: str) -> int | None:
    card = {
        "rank": 1, "title": _clip(a.title, 60), "summary": _clip(a.summary, 320),
        "story": _clip(a.story, 420), "why": _clip(a.why, 260),
        "markets": sorted(set(a.markets)), "direction": a.direction,
        "sectors": [_clip(s, 24) for s in a.sectors if s.strip()][:4],
        "our_stocks": [{"name": display_name(i), "role": "보유"} for i in hit],
        "sources": [{"title": s["title"], "publisher": s["publisher"], "url": s["url"],
                     "lang": s["lang"], "published": s["published"]} for s in sources],
    }
    payload = {"type": "breaking", "score": a.score, "news": [card], "held_ids": hit,
               "model": model, "meetings": []}
    with transaction(conn):
        cur = conn.execute(
            "INSERT OR IGNORE INTO inbox_items (kind, instrument_id, title, summary, payload, "
            "status, dedupe_key, created_at) VALUES ('adhoc', NULL, ?, ?, ?, 'INFO', ?, ?)",
            (f"[속보] {card['title']}", redact_text(str(card["why"]), limit=300),
             json.dumps(payload, ensure_ascii=False), f"{DEDUPE_PREFIX}{_key(sources[0])}",
             _iso(now)))
    return int(cur.lastrowid or 0) if cur.rowcount else None


def _note_meeting(conn: sqlite3.Connection, item: int, iid: str, run_id: str) -> None:
    row = conn.execute("SELECT payload FROM inbox_items WHERE id=?", (item,)).fetchone()
    payload = json.loads(row["payload"])
    payload["meetings"].append({"instrument_id": iid, "name": display_name(iid),
                                "run_id": run_id})
    with transaction(conn):
        conn.execute("UPDATE inbox_items SET payload=? WHERE id=?",
                     (json.dumps(payload, ensure_ascii=False), item))


def alerts_for(conn: sqlite3.Connection, instrument_id: str, now: datetime,
               within: timedelta = timedelta(hours=12)) -> list[dict[str, Any]]:
    """Recent alerts that hit this held stock (for the emergency meeting's input)."""
    out = []
    for r in conn.execute("SELECT title, summary, payload, created_at FROM inbox_items "
                          "WHERE dedupe_key LIKE ? AND created_at >= ? ORDER BY id",
                          (f"{DEDUPE_PREFIX}%", _iso(now - within))):
        payload = json.loads(r["payload"])
        if instrument_id in payload.get("held_ids", []):
            card = payload["news"][0]
            out.append({"title": r["title"], "summary": card["summary"], "why": card["why"],
                        "at": r["created_at"],
                        "sources": [s["title"] for s in card["sources"]]})
    return out


def emergency_buys_today(conn: sqlite3.Connection, now: datetime) -> int:
    """Add-on buy requests filed today (Korea time) by emergency meetings."""
    rows = conn.execute("SELECT i.payload FROM inbox_items i JOIN plans p ON p.item_id=i.id "
                        "WHERE i.kind='approval' AND p.side='BUY' AND i.created_at >= ?",
                        (_day_start(now),)).fetchall()
    return sum(1 for r in rows if json.loads(r["payload"]).get("trigger") == "breaking")


# ---------------------------------------------------------------------------- live wiring

def start_emergency(service: Any, iid: str, alert_id: int, now: datetime) -> str | None:
    """Queue an emergency meeting for a held stock (the main worker loop runs it)."""
    from stock_office.domain.models import CreateRunRequest
    from stock_office.runs.service import BudgetExceededError

    runs = service.repo.list_runs()
    today = _day_start(now)
    if sum(1 for r in runs if r.trigger == "breaking" and _iso(r.requested_at) >= today) \
            >= MAX_EMERGENCY_PER_DAY:
        return None
    if any(r.instrument_id == iid and r.requested_at >= now - EMERGENCY_GAP for r in runs):
        return None
    try:
        run = service.create_run(CreateRunRequest(instrument_id=iid, engine="tradingagents"),
                                 trigger="breaking", schedule_slot=f"breaking:{alert_id}")
    except BudgetExceededError as exc:
        log.warning("emergency meeting for %s skipped: %s", iid, exc)
        return None
    log.info("breaking news #%s -> emergency meeting %s for %s", alert_id, run.id, iid)
    return str(run.id)


def tick(service: Any, settings: Any, now: datetime) -> None:
    """Worker: poll the news every 30 minutes."""
    if service.inbox is None:
        return
    conn = service.inbox.conn
    last = last_poll(conn)
    if last is not None and now - last < EVERY:
        return
    from stock_office.market_news import _budget_ok

    held = [i for m in ("KR", "US") for i in held_by(service.inbox, m) if i in REGISTRY]
    writer = writer_for(service, settings, "NEWS", now.astimezone(KST).date(), BreakingDraft)
    poll(conn, now, naver_from(settings), writer, held,
         lambda: _budget_ok(service), emergency=lambda iid, item: start_emergency(
             service, iid, item, now))

