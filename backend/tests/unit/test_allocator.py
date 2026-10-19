"""Asset allocator (company policy, V2): deterministic size with every rule shown."""

from __future__ import annotations

from decimal import Decimal

from stock_office.paper.allocator import POLICY, allocate

NAV = Decimal(10_000_000)


def test_worked_example_from_the_plan() -> None:
    a = allocate(POLICY, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(0), rating="Buy",
                 multiplier=Decimal("0.25"), limit=Decimal(60000), stop=Decimal(56000),
                 fx_krw=Decimal(1))
    assert [v for _, v in a.lines] == [Decimal(250000), Decimal(1500000), Decimal(2000000),
                                       Decimal(8000000)]
    assert a.binding.startswith("기본 비중") and a.qty == 4
    assert a.notional_krw == Decimal(240000) and a.max_loss_krw == Decimal(16000)
    assert a.blocked is None


def test_risk_rule_binds_for_a_wide_stop_and_usd_is_fractional() -> None:
    a = allocate(POLICY, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(0), rating="Buy",
                 multiplier=Decimal(2), limit=Decimal(100), stop=Decimal(80),
                 fx_krw=Decimal(1400), currency="USD")
    # weight rule 2,000,000; risk rule 100,000 / 0.2 = 500,000 → binds
    assert a.binding.startswith("손절")
    assert a.qty == Decimal("3.5696")                             # 500,000 / (140,000 × 1.0005)
    assert a.notional == Decimal("356.96") and a.notional_krw == Decimal(499744)


def test_real_nvda_case_becomes_buyable_with_fractional_shares() -> None:
    # Stored NVDA meeting 3ec11363: Overweight, "0.25~0.5배", entry 226.59, stop 202.52,
    # USD/KRW 1,331.88.
    a = allocate(POLICY, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(0), rating="Overweight",
                 multiplier=Decimal("0.25"), limit=Decimal("226.59"), stop=Decimal("202.52"),
                 fx_krw=Decimal("1331.88"), currency="USD")
    assert a.blocked is None and a.qty == Decimal("0.4967")
    assert Decimal(140_000) < a.notional_krw <= Decimal(150_000)
    whole = allocate(POLICY, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(0), rating="Overweight",
                     multiplier=Decimal("0.25"), limit=Decimal("226.59"), stop=Decimal("202.52"),
                     fx_krw=Decimal("1331.88"), currency="KRW")      # whole shares → blocked
    assert whole.blocked is not None


def test_overweight_is_smaller_and_caps_apply() -> None:
    full = allocate(POLICY, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(0), rating="Buy",
                    multiplier=Decimal(1), limit=Decimal(10000), stop=Decimal(9000),
                    fx_krw=Decimal(1))
    ow = allocate(POLICY, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(0), rating="Overweight",
                  multiplier=Decimal(1), limit=Decimal(10000), stop=Decimal(9000),
                  fx_krw=Decimal(1))
    assert ow.qty < full.qty
    capped = allocate(POLICY, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(1_950_000),
                      rating="Buy", multiplier=Decimal(1), limit=Decimal(10000),
                      stop=Decimal(9000), fx_krw=Decimal(1))
    assert capped.blocked is not None                            # only 50,000 left under 20%


def test_non_buy_ratings_and_tiny_sizes_are_blocked() -> None:
    hold = allocate(POLICY, nav_krw=NAV, cash_krw=NAV, held_krw=Decimal(0), rating="Hold",
                    multiplier=Decimal(1), limit=Decimal(100), stop=Decimal(90),
                    fx_krw=Decimal(1400))
    assert hold.blocked and hold.qty == 0
    no_cash = allocate(POLICY, nav_krw=NAV, cash_krw=Decimal(2_000_000), held_krw=Decimal(0),
                       rating="Buy", multiplier=Decimal(1), limit=Decimal(100),
                       stop=Decimal(90), fx_krw=Decimal(1400))
    assert no_cash.blocked and no_cash.qty == 0                  # cash already at the 20% floor
