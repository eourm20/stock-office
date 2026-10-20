"""Low-level client for Kiwoom's mock-trading REST server (read-only in step K1).

Safety, by construction:
- The base URL is the mock server, fixed here; any other base is refused.
- `query` reaches only READ paths (accounts, quotes). `send` reaches only the order path of each
  market with the order API ids listed here; it is called from `desks.py` alone, after the
  deterministic risk policy (MOCK ONLY: the mock server is the only place an order can go).
- App key, secret and token never appear in logs, exceptions or return values.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

MOCK_BASE_URL = "https://mockapi.kiwoom.com"
TOKEN_PATH = "/oauth2/token"
ALLOWED_PATHS = frozenset({"/api/dostk/acnt", "/api/us/acnt",       # accounts
                           "/api/dostk/stkinfo", "/api/us/mrkcond"})  # current prices
ORDER_PATHS = frozenset({"/api/dostk/ordr", "/api/us/ordr"})
# buy, sell, cancel (domestic kt1000x, US ust2000x); modify is not used
ORDER_API_IDS = frozenset({"kt10000", "kt10001", "kt10003", "ust20000", "ust20001", "ust20003"})
# Mock server limit: about one call per second per API and account; keep a little margin.
MIN_INTERVAL_S = 1.1
KST = ZoneInfo("Asia/Seoul")


class KiwoomMockError(RuntimeError):
    """A refused call or an error answer (`return_code` != 0). The message never holds secrets."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class KiwoomMockClient:
    def __init__(self, app_key: str, app_secret: str, *, base_url: str = MOCK_BASE_URL,
                 http: httpx.Client | None = None, sleep: Any = time.sleep) -> None:
        if base_url.rstrip("/") != MOCK_BASE_URL:
            raise KiwoomMockError("only Kiwoom's mock-trading server is allowed (MOCK ONLY)")
        if not app_key or not app_secret:
            raise KiwoomMockError("mock app key/secret not configured")
        self._key, self._secret = app_key, app_secret
        self._http = http or httpx.Client(timeout=10.0)
        self._sleep = sleep
        self._token: str | None = None
        self._token_until: datetime | None = None
        self._last_call = 0.0
        self._lock = threading.Lock()

    def close(self) -> None:
        self._http.close()

    # ---------------------------------------------------------------- token
    def _get_token(self, force: bool = False) -> str:
        now = datetime.now(UTC)
        if (not force and self._token and self._token_until
                and now < self._token_until - timedelta(minutes=5)):
            return self._token
        resp = self._http.post(f"{MOCK_BASE_URL}{TOKEN_PATH}", json={
            "grant_type": "client_credentials", "appkey": self._key, "secretkey": self._secret,
        }, headers={"Content-Type": "application/json;charset=UTF-8"})
        payload = self._json(resp, "token")
        token = str(payload.get("token") or "").strip()
        if not token:
            raise KiwoomMockError("token missing in the token response")
        self._token = token
        self._token_until = _expires(str(payload.get("expires_dt") or ""))
        return token

    # ---------------------------------------------------------------- calls
    def query(self, path: str, api_id: str, body: dict[str, Any],
              max_pages: int = 5) -> list[dict[str, Any]]:
        """Call one allowed API, following `cont-yn`/`next-key` pages; returns the payloads."""
        if path not in ALLOWED_PATHS:
            raise KiwoomMockError(f"path not allowed for queries: {path}")
        return self._call(path, api_id, body, max_pages)

    def send(self, path: str, api_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """One order request (buy/sell/cancel) to the MOCK server. Only `desks.py` calls this."""
        if path not in ORDER_PATHS or api_id not in ORDER_API_IDS:
            raise KiwoomMockError(f"order request not allowed: {api_id} {path}")
        return self._call(path, api_id, body, 1)[0]

    def _call(self, path: str, api_id: str, body: dict[str, Any],
              max_pages: int) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        cont, next_key = "N", ""
        with self._lock:
            for _ in range(max_pages):
                resp = self._post(path, api_id, body, cont, next_key)
                payload = self._json(resp, api_id)
                if str(payload.get("return_code")) == "3":  # token no longer valid: renew once
                    self._get_token(force=True)
                    resp = self._post(path, api_id, body, cont, next_key)
                    payload = self._json(resp, api_id)
                code = str(payload.get("return_code", "0"))
                if code not in ("0", "None"):
                    msg = str(payload.get("return_msg") or "")[:200]
                    raise KiwoomMockError(f"{api_id}: {msg or 'error'} (code {code})", code)
                pages.append(payload)
                cont, next_key = resp.headers.get("cont-yn", "N"), resp.headers.get("next-key", "")
                if cont != "Y" or not next_key:
                    break
        return pages

    def _post(self, path: str, api_id: str, body: dict[str, Any], cont: str,
              next_key: str) -> httpx.Response:
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        headers = {"Content-Type": "application/json;charset=UTF-8",
                   "authorization": f"Bearer {self._get_token()}", "api-id": api_id,
                   "cont-yn": cont, "next-key": next_key}
        try:
            return self._http.post(f"{MOCK_BASE_URL}{path}", json=body, headers=headers)
        except httpx.HTTPError as exc:  # no request details: headers carry the token
            raise KiwoomMockError(f"{api_id}: network error ({type(exc).__name__})") from None
        finally:
            self._last_call = time.monotonic()

    @staticmethod
    def _json(resp: httpx.Response, what: str) -> dict[str, Any]:
        if resp.status_code >= 400:
            raise KiwoomMockError(f"{what}: HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError:
            raise KiwoomMockError(f"{what}: answer is not JSON") from None
        if not isinstance(data, dict):
            raise KiwoomMockError(f"{what}: unexpected answer")
        return data


def _expires(text: str) -> datetime:
    try:
        return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=KST).astimezone(UTC)
    except ValueError:
        return datetime.now(UTC) + timedelta(hours=1)
