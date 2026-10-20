"""The two Kiwoom mock desks (국장, 미장): approved plans become orders on Kiwoom's MOCK server.

Flow (deterministic; no model output reaches an order):
1. Approval (inside the inbox transaction, no network): `queue_entry` / `queue_exit` record a
   WAITING order with the approved limit, stop and target.
2. Worker `tick`, only while that market's regular session is open (Kiwoom mock: regular hours):
   - expire: WAITING past its deadline → EXPIRED; SENT past its deadline → cancel at Kiwoom.
   - sync: read today's orders from Kiwoom; fills move SENT → FILLED (Kiwoom is the truth).
   - send: size each WAITING entry again on the live account (POLICY_V3, own currency, whole shares,
     loss-limit stop); SENDING is committed before the request, so a crash can never send twice
     (a SENDING row left behind becomes REVIEW for a person to check).
   - watch: a filled entry still held at Kiwoom is sold when the price reaches its stop or target
     (marketable limit order); an unfilled exit is cancelled after a few minutes and re-placed.
3. After each close, `record_nav` stores the account value and the benchmark close (evaluation).
Every step that changes something files an inbox report. MOCK ONLY: the client can reach nothing
but Kiwoom's mock server.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from stock_office.db import transaction
from stock_office.domain.instruments import display_name, get_instrument
from stock_office.domain.models import Market
from stock_office.kiwoom_mock.accounts import MockAccount, kr_account, num, us_account
from stock_office.kiwoom_mock.client import KiwoomMockClient, KiwoomMockError
from stock_office.paper.allocator import POLICY_V3, Policy, allocate
from stock_office.schedule import closed_sessions, open_session

KST = ZoneInfo("Asia/Seoul")

log = logging.getLogger("stock_office.kiwoom_mock")
D = Decimal

# Kiwoom API ids per desk: order path, buy, sell, cancel.
ORDER_API = {"KR": ("/api/dostk/ordr", "kt10000", "kt10001", "kt10003"),
             "US": ("/api/us/ordr", "ust20000", "ust20001", "ust20003")}
US_EXCHANGE = {"NASDAQ": "ND", "NYSE": "NY", "AMEX": "NA"}
OPEN = ("WAITING", "SENDING", "SENT")
EXIT_RETRY = timedelta(minutes=3)   # an unfilled exit is re-placed at the new price after this
MAX_DRAWDOWN = D("0.10")            # IPS: no new buys once the account is 10% below its start
BENCHMARK = {"KR": "^KS11", "US": "^NDX"}  # KOSPI, NASDAQ-100
ROLE_KO = {"entry": "매수", "take_profit": "익절", "stop": "손절", "exit": "매도"}


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def money(amount: Decimal | str | None, currency: str) -> str:
    if amount is None:
        return "—"
    a = D(str(amount))
    return f"${a:,.2f}" if currency == "USD" else f"{a.quantize(D(1)):,}원"


def krx_tick(price: Decimal) -> Decimal:
    from stock_office.plan_extract import krx_tick as tick
    return tick(price)


def marketable_sell(market: str, price: Decimal) -> Decimal:
    """A sell limit a little under the current price, so it fills now (no market orders in mock)."""
    if market == "US":
        return (price * D("0.995")).quantize(D("0.01"), rounding=ROUND_DOWN)
    raw = price * D("0.99")
    step = krx_tick(raw)
    return (raw / step).to_integral_value(rounding=ROUND_DOWN) * step


def _code(instrument_id: str) -> tuple[str, str]:
    """('005930', 'KRX') or ('NVDA', 'ND')."""
    inst = get_instrument(instrument_id)
    return inst.symbol, US_EXCHANGE.get(inst.exchange, "ND") if inst.market is Market.US else "KRX"


def _norm_no(no: Any) -> str:
    return str(no or "").strip().lstrip("0")


class Desks:
    def __init__(self, conn: sqlite3.Connection,
                 clients: Callable[[str], KiwoomMockClient | None],
                 policy: Policy = POLICY_V3,
                 benchmark: Callable[[str, Any], Decimal | None] | None = None) -> None:
        self.conn, self.clients, self.policy, self.benchmark = conn, clients, policy, benchmark

    # ================================================================ queue (no network)
    def queue_entry(self, item_id: int, instrument_id: str, plan: dict[str, Any],
                    valid_until: str | None, now: datetime) -> None:
        market = get_instrument(instrument_id).market.value
        self.conn.execute(
            "INSERT OR IGNORE INTO km_orders (item_id, market, instrument_id, role, side, "
            "limit_price, stop, target, currency, status, valid_until, detail, idempotency_key, "
            "created_at) VALUES (?,?,?,'entry','BUY',?,?,?,?,'WAITING',?,?,?,?)",
            (item_id, market, instrument_id, str(plan["limit"]), str(plan["stop"]),
             str(plan["target"]), "USD" if market == "US" else "KRW", valid_until,
             json.dumps({"rating": plan.get("rating"),
                         "multiplier": str(plan.get("multiplier", 1))}),
             f"km-entry:{item_id}", iso(now)))

    def queue_exit(self, item_id: int, instrument_id: str, valid_until: str | None,
                   now: datetime) -> None:
        market = get_instrument(instrument_id).market.value
        self.conn.execute(
            "INSERT OR IGNORE INTO km_orders (item_id, market, instrument_id, role, side, "
            "currency, status, valid_until, idempotency_key, created_at) "
            "VALUES (?,?,?,'exit','SELL',?,'WAITING',?,?,?)",
            (item_id, market, instrument_id, "USD" if market == "US" else "KRW", valid_until,
             f"km-exit:{item_id}", iso(now)))

    # ================================================================ reading
    def orders(self, market: str | None = None, item_id: int | None = None,
               limit: int = 200) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM km_orders WHERE 1=1", list[Any]()
        if market:
            sql += " AND market=?"
            args.append(market)
        if item_id is not None:
            sql += " AND item_id=?"
            args.append(item_id)
        rows = self.conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d["detail"] or "{}")
            d["name"] = display_name(d["instrument_id"])
            out.append(d)
        return out

    def nav_history(self, market: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM km_nav WHERE market=? ORDER BY session", (market,))]

    def start_equity(self, market: str) -> Decimal | None:
        row = self.conn.execute("SELECT value FROM company_settings WHERE key=?",
                                (f"km_start_{market}",)).fetchone()
        return D(row["value"]) if row else None

    # ================================================================ worker
    def tick(self, now: datetime) -> None:
        for market in ("KR", "US"):
            try:
                self._expire_waiting(market, now)
                if open_session(Market(market), now) is None:
                    continue
                client = self.clients(market)
                if client is None:
                    continue
                self._market_tick(market, client, now)
            except Exception:  # never stop the worker; the next tick tries again
                log.exception("kiwoom mock desk %s failed", market)

    def _market_tick(self, market: str, client: KiwoomMockClient, now: datetime) -> None:
        self._recover_sending(market, now)
        self._sync(market, client, now)
        self._expire_sent(market, client, now)
        acc = self._account(market, client)
        if acc is None:
            return
        self._ensure_start(market, acc, now)
        for row in self._rows(market, "WAITING"):
            if row["role"] == "entry":
                self._send_entry(market, client, acc, row, now)
                acc = self._account(market, client) or acc  # cash moved: size the next on fresh
            else:
                self._send_exit(market, client, acc, row, now)
        self._watch(market, client, acc, now)

    # ---------------------------------------------------------------- pieces
    def _rows(self, market: str, *status: str) -> list[sqlite3.Row]:
        marks = ",".join("?" * len(status))
        return list(self.conn.execute(
            f"SELECT * FROM km_orders WHERE market=? AND status IN ({marks}) ORDER BY id",
            (market, *status)))

    @staticmethod
    def _account(market: str, client: KiwoomMockClient) -> MockAccount | None:
        acc = kr_account(client) if market == "KR" else us_account(client)
        return acc if acc.ok else None

    def _ensure_start(self, market: str, acc: MockAccount, now: datetime) -> None:
        if self.start_equity(market) is None and acc.cash is not None:
            nav = D(acc.cash) + D(acc.total_value or 0)
            with transaction(self.conn):
                self.conn.execute(
                    "INSERT OR IGNORE INTO company_settings (key, value, updated_at) "
                    "VALUES (?,?,?)",
                    (f"km_start_{market}", str(nav), iso(now)))

    def _set(self, order_id: int, **fields: Any) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE km_orders SET {cols} WHERE id=?", (*fields.values(), order_id))

    def _notice(self, row: sqlite3.Row | dict[str, Any], kind: str, title: str, summary: str,
                key: str, now: datetime, extra: dict[str, Any] | None = None) -> None:
        payload = {"name": display_name(row["instrument_id"]), "venue": "kiwoom_mock",
                   "order_id": row["id"], "item_id": row["item_id"], **(extra or {})}
        self.conn.execute(
            "INSERT OR IGNORE INTO inbox_items (kind, run_id, instrument_id, title, summary, "
            "payload, status, dedupe_key, created_at) VALUES (?,?,?,?,?,?, 'INFO', ?, ?)",
            (kind, None, row["instrument_id"], title, summary,
             json.dumps(payload, ensure_ascii=False), f"km:{key}", iso(now)))

    def _expire_waiting(self, market: str, now: datetime) -> None:
        with transaction(self.conn):
            for row in self._rows(market, "WAITING"):
                if row["valid_until"] and row["valid_until"] <= iso(now):
                    self._set(row["id"], status="EXPIRED", closed_at=iso(now),
                              reason="기한 안에 장이 열리지 않아 주문하지 않음")
                    self._notice(row, "execution", f"[미주문] {display_name(row['instrument_id'])} "
                                 f"{ROLE_KO[row['role']]}", "기한 안에 장이 열리지 않았습니다.",
                                 f"expired:{row['id']}", now)

    def _recover_sending(self, market: str, now: datetime) -> None:
        """A request whose answer was lost (crash, timeout): never resend; a person checks it."""
        with transaction(self.conn):
            for row in self._rows(market, "SENDING"):
                if row["sent_at"] and row["sent_at"] < iso(now - timedelta(minutes=2)):
                    self._set(row["id"], status="REVIEW",
                              reason="주문 응답을 받지 못함: 키움 모의 앱에서 주문 여부 확인 필요")

    def _fills(self, market: str, client: KiwoomMockClient) -> dict[str, dict[str, Any]]:
        """Today's orders at Kiwoom by order number: filled quantity and price."""
        if market == "KR":
            today = datetime.now(KST).strftime("%Y%m%d")
            pages = client.query("/api/dostk/acnt", "kt00007", {
                "ord_dt": today, "qry_tp": "1", "stk_bond_tp": "0", "sell_tp": "0", "stk_cd": "",
                "fr_ord_no": "", "dmst_stex_tp": "KRX"})
            rows = [r for p in pages for r in p.get("acnt_ord_cntr_prps_dtl") or []]
        else:
            pages = client.query("/api/us/acnt", "ust21510",
                                 {"slby_tp": "0", "stex_tp": "", "stk_cd": ""})
            rows = [r for p in pages for r in p.get("result_list") or []]
        return {_norm_no(r.get("ord_no")): r for r in rows if isinstance(r, dict)}

    def _sync(self, market: str, client: KiwoomMockClient, now: datetime) -> None:
        sent = self._rows(market, "SENT")
        if not sent:
            return
        try:
            seen = self._fills(market, client)
        except KiwoomMockError as exc:
            log.warning("fills %s: %s", market, exc)
            return
        with transaction(self.conn):
            for row in sent:
                got = seen.get(_norm_no(row["ext_order_no"]))
                if not got:
                    continue
                filled = num(got.get("cntr_qty")) or "0"
                price = num(got.get("cntr_uv"))
                if D(filled) <= D(row["filled_qty"]):
                    continue
                self._set(row["id"], filled_qty=filled, fill_price=price)
                if D(filled) >= D(row["qty"]):
                    self._set(row["id"], status="FILLED", closed_at=iso(now))
                    self._report_fill(row, D(filled), price, now)

    def _report_fill(self, row: sqlite3.Row, qty: Decimal, price: str | None,
                     now: datetime) -> None:
        name, cur = display_name(row["instrument_id"]), row["currency"]
        if row["role"] == "entry":
            self._notice(row, "execution", f"[체결] {name} 매수 {qty:f}주 @ {money(price, cur)}",
                         f"키움 모의 계좌 · 목표가 {money(row['target'], cur)} · "
                         f"손절가 {money(row['stop'], cur)}", f"fill:{row['id']}", now)
            return
        entry = self.conn.execute("SELECT * FROM km_orders WHERE id=?",
                                  (row["parent_id"],)).fetchone() if row["parent_id"] else None
        pnl = None
        if entry is not None and entry["fill_price"] and price:
            pnl = (D(price) - D(entry["fill_price"])) * qty
            self._set(entry["id"], detail=json.dumps(
                {**json.loads(entry["detail"] or "{}"), "closed": True, "pnl": str(pnl)}))
        self._notice(row, "closing",
                     f"[청산] {name} {ROLE_KO[row['role']]} {qty:f}주 @ {money(price, cur)}"
                     + (f" · {'+' if pnl >= 0 else '−'}{money(abs(pnl), cur)}" if pnl is not None
                        else ""),
                     "키움 모의 계좌 · 수수료·세금 제외 금액(키움 체결 내역 기준)",
                     f"fill:{row['id']}", now, {"pnl": str(pnl) if pnl is not None else None})

    def _expire_sent(self, market: str, client: KiwoomMockClient, now: datetime) -> None:
        for row in self._rows(market, "SENT"):
            deadline = row["valid_until"]
            stale_exit = (row["side"] == "SELL" and row["sent_at"]
                          and row["sent_at"] < iso(now - EXIT_RETRY))
            if not ((deadline and deadline <= iso(now)) or stale_exit):
                continue
            path, _, _, cancel = ORDER_API[market]
            code, exch = _code(row["instrument_id"])
            body = ({"dmst_stex_tp": "KRX", "orig_ord_no": row["ext_order_no"], "stk_cd": code,
                     "cncl_qty": "0"} if market == "KR"
                    else {"orig_ord_no": row["ext_order_no"], "stex_tp": exch, "stk_cd": code})
            try:
                client.send(path, cancel, body)
            except KiwoomMockError as exc:  # already filled or gone: the next sync settles it
                log.warning("cancel %s: %s", row["id"], exc)
            filled = D(row["filled_qty"])
            with transaction(self.conn):
                if filled > 0:
                    self._set(row["id"], status="FILLED", qty=str(filled), closed_at=iso(now),
                              reason="일부 체결 후 남은 수량 취소")
                    self._report_fill(row, filled, row["fill_price"], now)
                elif stale_exit and not (deadline and deadline <= iso(now)):
                    self._set(row["id"], status="CANCELLED", closed_at=iso(now),
                              reason="체결되지 않아 새 가격으로 다시 주문")
                else:
                    self._set(row["id"], status="EXPIRED", closed_at=iso(now),
                              reason="기한까지 체결되지 않아 취소")
                    self._notice(row, "execution", f"[미체결] {display_name(row['instrument_id'])} "
                                 f"{ROLE_KO[row['role']]} {row['qty']}주 · 지정가 "
                                 f"{money(row['limit_price'], row['currency'])}",
                                 "기한까지 가격이 닿지 않아 키움 모의 주문을 취소했습니다.",
                                 f"expired:{row['id']}", now)

    def _price(self, market: str, client: KiwoomMockClient, instrument_id: str) -> Decimal | None:
        code, exch = _code(instrument_id)
        try:
            if market == "KR":
                page = client.query("/api/dostk/stkinfo", "ka10001", {"stk_cd": code})[0]
            else:
                page = client.query("/api/us/mrkcond", "usa20100",
                                    {"stex_tp": exch, "stk_cd": code})[0]
        except KiwoomMockError as exc:
            log.warning("price %s: %s", instrument_id, exc)
            return None
        value = num(page.get("cur_prc"))
        return abs(D(value)) if value else None

    def _place(self, market: str, client: KiwoomMockClient, row: sqlite3.Row, side: str,
               qty: Decimal, limit: Decimal, now: datetime) -> str | None:
        """SENDING committed first; then one request; SENT or REJECTED. Returns the order number."""
        with transaction(self.conn):
            self._set(row["id"], status="SENDING", qty=str(qty), limit_price=str(limit),
                      sent_at=iso(now))
        path, buy, sell, _ = ORDER_API[market]
        code, exch = _code(row["instrument_id"])
        price = f"{limit:.2f}" if market == "US" else f"{limit:.0f}"
        body = ({"dmst_stex_tp": "KRX", "stk_cd": code, "ord_qty": f"{qty:.0f}", "ord_uv": price,
                 "trde_tp": "0", "cond_uv": ""} if market == "KR"
                else {"stex_tp": exch, "stk_cd": code, "ord_qty": f"{qty:.0f}", "trde_tp": "00",
                      "ord_uv": price})
        try:
            answer = client.send(path, buy if side == "BUY" else sell, body)
        except KiwoomMockError as exc:
            with transaction(self.conn):
                self._set(row["id"], status="REJECTED", closed_at=iso(now), reason=str(exc)[:300])
                self._notice(row, "execution", f"[주문 실패] {display_name(row['instrument_id'])} "
                             f"{ROLE_KO[row['role']]}", f"키움 모의 서버 응답: {str(exc)[:200]}",
                             f"failed:{row['id']}", now)
            return None
        no = str(answer.get("ord_no") or "").strip()
        with transaction(self.conn):
            self._set(row["id"], status="SENT", ext_order_no=no)
            if row["role"] == "entry":
                self._notice(row, "execution",
                             f"[주문] {display_name(row['instrument_id'])} 매수 {qty:f}주 · 지정가 "
                             f"{money(limit, row['currency'])}",
                             f"키움 모의 계좌 · 주문번호 {no} · 기한까지 체결되지 않으면 취소",
                             f"sent:{row['id']}", now)
        return no

    def _send_entry(self, market: str, client: KiwoomMockClient, acc: MockAccount,
                    row: sqlite3.Row, now: datetime) -> None:
        detail = json.loads(row["detail"] or "{}")
        cur = row["currency"]
        cash = D(acc.orderable or acc.cash or 0)
        nav = D(acc.cash or 0) + D(acc.total_value or 0)
        code, _ = _code(row["instrument_id"])
        held = sum((D(h.value or 0) for h in acc.holdings if h.code == code), D(0))
        start = self.start_equity(market)
        reason = None
        if start is not None and nav < start * (1 - MAX_DRAWDOWN):
            reason = (f"최대 손실 한도: 계좌가 시작 {money(start, cur)} 대비 "
                      f"{MAX_DRAWDOWN * 100:.0f}% 넘게 줄어 신규 매수를 멈춤")
        alloc = allocate(self.policy, nav_krw=nav, cash_krw=cash, held_krw=held,
                         rating=detail.get("rating"), multiplier=D(detail.get("multiplier", "1")),
                         limit=D(row["limit_price"]), stop=D(row["stop"]), fx_krw=D(1),
                         currency=cur, account_currency=cur)
        reason = reason or alloc.blocked
        if reason:
            with transaction(self.conn):
                self._set(row["id"], status="REJECTED", closed_at=iso(now), reason=reason)
                name = display_name(row["instrument_id"])
                self._notice(row, "execution", f"[리스크 거절] {name} 매수", reason,
                             f"rejected:{row['id']}", now)
            return
        with transaction(self.conn):
            self._set(row["id"], detail=json.dumps({**detail, "binding": alloc.binding,
                                                    "nav": str(nav), "cash": str(cash)}))
        self._place(market, client, row, "BUY", alloc.qty, D(row["limit_price"]), now)

    def _send_exit(self, market: str, client: KiwoomMockClient, acc: MockAccount,
                   row: sqlite3.Row, now: datetime) -> None:
        code, _ = _code(row["instrument_id"])
        qty = sum((D(h.qty or 0) for h in acc.holdings if h.code == code), D(0))
        price = self._price(market, client, row["instrument_id"])
        if qty <= 0 or price is None:
            with transaction(self.conn):
                self._set(row["id"], status="REJECTED", closed_at=iso(now),
                          reason=("키움 모의 계좌에 보유 수량이 없음" if qty <= 0
                                  else "현재가 조회 실패"))
            return
        self._place(market, client, row, "SELL", qty, marketable_sell(market, price), now)

    def _watch(self, market: str, client: KiwoomMockClient, acc: MockAccount,
               now: datetime) -> None:
        """Filled entries still held: sell at the stop or the target (C: intraday watch)."""
        for entry in self._rows(market, "FILLED"):
            if entry["role"] != "entry" or json.loads(entry["detail"] or "{}").get("closed"):
                continue
            code, _ = _code(entry["instrument_id"])
            held = sum((D(h.qty or 0) for h in acc.holdings if h.code == code), D(0))
            if held <= 0:
                continue
            busy = self.conn.execute(
                "SELECT 1 FROM km_orders WHERE instrument_id=? AND side='SELL' AND status IN "
                "('WAITING','SENDING','SENT')", (entry["instrument_id"],)).fetchone()
            if busy:
                continue
            price = self._price(market, client, entry["instrument_id"])
            if price is None:
                continue
            role = ("stop" if price <= D(entry["stop"])
                    else "take_profit" if price >= D(entry["target"]) else None)
            if role is None:
                continue
            qty = min(held, D(entry["filled_qty"]))
            n = self.conn.execute("SELECT COUNT(*) FROM km_orders WHERE parent_id=?",
                                  (entry["id"],)).fetchone()[0]
            with transaction(self.conn):
                cur = self.conn.execute(
                    "INSERT INTO km_orders (item_id, parent_id, market, instrument_id, role, side, "
                    "currency, status, idempotency_key, created_at, detail) "
                    "VALUES (?,?,?,?,?,'SELL',?,'WAITING',?,?,?)",
                    (entry["item_id"], entry["id"], market, entry["instrument_id"], role,
                     entry["currency"], f"km-{role}:{entry['id']}:{n}", iso(now),
                     json.dumps({"trigger_price": str(price)})))
                row = self.conn.execute("SELECT * FROM km_orders WHERE id=?",
                                        (cur.lastrowid,)).fetchone()
            self._place(market, client, row, "SELL", qty, marketable_sell(market, price), now)

    # ================================================================ evaluation (E)
    def record_nav(self, now: datetime) -> None:
        """One account snapshot per closed session (after the close), with the benchmark close."""
        for market in ("KR", "US"):
            try:
                sessions = closed_sessions(Market(market), now - timedelta(minutes=10), limit=1)
                if not sessions:
                    continue
                day = sessions[-1].day.isoformat()
                if self.conn.execute("SELECT 1 FROM km_nav WHERE market=? AND session=?",
                                     (market, day)).fetchone():
                    continue
                if now - sessions[-1].close > timedelta(hours=12):
                    continue  # too late for that session's value; the next one will do
                client = self.clients(market)
                acc = self._account(market, client) if client else None
                if acc is None or acc.cash is None:
                    continue
                bench = self.benchmark(BENCHMARK[market], sessions[-1].day) if self.benchmark \
                    else None
                nav = D(acc.cash) + D(acc.total_value or 0)
                with transaction(self.conn):
                    self.conn.execute(
                        "INSERT OR IGNORE INTO km_nav (market, session, nav, cash, holdings_value, "
                        "currency, benchmark, benchmark_close, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (market, day, str(nav), acc.cash, acc.total_value or "0", acc.currency,
                         BENCHMARK[market], str(bench) if bench is not None else None, iso(now)))
            except Exception:
                log.exception("nav snapshot %s failed", market)


def build_desks(settings: Any, conn: sqlite3.Connection) -> Desks:
    from stock_office.kiwoom_mock.link import build_link

    link = build_link(settings)
    cache: dict[str, KiwoomMockClient] = {}

    def clients(market: str) -> KiwoomMockClient | None:
        keys = link._keys.get(market)
        if keys is None:
            return None
        if market not in cache:
            cache[market] = KiwoomMockClient(*keys)
        return cache[market]

    def benchmark(symbol: str, day: Any) -> Decimal | None:
        from stock_office.providers.yahoo import index_close
        result: Decimal | None = index_close(symbol, day)
        return result

    return Desks(conn, clients, benchmark=benchmark)
