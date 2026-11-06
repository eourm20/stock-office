"""[시장 브리핑]: the market-moving news of the last day for the CEO, in plain Korean.

Owner, 2026-11-06: "I can't read all the news; collect it, pick what moves Korean or US stocks,
translate and summarise it, and explain it so someone who knows nothing gets it, with a story-like
example." Twice a day, before each market opens (국내장 07:20 KST, 해외장 90 minutes before the
NYSE open), the briefing desk:

1. collects headlines (title and the publisher's summary only, never article bodies): Yahoo
   Finance searches over the same market-wide topics the meetings read, Naver searches for the
   Korean market, economy and policy; each index's biggest movers of the last session (why did
   it move?); a fixed sweep of the main sectors (quiet sectors' big news); and the company's own
   stocks (all held, top 10 of each watchlist);
2. has the engine's cheap "quick" model pick up to 10 by impact on stocks, favouring our stocks
   and their sectors/themes, merge stories about the same event, and write each in Korean: what
   happened, an everyday analogy, why it matters, which market/sectors, in which direction, and
   which of our stocks it touches (only names from our list are kept);
3. files one inbox report shown on both desks. Sources (title, publisher, link) come from the
   collected list, never from the model; picks citing unknown sources are dropped.

It is an *AI summary of headlines*, labelled so, not advice; it never feeds orders or meetings.
Its tokens count against the monthly budget (`usages_in_month`). A failure is filed as such.

    uv run python -m stock_office.market_news [NOW|KR|US]   # write one now (paid, ~$0.005)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from stock_office.db import transaction
from stock_office.domain.instruments import REGISTRY, display_name
from stock_office.domain.models import Market
from stock_office.engine.ta_extensions import (
    GLOBAL_NEWS_QUERIES,
    YahooSearch,
    _yahoo_search,
    kr_market_headlines,
    yahoo_global_articles,
)
from stock_office.events.sanitize import redact_text
from stock_office.providers.naver import NaverNewsProvider

log = logging.getLogger("stock_office.market_news")
KST = ZoneInfo("Asia/Seoul")

LEADS = {"KR": timedelta(minutes=100), "US": timedelta(minutes=90)}
SLOT_KO = {"KR": "아침 · 국내장 개장 전", "US": "저녁 · 해외장 개장 전", "NOW": "수시"}
LOOKBACK_DAYS = 1
YAHOO_POOL = 24
# The Korean market, Korean economy and politics/policy (owner, 2026-11-06), and what Korean press
# says about the US market. No fixed sector: sectors come from the company's own stocks below.
NAVER_QUERIES = ("코스피 증시", "코스닥 증시", "외국인 순매도", "원달러 환율", "뉴욕증시",
                 "한국은행 기준금리", "수출 실적", "정부 증시 정책", "국회 법안 기업",
                 "경제 정책 발표")
NAVER_PER_QUERY = 4
# The company's own stocks (owner, 2026-11-06: "갖고 있는 종목, 관심 종목 기사도, 그 테마도"):
# every held stock and the top of each market's latest watchlist, a few newest headlines each.
WATCH_PER_MARKET = 10
STOCK_HEADLINES = 3
# Wider than our own stocks (owner, 2026-11-06): what moved in each index in its last session
# (biggest gainers and losers, at least 3%), and a sweep of the main sectors so a quiet sector's
# big news (policy, orders) is not missed. Sectors are a fixed, balanced list, not a favourite.
MOVERS_PER_SIDE = 3
MOVER_MIN = 0.03
MOVER_HEADLINES = 2
SECTORS_KR = ("반도체 업황", "2차전지 배터리", "바이오 제약", "자동차 업계", "조선 수주",
              "방산 수출", "은행 금융지주", "인터넷 게임", "정유 에너지", "화장품 소비재")
SECTORS_US = ("semiconductor stocks", "biotech pharma stocks", "EV battery automakers",
              "bank stocks financials", "software cloud stocks", "retail consumer stocks",
              "energy oil stocks", "defense aerospace stocks")
SECTOR_HEADLINES = 2
SUMMARY_IN_PROMPT = 280
MIN_CANDIDATES = 3
MAX_PICKS = 10
# Meetings come first: a briefing is written only while this much of the month's budget is left
# (about a day of meetings), so the budget never runs out on a briefing.
RESERVE_USD = Decimal("0.60")
DEDUPE_PREFIX = "market-briefing:"


# ------------------------------------------------------------------------------ schedule

def due(market: str, now: datetime) -> date | None:
    """The session day this market's briefing is for, if `now` is in its slot (lead → open)."""
    from stock_office.schedule import first_session_opening_after

    nxt = first_session_opening_after(Market(market), now)
    return nxt.day if nxt.open - LEADS[market] <= now < nxt.open else None


def dedupe_key(market: str, day: date) -> str:
    return f"{DEDUPE_PREFIX}{market}:{day.isoformat()}"


# ------------------------------------------------------------------------------- collect

Stock = tuple[str, str]   # (instrument id, "보유" | "관심")
Moves = Callable[[str], dict[str, float]]   # market -> {instrument id: last session's change}


def _ko(snap: Any, about: str = "") -> dict[str, Any]:
    p = snap.payload
    return {"lang": "ko", "publisher": "", "about": about,
            "published": snap.observed_at.astimezone(KST).strftime("%m-%d %H:%M"),
            "title": p["title"], "summary": p.get("description") or "",
            "url": p.get("link") or ""}


def _en(a: dict[str, Any], about: str = "") -> dict[str, Any]:
    pub = a.get("pub_date")
    return {"lang": "en", "publisher": a.get("publisher") or "", "about": about,
            "published": pub.astimezone(KST).strftime("%m-%d %H:%M") if pub else "",
            "title": a["title"], "summary": str(a.get("summary") or ""),
            "url": a.get("link") or ""}


def _numbered(rows: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    for n, row in enumerate(rows, start=1):
        row["id"] = f"{prefix}{n}"
    return rows


def our_stocks(conn: sqlite3.Connection, held: Callable[[str], list[str]]) -> list[Stock]:
    """Held stocks first, then the top of each market's latest watchlist (known instruments)."""
    out: dict[str, str] = {}
    for market in ("KR", "US"):
        for iid in held(market):
            out.setdefault(iid, "보유")
    for market in ("KR", "US"):
        row = conn.execute("SELECT watchlist FROM research_runs WHERE market=? ORDER BY id DESC "
                           "LIMIT 1", (market,)).fetchone()
        for iid in json.loads(row["watchlist"])[:WATCH_PER_MARKET] if row else []:
            out.setdefault(iid, "관심")
    return [(iid, role) for iid, role in out.items() if iid in REGISTRY]


def stock_headlines(labelled: Sequence[tuple[str, str, int]], as_of: str,
                    naver: NaverNewsProvider | None, search: YahooSearch) -> list[dict[str, Any]]:
    """Newest headlines about each (instrument, label, count): Naver by Korean name, Yahoo by
    ticker. The label (e.g. "보유: 삼성전자", "급등 +8.1%: 한화오션") travels as `about`."""
    end = date.fromisoformat(as_of)
    start = end - timedelta(days=LOOKBACK_DAYS)
    out: list[dict[str, Any]] = []
    for iid, about, count in labelled:
        inst = REGISTRY[iid]
        try:
            if inst.market is Market.KR:
                if naver is None or not naver.configured:
                    continue
                snaps = sorted(naver.fetch_range(inst, start, end, limit=10).snapshots,
                               key=lambda s: s.observed_at, reverse=True)[:count]
                out += [_ko(s, about) for s in snaps]
            else:
                arts = yahoo_global_articles(as_of, LOOKBACK_DAYS, count,
                                             [inst.provider_symbols["yahoo"]], search)
                out += [_en(a, about) for a in arts]
        except Exception as exc:
            log.warning("stock news for %s failed: %s", iid, type(exc).__name__)
    return out


def movers(moves: dict[str, float]) -> list[tuple[str, float]]:
    """Biggest gainers then biggest losers of one index (each at least MOVER_MIN)."""
    up = sorted(((i, c) for i, c in moves.items() if c >= MOVER_MIN), key=lambda x: -x[1])
    down = sorted(((i, c) for i, c in moves.items() if c <= -MOVER_MIN), key=lambda x: x[1])
    return up[:MOVERS_PER_SIDE] + down[:MOVERS_PER_SIDE]


def yahoo_moves(market: str) -> dict[str, float]:
    """Each index member's change over its last completed session (Yahoo daily closes)."""
    import yfinance as yf

    from stock_office.domain.instruments import UNIVERSE
    from stock_office.research.team import INDEX

    symbols = {REGISTRY[i].provider_symbols["yahoo"]: i
               for i in UNIVERSE[INDEX[market]] if i in REGISTRY}
    frame = yf.download(list(symbols), period="7d", interval="1d", group_by="ticker",
                        auto_adjust=False, threads=True, progress=False)
    out: dict[str, float] = {}
    for sym, iid in symbols.items():
        try:
            close = frame[sym]["Close"].dropna()
        except KeyError:
            continue
        if len(close) >= 2 and float(close.iloc[-2]) > 0:
            out[iid] = float(close.iloc[-1]) / float(close.iloc[-2]) - 1
    return out


def sector_headlines(as_of: str, naver: NaverNewsProvider | None,
                     search: YahooSearch) -> list[dict[str, Any]]:
    """A couple of newest headlines per main sector, Korean and US."""
    out: list[dict[str, Any]] = []
    if naver is not None and naver.configured:
        snaps = kr_market_headlines(naver, as_of, LOOKBACK_DAYS, SECTORS_KR,
                                    limit=SECTOR_HEADLINES * len(SECTORS_KR))
        out += [_ko(s, f"업종: {s.payload.get('query', '')}") for s in snaps]
    for query in SECTORS_US:
        arts = yahoo_global_articles(as_of, LOOKBACK_DAYS, SECTOR_HEADLINES, [query], search)
        out += [_en(a, f"업종: {query}") for a in arts]
    return out


def collect(as_of: str, naver: NaverNewsProvider | None, search: YahooSearch = _yahoo_search,
            stocks: Sequence[Stock] = (), moves: Moves | None = None) -> list[dict[str, Any]]:
    """Candidate headlines, numbered by kind: e (market-wide, English), k (market-wide, Korean),
    s (our stocks and the session's big movers; `about` says which), u (sector sweep)."""
    world = yahoo_global_articles(as_of, LOOKBACK_DAYS, YAHOO_POOL, GLOBAL_NEWS_QUERIES, search)
    korea = (kr_market_headlines(naver, as_of, LOOKBACK_DAYS, NAVER_QUERIES,
                                 limit=NAVER_PER_QUERY * len(NAVER_QUERIES))
             if naver is not None and naver.configured else [])
    labels: dict[str, tuple[str, int]] = {
        iid: (f"{role}: {display_name(iid)}", STOCK_HEADLINES) for iid, role in stocks}
    for market in ("KR", "US"):
        if moves is None:
            break
        try:
            moved = movers(moves(market))
        except Exception as exc:
            log.warning("%s movers failed: %s", market, type(exc).__name__)
            continue
        for iid, change in moved:
            tag = f"{'급등' if change > 0 else '급락'} {change:+.1%} (최근 거래일)"
            label, count = labels.get(iid, (display_name(iid), MOVER_HEADLINES))
            labels[iid] = (f"{label} · {tag}" if iid in labels else f"{tag}: {label}", count)
    return (_numbered([_en(a) for a in world], "e") + _numbered([_ko(s) for s in korea], "k")
            + _numbered(stock_headlines([(i, lab, n) for i, (lab, n) in labels.items()],
                                        as_of, naver, search), "s")
            + _numbered(sector_headlines(as_of, naver, search), "u"))


# --------------------------------------------------------------------------------- model

class NewsPick(BaseModel):
    source_ids: list[str] = Field(description="이 소식의 근거 기사 id (입력의 id 그대로, 1~3개)")
    title: str = Field(description="한국어 제목, 35자 이내 (영어 기사는 번역)")
    summary: str = Field(description="무슨 일인지 2~3문장, 기사에 있는 사실만")
    story: str = Field(description="주식을 모르는 사람을 위한 일상 비유 이야기 2~4문장")
    why: str = Field(description="주가에 왜 중요한지 1~2문장")
    markets: list[Literal["KR", "US"]] = Field(description="영향받는 시장")
    sectors: list[str] = Field(default_factory=list, description="영향받는 업종·대표 기업 최대 4개")
    direction: Literal["좋음", "나쁨", "엇갈림"] = Field(description="그 업종·시장에 미칠 방향")
    our_stocks: list[str] = Field(
        default_factory=list, description="이 소식이 영향을 주는 우리 회사 종목 이름 (목록 그대로)")


class MarketBriefingDraft(BaseModel):
    mood: str = Field(description="오늘 시장 분위기 한 문장")
    picks: list[NewsPick] = Field(description="중요한 순서로 최대 10개")


PROMPT = """너는 주식을 전혀 모르는 사장님께 시장 소식을 들려주는 비서다. 아래 JSON은 지난 하루 \
동안 모은 국내외 경제 기사의 제목과 짧은 요약이다(본문은 없다). lang이 en인 기사는 영어다.

할 일:
1. 한국 주식이나 미국 주식에 영향을 줄 만한 소식을 중요한 순서로 최대 10개 골라라.
   - 시장 전체를 흔드는 큰 소식(경제, 정치, 정부 정책, 금리, 환율 등)을 먼저 본다.
   - 우리 회사 종목(아래 목록)에 영향을 주는 소식을 우선한다. 보유 종목에 중요한 소식이 있으면
     꼭 넣는다. 그 종목 자체의 기사(about이 있는 기사)뿐 아니라 그 종목이 속한 업종·테마의
     소식도 본다. 예) 보유 종목이 화장품 회사면 중국 소비 소식, 은행이면 금리 소식.
   - about이 "급등"/"급락"인 기사는 최근 거래일에 크게 움직인 종목이다. 왜 움직였는지 설명하는
     기사가 있으면 넣어라(우리가 가지지 않은 종목이라도). 이유를 모르면 추측하지 마라.
   - about이 "업종"인 기사는 주요 업종을 고르게 훑은 것이다. 조용한 업종의 큰 소식(정책, 수주,
     규제)을 놓치지 마라.
   - 한 업종에 쏠리지 말고 다양하게: 같은 업종은 최대 3개.
   - 같은 사건을 다룬 기사는 하나로 묶고 source_ids에 함께 적어라.
   - 연예·스포츠·광고성 기사, 관계없는 작은 회사의 홍보 기사는 빼라.
2. 각 소식마다 title, summary, story, why, markets, sectors, direction, our_stocks를 써라.
   - story는 동네 가게, 학교, 마을, 집안 살림 같은 일상 비유로 쓴 짧은 이야기다.
     "비유하자면" 또는 "마치 ~처럼"으로 비유임을 드러내라.
     예) 금리 인상: 비유하자면 동네 은행이 대출 이자를 올리자, 가게 주인들이 새 가게를 내기를
     망설이고 손님들도 지갑을 닫는 것과 같아요.
   - why에는 어떤 회사나 업종이 왜 영향을 받는지 써라. 우리 회사 종목이 관련되면 그 이유도.
   - our_stocks에는 이 소식이 영향을 주는 우리 회사 종목 이름만 목록 그대로 적어라(없으면 빈 목록).
3. mood: 오늘 시장 분위기를 한 문장으로.

규칙:
- 입력에 없는 사실, 숫자, 회사 이름을 만들지 마라. 비유에도 새 사실을 넣지 마라.
- 확정되지 않은 소문·전망·법안은 "~라는 보도가 있어요", "~할 수 있다는 우려가 있어요"처럼
  확정되지 않았음을 밝혀라.
- 사라/팔라 같은 투자 권유를 하지 마라.
- 쉬운 존댓말(~요)로 써라. 전문 용어는 괄호로 풀어라. 예: 금리(돈을 빌리는 값)
- 영어 기사는 자연스러운 한국어로 옮겨라.

우리 회사 종목:
{stocks}

기사:
{payload}
"""


def build_prompt(candidates: Sequence[dict[str, Any]], stocks: Sequence[Stock] = ()) -> str:
    rows = [{"id": c["id"], "lang": c["lang"], "publisher": c["publisher"],
             "published": c["published"], "title": c["title"],
             "summary": c["summary"][:SUMMARY_IN_PROMPT],
             **({"about": c["about"]} if c.get("about") else {})} for c in candidates]
    held = ", ".join(display_name(i) for i, r in stocks if r == "보유") or "없음"
    watched = ", ".join(display_name(i) for i, r in stocks if r == "관심") or "없음"
    return PROMPT.format(stocks=f"보유: {held}\n관심: {watched}",
                         payload=json.dumps(rows, ensure_ascii=False, indent=0))


class Writer(Protocol):
    model: str

    def __call__(self, prompt: str) -> tuple[MarketBriefingDraft, dict[str, Any] | None]: ...


class QuickModelWriter:
    """The engine's quick-tier model (same provider/config as the meetings), structured output."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.model = str(config.get("quick_think_llm", ""))

    def __call__(self, prompt: str) -> tuple[MarketBriefingDraft, dict[str, Any] | None]:
        from langchain_core.callbacks import UsageMetadataCallbackHandler

        from stock_office.engine.upstream import import_tradingagents

        import_tradingagents()
        from tradingagents.llm_clients.factory import create_tier_client

        usage = UsageMetadataCallbackHandler()
        llm = create_tier_client(self.config, "quick").get_llm()
        result = llm.with_structured_output(MarketBriefingDraft).invoke(
            prompt, config={"callbacks": [usage]})
        if not isinstance(result, MarketBriefingDraft):
            raise TypeError("structured output did not return a MarketBriefingDraft")
        return result, {k: dict(v) for k, v in usage.usage_metadata.items()}


# ------------------------------------------------------------------------------ finalize

def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return redact_text(text if len(text) <= limit else text[: limit - 1] + "…", limit=limit + 20)


def finalize(draft: MarketBriefingDraft, candidates: Sequence[dict[str, Any]],
             stocks: Sequence[Stock] = ()) -> tuple[str, list[dict[str, Any]]]:
    """Keep picks that cite collected headlines; sources come from the collected list only, and
    only the company's own stocks are tagged."""
    by_id = {c["id"]: c for c in candidates}
    roles = {display_name(i): r for i, r in stocks}
    news: list[dict[str, Any]] = []
    used: set[str] = set()
    for pick in draft.picks:
        ids = [i for i in dict.fromkeys(pick.source_ids) if i in by_id and i not in used][:3]
        if not ids or not pick.title.strip() or not pick.summary.strip():
            continue
        used.update(ids)
        news.append({
            "rank": len(news) + 1,
            "title": _clip(pick.title, 60),
            "summary": _clip(pick.summary, 320),
            "story": _clip(pick.story, 420),
            "why": _clip(pick.why, 260),
            "markets": sorted(set(pick.markets)),
            "sectors": [_clip(s, 24) for s in pick.sectors if s.strip()][:4],
            "direction": pick.direction,
            "our_stocks": [{"name": n, "role": roles[n]}
                           for n in dict.fromkeys(pick.our_stocks) if n in roles],
            "sources": [{"title": by_id[i]["title"], "publisher": by_id[i]["publisher"],
                         "url": by_id[i]["url"], "lang": by_id[i]["lang"],
                         "published": by_id[i]["published"]} for i in ids],
        })
        if len(news) >= MAX_PICKS:
            break
    return _clip(draft.mood, 120), news


# ---------------------------------------------------------------------------------- file

def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def title_for(market: str, day: date) -> str:
    weekday = "월화수목금토일"[day.weekday()]
    return f"[시장 브리핑] {day.month}/{day.day}({weekday}) {SLOT_KO[market]}"


def write(conn: sqlite3.Connection, market: str, day: date, now: datetime,
          naver: NaverNewsProvider | None, writer: Writer | None,
          budget_ok: Callable[[], bool] = lambda: True,
          search: YahooSearch = _yahoo_search, stocks: Sequence[Stock] = (),
          moves: Moves | None = None) -> int | None:
    """Collect, summarise and file this slot's briefing once. Returns the inbox id (None when it
    was already filed). Failures are filed as such, never raised."""
    key = dedupe_key(market, day)
    if conn.execute("SELECT 1 FROM inbox_items WHERE dedupe_key=?", (key,)).fetchone():
        return None
    payload: dict[str, Any] = {"type": "market_briefing", "slot": market,
                               "session": day.isoformat(), "news": [], "briefing_status": "OK"}
    summary = ""
    try:
        candidates = collect(now.astimezone(KST).date().isoformat(), naver, search, stocks,
                             moves)
    except Exception as exc:
        log.exception("market briefing %s: collecting failed", key)
        candidates = []
        payload["error"] = redact_text(type(exc).__name__, limit=100)
    payload["candidates"] = len(candidates)
    payload["stocks"] = [{"name": display_name(i), "role": r} for i, r in stocks]
    if len(candidates) < MIN_CANDIDATES:
        payload["briefing_status"] = "INSUFFICIENT_DATA"
        payload["note"] = f"모은 기사가 {len(candidates)}건뿐이라 이번 브리핑은 쓰지 않았습니다."
    elif writer is None:
        payload["briefing_status"] = "FAILED"
        payload["note"] = "AI 요약을 쓸 수 없는 상태입니다 (엔진 미설정)."
    elif not budget_ok():
        payload["briefing_status"] = "SKIPPED_BUDGET"
        payload["note"] = "이번 달 AI 예산이 부족해 브리핑을 건너뛰었습니다."
    else:
        payload["model"] = writer.model
        try:
            draft, usage = writer(build_prompt(candidates, stocks))
            payload["token_usage"] = usage
            summary, payload["news"] = finalize(draft, candidates, stocks)
            if not payload["news"]:
                payload["briefing_status"] = "FAILED"
                payload["note"] = "AI 요약이 수집한 기사와 맞지 않아 버렸습니다."
        except Exception as exc:
            log.exception("market briefing %s: summary failed", key)
            payload["briefing_status"] = "FAILED"
            payload["error"] = redact_text(type(exc).__name__, limit=100)
            payload["note"] = "AI 요약 중 오류가 나서 이번 브리핑을 쓰지 못했습니다."
    title = title_for(market, day)
    if payload["briefing_status"] != "OK":
        title += " · 작성 못 함"
        summary = str(payload.get("note", ""))
    with transaction(conn):
        cur = conn.execute(
            "INSERT OR IGNORE INTO inbox_items (kind, instrument_id, title, summary, payload, "
            "status, dedupe_key, created_at) VALUES ('daily', NULL, ?, ?, ?, 'INFO', ?, ?)",
            (title, summary, json.dumps(payload, ensure_ascii=False), key, _iso(now)))
    return int(cur.lastrowid or 0) if cur.rowcount else None


def usages_in_month(conn: sqlite3.Connection, month: str) -> list[dict[str, Any]]:
    """Token usage of this month's briefings (Korea time), for the budget."""
    from stock_office.budget import month_key

    out: list[dict[str, Any]] = []
    for row in conn.execute("SELECT payload, created_at FROM inbox_items WHERE dedupe_key LIKE ?",
                            (f"{DEDUPE_PREFIX}%",)):
        if month_key(datetime.fromisoformat(row["created_at"])) != month:
            continue
        usage = json.loads(row["payload"]).get("token_usage")
        if isinstance(usage, dict):
            out.append(usage)
    return out


# ---------------------------------------------------------------------------- live wiring

def tick(service: Any, settings: Any, now: datetime) -> None:
    """Worker: write each market's briefing once in its slot."""
    if service.inbox is None:
        return
    for market in ("KR", "US"):
        day = due(market, now)
        if day is None:
            continue
        if service.inbox.conn.execute("SELECT 1 FROM inbox_items WHERE dedupe_key=?",
                                      (dedupe_key(market, day),)).fetchone():
            continue
        write(service.inbox.conn, market, day, now, naver_from(settings),
              writer_for(service, settings, market, day), lambda: _budget_ok(service),
              moves=yahoo_moves,
              stocks=our_stocks(service.inbox.conn, lambda m: held_by(service.inbox, m)))


def held_by(inbox: Any, market: str) -> list[str]:
    """Held instruments on this market's Kiwoom mock account (none when it cannot be read)."""
    try:
        acc = inbox.accounts(market) if inbox.accounts else None
    except Exception:
        return []
    if not acc or not acc.get("ok"):
        return []
    prefix = "KR:KRX:" if market == "KR" else "US:NASDAQ:"
    return [prefix + str(h["code"]) for h in acc.get("holdings", [])
            if h.get("code") and float(h.get("qty") or 0) > 0]


def _budget_ok(service: Any) -> bool:
    status = service.budget()
    return status is None or status.remaining_usd >= RESERVE_USD


def naver_from(settings: Any) -> NaverNewsProvider:
    return NaverNewsProvider(
        settings.naver_client_id.get_secret_value() if settings.naver_client_id else None,
        settings.naver_client_secret.get_secret_value() if settings.naver_client_secret else None,
    )


def writer_for(service: Any, settings: Any, market: str, day: date) -> Writer | None:
    from stock_office.engine.adapter import EngineNotConfiguredError

    engine = service.engines("tradingagents")
    try:
        engine.check_ready()
    except EngineNotConfiguredError:
        return None
    work = settings.data_dir / "market_briefings" / f"{market}-{day.isoformat()}"
    return QuickModelWriter(engine.build_config(work))


def main(argv: list[str]) -> int:
    from stock_office.config import get_settings
    from stock_office.schedule import first_session_opening_after
    from stock_office.wiring import build_service

    settings = get_settings()
    service = build_service(settings)
    now = datetime.now(UTC)
    for market in argv or ["NOW"]:
        # NOW: an extra briefing today, filed beside (not instead of) the scheduled slots.
        day = (now.astimezone(KST).date() if market == "NOW"
               else first_session_opening_after(Market(market), now).day)
        item = write(service.inbox.conn, market, day, now, naver_from(settings),
                     writer_for(service, settings, market, day), lambda: _budget_ok(service),
              moves=yahoo_moves,
                     stocks=our_stocks(service.inbox.conn, lambda m: held_by(service.inbox, m)))
        print(f"{market} {day}: {'filed #' + str(item) if item else 'already filed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
