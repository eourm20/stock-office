"""Paper book: approval → simulated orders → session settlement → cash, positions, reports.

DEMO meetings (fixture prices) are let into the book by the test inbox; bars are made up per test
around the plan's own prices. No network.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from stock_office.db import transaction
from stock_office.domain.models import CreateRunRequest, Market
from stock_office.engine.demo_engine import DemoEngine
from stock_office.inbox import DecisionError, InboxItem
from stock_office.paper.fills import DayBar
from stock_office.paper.settle import Settler
from stock_office.runs.service import RunService
from stock_office.schedule import Session, first_session_opening_after

KR = "KR:KRX:005930"
US = "US:NASDAQ:NVDA"
FX = (D(1400), datetime(2026, 10, 15, tzinfo=UTC))


class Bars:
    def __init__(self) -> None:
        self.by: dict[tuple[str, date], DayBar] = {}

    def set(self, instrument: str, session: Session, o: D, h: D, low: D, c: D) -> None:
        self.by[(instrument, session.day)] = DayBar(session.day, o, h, low, c)

    def __call__(self, instrument: str, day: date) -> DayBar | None:
        return self.by.get((instrument, day))


def meeting(service: RunService, instrument: str, rating: str) -> InboxItem:
    service.engines = lambda name: DemoEngine(rating=rating)
    run = service.create_run(CreateRunRequest(instrument_id=instrument, engine="demo"))
    service.execute(run.id)
    row = service.inbox.conn.execute(
        "SELECT id FROM inbox_items WHERE run_id=?", (run.id,)).fetchone()
    item: InboxItem | None = service.inbox.get(int(row["id"]))
    assert item is not None
    return item


def setup(make_service: Callable[..., RunService], instrument: str = KR, fx: Any = FX
          ) -> tuple[RunService, InboxItem, Settler, Bars, Session]:
    service = make_service()
    item = meeting(service, instrument, "Buy")
    bars = Bars()
    settler = Settler(service.inbox.book, bars, lambda: fx)
    entry = item.paper[0]
    session = first_session_opening_after(
        Market.KR if instrument == KR else Market.US,
        datetime.fromisoformat(entry["created_at"]))
    assert entry["active_from"] == session.open.astimezone(UTC).isoformat(timespec="microseconds")
    return service, item, settler, bars, session


def prices(item: InboxItem) -> tuple[D, D, D]:
    assert item.plan is not None
    return D(item.plan["limit"]), D(item.plan["stop"]), D(item.plan["target"])


def after(session: Session) -> datetime:
    return session.close + timedelta(hours=1)


def nxt(market: Market, session: Session) -> Session:
    return first_session_opening_after(market, session.close)


def kinds(service: RunService) -> list[str]:
    return [i.title.split("]")[0] + "]" for i in reversed(service.inbox.list())]


def test_auto_approval_books_one_entry_for_the_next_session(
        make_service: Callable[..., RunService]) -> None:
    service, item, *_ = setup(make_service)
    assert item.status == "APPROVED" and item.approvals[0]["auto"] is True
    assert [(o["role"], o["status"]) for o in item.paper] == [("entry", "OPEN")]
    order = item.paper[0]
    assert D(order["qty"]) > 0 and D(order["reserved_krw"]) > 0
    # approving again (or the same tap repeated) never books twice
    book = service.inbox.book
    with transaction(book.conn):
        again = book.open_bracket(item.id, KR, item.plan or {}, service.clock())
    assert again == order["id"]
    assert book.conn.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0] == 1


def test_entry_fill_moves_cash_into_a_position_and_sets_the_exit_pair(
        make_service: Callable[..., RunService]) -> None:
    service, item, settler, bars, s1 = setup(make_service)
    limit, stop, target = prices(item)
    bars.set(KR, s1, limit * D("1.01"), limit * D("1.02"), limit * D("0.999"), limit)
    result = settler.settle(Market.KR, s1, after(s1))
    assert (result.status, result.fills) == ("OK", 1)
    book = service.inbox.book
    pos = book.position(KR)
    assert pos is not None
    qty = D(pos["qty"])
    paid = D(book.conn.execute("SELECT amount_krw FROM paper_fills").fetchone()[0])
    assert book.cash_krw() == D(10_000_000) - paid
    assert book.nav_krw() == book.cash_krw() + (qty * limit).quantize(D(1))
    assert book.reserved_krw() == 0
    orders = service.inbox.book.orders_for_item(item.id)
    assert [(o["role"], o["status"], D(o["price"])) for o in orders] == [
        ("entry", "FILLED", limit), ("take_profit", "OPEN", target), ("stop", "OPEN", stop)]
    assert orders[0]["fill"]["rule"] == "low_touched_limit"
    assert "[체결]" in kinds(service)
    # the same session again: nothing moves
    assert settler.settle(Market.KR, s1, after(s1)).note == "already settled"
    assert book.conn.execute("SELECT COUNT(*) FROM paper_fills").fetchone()[0] == 1


def test_take_profit_closes_the_position_and_cancels_the_stop(
        make_service: Callable[..., RunService]) -> None:
    service, item, settler, bars, s1 = setup(make_service)
    limit, stop, target = prices(item)
    bars.set(KR, s1, limit, limit, limit, limit)
    settler.settle(Market.KR, s1, after(s1))
    s2 = nxt(Market.KR, s1)
    bars.set(KR, s2, limit, target * D("1.01"), limit * D("0.99"), target)
    assert settler.settle(Market.KR, s2, after(s2)).fills == 1
    book = service.inbox.book
    assert book.position(KR) is None
    roles = {o["role"]: o["status"] for o in book.orders_for_item(item.id)}
    assert roles == {"entry": "FILLED", "take_profit": "FILLED", "stop": "CANCELLED"}
    realized = D(book.portfolio()["realized_krw"])
    assert realized > 0 and book.cash_krw() == D(10_000_000) + realized
    closing = [i for i in service.inbox.list() if i.kind == "closing"]
    assert len(closing) == 1 and closing[0].title.startswith("[청산] 삼성전자 익절")


def test_same_day_touching_both_counts_as_the_stop(
        make_service: Callable[..., RunService]) -> None:
    service, item, settler, bars, s1 = setup(make_service)
    limit, stop, target = prices(item)
    bars.set(KR, s1, limit, limit, limit, limit)
    settler.settle(Market.KR, s1, after(s1))
    s2 = nxt(Market.KR, s1)
    bars.set(KR, s2, limit, target * D("1.02"), stop * D("0.99"), limit)
    settler.settle(Market.KR, s2, after(s2))
    roles = {o["role"]: o["status"] for o in service.inbox.book.orders_for_item(item.id)}
    assert roles["stop"] == "FILLED" and roles["take_profit"] == "CANCELLED"
    assert D(service.inbox.book.portfolio()["realized_krw"]) < 0


def test_entry_day_only_the_stop_is_checked(make_service: Callable[..., RunService]) -> None:
    service, item, settler, bars, s1 = setup(make_service)
    limit, stop, target = prices(item)
    # filled at the open, then ran to the target: the high may have come first → still held
    bars.set(KR, s1, limit, target * D("1.05"), limit * D("0.99"), target)
    settler.settle(Market.KR, s1, after(s1))
    assert service.inbox.book.position(KR) is not None


def test_entry_day_falling_through_the_stop_is_stopped_out(
        make_service: Callable[..., RunService]) -> None:
    service, item, settler, bars, s1 = setup(make_service)
    limit, stop, _ = prices(item)
    bars.set(KR, s1, limit, limit, stop * D("0.98"), stop)
    assert settler.settle(Market.KR, s1, after(s1)).fills == 2
    assert service.inbox.book.position(KR) is None


def test_unreached_limit_expires_and_frees_the_reservation(
        make_service: Callable[..., RunService]) -> None:
    service, item, settler, bars, s1 = setup(make_service)
    limit, _, _ = prices(item)
    bars.set(KR, s1, limit * D("1.03"), limit * D("1.05"), limit * D("1.01"), limit * D("1.04"))
    assert settler.settle(Market.KR, s1, after(s1)).fills == 0
    book = service.inbox.book
    assert book.orders_for_item(item.id)[0]["status"] == "EXPIRED"
    assert book.reserved_krw() == 0 and book.cash_krw() == D(10_000_000)
    assert any(t == "[미체결]" for t in kinds(service))


def test_missing_bar_waits_then_settles_without_filling(
        make_service: Callable[..., RunService]) -> None:
    service, item, settler, bars, s1 = setup(make_service)
    assert settler.settle(Market.KR, s1, after(s1)).status == "WAITING"
    assert service.inbox.book.conn.execute("SELECT COUNT(*) FROM settle_runs").fetchone()[0] == 0
    late = nxt(Market.KR, s1).open + timedelta(minutes=1)
    result = settler.settle(Market.KR, s1, late)
    assert result.status == "NO_DATA" and result.fills == 0
    order = service.inbox.book.orders_for_item(item.id)[0]
    assert (order["status"], order["reason"]) == ("EXPIRED", "시세 없음")


def test_usd_fill_converts_at_the_rate_with_spread_and_waits_without_it(
        make_service: Callable[..., RunService]) -> None:
    service, item, settler, bars, s1 = setup(make_service, US)
    limit, _, _ = prices(item)
    bars.set(US, s1, limit, limit, limit, limit)
    blind = Settler(service.inbox.book, bars, lambda: None)
    assert blind.settle(Market.US, s1, after(s1)).status == "WAITING"
    settler.settle(Market.US, s1, after(s1))
    fill = service.inbox.book.conn.execute("SELECT * FROM paper_fills").fetchone()
    assert D(fill["fx"]) == D("1403.5000")                      # 1,400 × (1 + 0.25%)
    assert D(fill["qty"]) % D(1) != 0 or D(fill["qty"]) >= 1    # fractional allowed
    pos = service.inbox.book.position(US)
    assert pos is not None and pos["currency"] == "USD" and D(pos["last_fx"]) == D(1400)


def test_sell_meeting_with_a_position_sells_everything_at_the_next_open(
        make_service: Callable[..., RunService]) -> None:
    service, item, settler, bars, s1 = setup(make_service)
    limit, _, _ = prices(item)
    bars.set(KR, s1, limit, limit, limit, limit)
    settler.settle(Market.KR, s1, after(s1))
    service.clock = lambda: after(s1)               # the next meeting comes after that close
    sell = meeting(service, KR, "Sell")
    assert sell.kind == "approval" and sell.status == "APPROVED"
    assert sell.plan is not None and sell.plan["side"] == "SELL"
    assert sell.title.startswith("[결재] 삼성전자 전량 매도")
    exit_order = sell.paper[0]
    assert (exit_order["role"], exit_order["status"]) == ("exit", "OPEN")
    s2 = first_session_opening_after(Market.KR, datetime.fromisoformat(exit_order["created_at"]))
    bars.set(KR, s2, limit * D("1.02"), limit * D("1.03"), limit, limit)
    settler.settle(Market.KR, s2, after(s2))
    book = service.inbox.book
    assert book.position(KR) is None
    statuses = {o["role"]: o["status"] for o in book.activity()}
    assert statuses == {"exit": "FILLED", "take_profit": "CANCELLED", "stop": "CANCELLED",
                        "entry": "FILLED"}
    fill = book.conn.execute(
        "SELECT price, rule FROM paper_fills WHERE order_id=?", (exit_order["id"],)).fetchone()
    assert fill["rule"] == "sold_at_open"
    assert D(fill["price"]) == (limit * D("1.02") * D("0.9995")).quantize(D("0.0001"))


def test_sell_meeting_without_a_position_is_a_report(
        make_service: Callable[..., RunService]) -> None:
    service = make_service()
    item = meeting(service, KR, "Sell")
    assert (item.kind, item.status, item.paper) == ("daily", "INFO", [])


def test_ceo_opinion_on_an_auto_approved_request_leaves_the_book_alone(
        make_service: Callable[..., RunService]) -> None:
    service = make_service()
    item = meeting(service, KR, "Buy")
    inbox = service.inbox
    assert item.auto_approved and item.opinion_open and item.ceo_opinion is None
    held = inbox.decide(item.id, "defer", "", "o1", service.clock())   # undecided: can still change
    assert (held.status, held.ceo_opinion, held.opinion_open) == ("APPROVED", "defer", True)
    after_ = inbox.decide(item.id, "reject", "too risky", "o2", service.clock())
    assert (after_.status, after_.ceo_opinion) == ("APPROVED", "reject")
    assert not after_.opinion_open
    assert after_.paper == item.paper  # the order follows the model
    assert [a["opinion"] for a in after_.approvals] == [False, True, True]
    repeated = inbox.decide(item.id, "reject", "too risky", "o2", service.clock())
    assert repeated.ceo_opinion == "reject"
    with pytest.raises(DecisionError):
        inbox.decide(item.id, "approve", "", "o3", service.clock())
    assert inbox.by_run()[item.run_id or ""] == {
        "status": "APPROVED", "auto": True, "paper": "OPEN", "opinion": "reject"}


def test_no_ceo_opinion_after_the_deadline(make_service: Callable[..., RunService]) -> None:
    service = make_service()
    item = meeting(service, KR, "Buy")
    assert item.expires_at is not None
    with pytest.raises(DecisionError):
        service.inbox.decide(item.id, "approve", "", "late", item.expires_at + timedelta(seconds=1))


def test_auto_approve_off_leaves_the_request_waiting(
        make_service: Callable[..., RunService]) -> None:
    service = make_service()
    with transaction(service.inbox.conn):
        service.inbox.book.set_auto_approve(False, service.clock())
    item = meeting(service, KR, "Buy")
    assert item.status == "PENDING" and item.paper == []


def test_policy_refusal_at_approval_is_reported(make_service: Callable[..., RunService]) -> None:
    service = make_service()
    book = service.inbox.book
    with transaction(book.conn):
        book.set_auto_approve(False, service.clock())
    item = meeting(service, KR, "Buy")
    with transaction(book.conn):  # before the CEO approves, the account spends almost everything
        book.ensure_started(service.clock())
        book.conn.execute("INSERT INTO paper_cash (amount_krw, reason, ref, created_at) "
                          "VALUES ('-9900000', 'test', 'drain', '2026-10-19T00:00:00+00:00')")
    approved = service.inbox.decide(item.id, "approve", "", "ceo", service.clock())
    order = approved.paper[0]
    assert order["status"] == "REJECTED" and "미만" in order["reason"]
    assert any(i.title.startswith("[리스크 거절]") for i in service.inbox.list())


def test_demo_meetings_stay_out_of_the_book_in_production(
        make_service: Callable[..., RunService]) -> None:
    service = make_service()
    service.inbox.book_demo_runs = False
    item = meeting(service, KR, "Buy")
    assert item.status == "PENDING" and item.paper == []           # no auto-approval for DEMO
    approved = service.inbox.decide(item.id, "approve", "", "t", service.clock())
    assert approved.status == "APPROVED" and approved.paper == []


@pytest.mark.parametrize("market", [Market.KR, Market.US])
def test_tick_settles_each_closed_session_once(
        make_service: Callable[..., RunService], market: Market) -> None:
    instrument = KR if market is Market.KR else US
    service, item, settler, bars, s1 = setup(make_service, instrument)
    limit, _, _ = prices(item)
    bars.set(instrument, s1, limit, limit, limit, limit)
    # too early for s1 (an earlier session may settle here, depending on the wall clock)
    early = settler.tick(s1.close)
    assert [r for r in early if r.market == market.value and r.session == s1.day] == []
    done = [r for r in settler.tick(after(s1)) if r.market == market.value]
    assert [(r.session, r.status) for r in done][-1] == (s1.day, "OK")
    assert [r for r in settler.tick(after(s1)) if r.market == market.value] == []
