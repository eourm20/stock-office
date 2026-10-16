"""Daily analysis schedule on real exchange calendars (weekends and holidays skipped).

- US (NYSE calendar): after the close, 17:00 New York time, for that session.
- KR (KRX calendar): before the open, 07:30 Seoul time, for that day's session. Evening DART
  filings from the previous day and the overnight US move are then known.

A slot runs at most once (no automatic retries; failures are reported, not repeated). A slot
missed while the worker was down still runs if the worker comes back before the deadline (the
next open), never after it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

import exchange_calendars as xcals


@dataclass(frozen=True)
class ScheduleRule:
    instrument_id: str
    calendar: str
    timezone: str
    at: time
    anchor: Literal["after_close", "before_open"]


DEFAULT_RULES: tuple[ScheduleRule, ...] = (
    ScheduleRule("US:NASDAQ:NVDA", "XNYS", "America/New_York", time(17, 0), "after_close"),
    ScheduleRule("KR:KRX:005930", "XKRX", "Asia/Seoul", time(7, 30), "before_open"),
)


@dataclass(frozen=True)
class DueSlot:
    rule: ScheduleRule
    session: date
    key: str            # "<instrument_id>@<session date>", unique per scheduled analysis
    scheduled_at: datetime
    deadline: datetime


@lru_cache(maxsize=8)
def _calendar(code: str) -> xcals.ExchangeCalendar:
    return xcals.get_calendar(code)


def slot_key(instrument_id: str, session: date) -> str:
    return f"{instrument_id}@{session.isoformat()}"


def _slot_for(rule: ScheduleRule, now: datetime) -> DueSlot | None:
    cal = _calendar(rule.calendar)
    tz = ZoneInfo(rule.timezone)
    today = now.astimezone(tz).date()
    if rule.anchor == "after_close":
        # The latest session on or before today; runs until the next session opens.
        day = today
        for _ in range(10):
            if cal.is_session(day.isoformat()):
                break
            day -= timedelta(days=1)
        else:
            return None
        deadline = cal.session_open(cal.next_session(day.isoformat())).to_pydatetime()
    else:
        if not cal.is_session(today.isoformat()):
            return None
        day = today
        deadline = cal.session_open(day.isoformat()).to_pydatetime()
    scheduled_at = datetime.combine(day, rule.at, tzinfo=tz)
    return DueSlot(rule, day, slot_key(rule.instrument_id, day), scheduled_at, deadline)


def due_slots(now: datetime, done: set[str],
              rules: tuple[ScheduleRule, ...] = DEFAULT_RULES) -> list[DueSlot]:
    """Slots whose time has come, whose deadline has not passed, and that never ran."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    due = []
    for rule in rules:
        slot = _slot_for(rule, now)
        if slot and slot.scheduled_at <= now < slot.deadline and slot.key not in done:
            due.append(slot)
    return due


def next_slots(now: datetime, rules: tuple[ScheduleRule, ...] = DEFAULT_RULES,
               horizon_days: int = 10) -> list[DueSlot]:
    """Upcoming slot per rule (for display/logging)."""
    out = []
    for rule in rules:
        probe = now
        for _ in range(horizon_days * 24):
            slot = _slot_for(rule, probe)
            if slot and slot.scheduled_at > now:
                out.append(slot)
                break
            probe += timedelta(hours=1)
    return out
