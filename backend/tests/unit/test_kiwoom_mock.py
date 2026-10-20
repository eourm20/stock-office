"""Kiwoom mock link (K1, read-only): fixed mock server, token handling, paging, parsing. No network:
answers come from httpx.MockTransport in the shape of Kiwoom's official examples."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from stock_office.kiwoom_mock.accounts import kr_account, num, us_account
from stock_office.kiwoom_mock.client import KiwoomMockClient, KiwoomMockError
from stock_office.kiwoom_mock.link import KiwoomMockLink, build_link

SECRET = "s3cr3t-value"


class FakeKiwoom:
    """Answers by api-id; records what was asked."""

    def __init__(self, answers: dict[str, list[tuple[dict[str, Any], dict[str, str]]]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str, dict[str, Any], dict[str, str]]] = []
        self.tokens = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "mockapi.kiwoom.com"
        body = json.loads(request.content or b"{}")
        if request.url.path == "/oauth2/token":
            self.tokens += 1
            assert body["appkey"] == "key" and body["secretkey"] == SECRET
            return httpx.Response(200, json={"token": f"T{self.tokens}",
                                             "expires_dt": "20991231235959", "return_code": 0})
        api = request.headers["api-id"]
        self.calls.append((request.url.path, api, body, dict(request.headers)))
        payload, headers = self.answers[api].pop(0)
        return httpx.Response(200, json=payload, headers=headers)


def client(fake: FakeKiwoom) -> KiwoomMockClient:
    return KiwoomMockClient("key", SECRET, http=httpx.Client(transport=httpx.MockTransport(fake)),
                            sleep=lambda s: None)


def ok(**fields: Any) -> dict[str, Any]:
    return {"return_code": 0, "return_msg": "정상", **fields}


def test_only_the_mock_server_and_account_queries() -> None:
    with pytest.raises(KiwoomMockError):
        KiwoomMockClient("key", SECRET, base_url="https://api.kiwoom.com")
    with pytest.raises(KiwoomMockError):
        KiwoomMockClient("", "")
    c = client(FakeKiwoom({}))
    with pytest.raises(KiwoomMockError, match="not allowed"):
        c.query("/api/dostk/ordr", "x", {})


def test_pages_token_and_headers() -> None:
    fake = FakeKiwoom({"kt00018": [(ok(a=1), {"cont-yn": "Y", "next-key": "K2"}),
                                   (ok(a=2), {"cont-yn": "N"})]})
    pages = client(fake).query("/api/dostk/acnt", "kt00018", {"qry_tp": "1"})
    assert [p["a"] for p in pages] == [1, 2] and fake.tokens == 1
    (_, _, _, h1), (_, _, _, h2) = fake.calls
    assert h1["authorization"] == "Bearer T1" and h1["cont-yn"] == "N"
    assert (h2["cont-yn"], h2["next-key"]) == ("Y", "K2")


def test_expired_token_is_renewed_once_and_errors_carry_no_secret() -> None:
    fake = FakeKiwoom({"kt00001": [({"return_code": 3, "return_msg": "token"}, {}),
                                   (ok(entr="1"), {})],
                       "kt00018": [({"return_code": 20, "return_msg": "모의투자 미지원"}, {})]})
    c = client(fake)
    assert c.query("/api/dostk/acnt", "kt00001", {})[0]["entr"] == "1"
    assert fake.tokens == 2
    with pytest.raises(KiwoomMockError) as err:
        c.query("/api/dostk/acnt", "kt00018", {})
    assert "모의투자 미지원" in str(err.value) and err.value.code == "20"
    assert SECRET not in str(err.value) and "T2" not in str(err.value)


def test_domestic_account_snapshot() -> None:
    fake = FakeKiwoom({
        "kt00001": [(ok(entr="000000010000000", ord_alow_amt="000000009500000"), {})],
        "kt00018": [(ok(tot_evlt_amt="000000000466317", acnt_evlt_remn_indv_tot=[{
            "stk_cd": "A005930", "stk_nm": "삼성전자", "rmnd_qty": "000000000009",
            "pur_pric": "000000051300", "cur_prc": "000000051813", "evlt_amt": "000000466317",
            "evltv_prft": "000000004547", "prft_rt": "0.98"}]), {})],
        "kt00007": [(ok(acnt_ord_cntr_prps_dtl=[{"ord_no": "1"}, {"ord_no": "2"}]), {})],
    })
    acc = kr_account(client(fake))
    assert acc.ok
    assert (acc.cash, acc.orderable, acc.total_value) == ("10000000", "9500000", "466317")
    h = acc.holdings[0]
    assert (h.code, h.name, h.qty) == ("005930", "삼성전자", "9")
    assert (h.avg_price, h.price) == ("51300", "51813")
    assert acc.fills_today == 2
    assert acc.fields["kt00018"][-1] == "[]stk_nm" and "tot_evlt_amt" in acc.fields["kt00018"]
    body = fake.calls[1][2]
    assert body == {"qry_tp": "1", "dmst_stex_tp": "KRX"}  # mock: KRX only


def test_overseas_account_snapshot_and_empty_history() -> None:
    fake = FakeKiwoom({
        "ust21110": [(ok(krw_entra="0", result_list=[
            {"crnc_code": "USD", "fc_entra": "10000.00", "fc_ord_alowa": "9800.50"}]), {})],
        "ust21070": [(ok(tot_evlt_amt="389.97", result_list=[{
            "stk_cd": "NVDA", "frgn_stk_nm": "NVIDIA", "poss_qty": "3",
            "frgn_stk_book_uv": "120.08",
            "now_pric": "129.99", "evlt_amt": "389.97", "pl_amt": "29.73", "pl_rt": "8.25"}]), {})],
        "ust21510": [({"return_code": 20, "return_msg": "조회할 내역이 없습니다"}, {})],
    })
    acc = us_account(client(fake))
    assert (acc.cash, acc.orderable, acc.holdings[0].qty) == ("10000", "9800.5", "3")
    # an empty-history answer is a note, not a failed account
    assert acc.ok and acc.fills_today is None and "조회할 내역이 없습니다" in acc.notes[0]


def test_a_failed_deposit_query_fails_the_account() -> None:
    fake = FakeKiwoom({"kt00001": [({"return_code": 1, "return_msg": "IP 미등록"}, {})]})
    acc = kr_account(client(fake))
    assert not acc.ok and "IP 미등록" in (acc.error or "") and acc.holdings == []


def test_numbers_are_never_guessed() -> None:
    assert (num("-000000123"), num("+12.30"), num(""), num(None), num("abc")) == \
        ("-123", "12.3", None, None, None)


def test_link_status_without_keys_and_fallback_to_one_key() -> None:
    from stock_office.config import Settings

    status = build_link(Settings(_env_file=None)).status()  # type: ignore[call-arg]
    assert status["configured"] == {"KR": False, "US": False}
    assert status["accounts"] == {"KR": None, "US": None} and status["read_only"] is True
    one = build_link(Settings(_env_file=None, kiwoom_mock_app_key="k",  # type: ignore[call-arg]
                              kiwoom_mock_app_secret="s"))
    assert one.configured == {"KR": True, "US": True}


def test_link_caches_and_reports_errors_per_market() -> None:
    made: list[str] = []

    def make(key: str, secret: str) -> KiwoomMockClient:
        made.append(key)
        raise KiwoomMockError("mock app key/secret not configured")

    link = KiwoomMockLink(("kr", "s"), None, make_client=make)
    first = link.status()
    assert first["accounts"]["KR"]["ok"] is False and first["accounts"]["US"] is None
    assert link.status() is first and link.status(refresh=True) is first  # throttled
    assert made == ["kr"]
