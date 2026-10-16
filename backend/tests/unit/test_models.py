from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from stock_office.config import Settings
from stock_office.domain.models import (
    DecisionAction,
    EventType,
    InvestmentDecision,
    MarketSnapshot,
    RunEvent,
)


def _snap(**kw: object) -> MarketSnapshot:
    base: dict[str, object] = dict(
        id="s1", instrument_id="US:NASDAQ:NVDA", source="t", kind="price_bar",
        observed_at="2026-10-15T20:00:00Z", available_at="2026-10-15T20:30:00Z",
        ingested_at="2026-10-16T00:00:00Z", payload={"close": "1"}, payload_hash="h",
    )
    base.update(kw)
    return MarketSnapshot.model_validate(base)


def test_snapshot_requires_timezone() -> None:
    with pytest.raises(ValidationError):
        _snap(observed_at="2026-10-15T20:00:00")


def test_snapshot_available_not_before_observed() -> None:
    with pytest.raises(ValidationError):
        _snap(available_at="2026-10-15T19:00:00Z")


def test_decision_is_proposal_with_decimal_money() -> None:
    d = InvestmentDecision(run_id="r", action=DecisionAction.HOLD, rationale="x",
                           model_version="m", created_at=datetime.now(UTC),
                           proposed_weight_pct=Decimal("2.50"))
    dumped = d.model_dump(mode="json")
    assert dumped["execution"] == "PROPOSED_ONLY"
    assert dumped["proposed_weight_pct"] == "2.50"  # Decimal serialized exactly, not float
    expected = {"run_id", "action", "proposed_weight_pct", "confidence", "rationale",
                "counterarguments", "risk_flags", "evidence_snapshot_ids", "model_version"}
    assert expected <= dumped.keys()


def test_event_seq_starts_at_one() -> None:
    with pytest.raises(ValidationError):
        RunEvent(event_id="e", run_id="r", seq=0, type=EventType.RUN_CREATED,
                 occurred_at=datetime.now(UTC))


def test_paper_only_cannot_be_disabled() -> None:
    with pytest.raises(ValidationError):
        Settings(paper_only=False, _env_file=None)  # type: ignore[call-arg]
