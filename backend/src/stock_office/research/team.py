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
from stock_office.schedule import closed_sessions, first_session_opening_after

log = logging.getLogger("stock_office.research")
INDEX = {"KR": "KOSPI200", "US": "NASDAQ100"}
MARKET_KO = {"KR": "국장", "US": "미장"}
KR_LEAD = timedelta(hours=2)          # research 2 h before the KRX open
US_AFTER = timedelta(minutes=90)      # research 90 min after the NYSE close

BarSource = Callable[[list[str], date], dict[str, Bars]]


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def window(market: str, now: datetime) -> tuple[date, datetime, datetime] | None:
    """(target session day, research may start, must finish by) if `now` is in the window."""
    nxt = first_session_opening_after(Market(market), now)
    if market == "KR":
        start = nxt.open - KR_LEAD
    else:
        last = closed_sessions(Market.US, now, limit=1)
        if not last:
            return None
        start = last[-1].close + US_AFTER
    return (nxt.day, start, nxt.open) if start <= now < nxt.open else None


def next_research(market: str, now: datetime) -> datetime:
    """When the next research run for this market will start (office schedule)."""
    for probe in (now, now + timedelta(hours=12), now + timedelta(days=1), now + timedelta(days=3)):
        nxt = first_session_opening_after(Market(market), probe)
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

    def research(self, market: str, day: date, now: datetime) -> list[str]:
        """Screen, store, report. Returns the focus instruments for the committee (in order)."""
        ids = UNIVERSE[INDEX[market]]
        bars = self.bars(ids, now.date())
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
            lines = [f"{display_name(i)} — {w}" for i, w in focus]
            top = ", ".join(f"{display_name(c.instrument_id)}({c.score})" for c in candidates[:5])
            summary = (f"오늘 위원회: {names}. " + " / ".join(lines)
                       + f" · 점수 상위: {top} · 관찰 {len(watch)}종목 · 유동성 통과 "
                       f"{len(candidates)}/{len(ids)}")
            self.conn.execute(
                "INSERT OR IGNORE INTO inbox_items (kind, instrument_id, title, summary, payload, "
                "status, dedupe_key, created_at) VALUES ('research', NULL, ?, ?, ?, 'INFO', ?, ?)",
                (f"[리서치] {MARKET_KO[market]} {day.isoformat()} · "
                 f"오늘 회의 {len(focus)}건: {names}",
                 summary[:1500], json.dumps({"market": market, "session": day.isoformat(),
                                            "focus": [i for i, _ in focus],
                                            "watchlist": watch, "rules": RULES_VERSION},
                                           ensure_ascii=False),
                 f"research:{market}:{day.isoformat()}", iso(now)))
        log.info("research %s %s: %d screened, %d liquid, focus %s", market, day, len(bars),
                 len(by_id), [i for i, _ in focus])
        return [i for i, _ in focus]


# ---------------------------------------------------------------- live wiring
def yahoo_bars(instrument_ids: list[str], until: date) -> dict[str, Bars]:
    """One year of daily bars per instrument from Yahoo, completed sessions before `until`."""
    import yfinance as yf

    symbols = {get_instrument(i).provider_symbols["yahoo"]: i for i in instrument_ids}
    frame = yf.download(list(symbols), period="14mo", interval="1d", group_by="ticker",
                        auto_adjust=False, threads=True, progress=False)
    out: dict[str, Bars] = {}
    for sym, iid in symbols.items():
        try:
            f = frame[sym].dropna(subset=["Close"])
        except KeyError:
            continue
        f = f[[d.date() < until for d in f.index]]
        if len(f) < 200:
            continue
        out[iid] = Bars([float(x) for x in f["Close"]], [float(x) for x in f["High"]],
                        [float(x) for x in f["Low"]], [float(x) for x in f["Volume"]])
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
    if len(args) != 2 or args[0] not in ("run", "dry") or args[1] not in ("KR", "US"):
        print("usage: python -m stock_office.research.team run|dry KR|US")
        return 2
    market = args[1]
    if args[0] == "dry":   # preview only: nothing stored, no meetings
        bars = yahoo_bars(UNIVERSE[INDEX[market]], datetime.now(UTC).date())
        cands = screen(market, bars)
        print(f"bars {len(bars)} / liquid {len(cands)}")
        for c in cands[:10]:
            print(c.score, display_name(c.instrument_id), "; ".join(c.reasons))
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
