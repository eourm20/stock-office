"""Trading cost assumptions of the paper book. Labelled as assumptions everywhere they are shown.

Values approximate what the owner pays in their own apps (2026-10); they are settings, not facts.
The book's cash is KRW only: a USD trade converts at the day's USD/KRW rate plus a spread.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Costs:
    kr_commission: Decimal = Decimal("0.00015")  # 0.015% each side
    kr_sell_tax: Decimal = Decimal("0.0020")  # securities transaction tax on KRX sells
    us_commission: Decimal = Decimal("0.001")  # 0.1% each side
    fx_spread: Decimal = Decimal("0.0025")  # KRW↔USD conversion, each way
    slippage: Decimal = Decimal("0.0005")  # stop and at-open exits fill this much worse

    def commission(self, currency: str) -> Decimal:
        return self.kr_commission if currency == "KRW" else self.us_commission

    def sell_tax(self, currency: str) -> Decimal:
        return self.kr_sell_tax if currency == "KRW" else Decimal(0)

    def describe(self) -> list[dict[str, str]]:
        def pct(x: Decimal) -> str:
            return f"{format((x * 100).normalize(), 'f')}%"

        return [
            {"label": "국내 수수료 (매수·매도 각각)", "value": pct(self.kr_commission)},
            {"label": "국내 매도 세금", "value": pct(self.kr_sell_tax)},
            {"label": "미국 수수료 (매수·매도 각각)", "value": pct(self.us_commission)},
            {"label": "환전 스프레드 (원↔달러 각각)", "value": pct(self.fx_spread)},
            {"label": "손절·시가 청산 미끄러짐", "value": pct(self.slippage)},
        ]


COSTS = Costs()
