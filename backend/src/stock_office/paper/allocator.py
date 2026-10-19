"""Asset allocator ("자산운용 담당"): how much of a BUY the company may take, by fixed rules.

Deterministic and versioned. The AI's sizing prose only scales a base weight; every cap below is
company policy that no model output can exceed. The result explains itself line by line so the
CEO can read why the size is what it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal


@dataclass(frozen=True)
class Policy:
    version: str = "POLICY_V1"
    initial_equity_krw: Decimal = Decimal(10_000_000)
    base_weight: Decimal = Decimal("0.10")  # a full-conviction position: 10% of NAV
    rating_factor: tuple[tuple[str, Decimal], ...] = (
        ("Buy", Decimal(1)),
        ("Overweight", Decimal("0.6")),
    )
    risk_per_trade: Decimal = Decimal("0.01")  # lose at most 1% of NAV if the stop is hit
    max_weight: Decimal = Decimal("0.20")  # one instrument ≤ 20% of NAV
    cash_floor: Decimal = Decimal("0.20")  # keep ≥ 20% of NAV in cash
    min_notional_krw: Decimal = Decimal(100_000)
    fee_rate: Decimal = Decimal("0.0005")  # buffer for commission/slippage in the sizing

    def factor(self, rating: str | None) -> Decimal:
        return dict(self.rating_factor).get(rating or "", Decimal(0))


POLICY_V1 = Policy()


@dataclass
class Allocation:
    qty: int
    notional: Decimal  # in the instrument's currency
    notional_krw: Decimal
    max_loss_krw: Decimal  # if the stop is hit
    binding: str  # which rule set the size
    lines: list[tuple[str, Decimal]] = field(default_factory=list)  # (rule, KRW limit)
    blocked: str | None = None  # reason the plan cannot be approved as a buy


def _won(x: Decimal) -> Decimal:
    return x.quantize(Decimal(1), rounding=ROUND_DOWN)


def allocate(
    policy: Policy,
    *,
    nav_krw: Decimal,
    cash_krw: Decimal,
    held_krw: Decimal,
    rating: str | None,
    multiplier: Decimal,
    limit: Decimal,
    stop: Decimal,
    fx_krw: Decimal,
) -> Allocation:
    """Shares to buy at `limit` (instrument currency); `fx_krw` = KRW per unit (1 for KRW)."""
    factor = policy.factor(rating)
    stop_distance = (limit - stop) / limit
    rules = [
        (
            "기본 비중 10% × 등급 계수 × AI 제시 배수",
            policy.base_weight * factor * multiplier * nav_krw,
        ),
        ("손절 시 손실을 자산의 1% 이내로", policy.risk_per_trade * nav_krw / stop_distance),
        ("한 종목 최대 20% (보유분 포함)", policy.max_weight * nav_krw - held_krw),
        ("현금 20% 이상 유지", cash_krw - policy.cash_floor * nav_krw),
    ]
    lines = [(label, _won(max(value, Decimal(0)))) for label, value in rules]
    binding, budget = min(lines, key=lambda line: line[1])
    unit_krw = limit * fx_krw * (1 + policy.fee_rate)
    qty = int((budget / unit_krw).to_integral_value(rounding=ROUND_DOWN)) if unit_krw > 0 else 0
    notional = limit * qty
    notional_krw = _won(notional * fx_krw)
    blocked = None
    if factor == 0:
        blocked = f"등급 '{rating}'은(는) 매수 대상이 아님"
    elif qty == 0 or notional_krw < policy.min_notional_krw:
        blocked = f"규정상 매수 가능 금액이 {policy.min_notional_krw:,.0f}원 미만"
    return Allocation(
        qty=qty if not blocked else 0,
        notional=notional if not blocked else Decimal(0),
        notional_krw=notional_krw if not blocked else Decimal(0),
        max_loss_krw=_won((limit - stop) * qty * fx_krw) if not blocked else Decimal(0),
        binding=binding,
        lines=lines,
        blocked=blocked,
    )
