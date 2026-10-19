import logging
from datetime import UTC, datetime

from stock_office.domain.models import MarketSnapshot
from stock_office.engine.ta_extensions import (
    collect_upstream_data_gaps,
    format_disclosures,
    instrument_for_provider_symbol,
)


def _disclosure(no: str, day: str, title: str) -> MarketSnapshot:
    payload = {"rcept_no": no, "report_nm": title, "rcept_dt": day, "flr_nm": "삼성전자"}
    return MarketSnapshot(
        id=f"dart-{no}", instrument_id="KR:KRX:005930", source="opendart", kind="disclosure",
        observed_at=datetime(2026, 10, 12, tzinfo=UTC),
        available_at=datetime(2026, 10, 13, tzinfo=UTC),
        ingested_at=datetime(2026, 10, 16, tzinfo=UTC), payload=payload, payload_hash="h",
        source_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={no}")


def test_provider_symbol_lookup() -> None:
    inst = instrument_for_provider_symbol("005930.KS")
    assert inst is not None and inst.id == "KR:KRX:005930"
    assert instrument_for_provider_symbol("UNKNOWN.KS") is None


def test_disclosures_are_labelled_as_filings_newest_first() -> None:
    text = format_disclosures("005930.KS", "2026-10-09", "2026-10-16", [
        _disclosure("1", "20261012", "자기주식취득결과보고서"),
        _disclosure("2", "20261013", "최대주주등소유주식변동신고서"),
    ])
    assert "NOT press news" in text
    lines = [line for line in text.splitlines() if line.startswith("- ")]
    assert lines[0].startswith("- 2026-10-13 | 최대주주등소유주식변동신고서")
    assert "rcpNo=1" in lines[1]


def test_upstream_warnings_become_redacted_deduplicated_gaps() -> None:
    log = logging.getLogger("tradingagents.dataflows.vendors.yfinance")
    with collect_upstream_data_gaps() as gaps:
        for _ in range(2):
            log.warning("Yahoo Finance has no news articles tagged %s", "005930.KS")
        logging.getLogger("tradingagents.dataflows.router").warning(
            "Vendor 'x' failed: GET https://h/api?crtfc_key=abcdef1234567890abcd")
        logging.getLogger("tradingagents.x").info("not a gap")
    assert len(gaps.gaps) == 2
    assert gaps.gaps[0].startswith("tradingagents: Yahoo Finance has no news")
    assert "abcdef1234567890" not in gaps.gaps[1]
    # Detached after the run: later warnings are not collected.
    log.warning("after run")
    assert len(gaps.gaps) == 2


def test_disabled_prediction_markets_are_not_a_data_gap() -> None:
    import logging

    from stock_office.engine.ta_extensions import collect_upstream_data_gaps

    log = logging.getLogger("tradingagents.dataflows")
    with collect_upstream_data_gaps() as gaps:
        log.warning("Vendor 'stockoffice_off' unavailable for get_prediction_markets: prediction "
                    "markets disabled in Stock Office (Polymarket blocks this network: HTTP 451)")
        log.warning("Polymarket search failed for 'Fed rate cut': 451 Client Error")
        log.warning("Vendor 'yfinance' unavailable for get_news: no news articles tagged X")
    assert len(gaps.gaps) == 1 and "get_news" in gaps.gaps[0]


def test_engine_config_runs_two_debate_rounds(tmp_path: object) -> None:
    from pathlib import Path

    from stock_office.config import Settings
    from stock_office.engine.tradingagents_engine import TradingAgentsEngine

    engine = TradingAgentsEngine(Settings(data_dir=Path(str(tmp_path)), _env_file=None))  # type: ignore[call-arg]
    overrides = engine._overrides()
    assert overrides["max_debate_rounds"] == 2 and overrides["max_risk_discuss_rounds"] == 2
