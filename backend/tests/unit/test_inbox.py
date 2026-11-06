"""Inbox rules: one document per meeting, expiry by exchange calendar, decision states."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from stock_office.db import transaction
from stock_office.domain.models import CreateRunRequest, Market
from stock_office.engine.demo_engine import DemoEngine
from stock_office.inbox import DecisionError, next_session_close
from stock_office.runs.service import RunService


def test_next_session_close_follows_each_exchange_calendar() -> None:
    # KR committee 07:30 KST Monday 2026-10-19 → that day's KRX close 15:30 KST (06:30 UTC)
    kr = next_session_close(Market.KR, datetime(2026, 10, 18, 22, 30, tzinfo=UTC))
    assert kr == datetime(2026, 10, 19, 6, 30, tzinfo=UTC)
    # US committee 17:00 ET Friday 2026-10-16 → next session Monday 16:00 ET (20:00 UTC, EDT)
    us = next_session_close(Market.US, datetime(2026, 10, 16, 21, 0, tzinfo=UTC))
    assert us == datetime(2026, 10, 19, 20, 0, tzinfo=UTC)
    # after the DST change (2026-11-01) the US close is 21:00 UTC
    assert next_session_close(Market.US, datetime(2026, 11, 2, 22, 0, tzinfo=UTC)) == \
        datetime(2026, 11, 3, 21, 0, tzinfo=UTC)
    # Korean holiday (Chuseok 2026-09-24..26): next close after the break
    assert next_session_close(Market.KR, datetime(2026, 9, 23, 7, 0, tzinfo=UTC)).date() > \
        datetime(2026, 9, 23).date()


def _buy_run(make_service: Callable[..., RunService]) -> tuple[RunService, int]:
    service = make_service(demo_engine=DemoEngine(rating="Buy"))
    with transaction(service.inbox.conn):           # the CEO decides by hand in these tests
        service.inbox.book.set_auto_approve(False, service.clock())
    run = service.create_run(CreateRunRequest(instrument_id="KR:KRX:005930", engine="demo"))
    service.execute(run.id)
    items = service.inbox.list()
    assert len(items) == 1 and items[0].kind == "approval"
    # filing again is a no-op (same meeting, same document)
    assert service.inbox.file_run(service.repo.get_run(run.id), service.clock()) == items[0].id
    assert len(service.inbox.list()) == 1
    return service, items[0].id


def test_defer_then_approve_and_expiry(make_service: Callable[..., RunService]) -> None:
    service, item_id = _buy_run(make_service)
    now = service.clock()
    assert service.inbox.decide(item_id, "defer", "내일 다시", "r1", now).status == "DEFERRED"
    assert service.inbox.decide(item_id, "approve", "", "r2", now).status == "APPROVED"
    with pytest.raises(DecisionError) as err:
        service.inbox.decide(item_id, "approve", "", "r3", now)
    assert err.value.status == 409


def test_expired_documents_cannot_be_decided(make_service: Callable[..., RunService]) -> None:
    service, item_id = _buy_run(make_service)
    item = service.inbox.get(item_id)
    assert item is not None and item.expires_at is not None
    later = item.expires_at + timedelta(minutes=1)
    with pytest.raises(DecisionError) as err:
        service.inbox.decide(item_id, "approve", "", "r1", later)
    assert err.value.status == 409
    assert service.inbox.get(item_id).status == "EXPIRED"          # type: ignore[union-attr]
    assert service.inbox.expire_due(later) == 0


def test_bad_action_and_reused_request_id(make_service: Callable[..., RunService]) -> None:
    service, item_id = _buy_run(make_service)
    with pytest.raises(DecisionError):
        service.inbox.decide(item_id, "buy-now", "", "r1", service.clock())
    service.inbox.decide(item_id, "reject", "", "r1", service.clock())
    with pytest.raises(DecisionError) as err:
        service.inbox.decide(item_id + 1000, "approve", "", "r1", service.clock())
    assert err.value.status == 409


def test_documents_before_operations_started_are_kept_but_not_listed(
        make_service: Callable[..., RunService]) -> None:
    service, item_id = _buy_run(make_service)
    inbox = service.inbox
    assert [i.id for i in inbox.list()] == [item_id]
    with transaction(inbox.conn):
        inbox.conn.execute("INSERT INTO company_settings (key, value) VALUES ('ops_start', ?)",
                           ((datetime.now(UTC) + timedelta(minutes=1)).isoformat(),))
    assert inbox.list() == []                                    # the test period is hidden
    assert [i.id for i in inbox.list(include_test=True)] == [item_id]
    assert inbox.get(item_id) is not None                         # and still there


def test_a_meeting_that_orders_nothing_is_still_reported(
    make_service: Callable[..., RunService], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kiwoom desk connected, stock not held, HOLD: no order, but the CEO gets the result
    (owner, 2026-11-06; before, such meetings reached the records only)."""
    service = make_service(demo_engine=DemoEngine(rating="Hold"))
    monkeypatch.setattr(service.inbox, "_kiwoom", lambda market, demo: True)
    monkeypatch.setattr(service.inbox, "accounts", lambda market: {"ok": True, "holdings": []})
    run = service.create_run(CreateRunRequest(instrument_id="KR:KRX:005930", engine="demo"))
    service.execute(run.id)
    [item] = service.inbox.list()
    assert item.kind == "daily" and item.status == "INFO" and item.plan is None
    assert item.title.endswith("유지 의견 · 주문 없음")
    assert "주문은 없습니다" in item.payload["note"]


def test_an_emergency_meeting_adds_only_on_good_news_once_a_day(
        make_service: Callable[..., RunService]) -> None:
    """Owner, 2026-11-06: an emergency meeting's BUY becomes an add-on only when the alert was
    good news, at most one a day; otherwise it is reported without an order."""
    import json

    service = make_service(demo_engine=DemoEngine(rating="Buy"))
    conn = service.inbox.conn

    def alert(n: int, direction: str) -> int:
        cur = conn.execute(
            "INSERT INTO inbox_items (kind, title, payload, status, dedupe_key, created_at) "
            "VALUES ('adhoc', '[속보] x', ?, 'INFO', ?, ?)",
            (json.dumps({"type": "breaking", "news": [{"direction": direction}]}),
             f"breaking:t{n}", service.clock().isoformat()))
        return int(cur.lastrowid or 0)

    def meet(iid: str, alert_id: int) -> str:
        run = service.create_run(CreateRunRequest(instrument_id=iid, engine="demo"),
                                 trigger="breaking", schedule_slot=f"breaking:{alert_id}")
        service.execute(run.id)
        return next(i.title for i in service.inbox.list() if i.run_id == run.id)

    assert meet("KR:KRX:005930", alert(1, "나쁨")).endswith("긴급 회의 (추가 매수 안 함)")
    assert meet("US:NASDAQ:NVDA", alert(2, "좋음")).startswith("[결재]")     # the one add-on
    assert meet("KR:KRX:005930", alert(3, "좋음")).endswith("긴급 회의 (추가 매수 안 함)")


def test_emergency_meetings_are_capped_and_spaced(
        make_service: Callable[..., RunService]) -> None:
    from stock_office.breaking import MAX_EMERGENCY_PER_DAY, start_emergency

    service = make_service()
    now = service.clock()
    service.engines = lambda name: DemoEngine()   # type: ignore[method-assign,assignment]
    first = start_emergency(service, "KR:KRX:005930", 1, now)
    assert first is not None
    assert start_emergency(service, "KR:KRX:005930", 2, now) is None   # met < 6 h ago
    ids = ["KR:KRX:000660", "KR:KRX:035420", "KR:KRX:005380"]
    started = [start_emergency(service, iid, 3 + n, now) for n, iid in enumerate(ids)]
    assert sum(1 for s in started if s) == MAX_EMERGENCY_PER_DAY - 1
