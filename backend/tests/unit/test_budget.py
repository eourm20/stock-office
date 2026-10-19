"""Monthly budget: cost from tokens, Korea calendar month, reservations, hard stop (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from stock_office.budget import (
    PENDING_RUN_ESTIMATE_USD,
    budget_status,
    can_start_paid_run,
    month_key,
    usage_cost,
)
from stock_office.domain.models import AnalysisRun, CreateRunRequest, RunStatus
from stock_office.runs.repository import RunRepository
from stock_office.runs.service import BudgetExceededError

# Real numbers of the scheduled NVDA run 7dcf0bb6 (sprint-2b): ≈ $0.048.
REAL_USAGE = {
    "gpt-6-luna": {"input_tokens": 83631, "output_tokens": 19919,
                   "input_token_details": {"cache_read": 15294}},
    "gpt-6-sol": {"input_tokens": 9333, "output_tokens": 1243,
                  "input_token_details": {"cache_read": 0}},
}


def test_usage_cost_matches_the_measured_run_and_never_undercounts_unknown_models() -> None:
    assert usage_cost(REAL_USAGE, {"gpt-6-luna": ("0.10", "0.01", "0.50"),
                                   "gpt-6-sol": ("2.00", "2.00", "10.00")}).quantize(
        Decimal("0.001")) == Decimal("0.048")
    unpriced: set[str] = set()
    cost = usage_cost({"new-model": {"input_tokens": 1_000_000, "output_tokens": 0}},
                      {"cheap": ("0.10", "0.01", "0.50"), "dear": ("2.00", "2.00", "10.00")},
                      unpriced)
    assert cost == Decimal("2.00") and unpriced == {"new-model"}     # priced as the dearest
    assert usage_cost(None, {}) == 0


def test_month_is_the_korean_calendar_month() -> None:
    assert month_key(datetime(2026, 10, 31, 15, 30, tzinfo=UTC)) == "2026-11"   # 00:30 KST
    assert month_key(datetime(2026, 10, 31, 14, 59, tzinfo=UTC)) == "2026-10"


def _run(repo: RunRepository, rid: str, at: datetime, status: RunStatus, demo: bool = False,
         usage: dict[str, object] | None = None) -> None:
    repo.save_run(AnalysisRun(id=rid, instrument_id="US:NASDAQ:NVDA", requested_at=at, as_of=at,
                              engine="demo" if demo else "tradingagents", status=status,
                              demo=demo, engine_version="t", config_hash="t", token_usage=usage))


def test_status_counts_this_month_only_reserves_pending_and_ignores_demo(tmp_path: Path) -> None:
    repo = RunRepository(tmp_path)
    now = datetime(2026, 10, 19, 3, tzinfo=UTC)
    _run(repo, "a", datetime(2026, 10, 2, tzinfo=UTC), RunStatus.COMPLETED, usage=REAL_USAGE)
    _run(repo, "b", datetime(2026, 9, 30, tzinfo=UTC), RunStatus.COMPLETED, usage=REAL_USAGE)
    _run(repo, "c", datetime(2026, 10, 19, 2, tzinfo=UTC), RunStatus.RUNNING)
    _run(repo, "d", datetime(2026, 10, 19, 2, tzinfo=UTC), RunStatus.COMPLETED, demo=True,
         usage=REAL_USAGE)
    repo.write_json("a", "briefing.json", {"token_usage": {"gpt-6-luna": {
        "input_tokens": 8751, "output_tokens": 1111}}})
    s = budget_status(repo, now, Decimal("7"))
    assert s.month == "2026-10" and s.paid_runs == 2
    assert s.spent_usd == Decimal("0.0495")              # run a + its briefing
    assert s.reserved_usd == PENDING_RUN_ESTIMATE_USD     # run c
    assert s.remaining_usd == Decimal("7") - s.spent_usd - s.reserved_usd
    assert can_start_paid_run(s)
    tight = budget_status(repo, now, Decimal("0.10"))
    assert not can_start_paid_run(tight)


def test_service_refuses_a_paid_run_over_budget_but_allows_demo(
        tmp_path: Path, make_service: object) -> None:
    from collections.abc import Callable
    from typing import cast

    from stock_office.runs.service import RunService

    service = cast(Callable[..., RunService], make_service)()
    service.monthly_budget_usd = Decimal("0.05")
    _run(service.repo, "x", service.clock(), RunStatus.COMPLETED, usage=REAL_USAGE)
    with pytest.raises(BudgetExceededError, match="monthly budget"):
        service.create_run(CreateRunRequest(instrument_id="US:NASDAQ:NVDA",
                                            engine="tradingagents"))
    assert service.create_run(CreateRunRequest(instrument_id="US:NASDAQ:NVDA",
                                               engine="demo")).demo is True
