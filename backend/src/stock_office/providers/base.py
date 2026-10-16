"""Read-only market data provider contract and point-in-time guard."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from stock_office.domain.models import Instrument, MarketSnapshot


class ProviderError(RuntimeError):
    """A provider could not serve data. `code` is stable and safe to show/store."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ProviderResult:
    snapshots: list[MarketSnapshot] = field(default_factory=list)
    coverage_gaps: list[str] = field(default_factory=list)


class MarketDataProvider(Protocol):
    name: str

    def supports(self, instrument: Instrument) -> bool: ...

    def fetch(self, instrument: Instrument, as_of: datetime) -> ProviderResult:
        """Return snapshots known by `as_of`. Must never place orders or write upstream."""
        ...


def payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class PointInTimeResult:
    allowed: list[MarketSnapshot]
    rejected: list[MarketSnapshot]


def enforce_point_in_time(snapshots: list[MarketSnapshot], as_of: datetime) -> PointInTimeResult:
    """Drop anything that was not available at `as_of` (no look-ahead into the future)."""
    allowed = [s for s in snapshots if s.available_at <= as_of]
    rejected = [s for s in snapshots if s.available_at > as_of]
    return PointInTimeResult(allowed=allowed, rejected=rejected)
