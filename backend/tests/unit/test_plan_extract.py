"""Approval plan extraction from the engine's labelled lines (fixtures copied from stored runs)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from stock_office.domain.models import Market
from stock_office.plan_extract import (
    Bar,
    Labels,
    atr,
    build_buy_plan,
    krx_tick,
    parse_labels,
    round_price,
    sizing_multiplier,
)

# Real lines from the scheduled NVDA run 7dcf0bb6 (BUY / Overweight) and SELL run afd91499.
NVDA_TRADER = """**Action**: Buy

**Reasoning**: 추세는 살아 있지만 …

**Entry Price**: 224.33

**Stop Loss**: 196.7

**Position Sizing**: 신규 매수는 표준 배분액의 최대 0.25배; 기존 보유량을 포함한 목표 비중 이내

FINAL TRANSACTION PROPOSAL: **BUY**"""
NVDA_PM = """**Rating**: Overweight

**Executive Summary**: NVDA는 제한적·조건부 비중 확대를 권고합니다.

**Price Target**: not provided

**Time Horizon**: 3~6개월"""
SAMSUNG_TRADER = """**Action**: Sell

**Entry Price**: not provided

**Stop Loss**: not provided

**Position Sizing**: 목표 보유량을 표준 배분의 50~75%로 설정"""
SAMSUNG_PM = """**Rating**: Underweight

**Price Target**: not provided

**Time Horizon**: 다음 실적 발표 및 추세 회복 여부 확인 시까지"""

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def bars(closes: list[float], spread: float = 2.0) -> list[Bar]:
    return [Bar(T0 + timedelta(days=i), Decimal(str(c + spread)), Decimal(str(c - spread)),
                Decimal(str(c))) for i, c in enumerate(closes)]


def test_parses_real_buy_and_sell_lines() -> None:
    buy = parse_labels(NVDA_TRADER, NVDA_PM)
    assert buy == Labels(rating="Overweight", entry=Decimal("224.33"), stop=Decimal("196.7"),
                         target=None, sizing_text=buy.sizing_text, horizon="3~6개월")
    assert sizing_multiplier(buy.sizing_text) == Decimal("0.25")
    sell = parse_labels(SAMSUNG_TRADER, SAMSUNG_PM)
    assert (sell.rating, sell.entry, sell.stop, sell.target) == ("Underweight", None, None, None)
    assert sizing_multiplier(sell.sizing_text) is None          # percent target, not a multiplier
    assert parse_labels("", "") == Labels()


def test_multiplier_ranges_take_the_cautious_end() -> None:
    assert sizing_multiplier("표준 배분의 0.25~0.5배로 분할") == Decimal("0.25")
    assert sizing_multiplier("1배") == Decimal("1")
    assert sizing_multiplier("적당히") is None


def test_buy_plan_uses_ai_numbers_and_fills_the_target_by_policy() -> None:
    plan = build_buy_plan(parse_labels(NVDA_TRADER, NVDA_PM), bars([220.0] * 20), Market.US)
    assert plan is not None
    assert (plan.limit, plan.stop) == (Decimal("224.33"), Decimal("196.70"))
    assert plan.sources == {"limit": "ai", "stop": "ai", "target": "policy"}
    assert plan.target == Decimal("279.59")       # limit + 2 × (limit − stop)
    assert plan.multiplier == Decimal("0.25") and plan.multiplier_source == "ai"
    assert plan.review_reasons == []               # 12.3% stop, entry within 10% of 220


def test_policy_defaults_from_atr_when_the_model_gave_no_prices() -> None:
    plan = build_buy_plan(Labels(rating="Buy"), bars([60000.0] * 20, spread=1000), Market.KR)
    assert plan is not None
    assert plan.sources == {"limit": "policy", "stop": "policy", "target": "policy"}
    assert plan.limit == Decimal(60300)                       # close × 1.005, KRX tick 100
    assert plan.atr == Decimal(2000)
    # 2 × ATR = 4,000 → 6.6% of the limit, inside the 3–12% band
    assert plan.stop == Decimal(56300) and plan.target == Decimal(68300)
    assert plan.review_reasons == []


def test_invalid_numbers_make_the_plan_unapprovable() -> None:
    far = build_buy_plan(Labels(rating="Buy", entry=Decimal(300), stop=Decimal(280)),
                         bars([220.0] * 20), Market.US)
    assert far is not None and any("10%" in r for r in far.review_reasons)
    upside_down = build_buy_plan(Labels(rating="Buy", entry=Decimal(220), stop=Decimal(230)),
                                 bars([220.0] * 20), Market.US)
    assert upside_down is not None and any("순서" in r for r in upside_down.review_reasons)
    assert build_buy_plan(Labels(rating="Buy"), [], Market.US) is None


def test_atr_needs_enough_bars_and_krx_ticks() -> None:
    assert atr(bars([100.0] * 10)) is None
    assert atr(bars([100.0] * 15)) == Decimal(4)
    assert krx_tick(Decimal(1500)) == 1 and krx_tick(Decimal(60000)) == 100
    assert krx_tick(Decimal(215500)) == 500 and krx_tick(Decimal(600000)) == 1000
    assert round_price(Decimal("215649"), Market.KR) == Decimal(215500)
    assert round_price(Decimal("224.334"), Market.US) == Decimal("224.33")
