"""The closing report (마감 보고): one inbox document per desk and session, after the close.

Owner's decisions (2026-10-21): inbox only (no phone notification), and it includes feedback on
the day's meetings — what each conclusion looked like by the close. Built from stored numbers and
the closing quotes only (no new AI; the "오늘 한눈에" mood line quotes the day's market briefing or
breaking news, which were already written). The feedback is a record for the CEO and the month-end
evaluation; nothing here changes how the company decides (learning is off during the evaluation).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

MARKET_KO = {"KR": "국내장", "US": "해외장"}
ACTION_KO = {"BUY": "매수", "SELL": "매도", "HOLD": "유지", "REVIEW": "판단 보류"}
BIG_MOVE = Decimal(3)   # % day move that makes a "유지" conclusion worth a remark
NOTE = ("회의 피드백은 하루 결과라 운의 영향이 큽니다. 기록용이며 판단 규칙에는 반영하지 않습니다 "
        "(평가 기간 학습 끔).")


@dataclass
class Meeting:
    name: str
    action: str                     # BUY | SELL | HOLD | REVIEW
    held: bool                      # held when the meeting ended
    move: Decimal | None            # today's % change at the close
    close: str | None               # closing price, formatted
    order: str | None = None        # what the desk did with its plan, if anything


def pct(x: Decimal | None) -> str:
    return "—" if x is None else f"{x:+.2f}%"


def feedback(m: Meeting) -> str:
    head = f"{m.name} · {ACTION_KO.get(m.action, m.action)}"
    day = f"오늘 {pct(m.move)}" + (f" (종가 {m.close})" if m.close else "")
    if m.order:
        return f"{head} → {m.order} · {day}"
    if m.action == "HOLD" and not m.held and m.move is not None and abs(m.move) >= BIG_MOVE:
        remark = "사지 않은 사이 크게 오름" if m.move > 0 else "사지 않아 하락 피함"
        return f"{head} → {day} · {remark}"
    if m.action == "HOLD" and m.held and m.move is not None and m.move <= -BIG_MOVE:
        return f"{head} → {day} · 들고 있는 동안 크게 내림"
    if m.action == "BUY":
        return f"{head} → 주문 없음 · {day}"
    return f"{head} → {day}"


def _is(word: str) -> str:
    """'…예요' after a vowel, '…이에요' after a final consonant (or a non-Hangul end)."""
    last = word[-1:] if word else ""
    vowel = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 == 0
    return f"{word}예요" if vowel else f"{word}이에요"


def glance(today: Decimal | None, bench_move: Decimal | None, meetings: list[Meeting],
           mood: str | None) -> list[str]:
    """The day in two or three plain lines (owner, 2026-11-06): the account against the market,
    the market's mood (the day's market briefing / breaking news, already written), the meetings."""
    lines: list[str] = []
    if today is not None and bench_move is not None:
        diff = today - bench_move
        verdict = ("시장보다 잘 버텼어요" if diff >= Decimal("0.1") else
                   "시장보다 부진했어요" if diff <= Decimal("-0.1") else "시장과 비슷했어요")
        lines.append(f"오늘 계좌는 {pct(today)}, 시장(지수)은 {pct(bench_move)}로 {verdict}.")
    elif today is not None:
        lines.append(f"오늘 계좌는 {pct(today)}였어요.")
    if mood:
        lines.append(f"오늘 시장 분위기: {mood}")
    if meetings:
        counts: dict[str, int] = {}
        for m in meetings:
            word = ACTION_KO.get(m.action, m.action)
            counts[word] = counts.get(word, 0) + 1
        what = " · ".join(f"{k} {v}" for k, v in counts.items())
        ordered = [m.name for m in meetings if m.order]
        missed = [m for m in meetings if m.action == "HOLD" and not m.held
                  and m.move is not None and m.move >= BIG_MOVE]
        tail = (f" 주문으로 이어진 건 {_is(', '.join(ordered))}." if ordered else
                " 주문으로 이어진 건 없어요.")
        if missed:
            tail += f" 사지 않은 {missed[0].name}은(는) 오늘 {pct(missed[0].move)} 올랐어요."
        lines.append(f"오늘 회의 {len(meetings)}건({what}).{tail}")
    return lines


def compose(market: str, day: str, money: str, nav: Decimal,
            prev_nav: Decimal | None, start: Decimal | None, bench_move: Decimal | None,
            trades: list[str], holdings: list[str], meetings: list[Meeting], waiting: list[str],
            mood: str | None = None) -> tuple[str, str, list[dict[str, object]]]:
    """(title, summary, sections) of the closing report."""
    today = (nav / prev_nav - 1) * 100 if prev_nav else None
    total = (nav / start - 1) * 100 if start else None
    title = (f"[마감] {MARKET_KO[market]} {day} · 평가액 {money} ({pct(today)}) · "
             f"지수 {pct(bench_move)}")
    summary = (f"시작 대비 {pct(total)} · 체결 {sum('체결' in t for t in trades)}건 · "
               f"보유 {len(holdings)}종목 · 오늘 회의 {len(meetings)}건")
    account = [f"평가액 {money} · 오늘 {pct(today)} · 시작 대비 {pct(total)}",
               f"비교 지수 오늘 {pct(bench_move)}"
               + (f" · 지수 대비 {pct(today - bench_move)}"
                  if today is not None and bench_move is not None else "")]
    sections: list[dict[str, object]] = []
    first = glance(today, bench_move, meetings, mood)
    if first:
        sections.append({"title": "오늘 한눈에", "lines": first})
    sections.append({"title": "계좌", "lines": account})
    sections.append({"title": "오늘 주문", "lines": trades or ["없음"]})
    sections.append({"title": "보유 종목", "lines": holdings or ["없음"]})
    sections.append({"title": "오늘 회의 피드백",
                     "lines": [feedback(m) for m in meetings] or ["오늘 회의 없음"]})
    if waiting:
        sections.append({"title": "다음 장 대기", "lines": waiting})
    return title, summary, sections
