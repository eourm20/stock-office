"""MOCK ONLY guard (was PAPER ONLY until 2026-10-20): no real-account order path can exist.

Orders may only ever reach the internal paper book or Kiwoom's mock-trading server. In step K1 the
Kiwoom link is read-only: no order API id or order path appears anywhere in the source.
"""

import re
from pathlib import Path

from fastapi.routing import APIRoute

from stock_office.api.app import create_app
from stock_office.config import Settings

SRC = Path(__file__).resolve().parents[2] / "src" / "stock_office"

FORBIDDEN = [
    r"_auto_execute", r"KiwoomClient", r"place_order", r"send_order",
    r"submit_order", r"order_cash", r"create_order", r"broker", r"account_no",
    r"/uapi/domestic-stock/v1/trading",  # KIS order endpoint family
]


def test_no_order_execution_code_in_source() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        # The package docstring may *state* that no broker code exists.
        if path.name == "__init__.py" and path.parent == SRC:
            continue
        for pattern in FORBIDDEN:
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(SRC)}: {pattern}")
    assert offenders == []


def test_no_order_or_account_modules() -> None:
    names = {p.stem for p in SRC.rglob("*.py")} | {p.name for p in SRC.rglob("*") if p.is_dir()}
    assert not names & {"orders", "order", "broker", "brokers", "execution", "trading_api"}


def test_api_exposes_no_order_routes(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, _env_file=None))  # type: ignore[call-arg]
    paths = {r.path for r in app.routes if isinstance(r, APIRoute)}
    assert not [p for p in paths if re.search(r"order|account|trade|broker", p)]
    mutating = {r.path for r in app.routes if isinstance(r, APIRoute) and r.methods - {"GET"}}
    # Every state-changing route is listed by name. An inbox decision records an approval and
    # books a simulated order in the local paper book; the auto-approve switch is a local
    # setting. Apart from push notifications to the owner's phone, nothing reaches any external
    # service.
    assert mutating == {
        "/api/v1/analysis-runs",
        "/api/v1/inbox/{item_id}/decision",
        "/api/v1/inbox/{item_id}/read",
        "/api/v1/company/auto-approve",
        # Phone notifications: the owner's own push subscription (known push services only)
        # and a test message to it. Notification text is inbox titles only.
        "/api/v1/notify/subscribe",
        "/api/v1/notify/unsubscribe",
        "/api/v1/notify/test",
    }


NETWORK_IMPORTS = re.compile(
    r"^\s*(?:import|from)\s+(httpx|requests|urllib|socket|aiohttp|yfinance|websocket\w*)\b",
    re.MULTILINE)


def test_paper_package_has_no_network_access() -> None:
    """Paper trading decides and simulates locally; it must not be able to talk to anything."""
    paper = SRC / "paper"
    assert paper.is_dir()
    offenders = [f"{path.relative_to(SRC)}: {m.group(1)}"
                 for path in paper.rglob("*.py")
                 for m in NETWORK_IMPORTS.finditer(path.read_text(encoding="utf-8"))]
    assert offenders == []


def _source() -> list[tuple[Path, str]]:
    return [(p, p.read_text(encoding="utf-8")) for p in SRC.rglob("*.py")]


def test_kiwoom_is_reached_only_through_the_mock_server() -> None:
    """The real trading domain (api.kiwoom.com) appears nowhere; only mockapi.kiwoom.com does."""
    real = re.compile(r"(?<!mock)api\.kiwoom\.com", re.IGNORECASE)
    assert [str(p.relative_to(SRC)) for p, text in _source() if real.search(text)] == []
    users = {str(p.relative_to(SRC)) for p, text in _source() if "mockapi.kiwoom.com" in text}
    assert users == {str(Path("kiwoom_mock") / "client.py")}

    from stock_office.kiwoom_mock.client import MOCK_BASE_URL, KiwoomMockClient, KiwoomMockError
    assert MOCK_BASE_URL == "https://mockapi.kiwoom.com"
    import pytest
    with pytest.raises(KiwoomMockError):
        KiwoomMockClient("k", "s", base_url="https://api.kiwoom.com")


def test_kiwoom_orders_only_from_the_desks() -> None:
    """Order endpoints and order API ids (domestic kt1000x, US ust2000x) appear only where the
    mock client allows them and where the desks send approved, risk-checked orders."""
    order = re.compile(r"/api/(?:dostk|us)/ordr|\bkt1000[0-9]\b|\bust2000[0-9]\b")
    users = {str(p.relative_to(SRC)) for p, text in _source() if order.search(text)}
    assert users == {str(Path("kiwoom_mock") / "client.py"), str(Path("kiwoom_mock") / "desks.py")}
    from stock_office.kiwoom_mock.client import ALLOWED_PATHS, ORDER_API_IDS, ORDER_PATHS
    assert "/api/dostk/ordr" not in ALLOWED_PATHS and "/api/us/ordr" not in ALLOWED_PATHS
    assert {"/api/dostk/ordr", "/api/us/ordr"} == ORDER_PATHS
    assert {"kt10000", "kt10001", "kt10003", "ust20000", "ust20001", "ust20003"} == ORDER_API_IDS


def test_health_declares_paper_only(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    app = create_app(Settings(data_dir=tmp_path, _env_file=None))  # type: ignore[call-arg]
    body = TestClient(app).get("/health").json()
    assert body["paper_only"] is True and body["live_orders"] is False
