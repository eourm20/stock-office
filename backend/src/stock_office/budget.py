"""Monthly LLM budget: spend from stored token usage × a configurable price table, and a hard stop.

The month is the calendar month in Korea (the owner's time zone). Spend counts every real-engine
run of the month (its analysis tokens and its briefing tokens). Runs that are queued or running have
no token count yet, so each is reserved at `PENDING_RUN_ESTIMATE_USD`; this keeps several runs
started together from overshooting the budget. Prices change: they live in settings, not code.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from stock_office.domain.models import AnalysisRun, RunStatus
from stock_office.runs.repository import RunRepository

MONTH_TZ = ZoneInfo("Asia/Seoul")
PENDING_RUN_ESTIMATE_USD = Decimal("0.07")      # measured runs: $0.04–0.05 + briefing ~$0.002
MTOK = Decimal(1_000_000)

# USD per 1M tokens: (input, cached input, output). Same table as sprint-0-report §10.
DEFAULT_PRICES: dict[str, tuple[str, str, str]] = {
    "gpt-6-luna": ("0.10", "0.01", "0.50"),
    "gpt-6-sol": ("2.00", "2.00", "10.00"),
}


class BudgetStatus(BaseModel):
    month: str                  # "2026-10" (Korea time)
    budget_usd: Decimal
    spent_usd: Decimal          # finished runs, from tokens
    reserved_usd: Decimal       # queued/running runs, estimated
    remaining_usd: Decimal
    paid_runs: int
    unpriced_models: list[str]  # models missing from the price table (priced as the dearest)


def _prices(table: dict[str, tuple[str, str, str]]) -> dict[str, tuple[Decimal, Decimal, Decimal]]:
    return {m: (Decimal(a), Decimal(b), Decimal(c)) for m, (a, b, c) in table.items()}


def usage_cost(usage: dict[str, Any] | None, table: dict[str, tuple[str, str, str]],
               unpriced: set[str] | None = None) -> Decimal:
    """Cost of one LangChain usage_metadata dict ({model: {input_tokens, output_tokens, ...}})."""
    prices = _prices(table)
    dearest = max(prices.values(), key=lambda p: p[2]) if prices else (Decimal(0),) * 3
    total = Decimal(0)
    for model, u in (usage or {}).items():
        if not isinstance(u, dict):
            continue
        p = prices.get(model)
        if p is None:
            p = dearest                       # never under-count an unknown model
            if unpriced is not None:
                unpriced.add(model)
        inp = Decimal(int(u.get("input_tokens", 0) or 0))
        cached = Decimal(int((u.get("input_token_details") or {}).get("cache_read", 0) or 0))
        out = Decimal(int(u.get("output_tokens", 0) or 0))
        total += ((inp - cached) * p[0] + cached * p[1] + out * p[2]) / MTOK
    return total


def month_key(at: datetime) -> str:
    return at.astimezone(MONTH_TZ).strftime("%Y-%m")


def _q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def budget_status(repo: RunRepository, now: datetime, budget_usd: Decimal,
                  table: dict[str, tuple[str, str, str]] = DEFAULT_PRICES) -> BudgetStatus:
    month = month_key(now)
    spent = reserved = Decimal(0)
    unpriced: set[str] = set()
    runs: list[AnalysisRun] = [r for r in repo.list_runs()
                               if not r.demo and month_key(r.requested_at) == month]
    for run in runs:
        if run.status in (RunStatus.QUEUED, RunStatus.RUNNING):
            reserved += PENDING_RUN_ESTIMATE_USD
            continue
        spent += usage_cost(run.token_usage, table, unpriced)
        briefing = repo.get_briefing(run.id)
        if briefing:
            usage = briefing.get("token_usage")
            spent += usage_cost(usage if isinstance(usage, dict) else None, table, unpriced)
    return BudgetStatus(
        month=month, budget_usd=budget_usd, spent_usd=_q(spent), reserved_usd=_q(reserved),
        remaining_usd=_q(budget_usd - spent - reserved), paid_runs=len(runs),
        unpriced_models=sorted(unpriced),
    )


def can_start_paid_run(status: BudgetStatus) -> bool:
    """A new paid run may start only if its estimate still fits in this month's budget."""
    return status.remaining_usd >= PENDING_RUN_ESTIMATE_USD
