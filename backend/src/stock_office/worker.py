"""Background worker. Long runs never execute inside an HTTP request.

    python -m stock_office.worker              # poll the queue forever
    python -m stock_office.worker --once       # drain the queue and exit
    python -m stock_office.worker --schedule   # also run the daily schedule (needs
                                               # STOCK_OFFICE_SCHEDULE_ENABLED=true)
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from stock_office.config import get_settings
from stock_office.domain.models import AnalysisRun, CreateRunRequest
from stock_office.engine.adapter import EngineNotConfiguredError
from stock_office.logging_setup import install_log_redaction
from stock_office.runs.service import BudgetExceededError, RunService
from stock_office.schedule import due_slots, next_slots
from stock_office.wiring import build_service

log = logging.getLogger("stock_office.worker")


class ThreadDispatcher:
    """In-process dispatcher for dev: one background thread executes runs in FIFO order."""

    def __init__(self, service: RunService) -> None:
        self.service = service
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="run-worker")

    def submit(self, run_id: str) -> None:
        self.pool.submit(self.service.execute, run_id)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=True)


def drain(service: RunService) -> int:
    count = 0
    for run_id in service.repo.queued_run_ids():
        run = service.execute(run_id)
        log.info("run %s -> %s", run.id, run.status.value)
        count += 1
    return count


def schedule_tick(service: RunService, now: datetime) -> list[AnalysisRun]:
    """Start every due scheduled analysis once (real engine), then execute it."""
    done = {r.schedule_slot for r in service.repo.list_runs()
            if r.trigger == "schedule" and r.schedule_slot}
    started: list[AnalysisRun] = []
    slots = due_slots(now, done)
    if not slots:
        return started
    try:
        # Not ready (no key / package): skip without burning the slot, so it runs once fixed.
        service.engines("tradingagents").check_ready()
    except EngineNotConfiguredError as exc:
        log.warning("schedule waiting, engine not ready: %s", exc)
        return started
    for slot in slots:
        try:
            run = service.create_run(
                CreateRunRequest(instrument_id=slot.rule.instrument_id, engine="tradingagents"),
                trigger="schedule", schedule_slot=slot.key)
        except BudgetExceededError as exc:
            log.warning("schedule %s skipped: %s", slot.key, exc)
            continue
        log.info("schedule %s -> run %s", slot.key, run.id)
        started.append(service.execute(run.id))
    return started


def main(clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--schedule", action="store_true")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    install_log_redaction()
    settings = get_settings()
    service = build_service(settings)
    scheduling = args.schedule and settings.schedule_enabled
    if args.schedule and not settings.schedule_enabled:
        log.warning("--schedule given but STOCK_OFFICE_SCHEDULE_ENABLED is false: queue only")
    if scheduling:
        for s in next_slots(clock()):
            log.info("next scheduled: %s at %s", s.key, s.scheduled_at.isoformat())
    last_tick = 0.0
    while True:
        drain(service)
        if scheduling and time.monotonic() - last_tick >= 60:
            last_tick = time.monotonic()
            schedule_tick(service, clock())
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
