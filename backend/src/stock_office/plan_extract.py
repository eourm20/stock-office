"""Approval plan from a finished committee run: deterministic, no model calls.

The pinned TradingAgents renders labelled lines from its structured outputs, with English labels
whatever the report language:
  trader:            **Entry Price**: 224.33 | not provided    **Stop Loss**: ...
                     **Position Sizing**: <prose, e.g. "표준 배분의 0.25~0.5배">
  portfolio manager: **Rating**: Buy|Overweight|...   **Price Target**: ...   **Time Horizon**: ...
Numbers the model gave are used as "AI 제시"; missing ones are filled by the company policy and
marked "규정 기본값". Reference price and ATR come from the run's own stored daily bars, so the plan
uses exactly the data the committee had. A plan that fails a check cannot be approved (REVIEW).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from stock_office.domain.models import Market, MarketSnapshot

Source = Literal["ai", "policy"]

_LABEL = re.compile(
    r"^\s*\**\s*(Entry Price|Stop Loss|Position Sizing|Price Target|Rating|Time Horizon)"
    r"\s*\**\s*[:：]\s*(.+?)\s*$",
    re.MULTILINE,
)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_NOT_GIVEN = re.compile(r"not provided|제공되지 않|없음|n/?a", re.IGNORECASE)
_MULTIPLIER = re.compile(r"(\d+(?:\.\d+)?)\s*(?:[~\-–]\s*(\d+(?:\.\d+)?))?\s*배")

# Company policy defaults (see paper/allocator.py Policy). Changing them: bump the policy version.
LIMIT_MARKUP = Decimal("1.005")
ATR_STOP_MULT = Decimal(2)
STOP_MIN, STOP_MAX = Decimal("0.03"), Decimal("0.12")
FALLBACK_STOP = Decimal("0.08")
REWARD_RISK = Decimal(2)
MAX_ENTRY_DEVIATION = Decimal("0.10")
STOP_DISTANCE_RANGE = (Decimal("0.01"), Decimal("0.25"))


@dataclass(frozen=True)
class Labels:
    rating: str | None = None
    entry: Decimal | None = None
    stop: Decimal | None = None
    target: Decimal | None = None
    sizing_text: str | None = None
    horizon: str | None = None


def _price(text: str | None) -> Decimal | None:
    """First number of a labelled value; a range "a~b" gives its lower bound."""
    if not text or _NOT_GIVEN.search(text):
        return None
    match = _NUMBER.search(text.replace("$", ""))
    return Decimal(match.group(0).replace(",", "")) if match else None


def parse_labels(trader_text: str, pm_text: str) -> Labels:
    found: dict[str, str] = {}
    for text in (trader_text or "", pm_text or ""):
        for label, value in _LABEL.findall(text):
            found.setdefault(label, value.strip().strip("*").strip())
    rating = found.get("Rating")
    return Labels(
        rating=rating.split()[0].strip("*.,") if rating else None,
        entry=_price(found.get("Entry Price")),
        stop=_price(found.get("Stop Loss")),
        target=_price(found.get("Price Target")),
        sizing_text=None
        if _NOT_GIVEN.search(found.get("Position Sizing", "n/a"))
        else found.get("Position Sizing"),
        horizon=None
        if _NOT_GIVEN.search(found.get("Time Horizon", "n/a"))
        else found.get("Time Horizon"),
    )


def sizing_multiplier(text: str | None) -> Decimal | None:
    """'표준 배분의 0.25~0.5배' → 0.25 (the cautious end). Percent targets are not multipliers."""
    if not text:
        return None
    match = _MULTIPLIER.search(text)
    return Decimal(match.group(1)) if match else None


@dataclass(frozen=True)
class Bar:
    at: datetime
    high: Decimal
    low: Decimal
    close: Decimal


def daily_bars(snapshots: list[MarketSnapshot]) -> list[Bar]:
    bars = []
    for s in snapshots:
        if s.kind != "price_bar":
            continue
        p = s.payload
        try:
            bars.append(
                Bar(
                    s.available_at,
                    Decimal(str(p["high"])),
                    Decimal(str(p["low"])),
                    Decimal(str(p["close"])),
                )
            )
        except (KeyError, ArithmeticError, ValueError):
            continue
    return sorted(bars, key=lambda b: b.at)


def atr(bars: list[Bar], period: int = 14) -> Decimal | None:
    """Average true range over the last `period` bars (simple mean); None without enough bars."""
    if len(bars) < period + 1:
        return None
    trs = []
    for prev, cur in zip(bars[-period - 1 : -1], bars[-period:], strict=True):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(trs, Decimal(0)) / period


def krx_tick(price: Decimal) -> Decimal:
    """KRX price tick by level (unified KOSPI/KOSDAQ table)."""
    for limit, tick in (
        (2_000, 1),
        (5_000, 5),
        (20_000, 10),
        (50_000, 50),
        (200_000, 100),
        (500_000, 500),
    ):
        if price < limit:
            return Decimal(tick)
    return Decimal(1_000)


def round_price(price: Decimal, market: Market) -> Decimal:
    step = krx_tick(price) if market is Market.KR else Decimal("0.01")
    return (price / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step


@dataclass
class PlanDraft:
    limit: Decimal
    stop: Decimal
    target: Decimal
    sources: dict[str, Source]
    ref_price: Decimal
    ref_at: datetime
    atr: Decimal | None
    multiplier: Decimal
    multiplier_source: Source
    rating: str | None
    sizing_text: str | None
    horizon: str | None
    review_reasons: list[str] = field(default_factory=list)

    @property
    def stop_distance(self) -> Decimal:
        return (self.limit - self.stop) / self.limit


def build_buy_plan(
    labels: Labels, bars: list[Bar], market: Market, default_multiplier: Decimal = Decimal("0.5")
) -> PlanDraft | None:
    """Entry limit, stop and target for a BUY. None when there is no price data at all."""
    if not bars:
        return None
    ref = bars[-1]
    vol = atr(bars)
    sources: dict[str, Source] = {}
    if labels.entry is not None:
        limit, sources["limit"] = labels.entry, "ai"
    else:
        limit, sources["limit"] = ref.close * LIMIT_MARKUP, "policy"
    limit = round_price(limit, market)
    if labels.stop is not None:
        stop, sources["stop"] = labels.stop, "ai"
    else:
        distance = (ATR_STOP_MULT * vol / limit) if vol else FALLBACK_STOP
        distance = min(max(distance, STOP_MIN), STOP_MAX)
        stop, sources["stop"] = limit * (1 - distance), "policy"
    stop = round_price(stop, market)
    if labels.target is not None:
        target, sources["target"] = labels.target, "ai"
    else:
        target, sources["target"] = limit + REWARD_RISK * (limit - stop), "policy"
    target = round_price(target, market)
    mult = sizing_multiplier(labels.sizing_text)
    draft = PlanDraft(
        limit=limit,
        stop=stop,
        target=target,
        sources=sources,
        ref_price=ref.close,
        ref_at=ref.at,
        atr=vol,
        multiplier=mult if mult is not None else default_multiplier,
        multiplier_source="ai" if mult is not None else "policy",
        rating=labels.rating,
        sizing_text=labels.sizing_text,
        horizon=labels.horizon,
    )
    draft.review_reasons = validate(draft)
    return draft


def validate(d: PlanDraft) -> list[str]:
    reasons = []
    if abs(d.limit / d.ref_price - 1) > MAX_ENTRY_DEVIATION:
        reasons.append(f"진입가가 최근 종가와 {MAX_ENTRY_DEVIATION:.0%} 넘게 차이 남")
    if not d.stop < d.limit < d.target:
        reasons.append("가격 순서가 맞지 않음 (손절가 < 진입가 < 목표가)")
    elif not STOP_DISTANCE_RANGE[0] <= d.stop_distance <= STOP_DISTANCE_RANGE[1]:
        reasons.append("손절 폭이 1~25% 범위를 벗어남")
    if d.multiplier <= 0 or d.multiplier > 2:
        reasons.append("AI가 제시한 비중 배수가 비정상적임")
    return reasons
