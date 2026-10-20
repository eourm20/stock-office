"""The research team's screener: deterministic scores on daily bars, no model involved.

Rules (RULES_VERSION), on bars up to the last completed session only:
- liquidity filter: 20-day average traded value ≥ 1억 KRW (국장) / $50M (미장); at least 200 bars
- +2 uptrend (close > 50-day MA > 200-day MA), or +1 if only close > 50-day MA
- +0..2 three-month momentum, by rank within the market (top third 2, middle third 1)
- +1 volume surge (last volume ≥ 1.5 × 20-day average)
- +1 near the 52-week high (close ≥ 95% of it), +1 more on a new 52-week closing high
- −1 too volatile (14-day ATR above 6% of the price), −1 overbought (14-day RSI above 80)
Every point is written out as a reason, so the CEO can read why a stock was picked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

RULES_VERSION = "SCREEN_V1"
MIN_VALUE = {"KR": 1e8 * 10, "US": 50e6}   # 10억 KRW (1e9) / $50M a day
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
        "close": b.close[-1], "sma50": _sma(b.close, 50), "sma200": _sma(b.close, 200),
        "mom63": (b.close[-1] / b.close[-64] - 1) * 100, "value20": value20,
        "vol_ratio": b.volume[-1] / (_sma(b.volume, 20) or 1),
        "high52": max(b.close[-252:]), "rsi14": _rsi(b.close), "atr_pct": _atr_pct(b),
    }


def screen(market: str, bars: dict[str, Bars]) -> list[Candidate]:
    """Score every liquid instrument; best first (ties: stronger momentum first)."""
    ms = {iid: m for iid, b in bars.items() if (m := metrics(b)) is not None
          and m["value20"] >= MIN_VALUE[market]}
    ranked = sorted(ms, key=lambda i: ms[i]["mom63"])
    third = len(ranked) / 3
    out = []
    for pos, iid in enumerate(ranked):
        m, score, why = ms[iid], 0, []
        if m["close"] > m["sma50"] > m["sma200"]:
            score += 2
            why.append("상승 추세 (종가 > 50일선 > 200일선)")
        elif m["close"] > m["sma50"]:
            score += 1
            why.append("종가가 50일선 위")
        if pos >= 2 * third:
            score += 2
            why.append(f"3개월 수익률 상위 1/3 ({m['mom63']:+.1f}%)")
        elif pos >= third:
            score += 1
            why.append(f"3개월 수익률 중간 ({m['mom63']:+.1f}%)")
        if m["vol_ratio"] >= 1.5:
            score += 1
            why.append(f"거래량 급증 (20일 평균의 {m['vol_ratio']:.1f}배)")
        if m["close"] >= 0.95 * m["high52"]:
            score += 1
            why.append("52주 고가의 95% 이상")
            if m["close"] >= m["high52"]:
                score += 1
                why.append("52주 신고가 (종가 기준)")
        if m["atr_pct"] > 6:
            score -= 1
            why.append(f"변동성 과다 (ATR {m['atr_pct']:.1f}%)")
        if m["rsi14"] > 80:
            score -= 1
            why.append(f"과열 (RSI {m['rsi14']:.0f})")
        out.append(Candidate(iid, score, why, {k: round(v, 4) for k, v in m.items()}))
    return sorted(out, key=lambda c: (c.score, c.metrics["mom63"]), reverse=True)


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
        focus.append((c.instrument_id, f"점수 {c.score}: " + ", ".join(c.reasons[:3])))
    for h in held:   # held stocks stay watched even when they no longer score
        if h not in watch:
            watch.append(h)
    return watch, focus


def to_json(c: Candidate) -> dict[str, Any]:
    return {"instrument_id": c.instrument_id, "score": c.score, "reasons": c.reasons,
            "metrics": c.metrics}


def as_decimal(x: float) -> Decimal:
    return Decimal(str(round(x, 4)))
