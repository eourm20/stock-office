"""CEO inbox end to end: a finished meeting files a document; the CEO decides once (DEMO data)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from stock_office.engine.demo_engine import DemoEngine
from tests.conftest import AS_OF


def run_demo(client: TestClient, instrument: str) -> str:
    resp = client.post("/api/v1/analysis-runs",
                       json={"instrument_id": instrument, "as_of": AS_OF, "engine": "demo"})
    assert resp.status_code == 202, resp.text
    return str(resp.json()["run_id"])


def test_buy_meeting_becomes_an_approval_request_and_the_ceo_decides_once(
        make_client: Callable[..., TestClient]) -> None:
    client = make_client(demo_engine=DemoEngine(rating="Buy"))
    off = client.post("/api/v1/company/auto-approve", json={"enabled": False})
    assert off.json() == {"auto_approve": False}
    run_id = run_demo(client, "US:NASDAQ:NVDA")

    items = client.get("/api/v1/inbox").json()
    assert len(items) == 1
    item = items[0]
    assert item["kind"] == "approval" and item["status"] == "PENDING"
    assert item["run_id"] == run_id and item["payload"]["demo"] is True
    assert item["title"].startswith("[결재] 엔비디아 매수 ")
    plan = item["plan"]
    # DEMO bars are too few for ATR: the policy's fallback stop and default multiplier apply.
    assert plan["sources"] == {"limit": "policy", "stop": "policy", "target": "policy"}
    assert plan["currency"] == "USD" and plan["fx_krw_per_unit"] == "1400"
    assert float(plan["allocation"]["qty"]) > 0 and plan["allocation"]["blocked"] is None
    assert plan["policy_version"] == "POLICY_V2"
    assert len(plan["allocation"]["lines"]) == 4
    expires = datetime.fromisoformat(item["expires_at"])
    assert datetime.now(UTC) < expires < datetime.now(UTC) + timedelta(days=5)

    body = {"action": "approve", "comment": "좋습니다", "client_request_id": "tap-1"}
    first = client.post(f"/api/v1/inbox/{item['id']}/decision", json=body)
    assert first.status_code == 200 and first.json()["status"] == "APPROVED"
    again = client.post(f"/api/v1/inbox/{item['id']}/decision", json=body)    # double tap
    assert again.status_code == 200 and again.json()["status"] == "APPROVED"
    assert len(again.json()["approvals"]) == 1 and again.json()["approvals"][0]["auto"] is False
    paper = again.json()["paper"]                   # the approval booked one simulated entry
    assert [(o["role"], o["status"]) for o in paper] == [("entry", "OPEN")]
    late = client.post(f"/api/v1/inbox/{item['id']}/decision",
                       json={"action": "reject", "client_request_id": "tap-2"})
    assert late.status_code == 409

    records = client.get("/api/v1/records").json()
    assert records[0]["run_id"] == run_id and records[0]["approval"] == "APPROVED"
    assert records[0]["name"] == "엔비디아" and records[0]["action"] == "BUY"
    now = client.get("/api/v1/office/now").json()
    assert now["pending_approvals"] == 0 and now["active"] is None


def test_hold_meeting_files_a_daily_report_only(make_client: Callable[..., TestClient]) -> None:
    client = make_client()                       # DEMO engine default rating: Hold
    run_demo(client, "KR:KRX:005930")
    run_id = run_demo(client, "KR:KRX:005930")
    items = client.get("/api/v1/inbox").json()
    assert [i["kind"] for i in items] == ["daily", "daily"]
    assert items[0]["status"] == "INFO" and items[0]["plan"] is None
    assert items[0]["title"] == "[일일 보고] 삼성전자 보유"
    assert client.post(f"/api/v1/inbox/{items[0]['id']}/decision",
                       json={"action": "approve", "client_request_id": "x"}).status_code == 409
    assert client.post(f"/api/v1/inbox/{items[0]['id']}/read").json() == {"ok": True}
    assert client.get(f"/api/v1/inbox/{items[0]['id']}").json()["read_at"] is not None
    assert {r["run_id"] for r in client.get("/api/v1/records").json()} >= {run_id}
    assert client.get("/api/v1/inbox/999").status_code == 404
