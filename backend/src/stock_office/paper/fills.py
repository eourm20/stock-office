"""Paper fills from one daily bar: pure functions, no I/O.

A daily bar does not tell the order of prices within the day, so the rules are conservative:
- Entry (buy limit): open ≤ limit → filled at the open; low ≤ limit → filled at the limit.
- Exit pair (take-profit limit + stop): a gap through either level fills at the open; if the bar
  touched both, the stop wins. On the entry's own day only the stop is checked (the high may
  have come before the fill).
- Exit at the open (CEO-approved sell): the open, less slippage.
Stops and at-open exits fill `slippage` worse; limit fills happen exactly at their price or better.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from stock_office.paper.costs import Costs

_PRICE = Decimal("0.0001")


@dataclass(frozen=True)
class DayBar:
    session: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class Fill:
    price: Decimal
    role: str  # entry | take_profit | stop | exit
    rule: str  # why this price (shown in the execution report)


def _p(x: Decimal) -> Decimal:
    return x.quantize(_PRICE)


def entry_fill(limit: Decimal, bar: DayBar) -> Fill | None:
    if bar.open <= limit:
        return Fill(_p(bar.open), "entry", "open_at_or_below_limit")
    if bar.low <= limit:
        return Fill(_p(limit), "entry", "low_touched_limit")
    return None


def exit_fill(
    bar: DayBar, *, stop: Decimal, target: Decimal | None, stop_only: bool, slippage: Decimal
) -> Fill | None:
    worse = 1 - slippage
    if bar.open <= stop:
        return Fill(_p(bar.open * worse), "stop", "gap_below_stop")
    if not stop_only and target is not None and bar.open >= target:
        return Fill(_p(bar.open), "take_profit", "gap_above_target")
    if bar.low <= stop:  # also when the high reached the target the same day: the stop wins
        return Fill(_p(stop * worse), "stop", "low_touched_stop")
    if not stop_only and target is not None and bar.high >= target:
        return Fill(_p(target), "take_profit", "high_touched_target")
    return None


def open_exit_fill(bar: DayBar, slippage: Decimal) -> Fill:
    return Fill(_p(bar.open * (1 - slippage)), "exit", "sold_at_open")


@dataclass(frozen=True)
class Cash:
    gross: Decimal  # price × qty, instrument currency
    fee: Decimal
    tax: Decimal
    fx: Decimal  # KRW per unit actually applied (spread included); 1 for KRW
    amount_krw: Decimal  # buy: total paid; sell: net received (whole won)


def buy_cash(price: Decimal, qty: Decimal, currency: str, fx_mid: Decimal, costs: Costs) -> Cash:
    gross = price * qty
    fee = gross * costs.commission(currency)
    fx = Decimal(1) if currency == "KRW" else fx_mid * (1 + costs.fx_spread)
    paid = ((gross + fee) * fx).quantize(Decimal(1), rounding=ROUND_CEILING)
    return Cash(_p(gross), _p(fee), Decimal(0), _p(fx), paid)


def sell_cash(price: Decimal, qty: Decimal, currency: str, fx_mid: Decimal, costs: Costs) -> Cash:
    gross = price * qty
    fee = gross * costs.commission(currency)
    tax = gross * costs.sell_tax(currency)
    fx = Decimal(1) if currency == "KRW" else fx_mid * (1 - costs.fx_spread)
    got = ((gross - fee - tax) * fx).quantize(Decimal(1), rounding=ROUND_FLOOR)
    return Cash(_p(gross), _p(fee), _p(tax), _p(fx), got)
