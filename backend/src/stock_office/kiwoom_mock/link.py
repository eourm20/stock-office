"""The company's view of its Kiwoom mock accounts: configured or not, last snapshot, cached.

Never raises to callers: a missing key or a Kiwoom error is part of the status. Snapshots are cached
(the mock server allows about one call per second per API), and refreshing is throttled.

    .venv/bin/python -m stock_office.kiwoom_mock.link     # one check, prints field names only
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

from stock_office.kiwoom_mock.accounts import MockAccount, kr_account, us_account
from stock_office.kiwoom_mock.client import MOCK_BASE_URL, KiwoomMockClient, KiwoomMockError

CACHE_S = 300
MIN_REFRESH_S = 30


class KiwoomMockLink:
    def __init__(self, kr: tuple[str, str] | None, us: tuple[str, str] | None,
                 make_client: Callable[[str, str], KiwoomMockClient] = KiwoomMockClient) -> None:
        self._keys = {"KR": kr, "US": us}
        self._make = make_client
        self._clients: dict[str, KiwoomMockClient] = {}
        self._cache: dict[str, Any] | None = None
        self._at = 0.0
        self._lock = threading.Lock()

    @property
    def configured(self) -> dict[str, bool]:
        return {m: k is not None for m, k in self._keys.items()}

    def _client(self, market: str) -> KiwoomMockClient:
        if market not in self._clients:
            key = self._keys[market]
            assert key is not None
            self._clients[market] = self._make(*key)
        return self._clients[market]

    def status(self, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            age = time.monotonic() - self._at
            if self._cache is not None and age < (MIN_REFRESH_S if refresh else CACHE_S):
                return self._cache
            accounts: dict[str, Any] = {}
            for market, read in (("KR", kr_account), ("US", us_account)):
                if self._keys[market] is None:
                    accounts[market] = None
                    continue
                try:
                    accounts[market] = read(self._client(market)).to_dict()
                except KiwoomMockError as exc:  # e.g. a refused base URL or missing key
                    accounts[market] = MockAccount(market, "KRW" if market == "KR" else "USD",
                                                   ok=False, error=str(exc)).to_dict()
            self._cache = {"server": MOCK_BASE_URL, "mode": "MOCK", "read_only": True,
                           "configured": self.configured, "accounts": accounts}
            self._at = time.monotonic()
            return self._cache


def build_link(settings: Any) -> KiwoomMockLink:
    def pair(key: Any, secret: Any) -> tuple[str, str] | None:
        return (key.get_secret_value(), secret.get_secret_value()) if key and secret else None

    kr = pair(settings.kiwoom_mock_app_key, settings.kiwoom_mock_app_secret)
    # One key for both accounts unless the overseas mock account has its own.
    us = pair(settings.kiwoom_mock_us_app_key, settings.kiwoom_mock_us_app_secret) or kr
    return KiwoomMockLink(kr, us)


def main() -> int:
    """K1 check on the server: which queries work and which fields come back (no amounts)."""
    from stock_office.config import get_settings

    status = build_link(get_settings()).status(refresh=True)
    report: dict[str, Any] = {"configured": status["configured"]}
    for market, acc in status["accounts"].items():
        if acc is None:
            report[market] = "not configured"
            continue
        report[market] = {"ok": acc["ok"], "error": acc["error"], "notes": acc["notes"],
                          "holdings": len(acc["holdings"]), "fills_today": acc["fills_today"],
                          "cash_present": acc["cash"] is not None, "fields": acc["fields"]}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
