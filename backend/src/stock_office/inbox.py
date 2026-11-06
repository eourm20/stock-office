"""The CEO inbox: one document per finished committee meeting, approval decisions and expiry.

- BUY with a valid plan and a non-zero allocation → approval request (PENDING, expires at the next
  session close of the instrument's exchange).
- SELL while the paper book holds the instrument → approval request to sell the whole position.
- Everything else → a report (INFO): HOLD/REVIEW, SELL without a position (the book is long-only),
  or a BUY whose plan failed a check (REVIEW reasons shown, cannot be approved).
With auto-approve on (the paper-trading default, ⚙), requests are approved as they are filed and
recorded as automatic; the CEO's buttons then record an opinion only (kept apart, never changes the
book), so the paper results measure the model alone. An approval books a simulated order in the
paper book (paper/book.py); nothing is sent anywhere.
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
from stock_office.paper.allocator import POLICY, POLICY_V3, Policy, allocate
from stock_office.paper.book import Book
from stock_office.plan_extract import build_buy_plan, daily_bars, parse_labels
from stock_office.runs.repository import RunRepository

FxSource = Callable[[], tuple[Decimal, datetime] | None]  # KRW per USD and when it was observed

ACTION_KO = {"BUY": "매수", "SELL": "매도", "HOLD": "유지", "REVIEW": "판단 보류"}
AUTO_COMMENT = "자동 승인 (모의투자 기간: 결재안을 그대로 따름)"


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
    paper: list[dict[str, Any]] = []  # simulated orders this document produced (internal book)
    mock_orders: list[dict[str, Any]] = []  # orders on the Kiwoom mock account (국장/미장 desks)
    auto_approved: bool = False
    ceo_opinion: str | None = None  # approve/reject/defer on an auto-approved request
    opinion_open: bool = False      # auto-approved and still within its deadline


def _iso(dt: datetime | None) -> str | None:
    # Fixed width (UTC, microseconds) so stored timestamps also compare correctly as text.
    return dt.astimezone(UTC).isoformat(timespec="microseconds") if dt else None


def _dt(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def next_session_close(market: Market, now: datetime) -> datetime:
    """First session close of the instrument's exchange strictly after `now`."""
    from stock_office.schedule import MARKET_CALENDAR, _calendar

    cal = _calendar(MARKET_CALENDAR[market])
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
        book: Book | None = None,
        book_demo_runs: bool = False,
        desks: Any = None,
        accounts: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> None:
        self.conn, self.repo, self.policy, self.fx = conn, repo, policy, fx
        self.book = book or Book(conn, policy)
        # DEMO meetings use fixture prices: they never reach the paper book (tests opt in).
        self.book_demo_runs = book_demo_runs
        # The Kiwoom mock desks (stock_office.kiwoom_mock.desks.Desks) and a cached read of each
        # desk's account. When a desk is connected, real meetings of that market trade there; the
        # internal paper book keeps only DEMO meetings (tests) and orders it already holds.
        self.desks = desks
        self.accounts = accounts

    def _books(self, demo: bool) -> bool:
        return not demo or self.book_demo_runs

    def _kiwoom(self, market: Market, demo: bool) -> bool:
        return (not demo and self.desks is not None
                and self.desks.clients(market.value) is not None)

    def _account(self, market: Market) -> dict[str, Any] | None:
        try:
            acc = self.accounts(market.value) if self.accounts else None
        except Exception:
            return None
        return acc if acc and acc.get("ok") else None

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
        # A meeting's result: what the committee concluded, and plainly whether anything happens.
        title = (f"[회의 결과] {name} · "
                 f"{ACTION_KO.get(decision.action.value, decision.action.value)} 의견")
        kiwoom = self._kiwoom(inst.market, run.demo)
        position = None
        if kiwoom:
            acc = self._account(inst.market)
            held = [h for h in (acc or {}).get("holdings", [])
                    if h.get("code") == inst.symbol and Decimal(h.get("qty") or 0) > 0]
            if held:
                position = held[0]
        elif self._books(run.demo):
            position = self.book.position(inst.id)
        if decision.action is DecisionAction.SELL and position is not None and kiwoom:
            kind, status = "approval", "PENDING"
            expires = next_session_close(inst.market, decision.created_at)
            if expires <= now:
                status = "EXPIRED"
                payload["filed_late"] = True
            ccy = "USD" if inst.market is Market.US else "KRW"
            plan_body = {
                "side": "SELL", "venue": "kiwoom_mock", "currency": ccy, "account_currency": ccy,
                "qty": position.get("qty"), "avg_price": position.get("avg_price"),
                "last_price": position.get("price"), "value_krw": position.get("value"),
                "cost_krw": None, "last_fx": "1", "marked_session": "",
                "rating": decision.engine_rating, "policy_version": POLICY_V3.version,
                "valid_until": _iso(expires),
                "execution": "승인되면 장중에 키움 모의 계좌에서 전량 매도 (현재가 근처 지정가)",
            }
            title = f"[결재] {name} 전량 매도 {format_qty(position.get('qty') or '0')}주"
        elif decision.action is DecisionAction.SELL and position is not None:
            kind, status = "approval", "PENDING"
            expires = next_session_close(inst.market, decision.created_at)
            if expires <= now:
                status = "EXPIRED"
                payload["filed_late"] = True
            plan_body = {
                "side": "SELL", "currency": position["currency"], "qty": position["qty"],
                "avg_price": position["avg_price"], "cost_krw": position["cost_krw"],
                "last_price": position["last_price"], "last_fx": position["last_fx"],
                "marked_session": position["marked_session"],
                "value_krw": self.book.value_krw(position), "rating": decision.engine_rating,
                "policy_version": self.policy.version, "valid_until": _iso(expires),
                "execution": "승인되면 다음 장 시가에 전량 매도 (모의)",
            }
            title = f"[결재] {name} 전량 매도 {format_qty(position['qty'])}주"
        elif decision.action is DecisionAction.SELL:
            payload["note"] = (
                "리서치팀이 고른 회의 종목이지만 보유하지 않아 매도할 것이 없습니다. 회의 결과만 "
                "보고합니다 (공매도는 하지 않음)."
            )
            title += " · 미보유라 주문 없음"
        if decision.action is DecisionAction.HOLD and position is not None and kiwoom:
            change, notes = self._adjust_plan(run, inst.id, position)
            if notes:
                payload["note"] = " ".join(notes)
            if change is not None:
                kind, status = "approval", "PENDING"
                expires = next_session_close(inst.market, decision.created_at)
                if expires <= now:
                    status = "EXPIRED"
                    payload["filed_late"] = True
                plan_body = {**change, "valid_until": _iso(expires)}
                held_qty = format_qty(position.get("qty") or "0")
                title = f"[결재] {name} 손절가·목표가 변경 (보유 {held_qty}주)"
        if decision.action is DecisionAction.BUY:
            plan_body, reasons = self._buy_plan(run, inst.market, decision.engine_rating, kiwoom)
            if plan_body is not None:
                plan_body["side"] = "BUY"
            if plan_body and not reasons:
                kind, status = "approval", "PENDING"
                # The deadline belongs to the meeting: the next close after it was decided.
                expires = next_session_close(inst.market, decision.created_at)
                if expires <= now:
                    status = "EXPIRED"
                    payload["filed_late"] = True
                qty_text = format_qty(plan_body['allocation']['qty'])
                if kiwoom and position is not None:   # a held stock's re-check: add a tranche
                    plan_body["add_on"] = True
                    plan_body["held_qty"] = position.get("qty")
                    title = (f"[결재] {name} 추가 매수 {qty_text}주 "
                             f"(보유 {format_qty(position.get('qty') or '0')}주)")
                else:
                    title = f"[결재] {name} 매수 {qty_text}주"
                plan_body["valid_until"] = _iso(expires)
            else:
                title = f"[검토 필요] {name} 매수 제안"
                payload["review_reasons"] = reasons
        if (kiwoom and position is None and kind != "approval"
                and decision.action is not DecisionAction.BUY):
            # Nothing to do (no holding, not a buy). Still reported (owner, 2026-11-06, replacing
            # 2026-10-20's records-only): what the company looked at and why it passed.
            payload.setdefault("note", "보유하지 않은 종목이고 매수 의견이 아니라 주문은 없습니다. "
                                       "검토 내용은 회의록에 있습니다.")
            if decision.action is not DecisionAction.SELL:
                title += " · 주문 없음"
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
                        plan_body.get("side", "BUY"),
                        json.dumps(_jsonable(plan_body), ensure_ascii=False),
                        self.policy.version,
                        _iso(expires),
                    ),
                )
        if status == "PENDING" and self.book.auto_approve() and self._books(run.demo):
            self.decide(item_id, "approve", AUTO_COMMENT, f"auto:{item_id}", now)
        return item_id

    def _labels(self, run: AnalysisRun) -> Any:
        reports = self.repo.get_reports(run.id)
        if reports:
            return parse_labels(reports.get("trader", ""), reports.get("portfolio_manager", ""))
        decision = self.repo.get_decision(run.id)
        return parse_labels("", decision.rationale if decision else "")

    def _adjust_plan(self, run: AnalysisRun, instrument_id: str, position: dict[str, Any]
                     ) -> tuple[dict[str, Any] | None, list[str]]:
        """A held stock's meeting said 유지 and gave its own stop/target: a change plan, through
        the rule that a stop only ever goes up (owner, 2026-10-21)."""
        open_ = self.desks.position(instrument_id) if self.desks else None
        if open_ is None:
            return None, []
        labels = self._labels(run)
        price = Decimal(str(position.get("price") or 0))
        stop, target = Decimal(open_["stop"]), Decimal(open_["target"])
        new_stop = Decimal(str(labels.stop)) if labels.stop is not None else None
        new_target = Decimal(str(labels.target)) if labels.target is not None else None
        notes: list[str] = []
        cur = open_["currency"]
        if new_stop is not None and new_stop < stop:
            notes.append(f"AI가 손절가를 {new_stop}로 낮추자고 했지만 손절가는 올리기만 허용해 "
                         f"기존 {stop}를 유지합니다.")
            new_stop = None
        if new_stop is not None and price and new_stop >= price:
            notes.append(f"AI 제시 손절가 {new_stop}가 현재가 {price} 이상이라 반영하지 않습니다.")
            new_stop = None
        if new_target is not None and price and new_target <= price:
            notes.append(f"AI 제시 목표가 {new_target}가 현재가 {price} 이하라 반영하지 않습니다.")
            new_target = None
        if new_stop == stop:
            new_stop = None
        if new_target == target:
            new_target = None
        if new_stop is None and new_target is None:
            return None, notes
        return {"side": "ADJUST", "venue": "kiwoom_mock", "currency": cur,
                "account_currency": cur, "stop_from": str(stop), "target_from": str(target),
                "stop": str(new_stop or stop), "target": str(new_target or target),
                "qty": position.get("qty"), "avg_price": open_.get("avg_price"),
                "last_price": str(price), "policy_version": POLICY_V3.version,
                "rule": "손절가는 올리기만 허용 (손절가 < 현재가 < 목표가)",
                "execution": "승인되면 보유 중인 전체 수량의 손절가·목표가를 바꿉니다"}, notes

    def position_context(self, instrument_id: str) -> str | None:
        """What a held stock's meeting is told: the position now and our earlier plans with what
        became of them. None when the stock is not held on its Kiwoom mock account."""
        inst = get_instrument(instrument_id)
        if self.desks is None or not self._kiwoom(inst.market, False):
            return None
        acc = self._account(inst.market)
        if acc is None:
            return None
        held = [h for h in acc.get("holdings", [])
                if h.get("code") == inst.symbol and Decimal(h.get("qty") or 0) > 0]
        open_ = self.desks.position(instrument_id)
        if not held or open_ is None:
            return None
        h, cur = held[0], open_["currency"]

        def m(x: Any) -> str:
            return "—" if x in (None, "") else (f"${Decimal(str(x)):,.2f}" if cur == "USD"
                                                 else f"{Decimal(str(x)):,.0f}원")

        nav = Decimal(str(acc.get("cash") or 0)) + Decimal(str(acc.get("total_value") or 0))
        weight = (Decimal(str(h.get("value") or 0)) / nav * 100) if nav else Decimal(0)
        lines = [
            "## Stock Office 보유 현황 (키움 모의 계좌, 회의 시작 시점)",
            f"- 보유 {h.get('qty')}주 · 평균 단가 {m(open_.get('avg_price'))} · 현재가 "
            f"{m(h.get('price'))} · 평가 손익 {h.get('pnl_pct') or '—'}%",
            f"- 손절가 {m(open_['stop'])} · 목표가 {m(open_['target'])}"
            + (" · 손절가를 매수가로 올린 상태(본전 손절)" if open_.get("breakeven") else ""),
            f"- 계좌 대비 비중 {weight:.1f}% (종목당 한도 20%) · 첫 체결 {open_.get('since', '—')}",
            "",
            "## 이전 결재안과 결과 (오래된 순)",
        ]
        for r in self.conn.execute(
                "SELECT i.id, i.title, i.summary, i.created_at, i.status, p.body "
                "FROM inbox_items i JOIN plans p ON p.item_id=i.id "
                "WHERE i.instrument_id=? AND i.kind='approval' "
                "ORDER BY i.id DESC LIMIT 3", (instrument_id,)).fetchall()[::-1]:
            body = json.loads(r["body"])
            orders = self.desks.orders(item_id=r["id"])
            done = "; ".join(f"{o['role']} {o['status']}"
                             + (f" @ {m(o['fill_price'])}" if o.get("fill_price") else "")
                             for o in orders) or "주문 없음"
            lines.append(f"- {r['created_at'][:10]} {r['title']} · 진입 {m(body.get('limit'))} / "
                         f"손절 {m(body.get('stop'))} / 목표 {m(body.get('target'))} → {done}"
                         + (f" · 근거: {r['summary'][:160]}" if r["summary"] else ""))
        lines += [
            "",
            "## 지시",
            "- 위 이전 판단은 참고 자료일 뿐이다. 오늘의 데이터로 처음부터 다시 판단하고, "
            "이전 근거가 틀렸다면 그렇다고 분명히 말하라.",
            "- 결론은 보유 기준으로: Buy/Overweight = 추가 매수, Hold = 유지, "
            "Underweight/Sell = 전량 매도.",
            "- 유지라면 지금 상황에 맞는 손절가(Stop Loss)와 목표가(Price Target)를 숫자로 "
            "제시하라. 단, 회사 규칙상 손절가는 올리기만 할 수 있다.",
        ]
        return "\n".join(lines)

    def _buy_plan(
        self, run: AnalysisRun, market: Market, rating: str | None, kiwoom: bool = False
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
        if kiwoom:
            return self._kiwoom_plan(run, market, rating, draft, reasons)
        if market is Market.US:
            got = self.fx() if self.fx else None
            if got is None:
                reasons.append("원/달러 환율을 구하지 못해 금액을 계산할 수 없음")
            else:
                fx_rate, fx_at = got
        # The paper book as it is now (DEMO meetings: the starting account, untouched).
        books = self._books(run.demo)
        nav = self.book.nav_krw() if books else self.policy.initial_equity_krw
        cash = self.book.cash_krw() - self.book.reserved_krw() if books else nav
        held = Decimal(0)
        if books:
            pos = self.book.position(run.instrument_id)
            held = (self.book.value_krw(pos) if pos else Decimal(0)) + \
                self.book.reserved_krw(run.instrument_id)
        alloc = allocate(
            self.policy,
            nav_krw=nav,
            cash_krw=cash,
            held_krw=held,
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
            "account_basis": "모의 계좌 현재 상태 기준 (승인 시 다시 계산)"
            if books else "DEMO: 가상 계좌 시작 금액 기준 (모의 주문 없음)",
        }
        return body, reasons

    def _kiwoom_plan(self, run: AnalysisRun, market: Market, rating: str | None, draft: Any,
                     reasons: list[str]) -> tuple[dict[str, Any] | None, list[str]]:
        """Plan sized on the desk's own Kiwoom mock account (POLICY_V3: own currency, whole shares).
        The desk sizes it again on the live account when the order is placed."""
        cur = "USD" if market is Market.US else "KRW"
        acc = self._account(market)
        if acc is not None:
            nav = Decimal(acc.get("cash") or 0) + Decimal(acc.get("total_value") or 0)
            cash = Decimal(acc.get("orderable") or acc.get("cash") or 0)
            held = sum((Decimal(h.get("value") or 0) for h in acc.get("holdings", [])
                        if h.get("code") == get_instrument(run.instrument_id).symbol), Decimal(0))
            basis = "키움 모의 계좌 현재 상태 기준 (주문 직전에 다시 계산)"
        else:
            start = self.desks.start_equity(market.value) if self.desks else None
            nav = cash = start or (Decimal(100_000) if cur == "USD" else Decimal(10_000_000))
            held = Decimal(0)
            basis = "키움 모의 계좌 조회 실패: 시작 자산 기준으로 표시 (주문 직전에 다시 계산)"
        if self.desks is not None and self.desks.open_buy(run.instrument_id):
            reasons.append("같은 종목의 매수 주문이 아직 체결 전이라 추가 매수를 올리지 않음")
        alloc = allocate(POLICY_V3, nav_krw=nav, cash_krw=cash, held_krw=held,
                         rating=rating or draft.rating, multiplier=draft.multiplier,
                         limit=draft.limit, stop=draft.stop, fx_krw=Decimal(1), currency=cur,
                         account_currency=cur)
        if alloc.blocked:
            reasons.append(alloc.blocked)
        body = {
            "venue": "kiwoom_mock", "currency": cur, "account_currency": cur,
            "limit": draft.limit, "stop": draft.stop, "target": draft.target,
            "sources": draft.sources, "ref_price": draft.ref_price, "ref_at": draft.ref_at,
            "atr": draft.atr, "stop_distance": draft.stop_distance,
            "multiplier": draft.multiplier, "multiplier_source": draft.multiplier_source,
            "rating": rating or draft.rating, "sizing_text": draft.sizing_text,
            "horizon": draft.horizon, "fx_krw_per_unit": Decimal(1), "fx_at": None,
            "allocation": asdict(alloc), "policy_version": POLICY_V3.version,
            "account_basis": basis,
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
        item.auto_approved = item.status == "APPROVED" and self.conn.execute(
            "SELECT 1 FROM approvals WHERE item_id=? AND client_request_id LIKE 'auto:%'",
            (item.id,)).fetchone() is not None
        if item.auto_approved:
            item.ceo_opinion = self._opinion(item.id)
            item.opinion_open = self._opinion_open(item.id, datetime.now(UTC))
        if plan:
            item.plan = json.loads(plan["body"])
        if detail:
            item.approvals = [
                {"action": r["action"], "comment": r["comment"], "decided_at": r["decided_at"],
                 "auto": str(r["client_request_id"]).startswith("auto:"),
                 "opinion": r["kind"] == "opinion"}
                for r in self.conn.execute(
                    "SELECT action, comment, client_request_id, decided_at, kind FROM approvals "
                    "WHERE item_id=? ORDER BY id",
                    (item.id,),
                )
            ]
        if item.kind == "approval":
            item.paper = self.book.orders_for_item(item.id)
            if self.desks is not None:
                item.mock_orders = self.desks.orders(item_id=item.id)
        return item

    def ops_start(self) -> str | None:
        """When the company started operating (research team live). Earlier documents are the
        development/test period: kept, but not shown in the inbox (records can show them)."""
        row = self.conn.execute(
            "SELECT value FROM company_settings WHERE key='ops_start'").fetchone()
        return str(row["value"]) if row else None

    def briefings(self, limit: int = 20) -> list[InboxItem]:
        """The news tab: market briefings, newest first (each stays; two new ones a day)."""
        rows = self.conn.execute(
            "SELECT * FROM inbox_items WHERE dedupe_key LIKE 'market-briefing:%' "
            "ORDER BY created_at DESC, id DESC LIMIT ?", (min(max(limit, 1), 100),))
        return [self._row(r) for r in rows]

    def list(self, limit: int = 100, include_test: bool = False) -> list[InboxItem]:
        """Decisions and reports. Market briefings live in the news tab (`briefings`)."""
        start = None if include_test else self.ops_start()
        rows = self.conn.execute(
            "SELECT * FROM inbox_items WHERE created_at >= ? "
            "AND dedupe_key NOT LIKE 'market-briefing:%' "
            "ORDER BY created_at DESC, id DESC LIMIT ?", (start or "", limit)
        )
        return [self._row(r) for r in rows]

    def get(self, item_id: int) -> InboxItem | None:
        row = self.conn.execute("SELECT * FROM inbox_items WHERE id=?", (item_id,)).fetchone()
        return self._row(row, detail=True) if row else None

    def by_run(self) -> dict[str, dict[str, Any]]:
        """run_id → approval outcome and what the paper book did with it (records list)."""
        out: dict[str, dict[str, Any]] = {}
        for r in self.conn.execute(
            "SELECT i.run_id, i.status, "
            "(SELECT client_request_id FROM approvals a WHERE a.item_id=i.id "
            " AND a.action='approve' AND a.kind='decision') AS approved_by, "
            "(SELECT action FROM approvals a WHERE a.item_id=i.id AND a.kind='opinion' "
            " ORDER BY a.id DESC LIMIT 1) AS opinion, "
            "COALESCE((SELECT status FROM km_orders k WHERE k.item_id=i.id "
            " AND k.role IN ('entry','exit')), (SELECT status FROM paper_orders o "
            " WHERE o.item_id=i.id AND o.role IN ('entry','exit'))) AS paper "
            "FROM inbox_items i WHERE i.run_id IS NOT NULL"
        ):
            out[r["run_id"]] = {
                "status": r["status"],
                "auto": str(r["approved_by"] or "").startswith("auto:"),
                "paper": r["paper"],
                "opinion": r["opinion"],
            }
        return out

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
            elif self._opinion_open(item_id, now):
                # Auto-approved: the order follows the model; the CEO's view is recorded beside it.
                self.conn.execute(
                    "INSERT INTO approvals (item_id, action, comment, client_request_id, "
                    "decided_at, kind) VALUES (?,?,?,?,?, 'opinion')",
                    (item_id, action, comment[:500], client_request_id, _iso(now)),
                )
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
                if status == "APPROVED":
                    self._book_approved(item_id, now)
        item = self.get(item_id)
        assert item is not None
        return item

    def _opinion(self, item_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT action FROM approvals WHERE item_id=? AND kind='opinion' ORDER BY id DESC",
            (item_id,)).fetchone()
        return row["action"] if row else None

    def _opinion_open(self, item_id: int, now: datetime) -> bool:
        """Auto-approved, before its deadline, and the CEO has not agreed or objected yet."""
        row = self.conn.execute(
            "SELECT i.expires_at FROM inbox_items i JOIN approvals a ON a.item_id=i.id "
            "WHERE i.id=? AND i.status='APPROVED' AND a.client_request_id LIKE 'auto:%'",
            (item_id,)).fetchone()
        if row is None or (row["expires_at"] and row["expires_at"] <= _iso(now)):
            return False
        return self._opinion(item_id) in (None, "defer")

    def _book_approved(self, item_id: int, now: datetime) -> None:
        """Approved plan → a WAITING order on the Kiwoom mock desk (no network here; the worker
        places it during the session), or a simulated order in the internal paper book."""
        row = self.conn.execute(
            "SELECT i.instrument_id, i.payload, i.expires_at, p.side, p.body FROM inbox_items i "
            "JOIN plans p ON p.item_id = i.id WHERE i.id=?", (item_id,)).fetchone()
        if row is None:
            return
        body = json.loads(row["body"])
        if body.get("venue") == "kiwoom_mock" and self.desks is not None:
            if row["side"] == "SELL":
                self.desks.queue_exit(item_id, row["instrument_id"], row["expires_at"], now)
            elif row["side"] == "ADJUST":
                self.desks.adjust(item_id, row["instrument_id"], body, now)
            else:
                self.desks.queue_entry(item_id, row["instrument_id"], body, row["expires_at"], now)
            return
        if not self._books(bool(json.loads(row["payload"]).get("demo"))):
            return
        if row["side"] == "SELL":
            self.book.book_exit(item_id, row["instrument_id"], now)
        else:
            self.book.open_bracket(item_id, row["instrument_id"], json.loads(row["body"]), now)

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
