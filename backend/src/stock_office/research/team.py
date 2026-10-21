"""The research team: before each market's next session, screen its universe, keep a watchlist and
send today's focus stocks to the committee.

When (per market, exchange calendars):
- 국장: from 2 h before the KRX open (07:00 KST) until the open, on the previous close.
- 미장: from 90 min after the NYSE close (≈ 06:30 KST) until the next open, on that close.
One research run per market and target session (`research_runs`, idempotent). Its report goes to
the inbox; the focus stocks become committee meetings (trigger "schedule"), which the worker runs
in order. Held stocks come first, then the best-scored stocks not met about recently.

    .venv/bin/python -m stock_office.research.team run US     # run now (e.g. the first evening)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from stock_office.db import transaction
from stock_office.domain.instruments import UNIVERSE, display_name, get_instrument
from stock_office.domain.models import Market
from stock_office.research.screener import (
    RECENT_DAYS,
    RULES_VERSION,
    Bars,
    Candidate,
    pick,
    screen,
    to_json,
)
from stock_office.schedule import (
    closed_sessions,
    first_session_opening_after,
    open_session,
    session_of,
)

log = logging.getLogger("stock_office.research")
INDEX = {"KR": "KOSPI200", "US": "NASDAQ100"}
MARKET_KO = {"KR": "국내장", "US": "해외장"}
KR_LEAD = timedelta(hours=2)          # research 2 h before the KRX open
US_AFTER = timedelta(minutes=90)      # research 90 min after the NYSE close

BarSource = Callable[[list[str], date], dict[str, Bars]]


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def window(market: str, now: datetime) -> tuple[date, datetime, datetime] | None:
    """(target session day, research may start, must finish by) if `now` is in the window.
    Never while a session is trading: its close is not in yet, so the bars would be stale."""
    if open_session(Market(market), now) is not None:
        return None
    nxt = first_session_opening_after(Market(market), now)
    if market == "KR":
        start = nxt.open - KR_LEAD
    else:
        last = closed_sessions(Market.US, now, limit=1)
        if not last:
            return None
        start = last[-1].close + US_AFTER
    return (nxt.day, start, nxt.open) if start <= now < nxt.open else None


def next_research(market: str, now: datetime,
                  done: Callable[[date], bool] = lambda day: False) -> datetime:
    """When the next research run for this market will start (office schedule). A session whose
    research is `done` is skipped, so a finished morning's research is not shown as "now"."""
    for probe in (now, now + timedelta(hours=12), now + timedelta(days=1), now + timedelta(days=3)):
        nxt = first_session_opening_after(Market(market), probe)
        if done(nxt.day):
            continue
        if market == "KR":
            start = nxt.open - KR_LEAD
        else:
            last = closed_sessions(Market.US, nxt.open - timedelta(minutes=1), limit=1)
            start = last[-1].close + US_AFTER
        if start >= now or (start <= now < nxt.open):
            return max(start, now)
    return now


class ResearchTeam:
    def __init__(self, conn: sqlite3.Connection, bars: BarSource,
                 held: Callable[[str], list[str]], recent: Callable[[str, datetime], set[str]]
                 ) -> None:
        self.conn, self.bars, self.held, self.recent = conn, bars, held, recent

    def done(self, market: str, day: date) -> bool:
        return self.conn.execute("SELECT 1 FROM research_runs WHERE market=? AND session=?",
                                 (market, day.isoformat())).fetchone() is not None

    def latest(self, market: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM research_runs WHERE market=? ORDER BY id DESC "
                                "LIMIT 1", (market,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        for k in ("candidates", "watchlist", "focus"):
            out[k] = json.loads(out[k])
        return out

    def _event(self, market: str, kind: str, title: str, detail: str, now: datetime) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO office_events (market, desk, kind, title, detail, created_at) "
                "VALUES (?, 'research', ?, ?, ?, ?)", (market, kind, title, detail[:300], iso(now)))

    def research(self, market: str, day: date, now: datetime) -> list[str]:
        """Screen, store, report. Returns the focus instruments for the committee (in order)."""
        if self.done(market, day):
            return []
        ids = UNIVERSE[INDEX[market]]
        # Bars of the sessions before the target session (exchange-local dates), so the last bar
        # is the close that just happened. Raises when the data is not in yet (retried next tick).
        bars = self.bars(ids, day)
        self._event(market, "started", f"{MARKET_KO[market]} 리서치 시작",
                    f"{INDEX[market]} {len(ids)}종목 점수 계산", now)
        candidates: list[Candidate] = screen(market, bars)
        known = set(ids) | {"KR:KRX:005930", "US:NASDAQ:NVDA"}
        held = [h for h in self.held(market) if h in known]
        watch, focus = pick(candidates, held, self.recent(market, now))
        by_id = {c.instrument_id: c for c in candidates}
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO research_runs (market, session, rules_version, universe, "
                "screened, liquid, candidates, watchlist, focus, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (market, day.isoformat(), RULES_VERSION, INDEX[market], len(bars), len(candidates),
                 json.dumps([to_json(c) for c in candidates[:40]], ensure_ascii=False),
                 json.dumps(watch), json.dumps([{"instrument_id": i, "why": w} for i, w in focus],
                                               ensure_ascii=False), iso(now)))
            if not cur.rowcount:
                return []
            names = ", ".join(display_name(i) for i, _ in focus) or "없음"
            title, summary, payload = report(
                market, day.isoformat(), RULES_VERSION, [to_json(c) for c in candidates],
                watch, [{"instrument_id": i, "why": w} for i, w in focus], len(candidates),
                len(ids))
            self.conn.execute(
                "INSERT OR IGNORE INTO inbox_items (kind, instrument_id, title, summary, payload, "
                "status, dedupe_key, created_at) VALUES ('research', NULL, ?, ?, ?, 'INFO', ?, ?)",
                (title, summary, json.dumps(payload, ensure_ascii=False),
                 f"research:{market}:{day.isoformat()}", iso(now)))
        self._event(market, "completed",
                    f"{MARKET_KO[market]} 리서치 완료 · 오늘 회의 {len(focus)}건", names, now)
        log.info("research %s %s: %d screened, %d liquid, focus %s", market, day, len(bars),
                 len(by_id), [i for i, _ in focus])
        return [i for i, _ in focus]


# ---------------------------------------------------------------- live wiring
class StaleBarsError(RuntimeError):
    """The close the research needs is not in the data yet."""


RULES_KO = {"SCREEN_V1": "SCREEN_V1 · 추세·모멘텀·52주 고점 근처",
            "SCREEN_V2": "SCREEN_V2 · 상승 추세 속 눌림목"}


def report(market: str, session: str, rules: str, candidates: list[dict[str, Any]],
           watch: list[str], focus: list[dict[str, str]], liquid: int, universe: int
           ) -> tuple[str, str, dict[str, Any]]:
    """The research report as (title, short summary, payload with titled sections), so the
    inbox shows lists instead of a paragraph."""
    by_id = {c["instrument_id"]: c for c in candidates}

    def why(c: dict[str, Any]) -> str:
        reasons = c["reasons"][1:] if rules == "SCREEN_V2" else c["reasons"]   # V2: skip the gate
        return " · ".join(reasons[:4])

    meetings = []
    for f in focus:
        c = by_id.get(f["instrument_id"])
        name = display_name(f["instrument_id"])
        meetings.append(f"{name} — {f['why']}" if c is None or f["why"] == "보유 종목 재점검"
                        else f"{name} ({c['score']}점) — {why(c)}")
    top = [f"{display_name(c['instrument_id'])} {c['score']}점" for c in candidates[:10]]
    names = ", ".join(display_name(f["instrument_id"]) for f in focus) or "없음"
    title = f"[리서치] {MARKET_KO[market]} {session} · 오늘 회의 {len(focus)}건: {names}"
    summary = (f"{INDEX[market]} {universe}종목 중 거래대금 통과 {liquid} · "
               f"관찰 {len(watch)}종목 · 규칙 {RULES_KO.get(rules, rules)}")
    sections = [
        {"title": "오늘 위원회 회의", "lines": meetings or ["없음"]},
        {"title": "점수 상위 10", "lines": [" · ".join(top[:5]), " · ".join(top[5:])]
         if len(top) > 5 else [" · ".join(top)] if top else ["없음"]},
        {"title": f"관찰 종목 {len(watch)}",
         "lines": [", ".join(display_name(i) for i in watch)] if watch else ["없음"]},
    ]
    payload = {"market": market, "session": session, "focus": [f["instrument_id"] for f in focus],
               "watchlist": watch, "rules": rules, "sections": sections,
               "note": "보유 종목은 점수와 관계없이 먼저 재점검합니다. 최근 5거래일 안에 회의한 "
                       "종목(보유 제외)은 빼고 고릅니다."}
    return title, summary, payload


def reformat_reports(conn: sqlite3.Connection) -> int:
    """Rewrite stored research reports in the sectioned form (same facts, from research_runs)."""
    n = 0
    with transaction(conn):
        for r in list(conn.execute("SELECT * FROM research_runs")):
            title, summary, payload = report(
                r["market"], r["session"], r["rules_version"], json.loads(r["candidates"]),
                json.loads(r["watchlist"]), json.loads(r["focus"]), r["liquid"],
                len(UNIVERSE[INDEX[r["market"]]]))
            n += conn.execute(
                "UPDATE inbox_items SET title=?, summary=?, payload=? WHERE dedupe_key=?",
                (title, summary, json.dumps(payload, ensure_ascii=False),
                 f"research:{r['market']}:{r['session']}")).rowcount
    return n


def last_close_day(market: str, until: date) -> date:
    """The session just before the target session `until` (exchange-local)."""
    target = session_of(Market(market), until)
    before = target.open if target else datetime.combine(until, datetime.min.time(), UTC)
    return closed_sessions(Market(market), before, limit=1)[-1].day


def _fill_last_close(f: Any, sym: str, need: date, yf: Any) -> Any:
    """Yahoo's daily download sometimes leaves the newest session's close empty (high, low and
    volume are there) for hours after the close. Fill it from the quote's last price, which is the
    close once the market has closed, only when it lies inside that day's range."""
    if not len(f) or f.index[-1].date() != need or f["Close"].iloc[-1] == f["Close"].iloc[-1]:
        return f
    try:
        price = float(yf.Ticker(sym).fast_info.last_price)
    except Exception:
        return f
    low, high = float(f["Low"].iloc[-1]), float(f["High"].iloc[-1])
    if low <= price <= high:
        f.loc[f.index[-1], "Close"] = price
    return f


def yahoo_bars(instrument_ids: list[str], until: date) -> dict[str, Bars]:
    """One year of daily bars per instrument from Yahoo: sessions before the target session
    `until`, each ending with the session just before it (stale instruments are left out; if
    none is fresh the data is not in yet and StaleBarsError is raised)."""
    import yfinance as yf

    symbols = {get_instrument(i).provider_symbols["yahoo"]: i for i in instrument_ids}
    frame = yf.download(list(symbols), period="14mo", interval="1d", group_by="ticker",
                        auto_adjust=False, threads=True, progress=False)
    out: dict[str, Bars] = {}
    need = last_close_day(get_instrument(instrument_ids[0]).market.value, until)
    stale = 0
    for sym, iid in symbols.items():
        try:
            f = _fill_last_close(frame[sym].copy(), sym, need, yf)
        except KeyError:
            continue
        f = f.dropna(subset=["Close"])
        f = f[[d.date() < until for d in f.index]]
        if len(f) and f.index[-1].date() < need:
            stale += 1
            continue
        if len(f) < 200:
            continue
        out[iid] = Bars([float(x) for x in f["Close"]], [float(x) for x in f["High"]],
                        [float(x) for x in f["Low"]], [float(x) for x in f["Volume"]])
    if not out and stale:
        raise StaleBarsError(f"{need} close not in Yahoo data yet ({stale} stale)")
    if stale:
        log.warning("research bars: %d instruments without the %s close", stale, need)
    return out


def build_team(settings: Any, conn: sqlite3.Connection, repo: Any) -> ResearchTeam:
    from stock_office.kiwoom_mock.link import build_link

    link = build_link(settings)

    def held(market: str) -> list[str]:
        acc = link.status()["accounts"].get(market) or {}
        prefix = "KR:KRX:" if market == "KR" else "US:NASDAQ:"
        return [prefix + str(h["code"]) for h in acc.get("holdings", [])
                if h.get("code") and float(h.get("qty") or 0) > 0]

    def recent(market: str, now: datetime) -> set[str]:
        since = now - timedelta(days=RECENT_DAYS + 2)
        return {r.instrument_id for r in repo.list_runs()
                if not r.demo and r.requested_at >= since and r.instrument_id.startswith(market)}

    return ResearchTeam(conn, yahoo_bars, held, recent)


def main(argv: Sequence[str] | None = None) -> int:
    """`run`: one market's research now, meetings queued for the worker. `dry`: preview only."""
    from stock_office.config import get_settings
    from stock_office.db import connect
    from stock_office.domain.models import CreateRunRequest
    from stock_office.wiring import build_service

    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["reformat"]:   # stored research reports → sectioned form
        settings = get_settings()
        print(f"reformatted {reformat_reports(connect(settings.data_dir))} reports")
        return 0
    if len(args) != 2 or args[0] not in ("run", "dry") or args[1] not in ("KR", "US"):
        print("usage: python -m stock_office.research.team run|dry KR|US | reformat")
        return 2
    market = args[1]
    if args[0] == "dry":   # preview only: nothing stored, no meetings
        last = closed_sessions(Market(market), datetime.now(UTC), limit=1)[-1].day
        bars = yahoo_bars(UNIVERSE[INDEX[market]], last + timedelta(days=1))
        cands = screen(market, bars)
        print(f"bars {len(bars)} / liquid {len(cands)}")
        for c in cands[:10]:
            print(c.score, display_name(c.instrument_id), "; ".join(c.reasons))
        print("focus (nothing held, nothing recent):",
              [display_name(i) for i, _ in pick(cands, [], set())[1]])
        return 0
    settings = get_settings()
    service = build_service(settings)
    team = build_team(settings, connect(settings.data_dir), service.repo)
    now = datetime.now(UTC)
    day = first_session_opening_after(Market(market), now).day
    focus = team.research(market, day, now)
    for iid in focus:
        run = service.create_run(CreateRunRequest(instrument_id=iid, engine="tradingagents"),
                                 trigger="schedule", schedule_slot=f"research:{iid}@{day}")
        print(f"queued {run.id} {display_name(iid)}")
    print(f"research {market} {day}: focus {len(focus)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
