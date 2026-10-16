"""Office summary: per instrument, the latest real decision and any run in progress."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from stock_office.domain.instruments import REGISTRY
from stock_office.domain.models import DecisionAction, RunStatus

from .repository import RunRepository

_ACTIVE = {RunStatus.QUEUED, RunStatus.RUNNING}


class LatestDecision(BaseModel):
    run_id: str
    action: DecisionAction
    engine_rating: str | None
    decided_at: datetime
    risk_flags: list[str]


class InstrumentSummary(BaseModel):
    instrument_id: str
    name: str
    latest: LatestDecision | None
    """Most recent decision from the real engine. DEMO runs never count as decisions."""
    active_run_id: str | None
    """A queued or running run of any engine, newest first."""
    active_status: RunStatus | None


class OfficeSummary(BaseModel):
    instruments: list[InstrumentSummary]


def build_summary(repo: RunRepository) -> OfficeSummary:
    runs = repo.list_runs()  # newest first
    items = []
    for inst in REGISTRY.values():
        mine = [r for r in runs if r.instrument_id == inst.id]
        active = next((r for r in mine if r.status in _ACTIVE), None)
        latest = None
        for r in mine:
            if r.demo or r.status is not RunStatus.COMPLETED:
                continue
            decision = repo.get_decision(r.id)
            if decision is not None:
                latest = LatestDecision(run_id=r.id, action=decision.action,
                                        engine_rating=decision.engine_rating,
                                        decided_at=decision.created_at,
                                        risk_flags=decision.risk_flags)
                break
        items.append(InstrumentSummary(
            instrument_id=inst.id, name=inst.name, latest=latest,
            active_run_id=active.id if active else None,
            active_status=active.status if active else None,
        ))
    return OfficeSummary(instruments=items)
