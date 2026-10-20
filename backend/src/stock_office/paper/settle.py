"""Session settlement of the paper book, after each exchange's close.

For one market and one session: take that session's daily bar for every instrument with open
orders or a position, apply paper/fills.py, move cash, update positions, mark them at the close
and file execution/closing reports, all in one transaction, then record the session as settled.
Bars and the USD/KRW rate are passed in (this package has no network access).

Missing data never fills anything. If a needed bar is not there yet, the session waits and is
retried until the next session opens; after that it is settled without it (entries expire).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from stock_office.db import transaction
from stock_office.domain.instruments import display_name
from stock_office.domain.models import Market
from stock_office.paper.book import ROLE_KO, Book, D, iso, money_text, qty_text
from stock_office.paper.fills import (
    DayBar,
    Fill,
    buy_cash,
    entry_fill,
    exit_fill,
    open_exit_fill,
    sell_cash,
)
from stock_office.schedule import Session, closed_sessions, first_session_opening_after

log = logging.getLogger("stock_office.settle")

BarSource = Callable[[str, date], DayBar | None]  # instrument id, session date → that day's bar
FxSource = Callable[[], tuple[Decimal, datetime] | None]

SETTLE_DELAY = {Market.KR: timedelta(minutes=40), Market.US: timedelta(minutes=30)}
RETRY_EVERY = timedelta(minutes=10)
RULE_KO = {
    "open_at_or_below_limit": "시가가 지정가 이하로 시작해 시가에 체결",
    "low_touched_limit": "장중 저가가 지정가에 닿아 지정가에 체결",
    "gap_below_stop": "시가가 손절가 아래로 시작해 시가에 손절",
    "gap_above_target": "시가가 목표가 위로 시작해 시가에 익절",
    "low_touched_stop": (
        "장중 저가가 손절가에 닿아 손절 (같은 날 목표가와 둘 다 닿으면 손절로 처리)"
    ),
    "high_touched_target": "장중 고가가 목표가에 닿아 익절",
    "sold_at_open": "승인된 매도를 시가에 처리",
}


def next_settle_times(now: datetime) -> list[tuple[Market, datetime]]:
    """When each market's next settlement is due (office screen)."""
    out = []
    for market in Market:
        session = first_session_opening_after(market, now - timedelta(days=1))
        while session.close + SETTLE_DELAY[market] <= now:
            session = first_session_opening_after(market, session.close)
        out.append((market, session.close + SETTLE_DELAY[market]))
    return out


@dataclass
class SettleResult:
    market: str
    session: date
    status: str  # OK | NO_DATA | WAITING
    fills: int = 0
    note: str = ""


class Settler:
    def __init__(self, book: Book, bars: BarSource, fx: FxSource) -> None:
        self.book, self.bars, self.fx = book, bars, fx
        self._retry_at: dict[str, datetime] = {}

    @property
    def conn(self) -> sqlite3.Connection:
        return self.book.conn

    # ---------------------------------------------------------------- what is due
    def due(self, market: Market, now: datetime) -> list[Session]:
        started = self.book.started_at()
        if started is None:
            return []
        done = {r["session"] for r in self.conn.execute(
            "SELECT session FROM settle_runs WHERE market=?", (market.value,))}
        return [s for s in closed_sessions(market, now - SETTLE_DELAY[market])
                if s.close > started and s.day.isoformat() not in done]

    def tick(self, now: datetime) -> list[SettleResult]:
        results = []
        for market in Market:
            if now < self._retry_at.get(market.value, now):
                continue
            for session in self.due(market, now):
                try:
                    result = self.settle(market, session, now)
                except Exception:  # never let one bad session stop the worker
                    log.exception("settle %s %s failed", market.value, session.day)
                    self._retry_at[market.value] = now + RETRY_EVERY
                    break
                results.append(result)
                if result.status == "WAITING":
                    self._retry_at[market.value] = now + RETRY_EVERY
                    break
        return results

    # ---------------------------------------------------------------- one session
    def settle(self, market: Market, session: Session, now: datetime) -> SettleResult:
        day = session.day.isoformat()
        orders = list(self.conn.execute(
            "SELECT * FROM paper_orders WHERE status='OPEN' AND market=? AND active_from<=? "
            "ORDER BY id", (market.value, iso(session.close))))
        positions = [p for p in self.book.positions() if p["market"] == market.value]
        instruments = sorted({o["instrument_id"] for o in orders}
                             | {p["instrument_id"] for p in positions})
        bars: dict[str, DayBar] = {}
        for instrument_id in instruments:
            bar = self.bars(instrument_id, session.day)
            if bar is not None and bar.session == session.day:
                bars[instrument_id] = bar
        fx_mid: Decimal | None = Decimal(1)
        if market is Market.US and instruments:
            got = self.fx()
            fx_mid = got[0] if got else None
        missing = [i for i in {o["instrument_id"] for o in orders} if i not in bars]
        if (missing or fx_mid is None) and now < first_session_opening_after(
                market, session.close).open:
            return SettleResult(market.value, session.day, "WAITING",
                                note="시세 대기: " + ", ".join(sorted(missing)) if missing
                                else "환율 대기")
        fills = 0
        with transaction(self.conn):
            if self.conn.execute("SELECT 1 FROM settle_runs WHERE market=? AND session=?",
                                 (market.value, day)).fetchone():
                return SettleResult(market.value, session.day, "OK", note="already settled")
            for instrument_id in instruments:
                bar = bars.get(instrument_id)
                if bar is None or fx_mid is None:
                    self._expire_entries(instrument_id, session, now,
                                         "시세 없음" if bar is None else "환율 없음")
                    continue
                fills += self._settle_instrument(instrument_id, bar, fx_mid, session, now)
            status = "OK" if not missing and fx_mid is not None else "NO_DATA"
            note = "" if status == "OK" else "자료 없음: " + ", ".join(sorted(missing) or ["환율"])
            self.conn.execute(
                "INSERT INTO settle_runs (market, session, status, note, nav_krw, cash_krw, "
                "created_at) VALUES (?,?,?,?,?,?,?)",
                (market.value, day, status, note, str(self.book.nav_krw()),
                 str(self.book.cash_krw()), iso(now)))
        log.info("settled %s %s: %s, %d fills", market.value, day, status, fills)
        return SettleResult(market.value, session.day, status, fills, note)

    def _open(self, instrument_id: str, roles: tuple[str, ...], session: Session) -> list[Any]:
        marks = ",".join("?" for _ in roles)
        return list(self.conn.execute(
            f"SELECT * FROM paper_orders WHERE status='OPEN' AND instrument_id=? AND role IN "
            f"({marks}) AND active_from<=? ORDER BY id",
            (instrument_id, *roles, iso(session.close))))

    def _settle_instrument(self, instrument_id: str, bar: DayBar, fx: Decimal,
                           session: Session, now: datetime) -> int:
        fills = 0
        slip = self.book.costs.slippage
        # 1. CEO-approved sells: the whole position at the open; everything else for it stops.
        for order in self._open(instrument_id, ("exit",), session):
            pos = self.book.position(instrument_id)
            if pos is None:
                self._close(order["id"], "CANCELLED", "보유 없음", now)
                continue
            self._fill_sell(order, open_exit_fill(bar, slip), D(pos["qty"]), fx, session, now)
            fills += 1
            for other in self._open(instrument_id, ("take_profit", "stop", "entry"), session):
                self._close(other["id"], "CANCELLED", "승인된 전량 매도로 취소", now)
        # 2. Exit pairs of earlier entries.
        fills += self._check_pairs(instrument_id, bar, fx, session, now, entry_day=False)
        # 3. Entries for this session.
        for order in self._open(instrument_id, ("entry",), session):
            if order["valid_until"] and order["valid_until"] < iso(session.open):
                self._expire(order, now, "유효 기간 지남")
                continue
            fill = entry_fill(D(order["price"]), bar)
            if fill is None:
                if order["valid_until"] and order["valid_until"] <= iso(session.close):
                    self._expire(order, now, "장중 가격이 지정가에 닿지 않음")
                continue
            if self._fill_buy(order, fill, fx, session, now):
                fills += 1
        fills += self._check_pairs(instrument_id, bar, fx, session, now, entry_day=True)
        # 4. Mark what is still held at the close.
        self.conn.execute(
            "UPDATE paper_positions SET last_price=?, last_fx=?, marked_session=? "
            "WHERE instrument_id=?", (str(bar.close), str(fx), session.day.isoformat(),
                                      instrument_id))
        return fills

    def _check_pairs(self, instrument_id: str, bar: DayBar, fx: Decimal, session: Session,
                     now: datetime, entry_day: bool) -> int:
        fills = 0
        stops = self._open(instrument_id, ("stop",), session)
        for stop in stops:
            parent_session = self.conn.execute(
                "SELECT session FROM paper_fills WHERE order_id=?", (stop["parent_id"],)
            ).fetchone()
            same_day = parent_session is not None and \
                parent_session["session"] == session.day.isoformat()
            if same_day != entry_day:
                continue
            target = self.conn.execute(
                "SELECT * FROM paper_orders WHERE parent_id=? AND role='take_profit' "
                "AND status='OPEN'", (stop["parent_id"],)).fetchone()
            fill = exit_fill(bar, stop=D(stop["price"]),
                             target=D(target["price"]) if target else None,
                             stop_only=entry_day, slippage=self.book.costs.slippage)
            if fill is None:
                continue
            pos = self.book.position(instrument_id)
            if pos is None:
                continue
            won, lost = (target, stop) if fill.role == "take_profit" else (stop, target)
            self._fill_sell(won, fill, min(D(won["qty"]), D(pos["qty"])), fx, session, now)
            if lost is not None:
                self._close(lost["id"], "CANCELLED", f"{ROLE_KO[fill.role]} 체결로 취소", now)
            fills += 1
        return fills

    # ---------------------------------------------------------------- ledger moves
    def _close(self, order_id: int, status: str, reason: str, now: datetime) -> None:
        self.conn.execute(
            "UPDATE paper_orders SET status=?, reason=?, closed_at=? WHERE id=? AND status='OPEN'",
            (status, reason, iso(now), order_id))

    def _expire(self, order: Any, now: datetime, reason: str) -> None:
        self._close(order["id"], "EXPIRED", reason, now)
        name = display_name(order["instrument_id"])
        price = money_text(D(order["price"]), order["currency"])
        self.book.notice(
            kind="execution", instrument_id=order["instrument_id"],
            title=f"[미체결] {name} 매수 {qty_text(order['qty'])}주 · 지정가 {price}",
            summary=reason,
            payload={"order_id": order["id"], "role": "entry", "status": "EXPIRED",
                     "reason": reason, "item_id": order["item_id"]},
            dedupe=f"order:{order['id']}:expired", now=now)

    def _expire_entries(self, instrument_id: str, session: Session, now: datetime,
                        reason: str) -> None:
        for order in self._open(instrument_id, ("entry",), session):
            if order["valid_until"] and order["valid_until"] <= iso(session.close):
                self._expire(order, now, reason)

    def _record_fill(self, order: Any, fill: Fill, qty: Decimal, cash: Any, session: Session,
                     now: datetime, realized: Decimal | None) -> None:
        self.conn.execute(
            "INSERT INTO paper_fills (order_id, session, price, qty, gross, fee, tax, fx, "
            "amount_krw, realized_krw, rule, filled_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (order["id"], session.day.isoformat(), str(fill.price), qty_text(qty),
             str(cash.gross), str(cash.fee), str(cash.tax), str(cash.fx), str(cash.amount_krw),
             None if realized is None else str(realized), fill.rule, iso(now)))
        self.conn.execute(
            "UPDATE paper_orders SET status='FILLED', qty=?, closed_at=? WHERE id=?",
            (qty_text(qty), iso(now), order["id"]))

    def _fill_buy(self, order: Any, fill: Fill, fx: Decimal, session: Session,
                  now: datetime) -> bool:
        qty, currency = D(order["qty"]), order["currency"]
        cash = buy_cash(fill.price, qty, currency, fx, self.book.costs)
        if cash.amount_krw > self.book.cash_krw():
            self._close(order["id"], "REJECTED", "체결 시점 현금 부족", now)
            return False
        self._record_fill(order, fill, qty, cash, session, now, None)
        self.conn.execute(
            "INSERT INTO paper_cash (amount_krw, reason, ref, created_at) VALUES (?,?,?,?)",
            (str(-cash.amount_krw), "매수 체결", f"fill:{order['id']}", iso(now)))
        pos = self.book.position(order["instrument_id"])
        if pos is None:
            self.conn.execute(
                "INSERT INTO paper_positions (instrument_id, market, currency, qty, avg_price, "
                "cost_krw, last_price, last_fx, marked_session, opened_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (order["instrument_id"], order["market"], currency, qty_text(qty),
                 str(fill.price), str(cash.amount_krw), str(fill.price), str(fx),
                 session.day.isoformat(), iso(now)))
        else:
            old = D(pos["qty"])
            avg = ((D(pos["avg_price"]) * old + fill.price * qty) / (old + qty)).quantize(
                Decimal("0.0001"))
            self.conn.execute(
                "UPDATE paper_positions SET qty=?, avg_price=?, cost_krw=? WHERE instrument_id=?",
                (qty_text(old + qty), str(avg), str(D(pos["cost_krw"]) + cash.amount_krw),
                 order["instrument_id"]))
        detail = json.loads(order["detail"] or "{}")
        for role, price in (("take_profit", detail.get("target")), ("stop", detail.get("stop"))):
            self.book._insert_order(
                item_id=None, parent_id=order["id"], instrument_id=order["instrument_id"],
                market=order["market"], currency=currency, role=role, side="SELL",
                qty=qty_text(qty), price=str(price), status="OPEN",
                active_from=iso(session.open), valid_until=None,
                idempotency_key=f"{role}:{order['id']}", created_at=iso(now))
        name = display_name(order["instrument_id"])
        self.book.notice(
            kind="execution", instrument_id=order["instrument_id"],
            title=f"[체결] {name} 매수 {qty_text(qty)}주 @ {money_text(fill.price, currency)}",
            summary=f"{RULE_KO[fill.rule]} · 총 {cash.amount_krw:,.0f}원 (비용 포함) · "
                    f"목표가 {money_text(D(detail.get('target')), currency)} / "
                    f"손절가 {money_text(D(detail.get('stop')), currency)} 자동 설정",
            payload={"order_id": order["id"], "role": "entry", "status": "FILLED",
                     "price": fill.price, "qty": qty, "amount_krw": cash.amount_krw,
                     "fee": cash.fee, "fx": cash.fx, "rule": fill.rule,
                     "session": session.day.isoformat(), "item_id": order["item_id"]},
            dedupe=f"order:{order['id']}:filled", now=now)
        return True

    def _fill_sell(self, order: Any, fill: Fill, qty: Decimal, fx: Decimal, session: Session,
                   now: datetime) -> None:
        pos = self.book.position(order["instrument_id"])
        assert pos is not None
        currency, held = order["currency"], D(pos["qty"])
        cash = sell_cash(fill.price, qty, currency, fx, self.book.costs)
        cost_part = (D(pos["cost_krw"]) * qty / held).quantize(Decimal(1))
        realized = cash.amount_krw - cost_part
        self._record_fill(order, fill, qty, cash, session, now, realized)
        self.conn.execute(
            "INSERT INTO paper_cash (amount_krw, reason, ref, created_at) VALUES (?,?,?,?)",
            (str(cash.amount_krw), f"{ROLE_KO[order['role']]} 체결", f"fill:{order['id']}",
             iso(now)))
        if qty >= held:
            self.conn.execute("DELETE FROM paper_positions WHERE instrument_id=?",
                              (order["instrument_id"],))
        else:
            self.conn.execute(
                "UPDATE paper_positions SET qty=?, cost_krw=? WHERE instrument_id=?",
                (qty_text(held - qty), str(D(pos["cost_krw"]) - cost_part),
                 order["instrument_id"]))
        name = display_name(order["instrument_id"])
        pct = (realized / cost_part * 100).quantize(Decimal("0.01")) if cost_part else Decimal(0)
        sign = "+" if realized >= 0 else "−"
        self.book.notice(
            kind="closing", instrument_id=order["instrument_id"],
            title=f"[청산] {name} {ROLE_KO[order['role']]} {qty_text(qty)}주 · "
                  f"{sign}{abs(realized):,.0f}원 ({sign}{abs(pct)}%)",
            summary=f"{RULE_KO[fill.rule]} · {money_text(fill.price, currency)} · "
                    f"받은 금액 {cash.amount_krw:,.0f}원 (비용·세금 차감)",
            payload={"order_id": order["id"], "role": order["role"], "status": "FILLED",
                     "price": fill.price, "qty": qty, "amount_krw": cash.amount_krw,
                     "realized_krw": realized, "realized_pct": pct, "rule": fill.rule,
                     "session": session.day.isoformat(), "item_id": order["item_id"]},
            dedupe=f"order:{order['id']}:filled", now=now)
