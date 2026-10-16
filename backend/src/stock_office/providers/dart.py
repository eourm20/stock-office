"""Korean disclosures from OpenDART `list.json` (read-only, needs DART_API_KEY).

Status: response parsing is unit-tested against a payload in the documented shape; the live
endpoint has NOT been verified in Sprint 0 (no key available). See docs/sprint-0-report.md.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from stock_office.domain.models import Instrument, Market, MarketSnapshot

from .base import ProviderError, ProviderResult, payload_hash, utcnow

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
_KST = ZoneInfo("Asia/Seoul")
_NO_DATA_STATUS = "013"  # OpenDART: no matching data


class DartDisclosureProvider:
    name = "opendart"

    def __init__(
        self, api_key: str | None, lookback_days: int = 30, client: httpx.Client | None = None
    ) -> None:
        self._api_key = api_key
        self.lookback_days = lookback_days
        self._client = client

    def supports(self, instrument: Instrument) -> bool:
        return instrument.market is Market.KR and "dart_corp_code" in instrument.provider_symbols

    def fetch(self, instrument: Instrument, as_of: datetime) -> ProviderResult:
        if not self._api_key:
            return ProviderResult(coverage_gaps=[f"{self.name}: DART_API_KEY not configured"])
        local = as_of.astimezone(_KST)
        params = {
            "crtfc_key": self._api_key,
            "corp_code": instrument.provider_symbols["dart_corp_code"],
            "bgn_de": (local - timedelta(days=self.lookback_days)).strftime("%Y%m%d"),
            "end_de": local.strftime("%Y%m%d"),
            "page_count": "100",
        }
        client = self._client or httpx.Client(timeout=15)
        try:
            response = client.get(LIST_URL, params=params)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Never include the request URL: it carries the key.
            raise ProviderError("PROVIDER_REQUEST_FAILED", type(exc).__name__) from None
        finally:
            if self._client is None:
                client.close()
        return parse_list_response(body, instrument)


def parse_list_response(body: dict[str, Any], instrument: Instrument) -> ProviderResult:
    status = str(body.get("status", ""))
    if status == _NO_DATA_STATUS:
        return ProviderResult(coverage_gaps=["opendart: no disclosures in window"])
    if status != "000":
        raise ProviderError("PROVIDER_REJECTED", f"opendart status {status}")
    ingested = utcnow()
    snapshots = []
    for item in body.get("list", []):
        filed = datetime.strptime(item["rcept_dt"], "%Y%m%d").date()
        # list.json carries only the filing date: treat it as available at end of that KST day,
        # so a same-day as_of never sees it early.
        observed = datetime.combine(filed, time(0, 0), tzinfo=_KST)
        available = datetime.combine(filed, time(23, 59, 59), tzinfo=_KST)
        payload = {
            "rcept_no": item["rcept_no"],
            "report_nm": item.get("report_nm", "").strip(),
            "corp_name": item.get("corp_name"),
            "flr_nm": item.get("flr_nm"),
            "rcept_dt": item["rcept_dt"],
        }
        snapshots.append(
            MarketSnapshot(
                id=f"dart-{item['rcept_no']}",
                instrument_id=instrument.id,
                source="opendart",
                kind="disclosure",
                observed_at=observed,
                available_at=available,
                ingested_at=ingested,
                payload=payload,
                payload_hash=payload_hash(payload),
                source_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item['rcept_no']}",
            )
        )
    return ProviderResult(snapshots=snapshots)
