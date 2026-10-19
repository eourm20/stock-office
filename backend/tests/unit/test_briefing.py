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
        agent_lines=[AgentLine(agent_id="market_analyst", line="상승 추세"),
                     AgentLine(agent_id="made_up_agent", line="invented"),
                     AgentLine(agent_id="trader", line="  ")],
        debate_gists=[DebateGist(seq=14, gist="오른다"), DebateGist(seq=999, gist="invented")],
    )
    b = finalize(draft, PAYLOAD, model="m", demo=False, usage=None, now=NOW)
    assert len(b.headline) <= 140 and b.headline.endswith("…")
    assert b.key_reasons == ["a", "b", "c"]
    assert "sk-abcdefghijklmnop" not in b.risks[0]
    assert b.agents == {"market_analyst": "상승 추세"}
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
