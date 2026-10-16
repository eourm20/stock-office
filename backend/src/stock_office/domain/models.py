"""Normalized Stock Office contracts shared by API, storage and engine adapters."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value


class Market(StrEnum):
    US = "US"
    KR = "KR"


class Currency(StrEnum):
    USD = "USD"
    KRW = "KRW"


class Instrument(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(description="COUNTRY:EXCHANGE:SYMBOL, e.g. US:NASDAQ:NVDA")
    market: Market
    exchange: str
    symbol: str
    name: str
    currency: Currency
    timezone: str
    provider_symbols: dict[str, str] = Field(default_factory=dict)


class MarketSnapshot(BaseModel):
    """One immutable piece of source data with explicit point-in-time stamps."""

    id: str
    instrument_id: str
    source: str
    kind: Literal["price_bar", "quote", "disclosure", "news", "fundamentals"]
    observed_at: datetime = Field(description="when the fact happened at the source")
    available_at: datetime = Field(description="when the fact became public/usable")
    ingested_at: datetime = Field(description="when Stock Office stored it")
    currency: Currency | None = None
    payload: dict[str, Any]
    payload_hash: str
    source_url: str | None = None
    demo: bool = False

    _utc = field_validator("observed_at", "available_at", "ingested_at")(_require_utc)

    @model_validator(mode="after")
    def _ordering(self) -> MarketSnapshot:
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot precede observed_at")
        return self


class Price(BaseModel):
    """Money is Decimal with an explicit currency."""

    amount: Decimal
    currency: Currency


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


TERMINAL_RUN_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.INSUFFICIENT_DATA}
)


class AgentStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"


class Finding(BaseModel):
    claim: str
    polarity: Literal["bullish", "bearish", "neutral"]
    evidence_snapshot_ids: list[str] = Field(default_factory=list)


class AgentResult(BaseModel):
    run_id: str
    agent_id: str
    role: str
    status: AgentStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    structured_output: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class DecisionAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    REVIEW = "REVIEW"


class InvestmentDecision(BaseModel):
    """A *proposal*. Never an order. `confidence` is model self-assessment, not a probability."""

    run_id: str
    action: DecisionAction
    engine_rating: str | None = Field(None, description="raw upstream rating, e.g. Overweight")
    proposed_weight_pct: Decimal | None = None
    confidence: Decimal | None = None
    rationale: str
    counterarguments: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    evidence_snapshot_ids: list[str] = Field(default_factory=list)
    model_version: str
    created_at: datetime
    demo: bool = False
    execution: Literal["PROPOSED_ONLY"] = "PROPOSED_ONLY"


class EventType(StrEnum):
    RUN_CREATED = "run.created"
    RUN_STARTED = "run.started"
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    DEBATE_MESSAGE = "debate.message"
    DECISION_CREATED = "decision.created"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"


TERMINAL_EVENT_TYPES = frozenset({EventType.RUN_COMPLETED, EventType.RUN_FAILED})


class RunEvent(BaseModel):
    event_id: str
    run_id: str
    seq: int = Field(ge=1)
    type: EventType
    agent_id: str | None = None
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    _utc = field_validator("occurred_at")(_require_utc)


EngineName = Literal["demo", "tradingagents"]


class AnalysisRun(BaseModel):
    id: str
    instrument_id: str
    requested_at: datetime
    as_of: datetime
    engine: EngineName
    status: RunStatus
    engine_version: str
    config_hash: str
    demo: bool
    started_at: datetime | None = None
    completed_at: datetime | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    snapshot_ids: list[str] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)
    token_usage: dict[str, Any] | None = None


class CreateRunRequest(BaseModel):
    instrument_id: str
    as_of: datetime | None = None
    engine: EngineName = "demo"


class CreateRunResponse(BaseModel):
    run_id: str
    status: RunStatus
