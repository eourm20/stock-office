"""PAPER ONLY guard: the codebase must not contain broker/order execution paths."""

import re
from pathlib import Path

from fastapi.routing import APIRoute

from stock_office.api.app import create_app
from stock_office.config import Settings

SRC = Path(__file__).resolve().parents[2] / "src" / "stock_office"

FORBIDDEN = [
    r"_auto_execute", r"kiwoom", r"KiwoomClient", r"place_order", r"send_order",
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
    assert mutating == {"/api/v1/analysis-runs"}


def test_health_declares_paper_only(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    app = create_app(Settings(data_dir=tmp_path, _env_file=None))  # type: ignore[call-arg]
    body = TestClient(app).get("/health").json()
    assert body["paper_only"] is True and body["live_orders"] is False
