"""Paper fill rules on one daily bar, and trading costs (pure, no I/O)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from stock_office.paper.costs import Costs
from stock_office.paper.fills import (
    DayBar,
    buy_cash,
    entry_fill,
    exit_fill,
    open_exit_fill,
    sell_cash,
)

DAY = date(2026, 10, 20)
SLIP = D("0.0005")


def bar(o: str, h: str, low: str, c: str) -> DayBar:
    return DayBar(DAY, D(o), D(h), D(low), D(c))


@pytest.mark.parametrize(("b", "price", "rule"), [
    (bar("99", "101", "98", "100"), "99", "open_at_or_below_limit"),     # opened below the limit
    (bar("102", "103", "99.5", "101"), "100", "low_touched_limit"),     # dipped to the limit
    (bar("102", "103", "100.01", "101"), None, None),                   # never reached it
])
def test_entry_limit(b: DayBar, price: str | None, rule: str | None) -> None:
    fill = entry_fill(D(100), b)
    if price is None:
        assert fill is None
    else:
        assert fill is not None and fill.price == D(price) and fill.rule == rule


@pytest.mark.parametrize(("b", "role", "price", "rule"), [
    (bar("88", "95", "87", "90"), "stop", "87.956", "gap_below_stop"),
    (bar("125", "126", "119", "121"), "take_profit", "125", "gap_above_target"),
    (bar("100", "121", "89", "110"), "stop", "89.955", "low_touched_stop"),  # both touched: stop
    (bar("100", "121", "95", "118"), "take_profit", "120", "high_touched_target"),
])
def test_exit_pair(b: DayBar, role: str, price: str, rule: str) -> None:
    fill = exit_fill(b, stop=D(90), target=D(120), stop_only=False, slippage=SLIP)
    assert fill is not None
    assert (fill.role, fill.price, fill.rule) == (role, D(price), rule)


def test_entry_day_checks_only_the_stop() -> None:
    reached_target = bar("100", "125", "95", "120")
    assert exit_fill(reached_target, stop=D(90), target=D(120), stop_only=True,
                     slippage=SLIP) is None
    fell = bar("100", "125", "89", "95")
    fill = exit_fill(fell, stop=D(90), target=D(120), stop_only=True, slippage=SLIP)
    assert fill is not None and fill.role == "stop"


def test_exit_at_open_has_slippage() -> None:
    assert open_exit_fill(bar("100", "101", "99", "100"), SLIP).price == D("99.95")


def test_costs_krw_and_usd() -> None:
    costs = Costs()
    # KRX: 10 shares at 50,000 → 500,000 + 0.015% fee = 500,075 won paid
    buy = buy_cash(D(50_000), D(10), "KRW", D(1), costs)
    assert (buy.fee, buy.fx, buy.amount_krw) == (D("75.0000"), D(1), D(500_075))
    # selling: fee 0.015% and tax 0.20% → 500,000 − 75 − 1,000
    sell = sell_cash(D(50_000), D(10), "KRW", D(1), costs)
    assert sell.amount_krw == D(498_925) and sell.tax == D("1000.0000")
    # US: 0.5 share at $200 = $100 + 0.1% fee; KRW at 1,400 × (1 + 0.25%) = 1,403.5
    usd = buy_cash(D(200), D("0.5"), "USD", D(1400), costs)
    assert usd.fx == D("1403.5000") and usd.amount_krw == D(140_491)  # ceil(100.1 × 1403.5)
    back = sell_cash(D(200), D("0.5"), "USD", D(1400), costs)
    assert back.fx == D("1396.5000") and back.amount_krw == D(139_510)  # floor(99.9 × 1396.5)
