"""Instrument identifiers (`COUNTRY:EXCHANGE:SYMBOL`) and the registry: the two milestone
instruments plus the research team's universe (KOSPI200, NASDAQ-100 snapshots in `universe/`)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Currency, Instrument, Market


class UnknownInstrumentError(LookupError):
    pass


class InvalidInstrumentIdError(ValueError):
    pass


_ID_RE = re.compile(r"^(US|KR):([A-Z]+):([A-Z0-9.\-]{1,12})$")

# Exchange -> (market, currency, exchange-local timezone, Yahoo suffix)
_EXCHANGES: dict[str, tuple[Market, Currency, str, str]] = {
    "NASDAQ": (Market.US, Currency.USD, "America/New_York", ""),
    "NYSE": (Market.US, Currency.USD, "America/New_York", ""),
    "KRX": (Market.KR, Currency.KRW, "Asia/Seoul", ".KS"),  # KOSPI board
    "KOSDAQ": (Market.KR, Currency.KRW, "Asia/Seoul", ".KQ"),
}

# DART corp codes are not derivable from the stock code; they must be looked up.
_DART_CORP_CODES = {"005930": "00126380"}

_NAMES = {
    "US:NASDAQ:NVDA": "NVIDIA Corporation",
    "KR:KRX:005930": "Samsung Electronics Co., Ltd.",
}

# Names people use in the office (display only; ids and data stay as they are).
_DISPLAY_KO = {
    "US:NASDAQ:NVDA": "엔비디아",
    "KR:KRX:005930": "삼성전자",
}

UNIVERSE_DIR = Path(__file__).resolve().parent.parent / "universe"


def _load_universe() -> dict[str, list[str]]:
    """Dated index snapshots → names and DART codes; returns the member ids per index."""
    members: dict[str, list[str]] = {"KOSPI200": [], "NASDAQ100": []}
    kr = json.loads((UNIVERSE_DIR / "kospi200.json").read_text(encoding="utf-8"))
    for m in kr["members"]:
        iid = f"KR:KRX:{m['code']}"
        members["KOSPI200"].append(iid)
        _NAMES.setdefault(iid, m["name"])
        _DISPLAY_KO.setdefault(iid, m["name"])
        if m.get("dart_corp_code"):
            _DART_CORP_CODES.setdefault(m["code"], m["dart_corp_code"])
    us = json.loads((UNIVERSE_DIR / "nasdaq100.json").read_text(encoding="utf-8"))
    for m in us["members"]:
        iid = f"US:NASDAQ:{m['symbol']}"
        members["NASDAQ100"].append(iid)
        _NAMES.setdefault(iid, m["name"])
        if m.get("name_ko"):
            _DISPLAY_KO.setdefault(iid, m["name_ko"])
    return members


UNIVERSE = _load_universe()


def display_name(instrument_id: str) -> str:
    return _DISPLAY_KO.get(instrument_id) or _NAMES.get(instrument_id) or instrument_id


def parse_instrument_id(instrument_id: str) -> Instrument:
    match = _ID_RE.match(instrument_id.strip().upper())
    if not match:
        raise InvalidInstrumentIdError(
            f"{instrument_id!r} is not COUNTRY:EXCHANGE:SYMBOL (e.g. US:NASDAQ:NVDA)"
        )
    country, exchange, symbol = match.groups()
    if exchange not in _EXCHANGES:
        raise InvalidInstrumentIdError(f"unsupported exchange {exchange!r}")
    market, currency, tz, yahoo_suffix = _EXCHANGES[exchange]
    if market.value != country:
        raise InvalidInstrumentIdError(f"exchange {exchange} is not in market {country}")
    if market is Market.KR and not re.fullmatch(r"\d{6}", symbol):
        raise InvalidInstrumentIdError("KR symbols are 6-digit KRX codes, e.g. 005930")
    canonical = f"{country}:{exchange}:{symbol}"
    provider_symbols = {"yahoo": f"{symbol}{yahoo_suffix}"}
    if symbol in _DART_CORP_CODES:
        provider_symbols["dart_corp_code"] = _DART_CORP_CODES[symbol]
    return Instrument(
        id=canonical,
        market=market,
        exchange=exchange,
        symbol=symbol,
        name=_NAMES.get(canonical, symbol),
        currency=currency,
        timezone=tz,
        provider_symbols=provider_symbols,
    )


# The two milestone instruments plus the research team's universe (KOSPI200, NASDAQ-100).
SUPPORTED_INSTRUMENT_IDS = tuple(dict.fromkeys(
    ("US:NASDAQ:NVDA", "KR:KRX:005930", *UNIVERSE["KOSPI200"], *UNIVERSE["NASDAQ100"])))
REGISTRY: dict[str, Instrument] = {i: parse_instrument_id(i) for i in SUPPORTED_INSTRUMENT_IDS}


def get_instrument(instrument_id: str) -> Instrument:
    canonical = parse_instrument_id(instrument_id).id
    try:
        return REGISTRY[canonical]
    except KeyError:
        raise UnknownInstrumentError(f"{canonical} is not in the registry") from None


def search_instruments(q: str = "", market: Market | None = None) -> list[Instrument]:
    q = q.strip().lower()
    return [
        inst
        for inst in REGISTRY.values()
        if (market is None or inst.market is market)
        and (not q or q in inst.id.lower() or q in inst.name.lower())
    ]
