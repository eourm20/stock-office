"""SEC EDGAR filings for US stocks (미장 공시 보고), read-only.

EDGAR is public and keyless, but SEC's fair-access rules require a User-Agent naming the operator
with a contact address and at most 10 requests a second. The owner sets it in the server `.env`
(`STOCK_OFFICE_SEC_USER_AGENT`); without it US filing reports stay off. Ticker → CIK comes from
SEC's own `company_tickers.json` (refreshed daily), filings from `data.sec.gov/submissions`.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import httpx

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

# Forms worth a report to the CEO: periodic results, and 8-Ks only for the items below. 6-Ks
# (foreign issuers' frequent notices), amendments and other forms are checked but not reported.
FORM_KO = {"8-K": "8-K 수시 공시", "10-Q": "10-Q 분기 보고서", "10-K": "10-K 연간 보고서",
           "20-F": "20-F 연간 보고서(해외 기업)"}
# 8-K items that matter (Reg FD notices, shareholder votes and "other events" do not).
ITEM_KO = {"1.01": "중요 계약", "1.02": "계약 종료", "2.01": "인수·매각 완료", "2.02": "실적 발표",
           "2.05": "구조조정", "2.06": "자산 손상", "3.01": "상장 유지 문제",
           "4.02": "재무제표 신뢰 불가", "5.01": "지배권 변경", "5.02": "임원·이사 변경"}
LOOKBACK = timedelta(days=3)   # an after-close or weekend filing still reaches the next session
MIN_INTERVAL_S = 0.15


class SecFilings:
    def __init__(self, user_agent: str, client: httpx.Client | None = None) -> None:
        self.headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        self.client = client or httpx.Client(timeout=15)
        self._ciks: dict[str, int] = {}
        self._ciks_day: date | None = None
        self._last = 0.0

    def _get(self, url: str) -> Any:
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        resp = self.client.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def cik(self, ticker: str, today: date) -> int | None:
        if self._ciks_day != today:
            data = self._get(TICKERS_URL)
            self._ciks = {str(r["ticker"]).upper(): int(r["cik_str"]) for r in data.values()}
            self._ciks_day = today
        return self._ciks.get(ticker.upper().replace(".", "-"))

    def recent(self, ticker: str, day: date) -> list[tuple[str, str, str]]:
        """Report-worthy filings dated within LOOKBACK of `day`:
        [(accession number, Korean title, link to the document)], oldest first."""
        cik = self.cik(ticker, day)
        if cik is None:
            return []
        recent = self._get(SUBMISSIONS_URL.format(cik=cik)).get("filings", {}).get("recent", {})
        out = []
        for i, form in enumerate(recent.get("form", [])):
            if form not in FORM_KO:
                continue
            filed = date.fromisoformat(recent["filingDate"][i])
            if not day - LOOKBACK <= filed <= day:
                continue
            acc = str(recent["accessionNumber"][i])
            items = [ITEM_KO[x] for x in str(_at(recent, "items", i)).split(",") if x in ITEM_KO]
            if form == "8-K" and not items:
                continue
            title = FORM_KO[form] + (f" · {', '.join(items[:2])}" if items else "")
            doc = _at(recent, "primaryDocument", i)
            url = (ARCHIVE_URL.format(cik=cik, acc=acc.replace("-", ""), doc=doc) if doc
                   else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}")
            out.append((acc, title, url))
        return out[::-1]


def _at(recent: dict[str, Any], key: str, i: int) -> str:
    values = recent.get(key) or []
    return str(values[i]) if i < len(values) and values[i] else ""
