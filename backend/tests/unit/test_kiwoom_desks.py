"""Kiwoom mock desks: approved plans → mock orders, fills, deadlines, stop/target, loss limit.
No network: a fake Kiwoom mock server (httpx.MockTransport) keeps the account state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import httpx
import pytest

from stock_office.db import connect, transaction
from stock_office.kiwoom_mock.client import KiwoomMockClient
from stock_office.kiwoom_mock.desks import Desks, marketable_sell

KR, US = "KR:KRX:005930", "US:NASDAQ:NVDA"
KR_OPEN = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)     # Tue 10:00 KST, KRX session
KR_CLOSED = datetime(2026, 10, 20, 7, 0, tzinfo=UTC)   # 16:00 KST
US_OPEN = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)    # 11:00 New York


class FakeMock:
    """Kiwoom's mock server, as far as the desks use it."""

    def __init__(self, market: str = "KR") -> None:
        self.market = market
        self.cash = D(10_000_000) if market == "KR" else D(100_000)
        self.holdings: dict[str, tuple[D, D]] = {}   # code -> (qty, avg)
        self.price = D(50_000) if market == "KR" else D("180")
        self.orders: dict[str, dict[str, Any]] = {}  # ord_no -> order
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.fail_next: str | None = None
        self.move: str | None = None   # day change (%) the quote reports
        self.n = 0

    def fill(self, no: str, price: D | None = None) -> None:
        o = self.orders[no]
        o["filled"] = o["qty"]
        o["price"] = price or D(o["body"]["ord_uv"])
        code = o["body"]["stk_cd"]
        qty, avg = self.holdings.get(code, (D(0), D(0)))
        if o["side"] == "BUY":
            self.holdings[code] = (qty + o["qty"], o["price"])
            self.cash -= o["qty"] * o["price"]
        else:
            self.holdings[code] = (qty - o["qty"], avg)
            self.cash += o["qty"] * o["price"]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "mockapi.kiwoom.com"
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json={"token": "T", "expires_dt": "20991231235959"})
        api, body = request.headers["api-id"], json.loads(request.content or b"{}")
        ok = {"return_code": 0, "return_msg": "ok"}
        if api in ("kt10000", "kt10001", "ust20000", "ust20001"):
            self.sent.append((api, body))
            if self.fail_next:
                msg, self.fail_next = self.fail_next, None
                return httpx.Response(200, json={"return_code": 2, "return_msg": msg})
            self.n += 1
            no = f"{self.n:07d}"
            self.orders[no] = {"body": body, "qty": D(body["ord_qty"]), "filled": D(0),
                               "price": None, "side": "BUY" if api in ("kt10000", "ust20000")
                               else "SELL"}
            return httpx.Response(200, json={**ok, "ord_no": no})
        if api in ("kt10003", "ust20003"):
            self.sent.append((api, body))
            return httpx.Response(200, json={**ok, "ord_no": "9"})
        if api == "kt00001":
            return httpx.Response(200, json={**ok, "entr": str(self.cash),
                                             "ord_alow_amt": str(self.cash)})
        if api == "kt00018":
            rows = [{"stk_cd": f"A{c}", "stk_nm": "삼성전자", "rmnd_qty": str(q),
                     "pur_pric": str(a), "cur_prc": str(self.price),
                     "evlt_amt": str(q * self.price)} for c, (q, a) in self.holdings.items() if q]
            total = sum((q * self.price for q, _ in self.holdings.values()), D(0))
            return httpx.Response(200, json={**ok, "tot_evlt_amt": str(total),
                                             "acnt_evlt_remn_indv_tot": rows})
        if api == "kt00007":
            return httpx.Response(200, json={**ok, "acnt_ord_cntr_prps_dtl": [
                {"ord_no": no, "cntr_qty": str(o["filled"]), "cntr_uv": str(o["price"] or 0)}
                for no, o in self.orders.items()]})
        if api == "ka10001":
            return httpx.Response(200, json={**ok, "cur_prc": f"-{self.price}",
                                             **({"flu_rt": self.move} if self.move else {})})
        if api == "ust21110":
            return httpx.Response(200, json={**ok, "result_list": [
                {"crnc_code": "USD", "fc_entra": str(self.cash), "fc_ord_alowa": str(self.cash)}]})
        if api == "ust21070":
            rows = [{"stk_cd": c, "poss_qty": str(q), "frgn_stk_book_uv": str(a),
                     "now_pric": str(self.price), "evlt_amt": str(q * self.price)}
                    for c, (q, a) in self.holdings.items() if q]
            total = sum((q * self.price for q, _ in self.holdings.values()), D(0))
            return httpx.Response(200, json={**ok, "tot_evlt_amt": str(total), "result_list": rows})
        if api == "ust21510":
            return httpx.Response(200, json={**ok, "result_list": [
                {"ord_no": no, "cntr_qty": str(o["filled"]), "cntr_uv": str(o["price"] or 0)}
                for no, o in self.orders.items()]})
        if api == "usa20100":
            return httpx.Response(200, json={**ok, "cur_prc": str(self.price)})
        raise AssertionError(f"unexpected api {api}")


def setup(tmp_path: Path, market: str = "KR",
          bench: Any = None) -> tuple[Desks, FakeMock]:
    fake = FakeMock(market)
    client = KiwoomMockClient("k", "s", http=httpx.Client(transport=httpx.MockTransport(fake)),
                              sleep=lambda s: None)
    desks = Desks(connect(tmp_path), lambda m: client if m == market else None, benchmark=bench)
    return desks, fake


def approve(desks: Desks, instrument: str = KR, *, limit: str = "50000", stop: str = "47000",
            target: str = "56000", deadline: datetime = KR_OPEN + timedelta(hours=5),
            item: int = 101) -> None:
    with transaction(desks.conn):
        desks.conn.execute(
            "INSERT INTO inbox_items (id, kind, instrument_id, title, status, dedupe_key, "
            "created_at) VALUES (?, 'approval', ?, 't', 'APPROVED', ?, ?)",
            (item, instrument, f"d{item}", KR_OPEN.isoformat()))
        desks.queue_entry(item, instrument, {"limit": limit, "stop": stop, "target": target,
                                             "rating": "Buy", "multiplier": "1"},
                          deadline.astimezone(UTC).isoformat(timespec="microseconds"), KR_OPEN)


def order(desks: Desks, role: str = "entry") -> dict[str, Any]:
    return next(o for o in desks.orders() if o["role"] == role)


def titles(desks: Desks) -> list[str]:
    return [r[0] for r in desks.conn.execute("SELECT title FROM inbox_items WHERE kind != "
                                             "'approval' ORDER BY id")]


def test_entry_is_sized_on_the_live_account_and_sent_once_during_the_session(
        tmp_path: Path) -> None:
    desks, fake = setup(tmp_path)
    approve(desks)
    desks.tick(KR_CLOSED - timedelta(hours=8))   # 07:00 KST: market not open yet
    assert fake.sent == [] and order(desks)["status"] == "WAITING"
    desks.tick(KR_OPEN)
    desks.tick(KR_OPEN + timedelta(seconds=30))   # again: never a second order
    # 10% of 10,000,000 = 1,000,000 (binding) / (50,000 × 1.0005) → 19 whole shares
    assert fake.sent == [("kt10000", {"dmst_stex_tp": "KRX", "stk_cd": "005930", "ord_qty": "19",
                                      "ord_uv": "50000", "trde_tp": "0", "cond_uv": ""})]
    o = order(desks)
    assert (o["status"], o["qty"], o["ext_order_no"]) == ("SENT", "19", "0000001")
    assert desks.start_equity("KR") == D(10_000_000)
    assert titles(desks) == ["[주문] 삼성전자 매수 19주 · 지정가 50,000원"]


def test_fill_then_stop_sells_at_a_marketable_limit_and_reports_the_loss(tmp_path: Path) -> None:
    desks, fake = setup(tmp_path)
    approve(desks)
    desks.tick(KR_OPEN)
    fake.fill("0000001")
    desks.tick(KR_OPEN + timedelta(minutes=1))
    assert order(desks)["status"] == "FILLED"
    fake.price = D(46_500)                          # below the 47,000 stop
    desks.tick(KR_OPEN + timedelta(minutes=2))
    api, body = fake.sent[-1]
    assert api == "kt10001" and body["ord_qty"] == "19"
    assert body["ord_uv"] == str(marketable_sell("KR", D(46_500))) == "46000"
    fake.fill("0000002", D(46_000))
    desks.tick(KR_OPEN + timedelta(minutes=3))
    assert order(desks, "stop")["status"] == "FILLED"
    assert titles(desks)[-1] == "[청산] 삼성전자 손절 19주 @ 46,000원 · −76,000원"
    desks.tick(KR_OPEN + timedelta(minutes=4))     # sold out: nothing more to do
    assert len([a for a, _ in fake.sent if a == "kt10001"]) == 1


def test_target_and_unfilled_exit_is_replaced(tmp_path: Path) -> None:
    desks, fake = setup(tmp_path)
    approve(desks)
    desks.tick(KR_OPEN)
    fake.fill("0000001")
    desks.tick(KR_OPEN + timedelta(minutes=1))
    fake.price = D(57_000)                          # above the 56,000 target
    desks.tick(KR_OPEN + timedelta(minutes=2))
    assert order(desks, "take_profit")["status"] == "SENT"
    desks.tick(KR_OPEN + timedelta(minutes=6))      # not filled for 3+ minutes: cancel, re-place
    assert [a for a, _ in fake.sent][-2:] == ["kt10003", "kt10001"]
    assert [o["status"] for o in desks.orders() if o["role"] == "take_profit"] == \
        ["SENT", "CANCELLED"]


def test_unfilled_entry_is_cancelled_at_its_deadline(tmp_path: Path) -> None:
    desks, fake = setup(tmp_path)
    approve(desks, deadline=KR_OPEN + timedelta(hours=1))
    desks.tick(KR_OPEN)
    desks.tick(KR_OPEN + timedelta(hours=1, minutes=1))
    assert fake.sent[-1] == ("kt10003", {"dmst_stex_tp": "KRX", "orig_ord_no": "0000001",
                                         "stk_cd": "005930", "cncl_qty": "0"})
    assert order(desks)["status"] == "EXPIRED"
    assert titles(desks)[-1].startswith("[미체결] 삼성전자 매수 19주")


def test_waiting_order_past_its_deadline_never_goes_out(tmp_path: Path) -> None:
    desks, fake = setup(tmp_path)
    approve(desks, deadline=KR_OPEN - timedelta(hours=1))
    desks.tick(KR_OPEN)
    assert fake.sent == [] and order(desks)["status"] == "EXPIRED"
    assert titles(desks) == ["[미주문] 삼성전자 매수"]


def test_loss_limit_stops_new_buys(tmp_path: Path) -> None:
    desks, fake = setup(tmp_path)
    with transaction(desks.conn):
        desks.conn.execute("INSERT INTO company_settings (key, value) VALUES ('km_start_KR', "
                           "'10000000')")
    fake.cash = D(8_900_000)                       # 11% below the start
    approve(desks)
    desks.tick(KR_OPEN)
    o = order(desks)
    assert fake.sent == [] and o["status"] == "REJECTED" and "최대 손실 한도" in o["reason"]
    assert titles(desks) == ["[리스크 거절] 삼성전자 매수"]


def test_a_refused_order_is_reported_and_a_lost_answer_is_never_resent(tmp_path: Path) -> None:
    desks, fake = setup(tmp_path)
    approve(desks)
    fake.fail_next = "[RC4025] 증거금 부족"
    desks.tick(KR_OPEN)
    assert order(desks)["status"] == "REJECTED" and titles(desks) == ["[주문 실패] 삼성전자 매수"]
    approve(desks, item=500)
    with transaction(desks.conn):                    # as if the process died mid-request
        desks.conn.execute("UPDATE km_orders SET status='SENDING', sent_at=? WHERE item_id=500",
                           (KR_OPEN.isoformat(timespec="microseconds"),))
    desks.tick(KR_OPEN + timedelta(minutes=5))
    review = [o for o in desks.orders() if o["item_id"] == 500][0]
    assert review["status"] == "REVIEW" and len(fake.sent) == 1


def test_us_desk_orders_whole_shares_in_dollars(tmp_path: Path) -> None:
    desks, fake = setup(tmp_path, "US")
    approve(desks, US, limit="180.50", stop="170", target="200",
            deadline=US_OPEN + timedelta(hours=3))
    desks.tick(KR_OPEN)                             # Korean daytime: US market closed
    assert fake.sent == []
    desks.tick(US_OPEN)
    # 10% of $100,000 = $10,000 / ($180.50 × 1.0005) → 55 shares
    assert fake.sent == [("ust20000", {"stex_tp": "ND", "stk_cd": "NVDA", "ord_qty": "55",
                                       "trde_tp": "00", "ord_uv": "180.50"})]
    assert titles(desks) == ["[주문] 엔비디아 매수 55주 · 지정가 $180.50"]


def test_a_session_value_is_recorded_once_after_the_close(tmp_path: Path) -> None:
    desks, fake = setup(tmp_path, bench=lambda symbol, day: D("2600.5"))
    desks.record_nav(KR_CLOSED)
    desks.record_nav(KR_CLOSED + timedelta(minutes=5))
    rows = desks.nav_history("KR")
    assert [(r["session"], r["nav"], r["benchmark"], r["benchmark_close"]) for r in rows] == \
        [("2026-10-20", "10000000", "^KS11", "2600.5")]


def test_marketable_sell_prices_respect_ticks() -> None:
    assert marketable_sell("KR", D(51_813)) == D(51_200)   # 51,294.87 → 100-won tick
    assert marketable_sell("US", D("180.37")) == D("179.46")


@pytest.mark.parametrize("deadline_hours", [5])
def test_exit_decision_sells_the_whole_holding(tmp_path: Path, deadline_hours: int) -> None:
    desks, fake = setup(tmp_path)
    fake.holdings["005930"] = (D(7), D(48_000))
    with transaction(desks.conn):
        desks.conn.execute("INSERT INTO inbox_items (id, kind, instrument_id, title, status, "
                           "dedupe_key, created_at) VALUES (1, 'approval', ?, 't', 'APPROVED', "
                           "'d1', ?)", (KR, KR_OPEN.isoformat()))
        desks.queue_exit(1, KR, (KR_OPEN + timedelta(hours=deadline_hours)).isoformat(), KR_OPEN)
    desks.tick(KR_OPEN)
    assert fake.sent == [("kt10001", {"dmst_stex_tp": "KRX", "stk_cd": "005930", "ord_qty": "7",
                                      "ord_uv": "49500", "trde_tp": "0", "cond_uv": ""})]


def test_approving_a_kiwoom_plan_queues_it_without_any_network(tmp_path: Path) -> None:
    from stock_office.inbox import Inbox

    desks, fake = setup(tmp_path)
    inbox = Inbox(desks.conn, repo=None, desks=desks)  # type: ignore[arg-type]
    body = {"venue": "kiwoom_mock", "side": "BUY", "currency": "KRW", "limit": "50000",
            "stop": "47000", "target": "56000", "rating": "Buy", "multiplier": "1"}
    deadline = (KR_OPEN + timedelta(hours=5)).isoformat(timespec="microseconds")
    with transaction(desks.conn):
        desks.conn.execute(
            "INSERT INTO inbox_items (id, kind, instrument_id, title, status, expires_at, "
            "dedupe_key, created_at) VALUES (7, 'approval', ?, '[결재]', 'PENDING', ?, 'r7', ?)",
            (KR, deadline, KR_OPEN.isoformat()))
        desks.conn.execute(
            "INSERT INTO plans (item_id, run_id, instrument_id, side, body, policy_version) "
            "VALUES (7, 'r', ?, 'BUY', ?, 'POLICY_V3')", (KR, json.dumps(body)))
    item = inbox.decide(7, "approve", "", "ceo-1", KR_OPEN)
    assert fake.sent == []                                   # nothing leaves at approval time
    assert [(o["role"], o["status"], o["limit_price"]) for o in item.mock_orders] == \
        [("entry", "WAITING", "50000")]
    assert item.paper == []                                   # not in the internal book
    inbox.decide(7, "approve", "", "ceo-1", KR_OPEN)          # repeated tap: still one
    assert len(desks.orders()) == 1


def test_sharp_moves_and_new_filings_are_reported_once(tmp_path: Path) -> None:
    calls: list[str] = []

    def filings(instrument_id: str, day: Any) -> list[tuple[str, str]]:
        calls.append(instrument_id)
        return [("20261020000123", "주요사항보고서(자기주식취득결정)")]

    desks, fake = setup(tmp_path)
    desks.filings = filings
    with transaction(desks.conn):   # the research team put Samsung on today's focus
        desks.conn.execute(
            "INSERT INTO research_runs (market, session, rules_version, universe, screened, "
            "liquid, candidates, watchlist, focus, created_at) VALUES ('KR', '2026-10-20', "
            "'SCREEN_V1', 'KOSPI200', 1, 1, '[]', ?, ?, 'x')",
            (json.dumps([KR]), json.dumps([{"instrument_id": KR, "why": "test"}])))
    fake.move = "-3.40"
    desks.tick(KR_OPEN)
    desks.tick(KR_OPEN + timedelta(minutes=1))       # same move, filings not due again
    fake.move = "-5.10"
    desks.tick(KR_OPEN + timedelta(minutes=2))
    fake.move = "-4.00"                               # back above −5%: nothing new
    desks.tick(KR_OPEN + timedelta(minutes=12))      # filings checked again: same receipt
    assert titles(desks) == ["[급변] 삼성전자 −3.4%",
                             "[공시] 삼성전자 · 주요사항보고서(자기주식취득결정)",
                             "[급변] 삼성전자 −5.1%"]
    assert calls == [KR, KR]
    keys = [r[0] for r in desks.conn.execute("SELECT dedupe_key FROM inbox_items")]
    assert all(k.startswith("watch:") for k in keys)  # reports, not order notifications


def test_an_add_on_buy_joins_the_position_and_the_stop_sells_it_all(tmp_path: Path) -> None:
    desks, fake = setup(tmp_path)
    approve(desks)                                              # first tranche: 19 @ 50,000
    desks.tick(KR_OPEN)
    fake.fill("0000001")
    desks.tick(KR_OPEN + timedelta(minutes=1))
    assert desks.open_buy(KR) is False
    approve(desks, item=200, limit="52000", stop="49000", target="60000")   # re-check: add on
    assert desks.open_buy(KR) is True                           # no third approval meanwhile
    fake.price = D(52_000)
    desks.tick(KR_OPEN + timedelta(minutes=2))
    fake.fill("0000002")
    desks.tick(KR_OPEN + timedelta(minutes=3))
    first, second = sorted((o for o in desks.orders() if o["role"] == "entry"),
                           key=lambda o: o["id"])
    assert first["detail"].get("merged_into") == second["id"]
    added = D(second["filled_qty"])
    assert D(second["detail"]["position_qty"]) == 19 + added
    avg = D(second["detail"]["avg_price"])
    assert D(50_000) < avg < D(52_000)
    assert titles(desks)[-1].startswith("[체결] 삼성전자 추가 매수")
    fake.price = D(48_500)                                     # below the latest stop (49,000)
    desks.tick(KR_OPEN + timedelta(minutes=4))
    api, body = fake.sent[-1]
    assert api == "kt10001" and body["ord_qty"] == f"{19 + added:.0f}"   # the whole position
    fake.fill(f"{fake.n:07d}", D(48_000))
    desks.tick(KR_OPEN + timedelta(minutes=5))
    loss = (D(48_000) - avg) * (19 + added)
    assert titles(desks)[-1].endswith(f"−{abs(loss).quantize(D(1)):,}원")
