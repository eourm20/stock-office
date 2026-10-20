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
