from datetime import UTC, date, datetime

import pytest

from stock_office.schedule import due_slots, next_slots, slot_key


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def keys(now: str, done: set[str] | None = None) -> list[str]:
    return [s.key for s in due_slots(at(now), done or set())]


def test_us_runs_after_close_and_catches_up_until_next_open() -> None:
    assert keys("2026-10-16T16:59:00-04:00") == []                         # before 17:00 ET
    assert "US:NASDAQ:NVDA@2026-10-16" in keys("2026-10-16T17:00:00-04:00")
    # Worker down Friday evening: still due over the weekend, until Monday's open.
    assert "US:NASDAQ:NVDA@2026-10-16" in keys("2026-10-18T12:00:00-04:00")
    assert "US:NASDAQ:NVDA@2026-10-16" not in keys("2026-10-19T09:31:00-04:00")


def test_us_holiday_has_no_new_slot() -> None:
    # Thanksgiving 2026-11-26: NYSE closed, so 17:00 that day still refers to Wednesday.
    due = keys("2026-11-26T17:30:00-05:00", done={"US:NASDAQ:NVDA@2026-11-25"})
    assert not any(k.startswith("US:") for k in due)


def test_kr_runs_before_open_only_on_trading_days() -> None:
    assert "KR:KRX:005930@2026-10-16" in keys("2026-10-16T07:30:00+09:00")
    assert not any(k.startswith("KR:") for k in keys("2026-10-16T07:29:00+09:00"))
    assert not any(k.startswith("KR:") for k in keys("2026-10-16T09:00:00+09:00"))  # opened
    assert not any(k.startswith("KR:") for k in keys("2026-10-09T08:00:00+09:00"))  # 한글날
    assert not any(k.startswith("KR:") for k in keys("2026-10-17T08:00:00+09:00"))  # Saturday


def test_a_slot_runs_once() -> None:
    now = "2026-10-16T08:00:00+09:00"
    assert "KR:KRX:005930@2026-10-16" in keys(now)
    done = {slot_key("KR:KRX:005930", date(2026, 10, 16))}       # session date, Seoul time
    assert "KR:KRX:005930@2026-10-16" not in keys(now, done=done)


def test_naive_time_rejected_and_next_slots_listed() -> None:
    with pytest.raises(ValueError):
        due_slots(datetime(2026, 10, 16), set())
    upcoming = {s.rule.instrument_id: s for s in next_slots(at("2026-10-16T10:00:00+09:00"))}
    assert upcoming["KR:KRX:005930"].session.isoformat() == "2026-10-19"   # next Monday
    assert upcoming["US:NASDAQ:NVDA"].session.isoformat() == "2026-10-16"  # tonight (ET)
