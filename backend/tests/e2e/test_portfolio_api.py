"""Paper trading end to end over HTTP: DEMO meeting → auto-approval → settlement → portfolio."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from fastapi.testclient import TestClient

from stock_office.api.app import create_app
from stock_office.config import Settings
from stock_office.domain.models import Market
from stock_office.engine.demo_engine import DemoEngine
from stock_office.paper.fills import DayBar
from stock_office.paper.settle import Settler
from stock_office.runs.service import RunService
from stock_office.schedule import first_session_opening_after
from tests.conftest import AS_OF, InlineDispatcher


def test_auto_approved_buy_is_filled_after_the_close_and_shows_in_the_portfolio(
        settings: Settings, make_service: Callable[..., RunService]) -> None:
    service = make_service(demo_engine=DemoEngine(rating="Buy"))
    client = TestClient(create_app(settings, service, InlineDispatcher(service)))
    assert client.get("/api/v1/company/settings").json()["auto_approve"] is True
    start = client.get("/api/v1/portfolio").json()
    assert start["nav_krw"] == "10000000" and start["holdings"] == [] and start["pending"] == []

    run = client.post("/api/v1/analysis-runs", json={
        "instrument_id": "KR:KRX:005930", "as_of": AS_OF, "engine": "demo"}).json()
    item = next(i for i in client.get("/api/v1/inbox").json() if i["run_id"] == run["run_id"])
    assert item["status"] == "APPROVED" and item["auto_approved"] is True
    doc = client.get(f"/api/v1/inbox/{item['id']}").json()
    assert doc["approvals"][0]["auto"] is True and doc["paper"][0]["status"] == "OPEN"
    pending = client.get("/api/v1/portfolio").json()["pending"]
    assert [p["role"] for p in pending] == ["entry"]

    limit = D(item["plan"]["limit"])
    session = first_session_opening_after(
        Market.KR, datetime.fromisoformat(doc["paper"][0]["created_at"]))
    close = limit * D("1.03")
    bar = DayBar(session.day, limit, close, limit * D("0.995"), close)
    settler = Settler(service.inbox.book, lambda i, d: bar if d == session.day else None,
                      lambda: (D(1400), datetime(2026, 10, 15, tzinfo=UTC)))
    assert settler.settle(Market.KR, session, session.close + timedelta(hours=1)).fills == 1

    book = client.get("/api/v1/portfolio").json()
    (held,) = book["holdings"]
    assert held["name"] == "삼성전자" and D(held["last_price"]) == close.quantize(D("0.0001"))
    assert D(held["pnl_krw"]) > 0 and held["take_profit"] and held["stop"]
    assert D(book["nav_krw"]) == D(book["cash_krw"]) + D(held["value_krw"])
    assert D(book["return_pct"]) > 0 and book["last_settles"][0]["status"] == "OK"
    assert len(book["costs"]) == 5
    activity = client.get("/api/v1/portfolio/activity").json()
    assert {a["role"] for a in activity} == {"entry", "take_profit", "stop"}
    kinds = [i["kind"] for i in client.get("/api/v1/inbox").json()]
    assert kinds.count("execution") == 1
    records = client.get("/api/v1/records").json()
    assert records[0]["approval_auto"] is True and records[0]["paper"] == "FILLED"
    upcoming = client.get("/api/v1/office/now").json()["next"]
    assert {u["kind"] for u in upcoming} == {"research", "settle"}  # fixed meetings are off
