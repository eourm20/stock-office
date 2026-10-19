"""Asset allocator (POLICY_V1): deterministic size with every rule shown."""

from __future__ import annotations

from decimal import Decimal

from stock_office.paper.allocator import POLICY_V1, allocate

NAV = Decimal(10_000_000)


def test_worked_example_from_the_plan() -> None:
    a = allocate(POLICY_V1, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(0), rating="Buy",
                 multiplier=Decimal("0.25"), limit=Decimal(60000), stop=Decimal(56000),
                 fx_krw=Decimal(1))
    assert [v for _, v in a.lines] == [Decimal(250000), Decimal(1500000), Decimal(2000000),
                                       Decimal(8000000)]
    assert a.binding.startswith("기본 비중") and a.qty == 4
    assert a.notional_krw == Decimal(240000) and a.max_loss_krw == Decimal(16000)
    assert a.blocked is None


def test_risk_rule_binds_for_a_wide_stop_and_usd_uses_fx() -> None:
    a = allocate(POLICY_V1, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(0), rating="Buy",
                 multiplier=Decimal(2), limit=Decimal(100), stop=Decimal(80),
                 fx_krw=Decimal(1400))
    # weight rule 2,000,000; risk rule 100,000 / 0.2 = 500,000 → binds
    assert a.binding.startswith("손절") and a.qty == 3           # 500,000 / (140,000 × 1.0005)
    assert a.notional == Decimal(300) and a.notional_krw == Decimal(420000)


def test_overweight_is_smaller_and_caps_apply() -> None:
    full = allocate(POLICY_V1, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(0), rating="Buy",
                    multiplier=Decimal(1), limit=Decimal(10000), stop=Decimal(9000),
                    fx_krw=Decimal(1))
    ow = allocate(POLICY_V1, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(0), rating="Overweight",
                  multiplier=Decimal(1), limit=Decimal(10000), stop=Decimal(9000),
                  fx_krw=Decimal(1))
    assert ow.qty < full.qty
    capped = allocate(POLICY_V1, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(1_950_000),
                      rating="Buy", multiplier=Decimal(1), limit=Decimal(10000),
                      stop=Decimal(9000), fx_krw=Decimal(1))
    assert capped.blocked is not None                            # only 50,000 left under 20%


def test_non_buy_ratings_and_tiny_sizes_are_blocked() -> None:
    hold = allocate(POLICY_V1, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(0), rating="Hold",
                    multiplier=Decimal(1), limit=Decimal(100), stop=Decimal(90),
                    fx_krw=Decimal(1400))
    assert hold.blocked and hold.qty == 0
    no_cash = allocate(POLICY_V1, nav_krw=NAV, cash_krw=Decimal(2_000_000), held_krw=Decimal(0),
                       rating="Buy", multiplier=Decimal(1), limit=Decimal(100),
                       stop=Decimal(90), fx_krw=Decimal(1400))
    assert no_cash.blocked and no_cash.qty == 0                  # cash already at the 20% floor
