"""The CEO inbox: one document per finished committee meeting, approval decisions and expiry.

- BUY with a valid plan and a non-zero allocation → approval request (PENDING, expires at the next
  session close of the instrument's exchange).
- Everything else → a report (INFO): HOLD/REVIEW, SELL without a position (the paper book is
  long-only and empty until paper orders exist), or a BUY whose plan failed a check (REVIEW reasons
  shown, cannot be approved).
Approving records the decision only; paper orders are connected in a later step (stated in the UI).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from stock_office.db import transaction
from stock_office.domain.instruments import display_name, get_instrument
from stock_office.domain.models import AnalysisRun, DecisionAction, Market
from stock_office.paper.allocator import POLICY, Policy, allocate
from stock_office.plan_extract import build_buy_plan, daily_bars, parse_labels
from stock_office.runs.repository import RunRepository

FxSource = Callable[[], tuple[Decimal, datetime] | None]  # KRW per USD and when it was observed

ACTION_KO = {"BUY": "매수", "SELL": "매도", "HOLD": "보유", "REVIEW": "판단 보류"}
_CALENDAR = {Market.KR: "XKRX", Market.US: "XNYS"}


class DecisionError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class InboxItem(BaseModel):
    id: int
    kind: str
    run_id: str | None
    instrument_id: str | None
    title: str
    summary: str
    payload: dict[str, Any]
    status: str
    expires_at: datetime | None
    read_at: datetime | None
    created_at: datetime
    decided_at: datetime | None
    plan: dict[str, Any] | None = None
    approvals: list[dict[str, Any]] = []


def _iso(dt: datetime | None) -> str | None:
    # Fixed width (UTC, microseconds) so stored timestamps also compare correctly as text.
    return dt.astimezone(UTC).isoformat(timespec="microseconds") if dt else None


def _dt(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def next_session_close(market: Market, now: datetime) -> datetime:
    """First session close of the instrument's exchange strictly after `now`."""
    from stock_office.schedule import _calendar

    cal = _calendar(_CALENDAR[market])
    day = now.astimezone(UTC).date()
    for _ in range(15):
        iso = day.isoformat()
        if cal.is_session(iso):
            close: datetime = cal.session_close(iso).to_pydatetime()
            if close > now:
                return close
        day = day.fromordinal(day.toordinal() + 1)
    raise RuntimeError("no session close within 15 days")


def format_qty(qty: Decimal | str | int) -> str:
    """4 → "4", 0.4530 → "0.453" (no trailing zeros, no exponent)."""
    text = format(Decimal(str(qty)).normalize(), "f")
    return text


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


class Inbox:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repo: RunRepository,
        policy: Policy = POLICY,
        fx: FxSource | None = None,
    ) -> None:
        self.conn, self.repo, self.policy, self.fx = conn, repo, policy, fx

    # ---------------------------------------------------------------- filing (worker)
    def file_run(self, run: AnalysisRun, now: datetime) -> int | None:
        """Create the meeting's inbox document once. Returns its id (None without a decision)."""
        existing = self.conn.execute(
            "SELECT id FROM inbox_items WHERE dedupe_key=?", (f"run:{run.id}",)
        ).fetchone()
        if existing:
            return int(existing["id"])
        decision = self.repo.get_decision(run.id)
        if decision is None:
            return None
        inst = get_instrument(run.instrument_id)
        name = display_name(inst.id)
        briefing = self.repo.get_briefing(run.id) or {}
        headline = str(briefing.get("headline") or "") if briefing.get("status") == "OK" else ""
        payload: dict[str, Any] = {
            "action": decision.action.value,
            "rating": decision.engine_rating,
            "risk_flags": decision.risk_flags,
            "demo": run.demo,
            "name": name,
            "trigger": run.trigger,
        }
        plan_body: dict[str, Any] | None = None
        kind, status, expires = "daily", "INFO", None
        title = f"[일일 보고] {name} {ACTION_KO.get(decision.action.value, decision.action.value)}"
        if decision.action is DecisionAction.SELL:
            payload["note"] = (
                "보유 종목이 없어 참고 보고로 올렸습니다 (모의 계좌는 매수만, 보유분만 매도)."
            )
        if decision.action is DecisionAction.BUY:
            plan_body, reasons = self._buy_plan(run, inst.market, decision.engine_rating)
            if plan_body and not reasons:
                kind, status = "approval", "PENDING"
                # The deadline belongs to the meeting: the next close after it was decided.
                expires = next_session_close(inst.market, decision.created_at)
                if expires <= now:
                    status = "EXPIRED"
                    payload["filed_late"] = True
                title = f"[결재] {name} 매수 {format_qty(plan_body['allocation']['qty'])}주"
                plan_body["valid_until"] = _iso(expires)
            else:
                title = f"[검토 필요] {name} 매수 제안"
                payload["review_reasons"] = reasons
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO inbox_items (kind, run_id, instrument_id, title, summary, payload, "
                "status, expires_at, dedupe_key, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    kind,
                    run.id,
                    inst.id,
                    title,
                    headline,
                    json.dumps(_jsonable(payload), ensure_ascii=False),
                    status,
                    _iso(expires),
                    f"run:{run.id}",
                    _iso(min(decision.created_at, now)),
                ),
            )
            item_id = int(cur.lastrowid or 0)
            if plan_body is not None:
                self.conn.execute(
                    "INSERT INTO plans (item_id, run_id, instrument_id, side, body, "
                    "policy_version, valid_until) VALUES (?,?,?,?,?,?,?)",
                    (
                        item_id,
                        run.id,
                        inst.id,
                        "BUY",
                        json.dumps(_jsonable(plan_body), ensure_ascii=False),
                        self.policy.version,
                        _iso(expires),
                    ),
                )
        return item_id

    def _buy_plan(
        self, run: AnalysisRun, market: Market, rating: str | None
    ) -> tuple[dict[str, Any] | None, list[str]]:
        reports = self.repo.get_reports(run.id)
        if reports:
            trader, pm = reports.get("trader", ""), reports.get("portfolio_manager", "")
        else:
            # Older runs: the trader's event summary (first 600 chars) and the stored decision
            # rationale still carry the labelled lines; missing numbers fall back to policy.
            trader = next((str(e.payload.get("summary", "")) for e in self.repo.events.read(run.id)
                           if e.type.value == "agent.completed" and e.agent_id == "trader"), "")
            decision = self.repo.get_decision(run.id)
            pm = decision.rationale if decision else ""
        labels = parse_labels(trader, pm)
        draft = build_buy_plan(labels, daily_bars(self.repo.get_snapshots(run.id)), market)
        if draft is None:
            return None, ["회의에 쓰인 시세 데이터가 없어 매매 조건을 만들 수 없음"]
        reasons = list(draft.review_reasons)
        fx_rate, fx_at = Decimal(1), None
        if market is Market.US:
            got = self.fx() if self.fx else None
            if got is None:
                reasons.append("원/달러 환율을 구하지 못해 금액을 계산할 수 없음")
            else:
                fx_rate, fx_at = got
        nav = self.policy.initial_equity_krw  # no paper book yet: full cash, nothing held
        alloc = allocate(
            self.policy,
            nav_krw=nav,
            cash_krw=nav,
            held_krw=Decimal(0),
            rating=rating or draft.rating,
            multiplier=draft.multiplier,
            limit=draft.limit,
            stop=draft.stop,
            fx_krw=fx_rate,
            currency="USD" if market is Market.US else "KRW",
        )
        if alloc.blocked:
            reasons.append(alloc.blocked)
        body = {
            "currency": "USD" if market is Market.US else "KRW",
            "limit": draft.limit,
            "stop": draft.stop,
            "target": draft.target,
            "sources": draft.sources,
            "ref_price": draft.ref_price,
            "ref_at": draft.ref_at,
            "atr": draft.atr,
            "stop_distance": draft.stop_distance,
            "multiplier": draft.multiplier,
            "multiplier_source": draft.multiplier_source,
            "rating": rating or draft.rating,
            "sizing_text": draft.sizing_text,
            "horizon": draft.horizon,
            "fx_krw_per_unit": fx_rate,
            "fx_at": fx_at,
            "allocation": asdict(alloc),
            "policy_version": self.policy.version,
            "account_basis": "가상 계좌 시작 금액 기준 (모의 계좌 연결 전)",
        }
        return body, reasons

    # ---------------------------------------------------------------- reading (API)
    def _row(self, row: sqlite3.Row, detail: bool = False) -> InboxItem:
        item = InboxItem(
            id=row["id"],
            kind=row["kind"],
            run_id=row["run_id"],
            instrument_id=row["instrument_id"],
            title=row["title"],
            summary=row["summary"],
            payload=json.loads(row["payload"]),
            status=row["status"],
            expires_at=_dt(row["expires_at"]),
            read_at=_dt(row["read_at"]),
            created_at=_dt(row["created_at"]) or datetime.now(UTC),
            decided_at=_dt(row["decided_at"]),
        )
        plan = self.conn.execute("SELECT body FROM plans WHERE item_id=?", (item.id,)).fetchone()
        if plan:
            item.plan = json.loads(plan["body"])
        if detail:
            item.approvals = [
                dict(r)
                for r in self.conn.execute(
                    "SELECT action, comment, decided_at FROM approvals WHERE item_id=? ORDER BY id",
                    (item.id,),
                )
            ]
        return item

    def list(self, limit: int = 100) -> list[InboxItem]:
        rows = self.conn.execute(
            "SELECT * FROM inbox_items ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        )
        return [self._row(r) for r in rows]

    def get(self, item_id: int) -> InboxItem | None:
        row = self.conn.execute("SELECT * FROM inbox_items WHERE id=?", (item_id,)).fetchone()
        return self._row(row, detail=True) if row else None

    def by_run(self) -> dict[str, str]:
        """run_id → inbox status, for the records list."""
        return {
            r["run_id"]: r["status"]
            for r in self.conn.execute(
                "SELECT run_id, status FROM inbox_items WHERE run_id IS NOT NULL"
            )
        }

    # ---------------------------------------------------------------- CEO actions
    def mark_read(self, item_id: int, now: datetime) -> None:
        self.conn.execute(
            "UPDATE inbox_items SET read_at=COALESCE(read_at, ?) WHERE id=?", (_iso(now), item_id)
        )

    def decide(
        self, item_id: int, action: str, comment: str, client_request_id: str, now: datetime
    ) -> InboxItem:
        if action not in ("approve", "reject", "defer"):
            raise DecisionError(422, "action must be approve, reject or defer")
        # Expire first in its own statement, so a refused late decision still leaves it EXPIRED.
        self.expire_due(now)
        with transaction(self.conn):
            seen = self.conn.execute(
                "SELECT item_id FROM approvals WHERE client_request_id=?", (client_request_id,)
            ).fetchone()
            if seen:  # a repeated tap: same answer
                if int(seen["item_id"]) != item_id:
                    raise DecisionError(409, "request id already used for another document")
            else:
                row = self.conn.execute(
                    "SELECT status, expires_at FROM inbox_items WHERE id=?", (item_id,)
                ).fetchone()
                if row is None:
                    raise DecisionError(404, "document not found")
                if row["status"] not in ("PENDING", "DEFERRED"):
                    raise DecisionError(409, f"already {row['status']}")
                status = {"approve": "APPROVED", "reject": "REJECTED", "defer": "DEFERRED"}[action]
                self.conn.execute(
                    "INSERT INTO approvals (item_id, action, comment, client_request_id, "
                    "decided_at) VALUES (?,?,?,?,?)",
                    (item_id, action, comment[:500], client_request_id, _iso(now)),
                )
                self.conn.execute(
                    "UPDATE inbox_items SET status=?, decided_at=?, read_at=COALESCE(read_at, ?) "
                    "WHERE id=?",
                    (status, None if status == "DEFERRED" else _iso(now), _iso(now), item_id),
                )
        item = self.get(item_id)
        assert item is not None
        return item

    def expire_due(self, now: datetime) -> int:
        cur = self.conn.execute(
            "UPDATE inbox_items SET status='EXPIRED' WHERE status IN ('PENDING','DEFERRED') "
            "AND expires_at IS NOT NULL AND expires_at <= ?",
            (_iso(now),),
        )
        return cur.rowcount


def main() -> int:
    """File every real meeting that has no inbox document yet (oldest first).

    Past deadlines are kept: such documents arrive as EXPIRED, for reference only.
        uv run python -m stock_office.inbox
    """
    from stock_office.config import get_settings
    from stock_office.wiring import build_service

    service = build_service(get_settings())
    filed = 0
    for run in reversed(service.repo.list_runs()):
        if run.demo or run.status.value != "COMPLETED":
            continue
        before = len(service.inbox.list(limit=10_000))
        item_id = service.inbox.file_run(run, service.clock())
        if item_id and len(service.inbox.list(limit=10_000)) > before:
            filed += 1
            item = service.inbox.get(item_id)
            if item:
                print(f"{run.id} -> #{item_id} {item.status} {item.title}")
    print(f"filed {filed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
