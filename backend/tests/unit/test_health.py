"""System alerts: each problem once, only from stored state, sent by their own notifier."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from stock_office.db import connect
from stock_office.domain.models import RunStatus
from stock_office.health import Watchdog, beat
from stock_office.notify import WORKER_CATEGORIES, Notifier

KST = timedelta(hours=9)


def kst(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC) - KST


class Repo:
    def __init__(self) -> None:
        self.runs: list[Any] = []

    def list_runs(self) -> list[Any]:
        return self.runs


def setup(tmp_path: Path, started: datetime) -> tuple[Any, Repo, Watchdog]:
    conn = connect(tmp_path)
    conn.execute("INSERT INTO company_settings (key, value, updated_at) VALUES "
                 "('ops_start', '2026-10-20T07:16:00+00:00', '')")
    for market, day in (("KR", "2026-10-20"), ("US", "2026-10-20")):   # as on the server
        conn.execute("INSERT INTO km_nav VALUES (?, ?, '1', '1', '0', 'X', NULL, NULL, '')",
                     (market, day))
    repo = Repo()
    return conn, repo, Watchdog(conn, repo, Notifier(conn, repo, None, categories=("system",)),
                                started=started)


def alerts(conn: Any) -> list[str]:
    return [r["dedupe_key"] for r in conn.execute(
        "SELECT dedupe_key FROM notifications WHERE category='system' ORDER BY id")]


def research(conn: Any, market: str, day: str) -> None:
    conn.execute("INSERT INTO research_runs (market, session, rules_version, universe, screened, "
                 "liquid, candidates, watchlist, focus, created_at) "
                 "VALUES (?, ?, 'v', 'u', 0, 0, '[]', '[]', '[]', '')", (market, day))


def test_worker_stop_is_reported_once_per_outage(tmp_path: Path) -> None:
    now = kst("2026-10-21T08:00")
    conn, _, dog = setup(tmp_path, now)
    research(conn, "KR", "2026-10-21")
    dog.check(now)
    assert alerts(conn) == []                                   # just started: no heartbeat yet
    dog.check(now + timedelta(minutes=10))
    assert alerts(conn) == ["system:worker:never"]
    beat(conn, now + timedelta(minutes=11))
    dog.check(now + timedelta(minutes=15))
    assert len(alerts(conn)) == 1                               # alive again
    dog.check(now + timedelta(minutes=25))
    dog.check(now + timedelta(minutes=40))
    assert len(alerts(conn)) == 2                               # a new outage, one alert


def test_stuck_meeting_and_missing_research_and_account_value(tmp_path: Path) -> None:
    now = kst("2026-10-21T09:20")                               # KRX open 09:00
    conn, repo, dog = setup(tmp_path, now)
    beat(conn, now)
    repo.runs.append(SimpleNamespace(id="r1", instrument_id="US:NASDAQ:NVDA",
                                     status=RunStatus.RUNNING,
                                     started_at=now - timedelta(minutes=31)))
    dog.check(now)
    assert alerts(conn) == ["system:stuck:r1", "system:research:KR:2026-10-21"]
    dog.check(now + timedelta(minutes=5))
    assert len(alerts(conn)) == 2                               # each once

    # 10/21 KR closed 15:30 with no account value: reported after 2 h.
    later = kst("2026-10-21T17:40")
    research(conn, "US", "2026-10-21")
    dog.check(later)
    assert "system:nav:KR:2026-10-21" in alerts(conn)


def test_test_period_sessions_are_not_checked(tmp_path: Path) -> None:
    now = kst("2026-10-20T23:00")                               # US 10/20 session open
    conn, _, dog = setup(tmp_path, now)
    beat(conn, now)
    dog.check(now)
    assert alerts(conn) == []                                   # 10/20 research was before ops


def test_system_rows_go_out_only_through_the_watchdog_notifier(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    sent: list[str] = []

    def sender(_: dict[str, Any], data: str) -> int:
        sent.append(json.loads(data)["title"])
        return 201

    conn.execute("INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at) "
                 "VALUES ('https://web.push.apple.com/x', 'k', 'a', '')")
    worker = Notifier(conn, Repo(), sender, categories=WORKER_CATEGORIES)
    api = Notifier(conn, Repo(), sender, categories=("system",))
    noon = kst("2026-10-21T12:00")
    worker.enqueue("system:x", "system", "[시스템 이상] 작업 서버가 멈춤", "", "/office", noon)
    assert worker.flush(noon) == 0
    assert api.flush(noon) == 1 and sent == ["[시스템 이상] 작업 서버가 멈춤"]
