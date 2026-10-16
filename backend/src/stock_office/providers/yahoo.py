"""Read-only daily price bars from Yahoo Finance via `yfinance` (optional `live` extra).

This is the same public source TradingAgents v0.6.0 uses by default. It is unofficial and
unlicensed for redistribution: raw responses are stored only under the git-ignored data dir.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from stock_office.domain.models import Instrument, MarketSnapshot

from .base import ProviderError, ProviderResult, payload_hash, utcnow

# A daily bar is treated as available only after the exchange-local close + buffer.
_CLOSE = {"America/New_York": time(16, 0), "Asia/Seoul": time(15, 30)}
_AVAILABILITY_BUFFER = timedelta(minutes=30)


def bar_available_at(bar_date: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    local_close = datetime.combine(bar_date.date(), _CLOSE[tz_name], tzinfo=tz)
    return local_close + _AVAILABILITY_BUFFER


def _dec(value: Any) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.0001")))


class YahooPriceProvider:
    name = "yahoo-yfinance"

    def __init__(self, lookback_days: int = 30) -> None:
        self.lookback_days = lookback_days

    def supports(self, instrument: Instrument) -> bool:
        return "yahoo" in instrument.provider_symbols

    def fetch(self, instrument: Instrument, as_of: datetime) -> ProviderResult:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise ProviderError("PROVIDER_NOT_INSTALLED", "install the 'live' extra") from exc

        symbol = instrument.provider_symbols["yahoo"]
        local_as_of = as_of.astimezone(ZoneInfo(instrument.timezone))
        start = (local_as_of - timedelta(days=self.lookback_days)).date()
        end = (local_as_of + timedelta(days=1)).date()  # yfinance `end` is exclusive
        try:
            frame = yf.Ticker(symbol).history(
                start=start.isoformat(), end=end.isoformat(), interval="1d", auto_adjust=False
            )
        except Exception as exc:
            raise ProviderError("PROVIDER_REQUEST_FAILED", f"{type(exc).__name__}") from exc

        if frame is None or frame.empty:
            return ProviderResult(coverage_gaps=[f"{self.name}: no daily bars for {symbol}"])

        ingested = utcnow()
        snapshots: list[MarketSnapshot] = []
        for idx, row in frame.iterrows():
            bar_ts = idx.to_pydatetime()
            if bar_ts.tzinfo is None:
                bar_ts = bar_ts.replace(tzinfo=ZoneInfo(instrument.timezone))
            payload = {
                "provider_symbol": symbol,
                "date": bar_ts.date().isoformat(),
                "open": _dec(row["Open"]),
                "high": _dec(row["High"]),
                "low": _dec(row["Low"]),
                "close": _dec(row["Close"]),
                "volume": int(row["Volume"]),
            }
            observed = datetime.combine(
                bar_ts.date(), _CLOSE[instrument.timezone], tzinfo=ZoneInfo(instrument.timezone)
            )
            snapshots.append(
                MarketSnapshot(
                    id=f"yahoo-{instrument.symbol}-{payload['date']}",
                    instrument_id=instrument.id,
                    source=self.name,
                    kind="price_bar",
                    observed_at=observed,
                    available_at=bar_available_at(bar_ts, instrument.timezone),
                    ingested_at=ingested,
                    currency=instrument.currency,
                    payload=payload,
                    payload_hash=payload_hash(payload),
                    source_url=f"https://finance.yahoo.com/quote/{symbol}",
                )
            )
        return ProviderResult(snapshots=snapshots)
