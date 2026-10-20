"""The paper book: KRW cash ledger, simulated orders, positions and the reports they produce.

Nothing here talks to any outside service. An approved plan becomes a simulated buy limit for
the next session ("entry"); its fill (paper/settle.py) adds a take-profit and a stop for the same
quantity, one cancelling the other. A CEO-approved sell becomes a sell at the next open ("exit").
Before booking, the allocator runs again on the book's current cash and holdings, so the
company policy holds against the real state, not the state at filing time.

Methods that write expect to run inside the caller's transaction (db.transaction).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from stock_office.domain.instruments import display_name, get_instrument
from stock_office.paper.allocator import POLICY, Policy, allocate
from stock_office.paper.costs import COSTS, Costs
from stock_office.schedule import first_session_opening_after

ROLE_KO = {"entry": "매수", "take_profit": "익절", "stop": "손절", "exit": "매도"}


def iso(dt: datetime | None) -> str | None:
    # Fixed width (UTC, microseconds) so stored timestamps also compare correctly as text.
    return dt.astimezone(UTC).isoformat(timespec="microseconds") if dt else None


def D(text: Any) -> Decimal:
    return Decimal(str(text)) if text is not None else Decimal(0)


def qty_text(qty: Decimal | str) -> str:
    return format(Decimal(str(qty)).normalize(), "f")


def money_text(amount: Decimal, currency: str) -> str:
    if currency == "KRW":
        return f"{amount:,.0f}원"
    return f"${amount:,.2f}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


class Book:
    def __init__(self, conn: sqlite3.Connection, policy: Policy = POLICY,
                 costs: Costs = COSTS) -> None:
        self.conn, self.policy, self.costs = conn, policy, costs

    # ---------------------------------------------------------------- company settings
    def setting(self, key: str, default: str) -> str:
        row = self.conn.execute("SELECT value FROM company_settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def auto_approve(self) -> bool:
        return self.setting("auto_approve", "1") == "1"

    def set_auto_approve(self, enabled: bool, now: datetime) -> None:
        self.conn.execute(
            "INSERT INTO company_settings (key, value, updated_at) VALUES ('auto_approve', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            ("1" if enabled else "0", iso(now)),
        )

    # ---------------------------------------------------------------- state
    def started_at(self) -> datetime | None:
        row = self.conn.execute(
            "SELECT created_at FROM paper_cash WHERE ref='initial'").fetchone()
        return datetime.fromisoformat(row["created_at"]) if row else None

    def ensure_started(self, now: datetime) -> None:
        """The paper account opens with the policy's initial equity, once."""
        self.conn.execute(
            "INSERT OR IGNORE INTO paper_cash (amount_krw, reason, ref, created_at) "
            "VALUES (?, '가상 계좌 시작 금액', 'initial', ?)",
            (str(self.policy.initial_equity_krw), iso(now)),
        )

    def cash_krw(self) -> Decimal:
        rows = self.conn.execute("SELECT amount_krw FROM paper_cash")
        total = sum((D(r["amount_krw"]) for r in rows), Decimal(0))
        return total if self.started_at() else self.policy.initial_equity_krw

    def reserved_krw(self, instrument_id: str | None = None) -> Decimal:
        sql = "SELECT reserved_krw FROM paper_orders WHERE status='OPEN' AND role='entry'"
        args: tuple[Any, ...] = ()
        if instrument_id:
            sql, args = sql + " AND instrument_id=?", (instrument_id,)
        return sum((D(r["reserved_krw"]) for r in self.conn.execute(sql, args)), Decimal(0))

    def position(self, instrument_id: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM paper_positions WHERE instrument_id=?", (instrument_id,)).fetchone()
        return row

    def positions(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM paper_positions ORDER BY opened_at"))

    @staticmethod
    def value_krw(pos: sqlite3.Row) -> Decimal:
        return (D(pos["qty"]) * D(pos["last_price"]) * D(pos["last_fx"])).quantize(Decimal(1))

    def nav_krw(self) -> Decimal:
        return self.cash_krw() + sum((self.value_krw(p) for p in self.positions()), Decimal(0))

    # ---------------------------------------------------------------- reports to the inbox
    def notice(self, *, kind: str, instrument_id: str, title: str, summary: str,
               payload: dict[str, Any], dedupe: str, now: datetime,
               run_id: str | None = None) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO inbox_items (kind, run_id, instrument_id, title, summary, "
            "payload, status, dedupe_key, created_at) VALUES (?,?,?,?,?,?, 'INFO', ?, ?)",
            (kind, run_id, instrument_id, title, summary,
             json.dumps(_jsonable(payload), ensure_ascii=False), dedupe, iso(now)),
        )

    # ---------------------------------------------------------------- booking
    def _insert_order(self, **o: Any) -> int:
        cols = ", ".join(o)
        cur = self.conn.execute(
            f"INSERT INTO paper_orders ({cols}) VALUES ({', '.join('?' for _ in o)})",
            tuple(_jsonable(v) if isinstance(v, Decimal | datetime) else v for v in o.values()),
        )
        return int(cur.lastrowid or 0)

    def open_bracket(self, item_id: int, instrument_id: str, plan: dict[str, Any],
                     now: datetime) -> int:
        """Approved BUY plan → simulated buy limit for the next session. Idempotent per document.

        Returns the order id (status OPEN, or REJECTED when the policy refuses it now)."""
        key = f"entry:{item_id}"
        seen = self.conn.execute(
            "SELECT id FROM paper_orders WHERE idempotency_key=?", (key,)).fetchone()
        if seen:
            return int(seen["id"])
        self.ensure_started(now)
        inst = get_instrument(instrument_id)
        currency = str(plan.get("currency") or inst.currency)
        limit, stop, target = D(plan["limit"]), D(plan["stop"]), D(plan["target"])
        fx = D(plan.get("fx_krw_per_unit") or 1)
        nav = self.nav_krw()
        held = sum((self.value_krw(p) for p in self.positions()
                    if p["instrument_id"] == instrument_id), Decimal(0))
        alloc = allocate(
            self.policy, nav_krw=nav, cash_krw=self.cash_krw() - self.reserved_krw(),
            held_krw=held + self.reserved_krw(instrument_id), rating=plan.get("rating"),
            multiplier=D(plan.get("multiplier") or "0.5"), limit=limit, stop=stop, fx_krw=fx,
            currency=currency,
        )
        session = first_session_opening_after(inst.market, now)
        status, reason = ("REJECTED", alloc.blocked) if alloc.blocked else ("OPEN", "")
        reserved = (limit * alloc.qty * fx * (1 + self.policy.fee_rate)).quantize(Decimal(1))
        order_id = self._insert_order(
            item_id=item_id, instrument_id=instrument_id, market=inst.market.value,
            currency=currency, role="entry", side="BUY", qty=qty_text(alloc.qty),
            price=str(limit), reserved_krw=str(reserved if status == "OPEN" else 0),
            status=status, reason=reason or "",
            detail=json.dumps(_jsonable({
                "stop": stop, "target": target, "fx_at_approval": fx, "nav_krw": nav,
                "allocation": asdict(alloc), "session": session.day.isoformat(),
            }), ensure_ascii=False),
            active_from=iso(session.open), valid_until=iso(session.close),
            idempotency_key=key, created_at=iso(now),
            closed_at=iso(now) if status == "REJECTED" else None,
        )
        name = display_name(instrument_id)
        if status == "REJECTED":
            self.notice(
                kind="execution", instrument_id=instrument_id,
                title=f"[리스크 거절] {name} 매수", summary=str(reason),
                payload={"order_id": order_id, "role": "entry", "status": status,
                         "reason": reason, "item_id": item_id},
                dedupe=f"order:{order_id}:rejected", now=now)
        return order_id

    def book_exit(self, item_id: int, instrument_id: str, now: datetime) -> int | None:
        """Approved SELL → sell the whole position at the next session's open."""
        key = f"exit:{item_id}"
        seen = self.conn.execute(
            "SELECT id FROM paper_orders WHERE idempotency_key=?", (key,)).fetchone()
        if seen:
            return int(seen["id"])
        pos = self.position(instrument_id)
        if pos is None:
            return None
        inst = get_instrument(instrument_id)
        session = first_session_opening_after(inst.market, now)
        return self._insert_order(
            item_id=item_id, instrument_id=instrument_id, market=inst.market.value,
            currency=pos["currency"], role="exit", side="SELL", qty=pos["qty"], price=None,
            status="OPEN", detail=json.dumps({"session": session.day.isoformat()}),
            active_from=iso(session.open), valid_until=iso(session.close),
            idempotency_key=key, created_at=iso(now),
        )

    # ---------------------------------------------------------------- reading
    def _order_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        out = {k: row[k] for k in row.keys() if k != "detail"}  # noqa: SIM118 (sqlite3.Row)
        out["detail"] = json.loads(row["detail"] or "{}")
        out["name"] = display_name(row["instrument_id"])
        fill = self.conn.execute(
            "SELECT * FROM paper_fills WHERE order_id=?", (row["id"],)).fetchone()
        out["fill"] = dict(fill) if fill else None
        return out

    def orders_for_item(self, item_id: int) -> list[dict[str, Any]]:
        """The document's orders and the exit pair its entry produced."""
        rows = self.conn.execute(
            "SELECT * FROM paper_orders WHERE item_id=? OR parent_id IN "
            "(SELECT id FROM paper_orders WHERE item_id=?) ORDER BY id", (item_id, item_id))
        return [self._order_dict(r) for r in rows]

    def activity(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM paper_orders ORDER BY COALESCE(closed_at, created_at) DESC, id DESC "
            "LIMIT ?", (limit,))
        return [self._order_dict(r) for r in rows]

    def last_settles(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT market, session, status, note, created_at FROM settle_runs s1 WHERE session ="
            " (SELECT MAX(session) FROM settle_runs s2 WHERE s2.market = s1.market)")
        return [dict(r) for r in rows]

    def portfolio(self) -> dict[str, Any]:
        cash, reserved = self.cash_krw(), self.reserved_krw()
        holdings = []
        for p in self.positions():
            value, cost = self.value_krw(p), D(p["cost_krw"])
            exits = {r["role"]: D(r["price"]) for r in self.conn.execute(
                "SELECT role, price FROM paper_orders WHERE instrument_id=? AND status='OPEN' "
                "AND role IN ('take_profit','stop') ORDER BY id", (p["instrument_id"],))}
            holdings.append({
                "instrument_id": p["instrument_id"], "name": display_name(p["instrument_id"]),
                "currency": p["currency"], "qty": p["qty"], "avg_price": p["avg_price"],
                "last_price": p["last_price"], "last_fx": p["last_fx"],
                "marked_session": p["marked_session"], "value_krw": str(value),
                "cost_krw": str(cost), "pnl_krw": str(value - cost),
                "pnl_pct": str(((value - cost) / cost * 100).quantize(Decimal("0.01")))
                if cost else "0",
                "take_profit": str(exits["take_profit"]) if "take_profit" in exits else None,
                "stop": str(exits["stop"]) if "stop" in exits else None,
            })
        nav = cash + sum((D(h["value_krw"]) for h in holdings), Decimal(0))
        initial = self.policy.initial_equity_krw
        pending = [self._order_dict(r) for r in self.conn.execute(
            "SELECT * FROM paper_orders WHERE status='OPEN' AND role IN ('entry','exit') "
            "ORDER BY active_from")]
        realized = sum((D(r["realized_krw"]) for r in self.conn.execute(
            "SELECT realized_krw FROM paper_fills WHERE realized_krw IS NOT NULL")), Decimal(0))
        return {
            "started_at": self.started_at(), "initial_krw": str(initial),
            "cash_krw": str(cash), "reserved_krw": str(reserved), "nav_krw": str(nav),
            "return_pct": str(((nav - initial) / initial * 100).quantize(Decimal("0.01"))),
            "realized_krw": str(realized), "cash_weight_pct": str(
                (cash / nav * 100).quantize(Decimal("0.1")) if nav else Decimal(0)),
            "holdings": holdings, "pending": pending, "last_settles": self.last_settles(),
            "costs": self.costs.describe(), "auto_approve": self.auto_approve(),
            "policy_version": self.policy.version,
        }
