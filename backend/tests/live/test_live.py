"""Live checks (network / keys). Never part of the default run: `uv run pytest -m live`."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dotenv import find_dotenv, load_dotenv

from stock_office.domain.instruments import get_instrument
from stock_office.providers.base import enforce_point_in_time

# Keys may live in backend/.env; the skip conditions below read os.environ at collection time.
load_dotenv(find_dotenv(usecwd=True), override=False)

pytestmark = pytest.mark.live


@pytest.mark.parametrize("instrument_id", ["US:NASDAQ:NVDA", "KR:KRX:005930"])
def test_yahoo_daily_bars(instrument_id: str) -> None:
    pytest.importorskip("yfinance")
    from stock_office.providers.yahoo import YahooPriceProvider

    inst = get_instrument(instrument_id)
    as_of = datetime.now(UTC)
    result = YahooPriceProvider(lookback_days=14).fetch(inst, as_of)
    assert result.snapshots, result.coverage_gaps
    pit = enforce_point_in_time(result.snapshots, as_of)
    assert pit.allowed
    for snap in pit.allowed:
        assert snap.currency == inst.currency and not snap.demo
    latest = pit.allowed[-1].payload
    print(f"\n{instrument_id}: {len(pit.allowed)} bars allowed, {len(pit.rejected)} not yet "
          f"available; latest={latest['date']} close={latest['close']}")


@pytest.mark.skipif(not os.environ.get("STOCK_OFFICE_DART_API_KEY"), reason="no DART key")
def test_dart_disclosures() -> None:
    from stock_office.providers.dart import DartDisclosureProvider

    result = DartDisclosureProvider(os.environ["STOCK_OFFICE_DART_API_KEY"]).fetch(
        get_instrument("KR:KRX:005930"), datetime.now(UTC))
    assert result.snapshots or result.coverage_gaps


# Real LLM runs cost money: they need the key AND an explicit opt-in, so `-m live` alone
# (free provider checks) never spends tokens. Choose instruments/profile per invocation:
#   STOCK_OFFICE_ALLOW_PAID_TESTS=1 STOCK_OFFICE_PAID_TEST_INSTRUMENTS=US:NASDAQ:NVDA \
#   STOCK_OFFICE_TA_COST_PROFILE=economy uv run pytest -m live -s -k real_tradingagents
_PAID = os.environ.get("STOCK_OFFICE_ALLOW_PAID_TESTS") == "1"
_PAID_INSTRUMENTS = os.environ.get(
    "STOCK_OFFICE_PAID_TEST_INSTRUMENTS", "US:NASDAQ:NVDA,KR:KRX:005930").split(",")


@pytest.mark.parametrize("instrument_id", [i.strip() for i in _PAID_INSTRUMENTS if i.strip()])
@pytest.mark.skipif(not _PAID, reason="paid LLM run: set STOCK_OFFICE_ALLOW_PAID_TESTS=1")
@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="no LLM key: real run blocked")
def test_real_tradingagents_run(instrument_id: str, tmp_path: Path) -> None:
    from stock_office.config import Settings
    from stock_office.domain.models import CreateRunRequest, RunStatus
    from stock_office.wiring import build_service

    # Reads STOCK_OFFICE_TA_* (incl. cost profile) from the environment / .env.
    service = build_service(Settings(data_dir=tmp_path))
    run = service.create_run(CreateRunRequest(instrument_id=instrument_id, engine="tradingagents"))
    run = service.execute(run.id)
    print(f"\n{instrument_id}: {run.status} {run.error_code} {run.latency_ms}ms "
          f"config={run.config_hash} tokens={run.token_usage}")
    assert run.status is RunStatus.COMPLETED, run.error_message
    assert service.repo.get_decision(run.id) is not None
