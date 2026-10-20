"""Phone notifications: only the three core categories, quiet hours, one summary, no network."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from stock_office.db import connect
from stock_office.notify import Notifier, compose, main, valid_endpoint

APPLE = "https://web.push.apple.com/QGrdx"
T0 = datetime(2026, 10, 20, 3, 0, tzinfo=UTC)  # 12:00 KST


@dataclass
class FakeSender:
    status: int = 201

    def __post_init__(self) -> None:
        self.sent: list[tuple[str, dict[str, str]]] = []

    def __call__(self, subscription: dict[str, Any], data: str) -> int:
        self.sent.append((subscription["endpoint"], json.loads(data)))
        return self.status


class Repo:
    def __init__(self) -> None:
        self.runs: list[Any] = []
        self.decisions: dict[str, str] = {}

    def list_runs(self) -> list[Any]:
        return self.runs

    def get_decision(self, run_id: str) -> Any:
        action = self.decisions.get(run_id)
        return SimpleNamespace(action=SimpleNamespace(value=action)) if action else None


def setup(tmp_path: Path, sender: FakeSender | None = None) -> tuple[Notifier, Repo]:
    repo = Repo()
    notifier = Notifier(connect(tmp_path), repo, sender if sender is not None else FakeSender())
    notifier.collect(T0)  # first run: only what happens from now on is notified
    return notifier, repo


def run(rid: str, status: str = "COMPLETED", *, trigger: str = "schedule", demo: bool = False,
        started: int | None = 1, done: int | None = 4, code: str | None = None) -> Any:
    def at(minutes: int | None) -> datetime | None:
        return None if minutes is None else T0 + timedelta(minutes=minutes)

    return SimpleNamespace(id=rid, demo=demo, trigger=trigger, instrument_id="KR:KRX:005930",
                           status=SimpleNamespace(value=status), started_at=at(started),
                           completed_at=at(done), error_code=code)


def doc(n: Notifier, run_id: str, kind: str, title: str, status: str = "INFO") -> None:
    n.conn.execute(
        "INSERT INTO inbox_items (kind, run_id, title, summary, payload, status, dedupe_key, "
        "created_at) VALUES (?,?,?,?,?,?,?,?)",
        (kind, run_id, title, "요약", "{}", status, f"run:{run_id}",
         (T0 + timedelta(minutes=4)).isoformat(timespec="microseconds")))


def queued(n: Notifier) -> list[tuple[str, str, str]]:
    return [(r["dedupe_key"], r["category"], r["title"]) for r in n.conn.execute(
        "SELECT dedupe_key, category, title FROM notifications ORDER BY id")]


def test_meeting_start_end_and_approval_only(tmp_path: Path) -> None:
    n, repo = setup(tmp_path)
    repo.runs = [run("live", "RUNNING", done=None)]
    n.collect(T0 + timedelta(minutes=2))
    assert queued(n) == [("start:live", "meeting_start", "[회의 시작] 삼성전자 정기 회의")]

    repo.runs = [
        run("hold"), run("buy"), run("late"), run("fail", "FAILED", code="ENGINE_ERROR"),
        run("manual", trigger="manual"),            # the CEO started it: no "started"
        run("demo", demo=True),                      # DEMO: never
        run("old", started=-90, done=-60),           # before notifications started
    ]
    repo.decisions = {"hold": "HOLD", "manual": "HOLD", "late": "BUY"}
    doc(n, "hold", "daily", "[일일 보고] 삼성전자 보유")
    doc(n, "buy", "approval", "[결재] 삼성전자 매수 9주", "APPROVED")
    doc(n, "late", "approval", "[결재] 삼성전자 매수 1주", "EXPIRED")
    doc(n, "manual", "daily", "[일일 보고] 삼성전자 보유 2")
    n.collect(T0 + timedelta(minutes=5))
    n.collect(T0 + timedelta(minutes=6))  # idempotent
    assert [k for k, *_ in queued(n)] == [
        "start:live", "start:hold", "end:hold", "start:buy", "approval:buy", "start:late",
        "end:late", "start:fail", "end:fail", "end:manual"]
    rows = {k: (c, t) for k, c, t in queued(n)}
    assert rows["end:hold"] == ("meeting_end", "[회의 끝] 삼성전자 · 보유")
    assert rows["approval:buy"] == ("approval", "[결재] 삼성전자 매수 9주")   # instead of "end"
    assert rows["end:late"] == ("meeting_end", "[회의 끝] 삼성전자 · 매수")  # expired request
    assert rows["end:fail"] == ("meeting_end", "[회의 끝] 삼성전자 · 실패")
    body = n.conn.execute(
        "SELECT body FROM notifications WHERE dedupe_key='approval:buy'").fetchone()[0]
    assert body == "자동 승인 · 모의 예약 주문 · 요약"


def test_budget_stop_is_a_meeting_that_did_not_start(tmp_path: Path) -> None:
    n, _ = setup(tmp_path)
    n.budget_skipped("KR:KRX:005930@2026-10-21", "KR:KRX:005930", T0)
    n.budget_skipped("KR:KRX:005930@2026-10-21", "KR:KRX:005930", T0)  # every minute: once
    assert queued(n) == [("budget:KR:KRX:005930@2026-10-21", "meeting_start",
                          "[회의 시작 못 함] 삼성전자 정기 회의")]


def test_a_start_is_dropped_when_its_end_arrives_in_the_same_batch(tmp_path: Path) -> None:
    sender = FakeSender()
    n, repo = setup(tmp_path, sender)
    n.subscribe(APPLE, "p", "a", T0)
    repo.runs = [run("nvda")]
    repo.decisions = {"nvda": "HOLD"}
    night = datetime(2026, 10, 20, 21, 0, tzinfo=UTC)  # 06:00 KST, quiet hours
    n.tick(night)
    n.tick(datetime(2026, 10, 20, 22, 0, tzinfo=UTC))  # 07:00 KST
    assert [m["title"] for _, m in sender.sent] == ["[회의 끝] 삼성전자 · 보유"]


def test_quiet_hours_hold_then_one_summary(tmp_path: Path) -> None:
    sender = FakeSender()
    n, _ = setup(tmp_path, sender)
    n.subscribe(APPLE, "p", "a", T0)
    night = datetime(2026, 10, 20, 20, 30, tzinfo=UTC)  # 05:30 KST next day
    for i in range(3):
        n.enqueue(f"k{i}", "meeting_end", f"[회의 끝] {i}", "", "/records", night)
    assert n.is_quiet(night) and n.flush(night) == 0 and sender.sent == []
    morning = datetime(2026, 10, 20, 22, 0, tzinfo=UTC)  # 07:00 KST
    assert not n.is_quiet(morning)
    assert n.flush(morning) == 3
    assert sender.sent == [(APPLE, {"title": "Stock Office 알림 3건",
                                    "body": "[회의 끝] 0\n[회의 끝] 1\n[회의 끝] 2",
                                    "url": "/records", "tag": "digest"})]
    assert n.flush(morning) == 0  # nothing twice


def test_single_message_and_dead_subscriptions(tmp_path: Path) -> None:
    sender = FakeSender(status=410)
    n, _ = setup(tmp_path, sender)
    n.subscribe(APPLE, "p", "a", T0)
    n.enqueue("k", "approval", "[결재] 삼성전자 매수 9주", "결재 필요", "/inbox/3", T0)
    n.flush(T0)
    assert sender.sent[0][1] == {"title": "[결재] 삼성전자 매수 9주", "body": "결재 필요",
                                 "url": "/inbox/3", "tag": "approval"}
    assert n.subscriptions() == 0  # 410 Gone: the phone turned notifications off


def test_without_a_phone_rows_are_closed_not_piled_up(tmp_path: Path) -> None:
    n, _ = setup(tmp_path)
    n.enqueue("k", "meeting_end", "[회의 끝] x", "", "/", T0)
    assert n.flush(T0) == 1
    assert n.conn.execute("SELECT outcome FROM notifications").fetchone()[0] == "no-subscriber"


def test_only_known_push_services_are_accepted(tmp_path: Path) -> None:
    assert valid_endpoint(APPLE)
    assert valid_endpoint("https://fcm.googleapis.com/fcm/send/abc")
    for bad in ("http://web.push.apple.com/x", "https://evil.example/push",
                "https://push.apple.com.evil.example/x", "https://127.0.0.1/x"):
        assert not valid_endpoint(bad), bad
    n, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        n.subscribe("https://evil.example/push", "p", "a", T0)


def test_long_summaries_are_cut() -> None:
    rows = [{"title": f"t{i}", "body": "", "url": f"/inbox/{i}", "category": "meeting_end"}
            for i in range(9)]
    msg = compose(rows)
    assert msg["body"].splitlines()[-1] == "외 3건" and msg["url"] == "/"


def test_key_command_prints_a_p256_pair() -> None:
    lines: list[str] = []
    assert main(["keys"], lines.append) == 0
    public = lines[0].split("=", 1)[1]
    private = lines[1].split("=", 1)[1]
    assert lines[0].startswith("STOCK_OFFICE_VAPID_PUBLIC_KEY=")
    assert len(base64.urlsafe_b64decode(public + "==")) == 65   # uncompressed point
    assert len(base64.urlsafe_b64decode(private + "=")) == 32   # raw private value


def test_default_contact_is_a_form_push_services_accept() -> None:
    """pywebpush/Apple accept only "mailto:..." or a bare https origin (a path is rejected)."""
    import re

    from stock_office.config import Settings

    subject = Settings(_env_file=None).vapid_subject  # type: ignore[call-arg]
    assert re.fullmatch(r"mailto:.+@.+|https://[\w.-]+", subject), subject


def test_kiwoom_desk_reports_become_order_notifications(tmp_path: Path) -> None:
    n, _ = setup(tmp_path)
    at = (T0 + timedelta(minutes=1)).isoformat(timespec="microseconds")
    for i, (title, item) in enumerate([("[주문] 삼성전자 매수 19주 · 지정가 50,000원", 7),
                                       ("[청산] 삼성전자 손절 19주 @ 46,000원 · −76,000원", None)]):
        n.conn.execute(
            "INSERT INTO inbox_items (kind, instrument_id, title, summary, payload, status, "
            "dedupe_key, created_at) VALUES ('execution', ?, ?, '키움 모의', ?, 'INFO', ?, ?)",
            ("KR:KRX:005930", title, json.dumps({"item_id": item}), f"km:x{i}", at))
    n.conn.execute(  # the internal paper book's report: not an order notification
        "INSERT INTO inbox_items (kind, title, payload, status, dedupe_key, created_at) "
        "VALUES ('execution', '[체결] 내부 장부', '{}', 'INFO', 'fill:1', ?)", (at,))
    n.collect(T0 + timedelta(minutes=2))
    rows = list(n.conn.execute("SELECT category, title, url FROM notifications ORDER BY id"))
    assert [tuple(r) for r in rows] == [
        ("order", "[주문] 삼성전자 매수 19주 · 지정가 50,000원", "/inbox/7"),
        ("order", "[청산] 삼성전자 손절 19주 @ 46,000원 · −76,000원", "/portfolio")]
