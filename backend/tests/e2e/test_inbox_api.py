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
    assert items[0]["title"] == "[회의 결과] 삼성전자 · 유지 의견"
    assert client.post(f"/api/v1/inbox/{items[0]['id']}/decision",
                       json={"action": "approve", "client_request_id": "x"}).status_code == 409
    assert client.post(f"/api/v1/inbox/{items[0]['id']}/read").json() == {"ok": True}
    assert client.get(f"/api/v1/inbox/{items[0]['id']}").json()["read_at"] is not None
    assert {r["run_id"] for r in client.get("/api/v1/records").json()} >= {run_id}
    assert client.get("/api/v1/inbox/999").status_code == 404



def test_market_briefings_live_in_the_news_tab_not_the_inbox(
        client: TestClient, settings: object) -> None:
    import json

    from stock_office.db import connect

    conn = connect(settings.data_dir)  # type: ignore[attr-defined]
    for n, at in enumerate(("2026-11-05T22:20:00+00:00", "2026-11-06T13:00:00+00:00")):
        conn.execute(
            "INSERT INTO inbox_items (kind, title, summary, payload, status, dedupe_key, "
            "created_at) VALUES ('daily', ?, '분위기', ?, 'INFO', ?, ?)",
            (f"[시장 브리핑] {n}", json.dumps({"type": "market_briefing", "briefing_status": "OK",
                                               "news": []}), f"market-briefing:X:{n}", at))
    run_demo(client, "KR:KRX:005930")
    inbox = client.get("/api/v1/inbox").json()
    assert inbox and not any(i["title"].startswith("[시장 브리핑]") for i in inbox)
    news = client.get("/api/v1/news").json()
    assert [i["title"] for i in news] == ["[시장 브리핑] 1", "[시장 브리핑] 0"]   # newest first
    assert news[0]["payload"]["type"] == "market_briefing"


def test_the_ceo_clears_one_desks_sharp_move_and_review_reports(
        client: TestClient, settings: object) -> None:
    from stock_office.db import connect

    conn = connect(settings.data_dir)  # type: ignore[attr-defined]
    for iid, title, key in (
            ("KR:KRX:005930", "[급변] 삼성", "watch:move:KR:KRX:005930:2026-11-06:down3"),
            ("KR:KRX:000660", "[급변] 하이닉스", "watch:move:KR:KRX:000660:2026-11-06:up5"),
            ("US:NASDAQ:NVDA", "[급변] 엔비디아", "watch:move:US:NASDAQ:NVDA:2026-11-06:up3"),
            ("KR:KRX:005930", "[검토 필요] 삼성전자 매수 제안", "run:x1"),
            ("KR:KRX:005930", "[회의 결과] 삼성전자 · 유지 의견", "run:x2")):
        conn.execute(
            "INSERT INTO inbox_items (kind, instrument_id, title, status, dedupe_key, created_at) "
            "VALUES (?, ?, ?, 'INFO', ?, '2026-11-06T01:00:00+00:00')",
            ("daily" if key.startswith("run:") else "adhoc", iid, title, key))
    hide = lambda what: client.post("/api/v1/inbox/hide",  # noqa: E731
                                    params={"market": "KR", "what": what}).json()
    assert hide("moves") == {"hidden": 2} and hide("reviews") == {"hidden": 1}
    assert hide("everything") == {"hidden": 0}
    titles = {i["title"] for i in client.get("/api/v1/inbox").json()}
    assert {"[급변] 엔비디아", "[회의 결과] 삼성전자 · 유지 의견"} <= titles
    assert not titles & {"[급변] 삼성", "[급변] 하이닉스", "[검토 필요] 삼성전자 매수 제안"}
    assert conn.execute("SELECT COUNT(*) FROM inbox_items WHERE hidden_at IS NOT NULL"
                        ).fetchone()[0] == 1                  # the review: hidden, kept
    assert conn.execute("SELECT COUNT(*) FROM inbox_items WHERE title LIKE '[급변]%'"
                        ).fetchone()[0] == 1                  # KR moves deleted, US kept
    assert conn.execute("SELECT COUNT(*) FROM cleared_keys").fetchone()[0] == 2


def test_stock_profile_route_serves_the_cache_and_says_when_it_cannot(
        client: TestClient, settings: object) -> None:
    import json

    from stock_office.db import connect

    assert client.get("/api/v1/stocks/KR:KRX:999999/profile").status_code == 404
    assert client.get("/api/v1/stocks/KR:KRX:005930/profile").status_code == 503  # no engine
    conn = connect(settings.data_dir)  # type: ignore[attr-defined]
    conn.execute("INSERT INTO stock_profiles (instrument_id, body, created_at) VALUES (?,?,?)",
                 ("KR:KRX:005930", json.dumps({"name": "삼성전자", "what": "전자 회사예요."}),
                  datetime.now(UTC).isoformat()))
    assert client.get("/api/v1/stocks/KR:KRX:005930/profile").json()["what"] == "전자 회사예요."
