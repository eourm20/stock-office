"""Run lifecycle: create (API) and execute (worker). No order or account code exists here."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, Literal
from zoneinfo import ZoneInfo

from stock_office.domain.instruments import get_instrument
from stock_office.domain.models import (
    AnalysisRun,
    CreateRunRequest,
    DecisionAction,
    EngineName,
    EventType,
    InvestmentDecision,
    MarketSnapshot,
    RunStatus,
)
from stock_office.engine.adapter import (
    AnalysisEngine,
    EngineContext,
    EngineNotConfiguredError,
    EngineOutcome,
    rating_to_action,
)
from stock_office.events.sanitize import redact_text
from stock_office.providers.base import (
    MarketDataProvider,
    ProviderError,
    enforce_point_in_time,
)

from .repository import RunRepository

EngineFactory = Callable[[EngineName], AnalysisEngine]
ProviderFactory = Callable[[EngineName], Sequence[MarketDataProvider]]

_CLOCK_SKEW = timedelta(minutes=1)


class FutureAsOfError(ValueError):
    pass


class BudgetExceededError(RuntimeError):
    """Too many paid (real-engine) runs in the last 24 hours."""


def _excerpts(text: str, limit: int = 400) -> list[str]:
    return [redact_text(text, limit=limit)] if text.strip() else []


class RunService:
    def __init__(
        self,
        repo: RunRepository,
        engines: EngineFactory,
        providers: ProviderFactory,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_paid_runs_per_day: int | None = None,
    ) -> None:
        self.repo = repo
        self.engines = engines
        self.providers = providers
        self.clock = clock
        self.max_paid_runs_per_day = max_paid_runs_per_day

    # ---------------------------------------------------------------- API side
    def paid_runs_last_24h(self) -> int:
        since = self.clock() - timedelta(hours=24)
        return sum(1 for r in self.repo.list_runs() if not r.demo and r.requested_at >= since)

    def create_run(self, request: CreateRunRequest, *,
                   trigger: Literal["manual", "schedule"] = "manual",
                   schedule_slot: str | None = None) -> AnalysisRun:
        instrument = get_instrument(request.instrument_id)
        now = self.clock()
        as_of = request.as_of or now
        if as_of.tzinfo is None:
            raise FutureAsOfError("as_of must be timezone-aware")
        if as_of > now + _CLOCK_SKEW:
            raise FutureAsOfError("as_of cannot be in the future (look-ahead is not allowed)")
        engine = self.engines(request.engine)
        limit = self.max_paid_runs_per_day
        if not engine.demo and limit is not None and self.paid_runs_last_24h() >= limit:
            raise BudgetExceededError(
                f"paid run limit reached ({self.max_paid_runs_per_day} per 24 h); "
                "raise STOCK_OFFICE_MAX_PAID_RUNS_PER_DAY to allow more")
        run = AnalysisRun(
            id=uuid.uuid4().hex[:16],
            instrument_id=instrument.id,
            requested_at=now,
            as_of=as_of.astimezone(UTC),
            engine=request.engine,
            status=RunStatus.QUEUED,
            engine_version=engine.version(),
            config_hash=engine.config_hash(),
            demo=engine.demo,
            trigger=trigger,
            schedule_slot=schedule_slot,
        )
        self.repo.save_run(run)
        self._emit(run, EventType.RUN_CREATED, payload={
            "instrument_id": run.instrument_id, "as_of": run.as_of.isoformat(),
            "engine": run.engine, "engine_version": run.engine_version, "trigger": trigger,
        }, dedupe_key="run.created")
        return run

    # ------------------------------------------------------------- worker side
    def _emit(self, run: AnalysisRun, type: EventType, *, agent_id: str | None = None,
              payload: dict[str, Any] | None = None, dedupe_key: str | None = None) -> object:
        body = {**(payload or {}), "demo": run.demo}
        return self.repo.events.append(run.id, type, agent_id=agent_id, payload=body,
                                       dedupe_key=dedupe_key)

    def execute(self, run_id: str) -> AnalysisRun:
        run = self.repo.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status is not RunStatus.QUEUED or not self.repo.claim(run_id):
            return run  # idempotent: someone else owns/finished it

        instrument = get_instrument(run.instrument_id)
        trade_date = run.as_of.astimezone(ZoneInfo(instrument.timezone)).date().isoformat()
        engine = self.engines(run.engine)
        started = time.perf_counter()
        run.status, run.started_at = RunStatus.RUNNING, self.clock()
        self.repo.save_run(run)
        self._emit(run, EventType.RUN_STARTED, payload={
            "trade_date": trade_date, "exchange_timezone": instrument.timezone,
            "engine_version": run.engine_version, "config_hash": run.config_hash,
            "model_version": engine.model_version(),
        }, dedupe_key="run.started")

        def finish(status: RunStatus, code: str | None = None, message: str | None = None) -> None:
            run.status, run.completed_at = status, self.clock()
            run.latency_ms = int((time.perf_counter() - started) * 1000)
            run.error_code, run.error_message = code, message
            self.repo.save_run(run)
            completed = status is RunStatus.COMPLETED
            event = EventType.RUN_COMPLETED if completed else EventType.RUN_FAILED
            self._emit(run, event, payload={"status": status.value, "error_code": code,
                                            "latency_ms": run.latency_ms}, dedupe_key="run.end")

        try:
            engine.check_ready()
            snapshots = self._collect(run, instrument, engine)
            if not snapshots:
                self._decide(run, engine, None, snapshots, forced_flags=["INSUFFICIENT_DATA"])
                finish(RunStatus.INSUFFICIENT_DATA, "INSUFFICIENT_DATA",
                       "no point-in-time data available; analysis blocked")
                return run
            outcome = engine.run(EngineContext(
                run_id=run.id, instrument=instrument, as_of=run.as_of, trade_date=trade_date,
                snapshots=snapshots, sink=partial(self._emit, run),
                work_dir=self.repo.root / run.id,
            ))
            run.token_usage = outcome.token_usage
            run.coverage_gaps = [*run.coverage_gaps, *outcome.coverage_gaps]
            self.repo.save_outputs(run.id, outcome.results)
            if outcome.reports:
                self.repo.write_json(run.id, "reports.json", outcome.reports)
            self._decide(run, engine, outcome, snapshots)
            finish(RunStatus.COMPLETED)
        except EngineNotConfiguredError as exc:
            finish(RunStatus.FAILED, EngineNotConfiguredError.code, str(exc))
        except ProviderError as exc:
            finish(RunStatus.FAILED, exc.code, redact_text(str(exc), limit=300))
        except Exception as exc:
            finish(RunStatus.FAILED, "ENGINE_ERROR", redact_text(type(exc).__name__, limit=300))
        return run

    def _collect(self, run: AnalysisRun, instrument: Any, engine: AnalysisEngine
                 ) -> list[MarketSnapshot]:
        agent = "data_collector"
        self._emit(run, EventType.AGENT_STARTED, agent_id=agent,
                   payload={"role": "Data Collection", "phase": "data"}, dedupe_key="collect:start")
        collected: list[MarketSnapshot] = []
        gaps: list[str] = []
        sources: list[str] = []
        for provider in self.providers(run.engine):
            if not provider.supports(instrument):
                # Not applicable (e.g. OpenDART for a US stock) is not a data gap. If no provider
                # applies, the run still ends INSUFFICIENT_DATA below.
                continue
            try:
                result = provider.fetch(instrument, run.as_of)
            except ProviderError as exc:
                gaps.append(f"{provider.name}: {exc.code}")
                continue
            sources.append(provider.name)
            collected.extend(result.snapshots)
            gaps.extend(result.coverage_gaps)
        pit = enforce_point_in_time(collected, run.as_of)
        for snap in pit.allowed:
            self.repo.save_snapshot(run.id, snap)
        run.snapshot_ids = [s.id for s in pit.allowed]
        run.coverage_gaps = gaps
        self.repo.save_run(run)
        self._emit(run, EventType.AGENT_COMPLETED, agent_id=agent, payload={
            "role": "Data Collection", "sources": sources, "snapshot_count": len(pit.allowed),
            "excluded_future_snapshots": [s.id for s in pit.rejected], "coverage_gaps": gaps,
        }, dedupe_key="collect:end")
        return pit.allowed

    def _decide(self, run: AnalysisRun, engine: AnalysisEngine, outcome: EngineOutcome | None,
                snapshots: list[MarketSnapshot], forced_flags: list[str] | None = None) -> None:
        flags = list(forced_flags or [])
        action = rating_to_action(outcome.rating if outcome else None)
        if outcome and action is DecisionAction.REVIEW:
            flags.append("UNPARSEABLE_OR_REVIEW_RATING")
        if not snapshots:
            flags.append("NO_GROUNDED_EVIDENCE")
            action = DecisionAction.REVIEW
        if run.coverage_gaps:
            flags.append("COVERAGE_GAP")
        if outcome:
            flags.extend(w.split(":", 1)[0] for w in outcome.warnings)
        if run.demo:
            flags.append("DEMO_NOT_ANALYSIS")
        decision = InvestmentDecision(
            run_id=run.id,
            action=action,
            engine_rating=outcome.rating if outcome else None,
            rationale=redact_text(outcome.final_report, limit=2000) if outcome
            else "Blocked: no point-in-time data was available for this run.",
            counterarguments=(_excerpts(outcome.bear_case) + _excerpts(outcome.risk_case))
            if outcome else [],
            risk_flags=sorted(set(flags)),
            evidence_snapshot_ids=[s.id for s in snapshots],
            model_version=engine.model_version(),
            created_at=self.clock(),
            demo=run.demo,
        )
        self.repo.save_decision(decision)
        self._emit(run, EventType.DECISION_CREATED, agent_id="portfolio_manager", payload={
            "action": decision.action.value, "engine_rating": decision.engine_rating,
            "risk_flags": decision.risk_flags, "execution": decision.execution,
            "evidence_count": len(decision.evidence_snapshot_ids),
        }, dedupe_key="decision.created")
