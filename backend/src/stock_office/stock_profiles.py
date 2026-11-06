"""What a stock is, in plain Korean, for the CEO (owner, 2026-11-06: "tap a stock in the research
report and see what it is: what the company does, which theme, or what an ETF holds").

On the first tap the API reads the stock's public profile from Yahoo Finance (type, name, sector,
industry and the business summary) and the engine's cheap "quick" model turns it into two plain
sentences and a few theme tags. Only that profile is the input: the model is told not to add
facts. The result is stored (`stock_profiles`) and reused for 90 days, so a stock costs about once.
Its tokens count in the monthly budget; nothing here feeds meetings or orders.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from stock_office.db import transaction
from stock_office.domain.instruments import REGISTRY, display_name
from stock_office.events.sanitize import redact_text

KEEP = timedelta(days=90)
SUMMARY_IN_PROMPT = 1500

InfoFetch = Callable[[str], dict[str, Any]]


class ProfileDraft(BaseModel):
    kind: Literal["회사", "ETF", "기타"] = Field(description="회사 주식인지 ETF인지")
    what: str = Field(description="무슨 회사(또는 ETF)인지 쉬운 말 1~2문장, 120자 이내")
    themes: list[str] = Field(default_factory=list,
                              description="관련 테마·업종 꼬리표 최대 4개 (예: AI 반도체, 2차전지)")


PROMPT = """아래는 한 종목의 공개 프로필이다. 주식을 전혀 모르는 사람이 이 종목이 무엇인지 알 수
있게 한국어로 정리하라.

- kind: 회사 주식이면 "회사", ETF면 "ETF".
- what: 무슨 일을 하는 회사인지(ETF면 무엇을 모아 담은 상품인지) 쉬운 존댓말 1~2문장.
  예) "스마트폰과 반도체를 만드는 한국 최대 전자 회사예요."
- themes: 사람들이 이 종목을 묶어 부르는 테마·업종 최대 4개 (예: AI 반도체, 2차전지, 방산, 바이오).
- 프로필에 없는 사실(실적 숫자, 최근 뉴스, 전망)을 만들지 마라. 투자 권유를 하지 마라.

프로필:
{payload}
"""


def _yahoo_info(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    info = yf.Ticker(symbol).info or {}
    return {k: info.get(k) for k in ("quoteType", "longName", "shortName", "sector", "industry",
                                     "longBusinessSummary", "category", "fundFamily")}


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def cached(conn: sqlite3.Connection, instrument_id: str, now: datetime) -> dict[str, Any] | None:
    row = conn.execute("SELECT body, created_at FROM stock_profiles WHERE instrument_id=?",
                       (instrument_id,)).fetchone()
    if row is None or now - datetime.fromisoformat(row["created_at"]) > KEEP:
        return None
    body: dict[str, Any] = json.loads(row["body"])
    return body


def profile(conn: sqlite3.Connection, instrument_id: str, now: datetime, writer: Any,
            fetch: InfoFetch = _yahoo_info) -> dict[str, Any]:
    """The stock's plain profile, from the cache or made now. Raises LookupError for an unknown
    stock and RuntimeError when it cannot be made (no engine, no data)."""
    if instrument_id not in REGISTRY:
        raise LookupError(instrument_id)
    hit = cached(conn, instrument_id, now)
    if hit is not None:
        return hit
    if writer is None:
        raise RuntimeError("AI 설명을 만들 수 없는 상태예요 (엔진 미설정 또는 예산 부족).")
    inst = REGISTRY[instrument_id]
    info = fetch(inst.provider_symbols["yahoo"])
    if not (info.get("longName") or info.get("shortName")):
        raise RuntimeError("이 종목의 공개 프로필을 찾지 못했어요.")
    info["longBusinessSummary"] = str(info.get("longBusinessSummary") or "")[:SUMMARY_IN_PROMPT]
    draft, usage = writer(PROMPT.format(payload=json.dumps(
        {"korean_name": display_name(instrument_id), **info}, ensure_ascii=False, indent=0)))
    body = {
        "instrument_id": instrument_id, "name": display_name(instrument_id),
        "kind": draft.kind, "what": redact_text(" ".join(draft.what.split()), limit=200),
        "themes": [" ".join(t.split())[:20] for t in draft.themes if t.strip()][:4],
        "industry": info.get("industry") or info.get("category") or "",
        "source": "Yahoo Finance 회사 프로필 → AI 요약", "model": getattr(writer, "model", ""),
    }
    with transaction(conn):
        conn.execute("INSERT OR REPLACE INTO stock_profiles (instrument_id, body, token_usage, "
                     "created_at) VALUES (?,?,?,?)",
                     (instrument_id, json.dumps(body, ensure_ascii=False),
                      json.dumps(usage) if usage else None, _iso(now)))
    return body


def usages(conn: sqlite3.Connection, month: str) -> list[dict[str, Any]]:
    """This month's profile-making token usage (Korea time), for the budget."""
    from stock_office.budget import month_key

    return [json.loads(r["token_usage"]) for r in conn.execute(
        "SELECT token_usage, created_at FROM stock_profiles WHERE token_usage IS NOT NULL")
        if month_key(datetime.fromisoformat(r["created_at"])) == month]


def writer_for(service: Any, settings: Any) -> Any:
    """The quick model when the engine is ready and the budget allows, else None."""
    from stock_office.engine.adapter import EngineNotConfiguredError
    from stock_office.market_news import QuickModelWriter, _budget_ok

    engine = service.engines("tradingagents")
    try:
        engine.check_ready()
    except EngineNotConfiguredError:
        return None
    if not _budget_ok(service):
        return None
    return QuickModelWriter(engine.build_config(settings.data_dir / "stock_profiles"),
                            ProfileDraft)
