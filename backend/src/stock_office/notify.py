"""Phone notifications: only what the CEO should not miss, as Web Push to the installed web app.

Four categories, nothing else (owner's choices, 2026-10-20):
- meeting_start: a scheduled real meeting started (or could not start: budget hard stop).
- meeting_end: a real meeting ended with its verdict, or failed.
- approval: the meeting ended with an approval request (BUY/SELL), auto-approved or waiting;
  this replaces its "meeting_end" so one meeting never sends two end notifications.
- order: what the Kiwoom mock desks did (order placed, filled, exit with P&L, unfilled and
  cancelled, refused by the risk policy or by Kiwoom).
The internal paper book's settlement and DEMO meetings are inbox/portfolio only.

The worker collects new events into an outbox (`notifications`, one row per event, idempotent)
and sends them outside quiet hours. Several waiting rows go out as one summary, and a "started"
row is dropped when the same meeting's end is in that batch (an early-morning meeting arrives as
one line at the end of quiet hours).
Notification text is the inbox title only: no prompts, reasoning or account data.

Keys (once, on the server; append the output to backend/.env):
    .venv/bin/python -m stock_office.notify keys >> .env
"""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from stock_office.db import transaction
from stock_office.domain.instruments import display_name
from stock_office.inbox import ACTION_KO

log = logging.getLogger("stock_office.notify")
KST = ZoneInfo("Asia/Seoul")

# Push services of the browsers we serve (Safari/iOS, Chrome, Firefox, Edge). Subscriptions to
# anything else are refused, so the server never posts to an arbitrary address.
PUSH_HOSTS = ("push.apple.com", "fcm.googleapis.com", "push.services.mozilla.com",
              "notify.windows.com")
DIGEST_LINES = 6


class Sender(Protocol):
    def __call__(self, subscription: dict[str, Any], data: str) -> int:
        """Deliver one message; returns the push service's HTTP status."""


def valid_endpoint(endpoint: str) -> bool:
    url = urlparse(endpoint)
    host = url.hostname or ""
    return url.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def _iso(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo("UTC")).isoformat(timespec="microseconds")


class Notifier:
    def __init__(self, conn: sqlite3.Connection, repo: Any, sender: Sender | None,
                 quiet: tuple[int, int] = (23, 7)) -> None:
        self.conn, self.repo, self.sender, self.quiet = conn, repo, sender, quiet

    # ---------------------------------------------------------------- subscriptions
    def subscribe(self, endpoint: str, p256dh: str, auth: str, now: datetime) -> None:
        if not valid_endpoint(endpoint):
            raise ValueError("unsupported push service")
        self.conn.execute(
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at) VALUES (?,?,?,?) "
            "ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh, auth=excluded.auth, "
            "failures=0", (endpoint, p256dh, auth, _iso(now)))

    def unsubscribe(self, endpoint: str) -> None:
        self.conn.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))

    def subscriptions(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0])

    # ---------------------------------------------------------------- outbox
    def enqueue(self, key: str, category: str, title: str, body: str, url: str,
                now: datetime) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO notifications (dedupe_key, category, title, body, url, "
            "created_at) VALUES (?,?,?,?,?,?)", (key, category, title[:120], body[:200], url,
                                                  _iso(now)))

    def _since(self, now: datetime) -> str:
        """Events after this moment are notified; set when notifications first run."""
        row = self.conn.execute(
            "SELECT value FROM company_settings WHERE key='notify_since'").fetchone()
        if row:
            return str(row["value"])
        self.conn.execute("INSERT INTO company_settings (key, value, updated_at) "
                          "VALUES ('notify_since', ?, ?)", (_iso(now), _iso(now)))
        return _iso(now)

    def collect(self, now: datetime) -> None:
        """Turn meetings that started or ended since the last look into outbox rows."""
        with transaction(self.conn):
            since = self._since(now)
            self._orders(since, now)
            for run in self.repo.list_runs():
                if run.demo:
                    continue
                name = display_name(run.instrument_id)
                started, done = run.started_at, run.completed_at
                if run.trigger == "schedule" and started is not None and _iso(started) > since:
                    self.enqueue(f"start:{run.id}", "meeting_start",
                                 f"[회의 시작] {name} 정기 회의",
                                 "결론이 나오면 다시 알려 드립니다.", "/office", now)
                if done is None or _iso(done) <= since:
                    continue
                if run.status.value != "COMPLETED":
                    self.enqueue(f"end:{run.id}", "meeting_end", f"[회의 끝] {name} · 실패",
                                 f"{run.error_code or run.status.value} · 회의록에서 확인",
                                 f"/records/{run.id}", now)
                    continue
                doc = self.conn.execute(
                    "SELECT id, kind, title, summary, status FROM inbox_items WHERE run_id=?",
                    (run.id,)).fetchone()
                if doc and doc["kind"] == "approval" and doc["status"] != "EXPIRED":
                    # The approval request is the meeting's end: one notification, not two.
                    state = ("자동 승인 · 모의 예약 주문" if doc["status"] == "APPROVED"
                             else "결재 필요")
                    body = f"{state} · {doc['summary']}" if doc["summary"] else state
                    self.enqueue(f"approval:{run.id}", "approval", doc["title"], body,
                                 f"/inbox/{doc['id']}", now)
                    continue
                decision = self.repo.get_decision(run.id)
                verdict = (ACTION_KO.get(decision.action.value, decision.action.value)
                           if decision else "결론 없음")
                self.enqueue(f"end:{run.id}", "meeting_end", f"[회의 끝] {name} · {verdict}",
                             doc["summary"] if doc and doc["summary"]
                             else "결재함에서 보고 확인" if doc else "주문 없음 · 회의록에서 확인",
                             f"/inbox/{doc['id']}" if doc else f"/records/{run.id}", now)

    def _orders(self, since: str, now: datetime) -> None:
        """Reports the Kiwoom mock desks filed (dedupe `km:...`): one notification each."""
        for r in self.conn.execute(
                "SELECT id, title, summary, payload FROM inbox_items WHERE created_at > ? "
                "AND dedupe_key LIKE 'km:%' ORDER BY id", (since,)):
            item = json.loads(r["payload"]).get("item_id")
            self.enqueue(f"inbox:{r['id']}", "order", r["title"], r["summary"] or "",
                         f"/inbox/{item}" if item else "/portfolio", now)

    def budget_skipped(self, slot_key: str, instrument_id: str, now: datetime) -> None:
        with transaction(self.conn):
            self.enqueue(f"budget:{slot_key}", "meeting_start",
                         f"[회의 시작 못 함] {display_name(instrument_id)} 정기 회의",
                         "이번 달 AI 예산 한도에 닿아 유료 회의를 시작하지 않았습니다.",
                         "/settings", now)

    # ---------------------------------------------------------------- delivery
    def is_quiet(self, now: datetime) -> bool:
        start, end = self.quiet
        hour = now.astimezone(KST).hour
        return (start <= hour or hour < end) if start > end else start <= hour < end

    def flush(self, now: datetime) -> int:
        """Send waiting rows (one summary when several). Returns how many rows were handled."""
        if self.is_quiet(now):
            return 0
        rows = list(self.conn.execute(
            "SELECT * FROM notifications WHERE sent_at IS NULL ORDER BY id"))
        if not rows:
            return 0
        message = compose(current(rows))
        outcome = "no-subscriber"
        if self.sender is None:
            outcome = "push-not-configured"
        elif self.subscriptions():
            sent = self.send(message, now)
            outcome = f"sent:{sent}"
        with transaction(self.conn):
            self.conn.executemany("UPDATE notifications SET sent_at=?, outcome=? WHERE id=?",
                                  [(_iso(now), outcome, r["id"]) for r in rows])
        return len(rows)

    def send(self, message: dict[str, str], now: datetime) -> int:
        """Deliver to every subscription now (no quiet hours); drops ones the service rejects."""
        if self.sender is None:
            return 0
        data = json.dumps(message, ensure_ascii=False)
        delivered = 0
        for sub in list(self.conn.execute("SELECT * FROM push_subscriptions")):
            info = {"endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}
            try:
                status = self.sender(info, data)
            except Exception:  # network trouble: keep the subscription, count the failure
                log.warning("push to %s failed", urlparse(sub["endpoint"]).hostname)
                status = 0
            if status in (404, 410):  # unsubscribed on the phone
                self.unsubscribe(sub["endpoint"])
            elif 200 <= status < 300:
                delivered += 1
                self.conn.execute("UPDATE push_subscriptions SET last_sent_at=?, failures=0 "
                                  "WHERE endpoint=?", (_iso(now), sub["endpoint"]))
            else:
                self.conn.execute("UPDATE push_subscriptions SET failures=failures+1 "
                                  "WHERE endpoint=?", (sub["endpoint"],))
        return delivered

    def tick(self, now: datetime) -> None:
        """Worker step. Never raises: notification trouble must not stop meetings or settlement."""
        try:
            self.collect(now)
            self.flush(now)
        except Exception:
            log.exception("notifications failed")


def current(rows: Sequence[sqlite3.Row]) -> list[sqlite3.Row]:
    """Drop "meeting started" when the same meeting's end (or approval) is in the batch."""
    keys = {r["dedupe_key"] for r in rows}
    return [r for r in rows if not (
        r["dedupe_key"].startswith("start:")
        and ({f"end:{r['dedupe_key'][6:]}", f"approval:{r['dedupe_key'][6:]}"} & keys))]


def compose(rows: Sequence[sqlite3.Row | dict[str, Any]]) -> dict[str, str]:
    if len(rows) == 1:
        r = rows[0]
        return {"title": r["title"], "body": r["body"], "url": r["url"], "tag": r["category"]}
    lines = [r["title"] for r in rows[:DIGEST_LINES]]
    if len(rows) > DIGEST_LINES:
        lines.append(f"외 {len(rows) - DIGEST_LINES}건")
    urls = {r["url"] for r in rows}
    return {"title": f"Stock Office 알림 {len(rows)}건", "body": "\n".join(lines),
            "url": urls.pop() if len(urls) == 1 else "/", "tag": "digest"}


def web_push_sender(private_key: str, subject: str) -> Sender:
    """Real delivery through pywebpush (the `live` extra). Imported lazily: tests never send."""
    from pywebpush import WebPushException, webpush

    def send(subscription: dict[str, Any], data: str) -> int:
        try:
            resp = webpush(subscription_info=subscription, data=data,
                           vapid_private_key=private_key, vapid_claims={"sub": subject},
                           ttl=24 * 3600, timeout=10)
            return int(getattr(resp, "status_code", 201))
        except WebPushException as exc:
            return int(getattr(exc.response, "status_code", 0) or 0)

    return send


def build_notifier(settings: Any, conn: sqlite3.Connection, repo: Any) -> Notifier:
    sender: Sender | None = None
    if settings.vapid_public_key and settings.vapid_private_key:
        try:
            sender = web_push_sender(settings.vapid_private_key.get_secret_value(),
                                     settings.vapid_subject)
        except ImportError:
            log.warning("pywebpush missing (install the 'live' extra): notifications not sent")
    return Notifier(conn, repo, sender, (settings.notify_quiet_start, settings.notify_quiet_end))


def generate_keys() -> tuple[str, str]:
    """A new VAPID key pair: (public, uncompressed point; private, raw 32 bytes), base64url."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.private_numbers().private_value.to_bytes(32, "big")
    point = key.public_key().public_bytes(serialization.Encoding.X962,
                                          serialization.PublicFormat.UncompressedPoint)

    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    return b64(point), b64(raw)


def main(argv: Sequence[str] | None = None, out: Callable[[str], Any] = print) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] != ["keys"]:
        out("usage: python -m stock_office.notify keys >> .env")
        return 2
    public, private = generate_keys()
    out(f"STOCK_OFFICE_VAPID_PUBLIC_KEY={public}")
    out(f"STOCK_OFFICE_VAPID_PRIVATE_KEY={private}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
