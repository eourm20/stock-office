"""Read-only snapshots of the owner's Kiwoom mock accounts (domestic KRW, overseas USD).

Field names follow Kiwoom's official examples (domestic: kt00001 / kt00018 / kt00007; US: ust21110 /
ust21070 / ust21510). Parsing is lenient: a missing field is None, never a guessed number, and the
field names actually returned are kept so step K1 can confirm them against the live mock server.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from stock_office.kiwoom_mock.client import KiwoomMockClient, KiwoomMockError

KST = ZoneInfo("Asia/Seoul")
KR_PATH, US_PATH = "/api/dostk/acnt", "/api/us/acnt"


@dataclass
class MockHolding:
    code: str
    name: str
    qty: str | None
    avg_price: str | None
    price: str | None
    value: str | None
    pnl: str | None
    pnl_pct: str | None


@dataclass
class MockAccount:
    market: str                      # KR | US
    currency: str                    # KRW | USD
    ok: bool = True
    error: str | None = None
    cash: str | None = None          # deposit in the account currency
    orderable: str | None = None
    total_value: str | None = None   # holdings at the current price
    holdings: list[MockHolding] = field(default_factory=list)
    fills_today: int | None = None
    checked_at: str = ""
    # Queries after the deposit that failed (e.g. "no data" answers); the account is still shown.
    notes: list[str] = field(default_factory=list)
    # API id → field names seen (checked in K1; values are never kept here)
    fields: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def num(value: Any) -> str | None:
    """Kiwoom numbers come as zero-padded strings with signs ("-000000123", "+12.3")."""
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return format(Decimal(text).normalize(), "f")
    except InvalidOperation:
        return None


def _rows(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        rows = payload.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def _fields(payload: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    top = sorted(k for k in payload if k not in ("return_code", "return_msg"))
    return top + (sorted(f"[]{k}" for k in rows[0]) if rows else [])


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _step(acc: MockAccount, run: Any) -> None:
    """A query after the deposit: its failure is noted, the rest of the account still shows."""
    try:
        run()
    except KiwoomMockError as exc:
        acc.notes.append(str(exc))


def kr_account(client: KiwoomMockClient) -> MockAccount:
    acc = MockAccount("KR", "KRW", checked_at=_now())
    try:
        dep = client.query(KR_PATH, "kt00001", {"qry_tp": "3"})[0]
    except KiwoomMockError as exc:
        acc.ok, acc.error = False, str(exc)
        return acc
    acc.cash, acc.orderable = num(dep.get("entr")), num(dep.get("ord_alow_amt"))
    acc.fields["kt00001"] = _fields(dep, [])

    def balance() -> None:
        pages = client.query(KR_PATH, "kt00018", {"qry_tp": "1", "dmst_stex_tp": "KRX"})
        rows = [r for p in pages for r in _rows(p, "acnt_evlt_remn_indv_tot")]
        acc.total_value = num(pages[0].get("tot_evlt_amt"))
        acc.fields["kt00018"] = _fields(pages[0], rows)
        acc.holdings = [MockHolding(
            code=str(r.get("stk_cd") or "").strip().lstrip("A"), name=str(r.get("stk_nm") or ""),
            qty=num(r.get("rmnd_qty")), avg_price=num(r.get("pur_pric")),
            price=num(r.get("cur_prc")), value=num(r.get("evlt_amt")),
            pnl=num(r.get("evltv_prft")), pnl_pct=num(r.get("prft_rt"))) for r in rows]

    def fills() -> None:
        today = datetime.now(KST).strftime("%Y%m%d")
        pages = client.query(KR_PATH, "kt00007", {
            "ord_dt": today, "qry_tp": "1", "stk_bond_tp": "0", "sell_tp": "0", "stk_cd": "",
            "fr_ord_no": "", "dmst_stex_tp": "KRX"})
        rows = [r for p in pages for r in _rows(p, "acnt_ord_cntr_prps_dtl")]
        acc.fills_today = len(rows)
        acc.fields["kt00007"] = _fields(pages[0], rows)

    _step(acc, balance)
    _step(acc, fills)
    return acc


def us_account(client: KiwoomMockClient) -> MockAccount:
    acc = MockAccount("US", "USD", checked_at=_now())
    try:
        dep = client.query(US_PATH, "ust21110", {})[0]
    except KiwoomMockError as exc:
        acc.ok, acc.error = False, str(exc)
        return acc
    cur = _rows(dep, "result_list")
    usd = next((r for r in cur if str(r.get("crnc_code") or "").upper() == "USD"), None)
    if usd:
        acc.cash, acc.orderable = num(usd.get("fc_entra")), num(usd.get("fc_ord_alowa"))
    acc.fields["ust21110"] = _fields(dep, cur)

    def balance() -> None:
        pages = client.query(US_PATH, "ust21070", {"stex_tp": "", "stk_cd": ""})
        rows = [r for p in pages for r in _rows(p, "result_list")]
        acc.total_value = num(pages[0].get("tot_evlt_amt"))
        acc.fields["ust21070"] = _fields(pages[0], rows)
        acc.holdings = [MockHolding(
            code=str(r.get("stk_cd") or "").strip(), name=str(r.get("frgn_stk_nm") or ""),
            qty=num(r.get("poss_qty")), avg_price=num(r.get("frgn_stk_book_uv")),
            price=num(r.get("now_pric")), value=num(r.get("evlt_amt")),
            pnl=num(r.get("pl_amt")), pnl_pct=num(r.get("pl_rt"))) for r in rows]

    def fills() -> None:
        pages = client.query(US_PATH, "ust21510", {"slby_tp": "0", "stex_tp": "", "stk_cd": ""})
        rows = [r for p in pages for r in _rows(p, "result_list")]
        acc.fills_today = len(rows)
        acc.fields["ust21510"] = _fields(pages[0], rows)

    _step(acc, balance)
    _step(acc, fills)
    return acc
