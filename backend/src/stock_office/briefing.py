"""One-page briefing of a finished run: conclusion, reasons, risks, what to watch, one line per
agent and the gist of each debate message.

It is an *AI summary of the stored reports* (labelled so in the UI), written by the engine's cheap
"quick" model with structured output. The input is only what Stock Office already stored and
published (redacted reports, debate lines, the decision); the output is validated, clipped and
redacted, and unknown agents or messages are dropped. A failed briefing never fails the run.

    uv run python -m stock_office.briefing <run_id> [...]   # backfill older runs (paid, ~$0.003)
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from stock_office.domain.models import AnalysisRun, EventType, InvestmentDecision
from stock_office.engine.adapter import AGENT_CATALOG
from stock_office.events.sanitize import redact_text
from stock_office.runs.repository import RunRepository

MAX_ITEMS = 3
HEADLINE_CHARS = 120
ITEM_CHARS = 160
REPORT_CHARS_IN_PROMPT = 4000
AGENT_IDS = {spec.agent_id for spec in AGENT_CATALOG.values()} - {"memory_log"}


class AgentLine(BaseModel):
    agent_id: str = Field(description="agent id exactly as given in the input")
    line: str = Field(description="한 문장 요약 (60자 이내)")


class DebateGist(BaseModel):
    seq: int = Field(description="message seq exactly as given in the input")
    gist: str = Field(description="그 발언의 핵심 주장 한두 문장 (80자 이내)")


class BriefingDraft(BaseModel):
    """What the model returns."""

    headline: str = Field(description="결론 한 문장 (60자 이내)")
    key_reasons: list[str] = Field(description="결정을 뒷받침한 핵심 근거, 최대 3개, 각 한 문장")
    risks: list[str] = Field(description="주요 위험·반대 논거, 최대 3개, 각 한 문장")
    watch_next: list[str] = Field(description="다음에 확인할 지표나 사건, 최대 3개")
    agent_lines: list[AgentLine] = Field(default_factory=list)
    debate_gists: list[DebateGist] = Field(default_factory=list)


class Briefing(BaseModel):
    """What is stored and served."""

    status: str = "OK"                       # OK | FAILED
    headline: str = ""
    key_reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    watch_next: list[str] = Field(default_factory=list)
    agents: dict[str, str] = Field(default_factory=dict)
    debate: dict[str, str] = Field(default_factory=dict)   # seq (as text) -> gist
    model: str = ""
    generated_at: datetime | None = None
    demo: bool = False
    token_usage: dict[str, Any] | None = None
    error: str | None = None


class BriefingWriter(Protocol):
    model: str

    def __call__(self, prompt: str) -> tuple[BriefingDraft, dict[str, Any] | None]: ...


# ------------------------------------------------------------------------------- input

def collect_input(repo: RunRepository, run: AnalysisRun) -> dict[str, Any] | None:
    """Everything the briefing may use, from storage only. None when there is no decision."""
    decision: InvestmentDecision | None = repo.get_decision(run.id)
    if decision is None:
        return None
    reports = repo.get_reports(run.id) or {}
    agents: dict[str, str] = {}
    for out in repo.get_outputs(run.id):
        if out.agent_id in AGENT_IDS:
            text = reports.get(out.agent_id) or out.summary
            if text.strip():
                agents[out.agent_id] = text[:REPORT_CHARS_IN_PROMPT]
    debate = [
        {"seq": e.seq, "agent_id": e.agent_id, "stance": e.payload.get("stance"),
         "turn": e.payload.get("turn"), "text": str(e.payload.get("text", ""))[:1500]}
        for e in repo.events.read(run.id) if e.type is EventType.DEBATE_MESSAGE
    ]
    return {
        "instrument": run.instrument_id,
        "decision": {"action": decision.action.value, "rating": decision.engine_rating,
                     "risk_flags": decision.risk_flags,
                     "final_report": (reports.get("portfolio_manager") or decision.rationale)
                     [:REPORT_CHARS_IN_PROMPT]},
        "agent_reports": agents,
        "debate": debate,
    }


PROMPT = """너는 투자위원회 회의 결과를 임원에게 보고하는 비서다. 아래 JSON은 이번 회의에서 저장된 \
보고서와 발언 전부다. 이 내용만 사용해 한국어로 짧고 명확한 브리핑을 써라.

규칙:
- 입력에 없는 숫자·사실·전망을 만들지 마라. 확실하지 않으면 쓰지 마라.
- 결론(headline)은 최종 결정(decision.action, rating)과 일치해야 한다.
- 각 항목은 한 문장, 핵심만. 최대 3개.
- agent_lines: agent_reports의 각 agent_id마다 한 문장.
- debate_gists: debate의 각 seq마다 그 발언의 핵심 주장을 한두 문장으로.
- 투자 권유나 수익 보장 표현을 쓰지 마라. 외부 도구나 검색을 쓰지 마라.

입력:
{payload}
"""


def build_prompt(payload: dict[str, Any]) -> str:
    return PROMPT.format(payload=json.dumps(payload, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------------------ output

def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return redact_text(text if len(text) <= limit else text[: limit - 1] + "…", limit=limit + 20)


def finalize(draft: BriefingDraft, payload: dict[str, Any], *, model: str, demo: bool,
             usage: dict[str, Any] | None, now: datetime) -> Briefing:
    """Clip, redact and keep only agents/messages that exist in this run."""
    agents_in = set(payload["agent_reports"])
    seqs_in = {int(d["seq"]) for d in payload["debate"]}
    return Briefing(
        headline=_clip(draft.headline, HEADLINE_CHARS),
        key_reasons=[_clip(x, ITEM_CHARS) for x in draft.key_reasons if x.strip()][:MAX_ITEMS],
        risks=[_clip(x, ITEM_CHARS) for x in draft.risks if x.strip()][:MAX_ITEMS],
        watch_next=[_clip(x, ITEM_CHARS) for x in draft.watch_next if x.strip()][:MAX_ITEMS],
        agents={a.agent_id: _clip(a.line, ITEM_CHARS) for a in draft.agent_lines
                if a.agent_id in agents_in and a.line.strip()},
        debate={str(d.seq): _clip(d.gist, ITEM_CHARS) for d in draft.debate_gists
                if d.seq in seqs_in and d.gist.strip()},
        model=model, generated_at=now, demo=demo, token_usage=usage,
    )


def write_briefing(repo: RunRepository, run: AnalysisRun, writer: BriefingWriter,
                   clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> Briefing | None:
    """Create and store `briefing.json`. Errors are stored as status FAILED, never raised."""
    payload = collect_input(repo, run)
    if payload is None:
        return None
    try:
        draft, usage = writer(build_prompt(payload))
        briefing = finalize(draft, payload, model=writer.model, demo=run.demo, usage=usage,
                            now=clock())
    except Exception as exc:  # the run itself already succeeded
        briefing = Briefing(status="FAILED", model=writer.model, generated_at=clock(),
                            demo=run.demo, error=redact_text(type(exc).__name__, limit=100))
    repo.write_json(run.id, "briefing.json", briefing.model_dump(mode="json"))
    return briefing


# ----------------------------------------------------------------------------- writers

class DemoBriefingWriter:
    """No model call: a fixed, clearly labelled synthetic briefing for DEMO runs."""

    model = "demo-fixture (no model called)"

    def __call__(self, prompt: str) -> tuple[BriefingDraft, dict[str, Any] | None]:
        payload = json.loads(prompt[prompt.index("{"):])
        return BriefingDraft(
            headline=f"DEMO 브리핑: 최종 결정 {payload['decision']['action']} (합성 데이터)",
            key_reasons=["DEMO: 실제 분석이 아닌 화면 시험용 근거입니다."],
            risks=["DEMO: 실제 위험 평가가 아닙니다."],
            watch_next=["DEMO: 실제 분석을 실행해 보세요."],
            agent_lines=[AgentLine(agent_id=a, line="DEMO 요약 한 줄")
                         for a in payload["agent_reports"]],
            debate_gists=[DebateGist(seq=d["seq"], gist="DEMO 발언 요지")
                          for d in payload["debate"]],
        ), None


class QuickModelBriefingWriter:
    """The engine's quick-tier model (same provider/config as the analysis), structured output."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.model = str(config.get("quick_think_llm", ""))

    def __call__(self, prompt: str) -> tuple[BriefingDraft, dict[str, Any] | None]:
        from langchain_core.callbacks import UsageMetadataCallbackHandler

        from stock_office.engine.upstream import import_tradingagents

        import_tradingagents()
        from tradingagents.llm_clients.factory import create_tier_client

        usage = UsageMetadataCallbackHandler()
        llm = create_tier_client(self.config, "quick").get_llm()
        result = llm.with_structured_output(BriefingDraft).invoke(
            prompt, config={"callbacks": [usage]})
        if not isinstance(result, BriefingDraft):
            raise TypeError("structured output did not return a BriefingDraft")
        return result, {k: dict(v) for k, v in usage.usage_metadata.items()}


def main(argv: list[str]) -> int:
    from stock_office.config import get_settings
    from stock_office.wiring import build_service

    service = build_service(get_settings())
    for run_id in argv:
        run = service.repo.get_run(run_id)
        if run is None:
            print(f"{run_id}: not found")
            continue
        briefing = service.brief(run)
        print(f"{run_id}: {briefing.status if briefing else 'no decision'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
