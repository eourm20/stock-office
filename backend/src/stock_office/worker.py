"""Background worker. Long runs never execute inside an HTTP request.

    python -m stock_office.worker              # poll the queue forever
    python -m stock_office.worker --once       # drain the queue and exit
    python -m stock_office.worker --schedule   # also run the daily schedule (needs
                                               # STOCK_OFFICE_SCHEDULE_ENABLED=true)
"""

from __future__ import annotations

import argparse
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from stock_office.config import Settings, get_settings
from stock_office.db import connect
from stock_office.domain.models import AnalysisRun, CreateRunRequest
from stock_office.engine.adapter import EngineNotConfiguredError
from stock_office.logging_setup import install_log_redaction
from stock_office.notify import Notifier, build_notifier
from stock_office.runs.service import BudgetExceededError, RunService
from stock_office.schedule import DEFAULT_RULES, ScheduleRule, due_slots, next_slots
from stock_office.wiring import build_service, build_settler

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


def schedule_tick(service: RunService, now: datetime, notifier: Notifier | None = None,
                  rules: tuple[ScheduleRule, ...] = DEFAULT_RULES) -> list[AnalysisRun]:
    """Start every due scheduled analysis once (real engine), then execute it."""
    done = {r.schedule_slot for r in service.repo.list_runs()
            if r.trigger == "schedule" and r.schedule_slot}
    started: list[AnalysisRun] = []
    slots = due_slots(now, done, rules)
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
            if notifier is not None:
                notifier.budget_skipped(slot.key, slot.rule.instrument_id, now)
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
    settler = build_settler(service.inbox) if scheduling and service.inbox else None
    notifier = (build_notifier(settings, service.inbox.conn, service.repo)
                if scheduling and service.inbox else None)
    if notifier is not None:
        threading.Thread(target=notify_loop, args=(settings, service.repo, clock), daemon=True,
                         name="notify").start()
    team = None
    if scheduling and service.inbox is not None:
        from stock_office.research.team import build_team

        team = build_team(settings, service.inbox.conn, service.repo)
    if scheduling:
        threading.Thread(target=desk_loop, args=(settings, clock), daemon=True,
                         name="kiwoom-mock-desks").start()
    last_tick = 0.0
    while True:
        drain(service)
        if service.inbox is not None:
            service.inbox.expire_due(clock())
        if scheduling and time.monotonic() - last_tick >= 60:
            last_tick = time.monotonic()
            schedule_tick(service, clock(), notifier)
            if team is not None:
                research_tick(team, service, clock(), notifier)
            if settler is not None:
                for result in settler.tick(clock()):
                    log.info("settle %s %s -> %s (%d fills) %s", result.market, result.session,
                             result.status, result.fills, result.note)
        if args.once:
            return
        time.sleep(args.interval)


def research_tick(team: Any, service: RunService, now: datetime,
                  notifier: Notifier | None = None) -> None:
    """Each market's research once per target session, then its focus meetings, in order."""
    from stock_office.research.team import window

    for market in ("KR", "US"):
        try:
            win = window(market, now)
            if win is None or team.done(market, win[0]):
                continue
            day = win[0]
            focus = team.research(market, day, now)
        except Exception:
            log.exception("research %s failed", market)
            continue
        for iid in focus:
            slot = f"research:{iid}@{day}"
            try:
                run = service.create_run(
                    CreateRunRequest(instrument_id=iid, engine="tradingagents"),
                    trigger="schedule", schedule_slot=slot)
            except BudgetExceededError as exc:
                log.warning("research meeting %s skipped: %s", slot, exc)
                if notifier is not None:
                    notifier.budget_skipped(slot, iid, now)
                continue
            log.info("research %s -> run %s", slot, run.id)
            service.execute(run.id)


def desk_loop(settings: Settings, clock: Callable[[], datetime], every_s: float = 30.0) -> None:
    """Kiwoom mock desks on their own thread and connection: place approved orders during each
    market's regular session, read fills, cancel at deadlines, watch stops/targets, and record
    each closed session's account value. Meetings never wait for it, nor it for them."""
    from stock_office.kiwoom_mock.desks import build_desks

    desks = build_desks(settings, connect(settings.data_dir))
    while True:
        now = clock()
        desks.tick(now)
        desks.record_nav(now)
        time.sleep(every_s)


def notify_loop(settings: Settings, repo: object, clock: Callable[[], datetime],
                every_s: float = 20.0) -> None:
    """Phone notifications on their own thread and connection: a meeting runs for minutes inside
    the main loop, and "meeting started" must not wait for it to end."""
    notifier = build_notifier(settings, connect(settings.data_dir), repo)
    while True:
        notifier.tick(clock())
        time.sleep(every_s)


if __name__ == "__main__":
    main()
