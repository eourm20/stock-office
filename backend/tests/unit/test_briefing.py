"""Briefing: validation, clipping, redaction and failure handling (no model, no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stock_office.briefing import (
    ITEM_CHARS,
    AgentLine,
    BriefingDraft,
    DebateGist,
    build_prompt,
    finalize,
    write_briefing,
)
from stock_office.domain.models import AnalysisRun, InvestmentDecision
from stock_office.runs.repository import RunRepository

NOW = datetime(2026, 10, 19, tzinfo=UTC)
PAYLOAD: dict[str, Any] = {
    "instrument": "US:NASDAQ:NVDA",
    "decision": {"action": "BUY", "rating": "Overweight", "risk_flags": [], "final_report": "x"},
    "agent_reports": {"market_analyst": "trend up", "trader": "buy some"},
    "debate": [{"seq": 14, "agent_id": "bull_researcher", "stance": "bull", "turn": 1,
                "text": "up"}],
}


def test_finalize_keeps_only_known_agents_and_messages_and_clips() -> None:
    draft = BriefingDraft(
        headline="매수 의견 " + "가" * 300,
        key_reasons=["a", "b", "c", "d", "  "],
        risks=["위험 api_key=sk-abcdefghijklmnop0000"],
        watch_next=[],
        agent_lines=[AgentLine(agent_id="market_analyst", line="상승 추세",
                               points=["p1", "p2", "p3", "p4", " "]),
                     AgentLine(agent_id="made_up_agent", line="invented"),
                     AgentLine(agent_id="trader", line="  ")],
        debate_gists=[DebateGist(seq=14, gist="오른다"), DebateGist(seq=999, gist="invented")],
    )
    b = finalize(draft, PAYLOAD, model="m", demo=False, usage=None, now=NOW)
    assert len(b.headline) <= 140 and b.headline.endswith("…")
    assert b.key_reasons == ["a", "b", "c"]
    assert "sk-abcdefghijklmnop" not in b.risks[0]
    assert b.agents == {"market_analyst": "상승 추세"}
    assert b.agent_points == {"market_analyst": ["p1", "p2", "p3"]}
    assert b.debate == {"14": "오른다"}
    assert all(len(x) <= ITEM_CHARS + 20 for x in b.key_reasons + b.risks)


def test_prompt_carries_only_the_stored_payload() -> None:
    prompt = build_prompt(PAYLOAD)
    assert '"market_analyst": "trend up"' in prompt and "입력에 없는 숫자" in prompt


class _Boom:
    model = "boom-model"

    def __call__(self, prompt: str) -> tuple[BriefingDraft, dict[str, Any] | None]:
        raise TimeoutError("provider down")


def _seed(tmp_path: Path) -> tuple[RunRepository, AnalysisRun]:
    repo = RunRepository(tmp_path)
    run = AnalysisRun(id="r1", instrument_id="US:NASDAQ:NVDA", requested_at=NOW, as_of=NOW,
                      engine="tradingagents", status="COMPLETED", demo=False,
                      engine_version="test", config_hash="test")
    repo.save_run(run)
    return repo, run


def test_no_decision_means_no_briefing(tmp_path: Path) -> None:
    repo, run = _seed(tmp_path)
    assert write_briefing(repo, run, _Boom(), lambda: NOW) is None
    assert repo.get_briefing("r1") is None


def test_a_failed_model_call_is_stored_as_failed_not_raised(tmp_path: Path) -> None:
    repo, run = _seed(tmp_path)
    repo.save_decision(InvestmentDecision(run_id="r1", action="BUY", rationale="r",
                                          model_version="m", created_at=NOW))
    briefing = write_briefing(repo, run, _Boom(), lambda: NOW)
    assert briefing is not None and briefing.status == "FAILED" and briefing.error == "TimeoutError"
    stored = repo.get_briefing("r1")
    assert stored is not None and stored["status"] == "FAILED" and stored["headline"] == ""


def test_story_and_terms_are_kept_clipped_and_capped() -> None:
    from stock_office.briefing import MAX_TERMS, STORY_CHARS, StoryLine, Term

    draft = BriefingDraft(
        headline="매수", key_reasons=[], risks=[], watch_next=[],
        story=[StoryLine(text="비유하자면 과일 가게가 " + "가" * 2000),
               StoryLine(text="요즘 기세가 좋아요.", basis="trend up"),
               StoryLine(text="지어낸 근거", basis="RSI 99 폭등")],
        terms=[Term(term=f"용어{n}", meaning="쉬운 풀이") for n in range(MAX_TERMS + 3)]
        + [Term(term=" ", meaning="빈 용어")],
    )
    b = finalize(draft, PAYLOAD, model="m", demo=False, usage=None, now=NOW)
    assert b.story.startswith("비유하자면") and len(b.story) <= STORY_CHARS + 20
    assert list(b.terms) == [f"용어{n}" for n in range(MAX_TERMS)]
    assert [x["basis"] for x in b.story_lines] == ["", "trend up", ""]   # only real wording
    assert "이야기처럼" in build_prompt(PAYLOAD)


def test_the_story_is_told_what_the_company_actually_does(tmp_path: Path) -> None:
    """A SELL on a stock the company does not hold places no order, whatever the committee wrote
    about trimming; the meeting's saved holdings input tells held from not held."""
    from stock_office.briefing import collect_input

    repo, run = _seed(tmp_path)
    repo.save_decision(InvestmentDecision(run_id="r1", action="SELL", rationale="r",
                                          model_version="m", created_at=NOW))
    company = (collect_input(repo, run) or {})["company"]
    assert company["held_at_meeting"] is False and "주문은 없어요" in company["what_happens"]
    (repo.root / "r1" / "portfolio_context.md").write_text("보유 3주", encoding="utf-8")
    company = (collect_input(repo, run) or {})["company"]
    assert company["held_at_meeting"] is True and "전부 파는" in company["what_happens"]
    assert "company.what_happens" in build_prompt(collect_input(repo, run) or {})
