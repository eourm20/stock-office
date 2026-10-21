"""Research team: deterministic screener scores, focus picking, research windows, one run a day."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from stock_office.db import connect
from stock_office.research.screener import Bars, pick, screen
from stock_office.research.team import ResearchTeam, next_research, window


def trend(n: int = 260, start: float = 100, step: float = 0.5, last_volume: float = 1e6,
          value: float = 1e6) -> Bars:
    close = [start + step * i for i in range(n)]
    return Bars(close, [c * 1.01 for c in close], [c * 0.99 for c in close],
                [value] * (n - 1) + [last_volume])


def pullback(n: int = 260, pairs: int = 6, down: float = 0.025, up: float = 0.012) -> Bars:
    """An uptrend, then a choppy pullback on lighter volume, and a first up day."""
    close = [100 + 0.5 * i for i in range(n - 2 * pairs - 1)]
    for _ in range(pairs):
        close.append(close[-1] * (1 - down))
        close.append(close[-1] * (1 + up))
    close.append(close[-1] * 1.005)
    volume = [1e6] * (len(close) - 5) + [6e5] * 5
    return Bars(close, [c * 1.01 for c in close], [c * 0.99 for c in close], volume)


def test_v2_prefers_a_pullback_in_an_uptrend_over_a_stock_at_its_high() -> None:
    bars = {
        "US:NASDAQ:PULL": pullback(),
        "US:NASDAQ:TOP": trend(last_volume=3e6),            # straight up, at its high
        "US:NASDAQ:DOWN": trend(start=300, step=-0.5),      # no uptrend: gate
        "US:NASDAQ:THIN": trend(value=10),                  # traded value far too low
        "US:NASDAQ:NEW": trend(n=150),                      # too little history
    }
    out = screen("US", bars)
    assert [(c.instrument_id, c.score) for c in out] == [
        ("US:NASDAQ:PULL", 5), ("US:NASDAQ:TOP", 3), ("US:NASDAQ:DOWN", 0)]
    pull, top, down = out
    assert pull.reasons == ["장기 상승 추세 (종가·50일선 > 200일선)", "눌림 7.3% (20일 고점 대비)",
                            "RSI 34", "조정 중 거래량 감소 (5일 평균이 20일의 0.7배)",
                            "반등 시작 (전일 대비 상승)"]
    assert "고점 근처 (20일 고점 대비 0.0%)" in top.reasons
    assert down.reasons == ["장기 상승 추세 아님 (200일선 아래 또는 50일선 < 200일선)"]


def test_focus_puts_held_first_skips_recent_and_unattractive() -> None:
    cands = screen("US", {"US:NASDAQ:A": trend(last_volume=3e6), "US:NASDAQ:B": trend(step=0.4),
                          "US:NASDAQ:C": trend(step=0.3),
                          "US:NASDAQ:D": trend(start=300, step=-0.5)})
    watch, focus = pick(cands, held=["US:NASDAQ:H"], recent={"US:NASDAQ:A"}, focus_size=3)
    assert [i for i, _ in focus] == ["US:NASDAQ:H", "US:NASDAQ:B", "US:NASDAQ:C"]
    assert focus[0][1] == "보유 종목 재점검" and focus[1][1].startswith("점수 ")
    assert "장기 상승 추세" not in focus[1][1]          # the gate is not news: reasons after it
    assert "US:NASDAQ:H" in watch and "US:NASDAQ:D" not in [i for i, _ in focus]


def test_research_windows_follow_each_exchange() -> None:
    kst = lambda s: datetime.fromisoformat(s + "+09:00")  # noqa: E731
    assert window("KR", kst("2026-10-21T06:59")) is None
    day, start, until = window("KR", kst("2026-10-21T07:00"))  # type: ignore[misc]
    assert day == date(2026, 10, 21) and until == kst("2026-10-21T09:00")
    assert window("US", kst("2026-10-21T06:00")) is None          # 05:00 close + 90 min
    day, start, _ = window("US", kst("2026-10-21T06:30"))  # type: ignore[misc]
    assert day == date(2026, 10, 21) and start == kst("2026-10-21T06:30")
    assert window("US", kst("2026-10-20T17:00")) is not None      # evening before the US open
    assert window("US", kst("2026-10-20T22:31")) is None          # US session trading: stale bars
    assert window("US", kst("2026-10-21T04:59")) is None
    assert next_research("KR", kst("2026-10-20T17:00")) == kst("2026-10-21T07:00")


def test_one_research_per_market_and_session_with_an_inbox_report(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    bars = {"US:NASDAQ:NVDA": trend(last_volume=3e6), "US:NASDAQ:AAPL": trend(step=0.4)}
    team = ResearchTeam(conn, lambda ids, until: bars, lambda m: [], lambda m, now: set())
    now = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    focus = team.research("US", date(2026, 10, 20), now)
    assert focus == ["US:NASDAQ:NVDA", "US:NASDAQ:AAPL"]
    assert team.research("US", date(2026, 10, 20), now) == []      # same session: never twice
    assert team.done("US", date(2026, 10, 20))
    latest = team.latest("US")
    assert latest is not None and latest["watchlist"] == ["US:NASDAQ:NVDA", "US:NASDAQ:AAPL"]
    title, payload = conn.execute(
        "SELECT title, payload FROM inbox_items WHERE kind='research'").fetchone()
    assert title == "[리서치] 해외장 2026-10-20 · 오늘 회의 2건: 엔비디아, 애플"
    assert json.loads(payload)["rules"] == "SCREEN_V2"
    events = [(r[0], r[1]) for r in conn.execute(
        "SELECT kind, title FROM office_events WHERE desk='research' ORDER BY id")]
    assert events == [("started", "해외장 리서치 시작"),
                      ("completed", "해외장 리서치 완료 · 오늘 회의 2건")]   # once


def test_research_uses_the_close_just_before_the_target_session(tmp_path: Path) -> None:
    from stock_office.research.team import last_close_day

    asked: list[date] = []

    def bars(ids: list[str], until: date) -> dict[str, Bars]:
        asked.append(until)
        return {}

    team = ResearchTeam(connect(tmp_path), bars, lambda m: [], lambda m, now: set())
    # 06:30 KST 10/21 is still 10/20 in UTC: the bars must run to the 10/20 US close anyway.
    team.research("US", date(2026, 10, 21), datetime(2026, 10, 20, 21, 30, tzinfo=UTC))
    assert asked == [date(2026, 10, 21)]                       # sessions before 10/21
    assert last_close_day("US", date(2026, 10, 21)) == date(2026, 10, 20)
    assert last_close_day("KR", date(2026, 10, 21)) == date(2026, 10, 20)
    assert last_close_day("US", date(2026, 10, 26)) == date(2026, 10, 23)   # Monday: Friday


def test_an_empty_newest_close_is_filled_from_the_quote_inside_the_day_range() -> None:
    import pandas as pd

    from stock_office.research.team import _fill_last_close

    class Quote:
        def __init__(self, price: float) -> None:
            self.fast_info = type("F", (), {"last_price": price})()

    def frame() -> pd.DataFrame:
        return pd.DataFrame({"Close": [171.06, float("nan")], "High": [174.36, 176.26],
                             "Low": [169.53, 170.36]},
                            index=pd.to_datetime(["2026-10-19", "2026-10-20"]))

    def yf(price: float) -> object:
        return type("YF", (), {"Ticker": staticmethod(lambda sym: Quote(price))})()

    day = date(2026, 10, 20)
    assert _fill_last_close(frame(), "SHOP", day, yf(173.48))["Close"].iloc[-1] == 173.48
    assert pd.isna(_fill_last_close(frame(), "SHOP", day, yf(190.0))["Close"].iloc[-1])
    assert pd.isna(_fill_last_close(frame(), "SHOP", date(2026, 10, 21), yf(173.48))["Close"]
                   .iloc[-1])                                    # not the session we need
