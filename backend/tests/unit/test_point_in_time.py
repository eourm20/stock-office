from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stock_office.domain.instruments import get_instrument
from stock_office.providers.base import ProviderError, enforce_point_in_time
from stock_office.providers.dart import parse_list_response
from stock_office.providers.fixture import FixtureProvider
from stock_office.providers.yahoo import bar_available_at
from tests.conftest import utc


def test_future_snapshots_are_excluded() -> None:
    nvda = get_instrument("US:NASDAQ:NVDA")
    as_of = utc("2026-10-15T12:00:00Z")  # before the 10-15 close is published
    result = FixtureProvider().fetch(nvda, as_of)
    pit = enforce_point_in_time(result.snapshots, as_of)
    assert all(s.available_at <= as_of for s in pit.allowed)
    assert [s.payload["date"] for s in pit.rejected] == ["2026-10-15"]


def test_boundary_is_inclusive() -> None:
    nvda = get_instrument("US:NASDAQ:NVDA")
    as_of = utc("2026-10-15T20:30:00Z")
    pit = enforce_point_in_time(FixtureProvider().fetch(nvda, as_of).snapshots, as_of)
    assert not pit.rejected


def test_fixture_snapshots_are_labelled_demo() -> None:
    snaps = FixtureProvider().fetch(get_instrument("KR:KRX:005930"), utc("2026-10-16T00:00:00Z"))
    assert snaps.snapshots and all(s.demo for s in snaps.snapshots)
    assert snaps.coverage_gaps  # KR news gap is reported, not hidden


def test_daily_bar_available_after_local_close() -> None:
    us = bar_available_at(datetime(2026, 10, 15), "America/New_York")
    kr = bar_available_at(datetime(2026, 10, 15), "Asia/Seoul")
    assert us == datetime(2026, 10, 15, 16, 30, tzinfo=ZoneInfo("America/New_York"))
    assert kr == datetime(2026, 10, 15, 16, 0, tzinfo=ZoneInfo("Asia/Seoul"))


def test_dart_disclosure_available_end_of_filing_day() -> None:
    samsung = get_instrument("KR:KRX:005930")
    body = {"status": "000", "list": [{"rcept_no": "20261015000001", "report_nm": " 분기보고서 ",
                                       "corp_name": "삼성전자", "flr_nm": "삼성전자",
                                       "rcept_dt": "20261015"}]}
    snap = parse_list_response(body, samsung).snapshots[0]
    assert snap.available_at == datetime(2026, 10, 15, 23, 59, 59, tzinfo=ZoneInfo("Asia/Seoul"))
    assert snap.payload["report_nm"] == "분기보고서"
    pit = enforce_point_in_time([snap], utc("2026-10-15T06:00:00Z"))  # 15:00 KST same day
    assert pit.rejected == [snap]


def test_dart_status_handling() -> None:
    samsung = get_instrument("KR:KRX:005930")
    assert parse_list_response({"status": "013"}, samsung).coverage_gaps
    with pytest.raises(ProviderError) as err:
        parse_list_response({"status": "020", "message": "limit"}, samsung)
    assert err.value.code == "PROVIDER_REJECTED"


def test_dart_without_key_reports_gap_not_success() -> None:
    from stock_office.providers.dart import DartDisclosureProvider

    result = DartDisclosureProvider(api_key=None).fetch(
        get_instrument("KR:KRX:005930"), utc("2026-10-16T00:00:00Z"))
    assert not result.snapshots and "DART_API_KEY" in result.coverage_gaps[0]
