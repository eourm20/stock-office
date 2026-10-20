"""System alerts: the company runs alone for a month, so a silent stop must reach the CEO's phone.

Owner's decision (2026-10-20): a fifth notification category, "system", for these only, each sent
once per problem:
- the worker stopped: its Kiwoom desk thread writes a heartbeat every 30 s; none for 10 min;
- a meeting has not ended 30 min after it started;
- a market opened and that session had no research (no focus meetings that day);
- 2 h after a close the desk still has no account value for that session (Kiwoom link trouble).
The checks run in the API process, so they still work when the worker is down, and only the API
sends "system" rows (the worker's notifier sends the other four: no row goes out twice).
They read stored state only and never touch meetings, approvals or orders.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from stock_office.db import transaction
from stock_office.domain.instruments import display_name
from stock_office.domain.models import Market, RunStatus
from stock_office.notify import Notifier
from stock_office.schedule import MARKET_TZ, closed_sessions, session_of

log = logging.getLogger("stock_office.health")
HEARTBEAT_KEY = "worker_heartbeat"
WORKER_SILENT = timedelta(minutes=10)
MEETING_TOO_LONG = timedelta(minutes=30)
RESEARCH_GRACE = timedelta(minutes=10)     # after the open
NAV_GRACE = timedelta(hours=2)             # after the close
MARKET_KO = {"KR": "국내장", "US": "해외장"}


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def beat(conn: sqlite3.Connection, now: datetime) -> None:
    """The worker is alive (called by its Kiwoom desk thread, which never waits for meetings)."""
    conn.execute("INSERT INTO company_settings (key, value, updated_at) VALUES (?, ?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                 "updated_at=excluded.updated_at", (HEARTBEAT_KEY, iso(now), iso(now)))


class Watchdog:
    def __init__(self, conn: sqlite3.Connection, repo: Any, notifier: Notifier,
                 started: datetime, kiwoom: bool = True) -> None:
        self.conn, self.repo, self.notifier = conn, repo, notifier
        self.started, self.kiwoom = started, kiwoom

    def _setting(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM company_settings WHERE key=?",
                                (key,)).fetchone()
        return str(row["value"]) if row else None

    def _ops_day(self, market: str) -> date | None:
        """Sessions from operations start on are checked (the test period is not)."""
        start = self._setting("ops_start")
        if start is None:
            return None
        return datetime.fromisoformat(start).astimezone(MARKET_TZ[Market(market)]).date()

    def _alert(self, key: str, title: str, body: str, url: str, now: datetime) -> None:
        self.notifier.enqueue(f"system:{key}", "system", title, body, url, now)

    def check(self, now: datetime) -> None:
        with transaction(self.conn):
            self._worker(now)
            self._meetings(now)
            for market in ("KR", "US"):
                self._research(market, now)
                if self.kiwoom:
                    self._nav(market, now)

    def _worker(self, now: datetime) -> None:
        last = self._setting(HEARTBEAT_KEY)
        if last is None:
            if now - self.started >= WORKER_SILENT:
                self._alert("worker:never", "[시스템 이상] 작업 서버가 응답하지 않음",
                            "워커의 생존 기록이 없습니다. 회의·주문이 멈췄을 수 있습니다.",
                            "/office", now)
            return
        if now - datetime.fromisoformat(last) >= WORKER_SILENT:
            # One alert per outage: the key is the last heartbeat before it.
            self._alert(f"worker:{last}", "[시스템 이상] 작업 서버가 멈춤",
                        f"{_kst(last)} 이후 응답이 없습니다. 회의·주문·감시가 멈췄을 수 있습니다.",
                        "/office", now)

    def _meetings(self, now: datetime) -> None:
        for run in self.repo.list_runs():
            if run.status is RunStatus.RUNNING and run.started_at is not None \
                    and now - run.started_at >= MEETING_TOO_LONG:
                self._alert(f"stuck:{run.id}",
                            f"[시스템 이상] {display_name(run.instrument_id)} 회의가 끝나지 않음",
                            f"{_kst(iso(run.started_at))}에 시작해 30분 넘게 진행 중입니다.",
                            f"/records/{run.id}", now)

    def _last_open(self, market: str, now: datetime) -> Any:
        local = now.astimezone(MARKET_TZ[Market(market)]).date()
        for back in range(0, 7):
            session = session_of(Market(market), local - timedelta(days=back))
            if session is not None and session.open + RESEARCH_GRACE <= now:
                return session
        return None

    def _research(self, market: str, now: datetime) -> None:
        session = self._last_open(market, now)
        first = self._ops_day(market)
        if session is None or first is None or session.day <= first:
            return
        if now - session.open > timedelta(hours=12):
            return  # long past: the next session gets its own check
        if self.conn.execute("SELECT 1 FROM research_runs WHERE market=? AND session=?",
                             (market, session.day.isoformat())).fetchone():
            return
        self._alert(f"research:{market}:{session.day}",
                    f"[시스템 이상] {MARKET_KO[market]} 리서치가 열리지 않음",
                    f"{session.day} 장이 열렸는데 리서치 기록이 없습니다. "
                    "오늘 회의·주문이 없습니다.",
                    "/settings", now)

    def _nav(self, market: str, now: datetime) -> None:
        sessions = closed_sessions(Market(market), now - NAV_GRACE, limit=1)
        first = self._ops_day(market)
        if not sessions or first is None or sessions[-1].day < first:
            return
        session = sessions[-1]
        if now - session.close > timedelta(hours=12):
            return
        if self.conn.execute("SELECT 1 FROM km_nav WHERE market=? AND session=?",
                             (market, session.day.isoformat())).fetchone():
            return
        self._alert(f"nav:{market}:{session.day}",
                    f"[시스템 이상] {MARKET_KO[market]} 계좌 평가액 기록 안 됨",
                    f"{session.day} 마감 뒤 키움 모의 계좌를 읽지 못했습니다. "
                    "키움 연결을 확인해 주세요.",
                    "/portfolio", now)

    def tick(self, now: datetime) -> None:
        """Never raises: a broken check must not take the API down."""
        try:
            self.check(now)
            self.notifier.flush(now)
        except Exception:
            log.exception("system checks failed")


def _kst(value: str) -> str:
    from zoneinfo import ZoneInfo

    return datetime.fromisoformat(value).astimezone(ZoneInfo("Asia/Seoul")).strftime("%m-%d %H:%M")


def start_watchdog(dog: Watchdog, clock: Callable[[], datetime], every_s: float = 60.0
                   ) -> threading.Thread:
    def loop() -> None:
        while True:
            dog.tick(clock())
            time.sleep(every_s)

    thread = threading.Thread(target=loop, daemon=True, name="watchdog")
    thread.start()
    return thread
