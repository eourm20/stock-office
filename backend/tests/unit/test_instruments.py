import pytest

from stock_office.domain.instruments import (
    InvalidInstrumentIdError,
    UnknownInstrumentError,
    get_instrument,
    parse_instrument_id,
    search_instruments,
)
from stock_office.domain.models import Currency, Market


def test_nvda_mapping() -> None:
    inst = get_instrument("US:NASDAQ:NVDA")
    assert (inst.market, inst.currency, inst.timezone) == (Market.US, Currency.USD,
                                                           "America/New_York")
    assert inst.provider_symbols == {"yahoo": "NVDA"}


def test_samsung_mapping() -> None:
    inst = get_instrument("kr:krx:005930")  # case-insensitive input, canonical output
    assert inst.id == "KR:KRX:005930"
    assert (inst.currency, inst.timezone) == (Currency.KRW, "Asia/Seoul")
    assert inst.provider_symbols["yahoo"] == "005930.KS"
    assert inst.provider_symbols["dart_corp_code"] == "00126380"


def test_kosdaq_suffix() -> None:
    assert parse_instrument_id("KR:KOSDAQ:035720").provider_symbols["yahoo"] == "035720.KQ"


@pytest.mark.parametrize("bad", ["NVDA", "US:NVDA", "US:KRX:005930", "KR:KRX:SAMSUNG",
                                 "JP:TSE:7203", "US:NASDAQ:"])
def test_invalid_ids_rejected(bad: str) -> None:
    with pytest.raises(InvalidInstrumentIdError):
        parse_instrument_id(bad)


def test_valid_but_not_enabled() -> None:
    with pytest.raises(UnknownInstrumentError):
        get_instrument("US:NASDAQ:AAPL")


def test_search() -> None:
    assert [i.id for i in search_instruments("samsung")] == ["KR:KRX:005930"]
    assert [i.id for i in search_instruments(market=Market.US)] == ["US:NASDAQ:NVDA"]
