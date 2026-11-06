"""The research team's screener: deterministic scores on daily bars, no model involved.

SCREEN_V2 (owner's decision, 2026-10-21; from the 10/22 research): **a pullback in an uptrend**.
Look for strong stocks that have cooled off, not for stocks at their highs (V1 picked those, and
the committee then set entries below the price that were never reached). On bars up to the last
completed session only:
- liquidity filter: 20-day average traded value ≥ 10억 KRW (국내장) / $50M (해외장); ≥ 200 bars
- gate: long-term uptrend (close > 200-day MA and 50-day MA > 200-day MA); otherwise score 0
- +2 pullback of 5–15% from the 20-day closing high (+1 for 3–5% or 15–20%; none when still at
  the top or more than 20% down, where the trend may be breaking)
- +2 RSI(14) cooled to 35–55 (+1 for 30–35 or 55–60)
- +1 holding the 50-day MA (close ≥ 97% of it), −1 when well below it (< 92%)
- +1 strong over three months (top third of the market by 63-day return)
- +1 volume drying up in the pullback (5-day average < 80% of the 20-day average)
- +1 turning up (last close above the previous close)
- −1 too volatile (14-day ATR above 6% of the price)
Every point is written out as a reason, so the CEO can read why a stock was picked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

RULES_VERSION = "SCREEN_V2"
MIN_VALUE = {"KR": 1e9, "US": 50e6}   # 10억 KRW / $50M a day
WATCH_SIZE = 25
FOCUS_SIZE = 3
RECENT_DAYS = 5   # do not re-meet a non-held stock within this many sessions


@dataclass
class Bars:
    """Daily bars, oldest first (last element = last completed session)."""
    close: list[float]
    high: list[float]
    low: list[float]
    volume: list[float]


@dataclass
class Candidate:
    instrument_id: str
    score: int
    reasons: list[str]
    metrics: dict[str, float] = field(default_factory=dict)


def _sma(xs: list[float], n: int) -> float:
    return sum(xs[-n:]) / n


def _rsi(close: list[float], n: int = 14) -> float:
    gains = losses = 0.0
    for a, b in zip(close[-n - 1:-1], close[-n:], strict=True):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    return 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)


def _atr_pct(b: Bars, n: int = 14) -> float:
    trs = [max(h - lo, abs(h - pc), abs(lo - pc))
           for h, lo, pc in zip(b.high[-n:], b.low[-n:], b.close[-n - 1:-1], strict=True)]
    return sum(trs) / n / b.close[-1] * 100


def metrics(b: Bars) -> dict[str, float] | None:
    if len(b.close) < 200 or b.close[-1] <= 0:
        return None
    value20 = sum(c * v for c, v in zip(b.close[-20:], b.volume[-20:], strict=True)) / 20
    return {
        "close": b.close[-1], "prev_close": b.close[-2], "sma50": _sma(b.close, 50),
        "sma200": _sma(b.close, 200), "mom63": (b.close[-1] / b.close[-64] - 1) * 100,
        "value20": value20, "high20": max(b.close[-20:]),
        "pullback": (1 - b.close[-1] / max(b.close[-20:])) * 100,
        "vol5_ratio": _sma(b.volume, 5) / (_sma(b.volume, 20) or 1),
        "high52": max(b.close[-252:]), "rsi14": _rsi(b.close), "atr_pct": _atr_pct(b),
    }


def screen(market: str, bars: dict[str, Bars]) -> list[Candidate]:
    """Score every liquid instrument; best first (ties: stronger momentum first)."""
    ms = {iid: m for iid, b in bars.items() if (m := metrics(b)) is not None
          and m["value20"] >= MIN_VALUE[market]}
    ranked = sorted(ms, key=lambda i: ms[i]["mom63"])
    strong = set(ranked[int(len(ranked) * 2 / 3):])
    out = []
    for iid in ranked:
        m = ms[iid]
        score, why = _score(m, iid in strong)
        out.append(Candidate(iid, score, why, {k: round(v, 4) for k, v in m.items()}))
    return sorted(out, key=lambda c: (c.score, c.metrics["mom63"]), reverse=True)


def _score(m: dict[str, float], strong: bool) -> tuple[int, list[str]]:
    if not (m["close"] > m["sma200"] and m["sma50"] > m["sma200"]):
        return 0, ["장기 상승 추세 아님 (200일선 아래 또는 50일선 < 200일선)"]
    score, why = 0, ["장기 상승 추세 (종가·50일선 > 200일선)"]
    pb = m["pullback"]
    if 5 <= pb <= 15:
        score += 2
        why.append(f"눌림 {pb:.1f}% (20일 고점 대비)")
    elif 3 <= pb < 5 or 15 < pb <= 20:
        score += 1
        why.append(f"눌림 {pb:.1f}% (20일 고점 대비)")
    elif pb < 3:
        why.append(f"고점 근처 (20일 고점 대비 {pb:.1f}%)")
    else:
        why.append(f"하락 깊음 (20일 고점 대비 {pb:.1f}%)")
    rsi = m["rsi14"]
    if 35 <= rsi <= 55:
        score += 2
        why.append(f"과열 해소 (RSI {rsi:.0f})")
    elif 30 <= rsi < 35 or 55 < rsi <= 60:
        score += 1
        why.append(f"RSI {rsi:.0f}")
    if m["close"] >= 0.97 * m["sma50"]:
        score += 1
        why.append("50일선 지지")
    elif m["close"] < 0.92 * m["sma50"]:
        score -= 1
        why.append("50일선 크게 이탈")
    if strong:
        score += 1
        why.append(f"3개월 수익률 상위 1/3 ({m['mom63']:+.1f}%)")
    if m["vol5_ratio"] < 0.8:
        score += 1
        why.append(f"조정 중 거래량 감소 (5일 평균이 20일의 {m['vol5_ratio']:.1f}배)")
    if m["close"] > m["prev_close"]:
        score += 1
        why.append("반등 시작 (전일 대비 상승)")
    if m["atr_pct"] > 6:
        score -= 1
        why.append(f"변동성 과다 (ATR {m['atr_pct']:.1f}%)")
    return score, why


def plain(m: dict[str, Any], strong: bool) -> str:
    """The same reasons as `_score`, in plain Korean for the CEO (owner, 2026-11-06), from the
    same numbers: no model, nothing added."""
    out: list[str] = []
    pb = m.get("pullback")
    if pb is not None:
        if pb < 3:
            out.append("최근 20일 중 가장 비쌌던 가격 근처에 있어요")
        elif pb <= 20:
            out.append(f"최근 20일 중 가장 비쌌던 가격보다 {pb:.1f}% 내려와 잠깐 쉬는 중이에요")
        else:
            out.append(f"최근 20일 중 가장 비쌌던 가격보다 {pb:.1f}%나 내려와 많이 떨어졌어요")
    rsi = m.get("rsi14")
    if rsi is not None:
        out.append("너무 달아오르지도 식지도 않은 상태예요" if 35 <= rsi <= 55 else
                   "많이 식은 상태예요" if rsi < 35 else
                   "살짝 달아오른 상태예요" if rsi <= 60 else "꽤 달아오른 상태예요")
    if m.get("close") and m.get("sma50"):
        if m["close"] >= 0.97 * m["sma50"]:
            out.append("최근 50일 평균 가격 근처나 그 위에서 버티고 있어요")
        elif m["close"] < 0.92 * m["sma50"]:
            out.append("최근 50일 평균 가격보다 꽤 아래로 내려왔어요")
    if strong and m.get("mom63") is not None:
        out.append(f"지난 3개월 동안 다른 종목들보다 많이 올랐어요({m['mom63']:+.1f}%)")
    if m.get("vol5_ratio") is not None and m["vol5_ratio"] < 0.8:
        out.append("쉬는 동안 거래가 줄어서 서둘러 파는 사람은 많지 않아 보여요")
    if m.get("close") and m.get("prev_close") and m["close"] > m["prev_close"]:
        out.append("어제는 다시 올랐어요")
    if m.get("atr_pct") is not None and m["atr_pct"] > 6:
        out.append("다만 하루에 가격이 크게 출렁이는 편이에요")
    return ", ".join(out) + "." if out else ""


def pick(candidates: list[Candidate], held: list[str], recent: set[str],
         watch_size: int = WATCH_SIZE, focus_size: int = FOCUS_SIZE
         ) -> tuple[list[str], list[tuple[str, str]]]:
    """Watchlist (top scores) and today's focus: held stocks first, then the best-scored stocks
    the committee has not met about recently. Returns (watchlist, [(instrument, why)])."""
    watch = [c.instrument_id for c in candidates[:watch_size]]
    focus: list[tuple[str, str]] = [(h, "보유 종목 재점검") for h in held][:focus_size]
    for c in candidates:
        if len(focus) >= focus_size:
            break
        if c.instrument_id in held or c.instrument_id in recent or c.score <= 0:
            continue
        focus.append((c.instrument_id, f"점수 {c.score}: " + ", ".join(c.reasons[1:4])))
    for h in held:   # held stocks stay watched even when they no longer score
        if h not in watch:
            watch.append(h)
    return watch, focus


def to_json(c: Candidate) -> dict[str, Any]:
    return {"instrument_id": c.instrument_id, "score": c.score, "reasons": c.reasons,
            "metrics": c.metrics}


def as_decimal(x: float) -> Decimal:
    return Decimal(str(round(x, 4)))
