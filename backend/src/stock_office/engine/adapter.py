"""TradingAgentsAdapter: projects TradingAgents' LangGraph stream onto Stock Office events.

Verified against TradingAgents v0.6.0 (commit 1394a3f). The projection consumes the
top-level graph stream with `stream_mode=["tasks", "values"]`:
  * tasks start  -> {"id", "name", "input", "triggers"}            => agent.started
  * tasks finish -> {"id", "name", "error", "result", "interrupts"} => agent.completed/failed
  * values       -> the full run state after a step                 => kept as final state
With `subgraphs=True`, chunks from inside an analyst's own graph arrive with a namespace
`("<Analyst node>:<parent task id>", ...)`. Only its `tools` task starts are used, as tool.called
with the tool *names*; arguments, results and messages are never forwarded.
Only sanitized report excerpts are published.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from stock_office.domain.models import (
    AgentResult,
    AgentStatus,
    DecisionAction,
    EventType,
    Instrument,
    MarketSnapshot,
)
from stock_office.events.sanitize import redact_text


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    role: str
    phase: str
    report_key: str | None = None
    debate: str | None = None  # "investment" | "risk"
    stance: str | None = None


# Upstream LangGraph node name -> normalized agent.
# Guarded by tests/contract/test_upstream_graph.py.
AGENT_CATALOG: dict[str, AgentSpec] = {
    "Market Analyst": AgentSpec("market_analyst", "Market Analyst", "analysis", "market_report"),
    "Sentiment Analyst": AgentSpec(
        "sentiment_analyst", "Sentiment Analyst", "analysis", "sentiment_report"
    ),
    "News Analyst": AgentSpec("news_analyst", "News Analyst", "analysis", "news_report"),
    "Fundamentals Analyst": AgentSpec(
        "fundamentals_analyst", "Fundamentals Analyst", "analysis", "fundamentals_report"
    ),
    "Memory Log": AgentSpec("memory_log", "Memory Log", "analysis", "memory_note"),
    "Bull Researcher": AgentSpec(
        "bull_researcher", "Bull Researcher", "research_debate", debate="investment", stance="bull"
    ),
    "Bear Researcher": AgentSpec(
        "bear_researcher", "Bear Researcher", "research_debate", debate="investment", stance="bear"
    ),
    "Research Manager": AgentSpec(
        "research_manager", "Research Manager", "research_debate", "investment_plan"
    ),
    "Trader": AgentSpec("trader", "Trader", "trading", "trader_investment_plan"),
    "Aggressive Analyst": AgentSpec(
        "risk_aggressive", "Aggressive Risk Analyst", "risk_debate", debate="risk",
        stance="aggressive",
    ),
    "Conservative Analyst": AgentSpec(
        "risk_conservative", "Conservative Risk Analyst", "risk_debate", debate="risk",
        stance="conservative",
    ),
    "Neutral Analyst": AgentSpec(
        "risk_neutral", "Neutral Risk Analyst", "risk_debate", debate="risk", stance="neutral"
    ),
    "Portfolio Manager": AgentSpec(
        "portfolio_manager", "Portfolio Manager", "decision", "final_trade_decision"
    ),
}

_RISK_RESPONSE_KEY = {
    "aggressive": "current_aggressive_response",
    "conservative": "current_conservative_response",
    "neutral": "current_neutral_response",
}


_TOOL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_MAX_TOOLS_PER_EVENT = 8


def _tool_names(task_input: Any) -> list[str]:
    """Names of the tool calls a `tools` task is about to run (never their arguments)."""
    messages = task_input.get("messages") if isinstance(task_input, dict) else None
    if not messages:
        return []
    last = messages[-1]
    calls = last.get("tool_calls") if isinstance(last, dict) else getattr(last, "tool_calls", None)
    names: list[str] = []
    for call in calls or []:
        name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
        name = name if isinstance(name, str) and _TOOL_NAME.match(name) else "other"
        if name not in names:
            names.append(name)
    return names[:_MAX_TOOLS_PER_EVENT]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def spec_for(node_name: str) -> AgentSpec:
    return AGENT_CATALOG.get(node_name) or AgentSpec(_slug(node_name), node_name, "unknown")


class EventSink(Protocol):
    def __call__(
        self,
        type: EventType,
        *,
        agent_id: str | None = None,
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> object: ...


def _as_dict(result: Any) -> dict[str, Any]:
    """LangGraph task results are a dict (1.x) or a list of (channel, value) pairs (older)."""
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return {k: v for k, v in result if isinstance(k, str)}
    return {}


@dataclass
class _OpenTask:
    node: str
    spec: AgentSpec
    started_at: datetime
    turn: int


@dataclass
class TradingAgentsProjection:
    """Pure stream -> event projection. No upstream import; unit-testable with synthetic chunks."""

    run_id: str
    sink: EventSink
    final_state: dict[str, Any] = field(default_factory=dict)
    results: list[AgentResult] = field(default_factory=list)
    _open: dict[str, _OpenTask] = field(default_factory=dict)
    _turns: dict[str, int] = field(default_factory=dict)
    _tool_rounds: dict[str, int] = field(default_factory=dict)
    _tool_tasks: set[str] = field(default_factory=set)

    def consume(self, mode: str, chunk: Any, namespace: tuple[str, ...] = ()) -> None:
        if namespace:
            # Inside an analyst's own graph. Its `values` are private working state and must
            # never replace the run's final state.
            if mode == "tasks" and isinstance(chunk, dict):
                self._on_nested_task(namespace, chunk)
            return
        if mode == "values" and isinstance(chunk, dict):
            self.final_state = chunk
        elif mode == "tasks" and isinstance(chunk, dict):
            if "input" in chunk and "result" not in chunk:
                self._on_start(chunk)
            elif "result" in chunk or "error" in chunk:
                self._on_finish(chunk)

    def _on_start(self, chunk: dict[str, Any]) -> None:
        node = str(chunk.get("name", ""))
        if node.startswith("__"):
            return
        spec = spec_for(node)
        turn = self._turns.get(node, 0) + 1
        self._turns[node] = turn
        task_id = str(chunk.get("id"))
        self._open[task_id] = _OpenTask(node, spec, datetime.now(UTC), turn)
        self.sink(
            EventType.AGENT_STARTED,
            agent_id=spec.agent_id,
            payload={"role": spec.role, "phase": spec.phase, "turn": turn, "node": node},
            dedupe_key=f"task:{task_id}:start",
        )

    def _on_nested_task(self, namespace: tuple[str, ...], chunk: dict[str, Any]) -> None:
        if chunk.get("name") != "tools" or "input" not in chunk or "result" in chunk:
            return
        parent_id = namespace[0].partition(":")[2]
        task = self._open.get(parent_id)
        if task is None:
            return
        tool_task = str(chunk.get("id"))
        names = _tool_names(chunk.get("input"))
        if not names or tool_task in self._tool_tasks:     # a re-sent chunk is not a new round
            return
        self._tool_tasks.add(tool_task)
        rounds = self._tool_rounds.get(parent_id, 0) + 1
        self._tool_rounds[parent_id] = rounds
        self.sink(
            EventType.TOOL_CALLED,
            agent_id=task.spec.agent_id,
            payload={"role": task.spec.role, "turn": task.turn, "round": rounds, "tools": names},
            dedupe_key=f"task:{tool_task}:tools",
        )

    def _on_finish(self, chunk: dict[str, Any]) -> None:
        task_id = str(chunk.get("id"))
        task = self._open.pop(task_id, None)
        if task is None:
            return
        spec, now = task.spec, datetime.now(UTC)
        error = chunk.get("error")
        if error:
            reason = redact_text(f"{type(error).__name__}: {error}", limit=300)
            self.sink(
                EventType.AGENT_FAILED,
                agent_id=spec.agent_id,
                payload={"role": spec.role, "turn": task.turn, "error": reason},
                dedupe_key=f"task:{task_id}:end",
            )
            self.results.append(
                AgentResult(run_id=self.run_id, agent_id=spec.agent_id, role=spec.role,
                            status=AgentStatus.FAILED, started_at=task.started_at,
                            completed_at=now, warnings=[reason])
            )
            return

        result = _as_dict(chunk.get("result"))
        text = self._debate_text(spec, result) if spec.debate else ""
        if text:
            self.sink(
                EventType.DEBATE_MESSAGE,
                agent_id=spec.agent_id,
                payload={"debate": spec.debate, "stance": spec.stance, "turn": task.turn,
                         "text": redact_text(text)},
                dedupe_key=f"task:{task_id}:debate",
            )
        report = str(result.get(spec.report_key, "") or "") if spec.report_key else text
        summary = redact_text(report, limit=600)
        self.sink(
            EventType.AGENT_COMPLETED,
            agent_id=spec.agent_id,
            payload={"role": spec.role, "turn": task.turn, "summary": summary,
                     "duration_ms": int((now - task.started_at).total_seconds() * 1000)},
            dedupe_key=f"task:{task_id}:end",
        )
        self.results.append(
            AgentResult(run_id=self.run_id, agent_id=spec.agent_id, role=spec.role,
                        status=AgentStatus.COMPLETED, started_at=task.started_at,
                        completed_at=now, summary=summary,
                        structured_output={"turn": task.turn, "phase": spec.phase})
        )

    @staticmethod
    def _debate_text(spec: AgentSpec, result: dict[str, Any]) -> str:
        if spec.debate == "investment":
            state = result.get("investment_debate_state") or {}
            return str(state.get("current_response", "") or "")
        state = result.get("risk_debate_state") or {}
        return str(state.get(_RISK_RESPONSE_KEY.get(spec.stance or "", ""), "") or "")

    def abort_open_tasks(self, reason: str) -> None:
        """Close every still-running agent explicitly instead of leaving it RUNNING forever."""
        for task_id, task in list(self._open.items()):
            self.sink(
                EventType.AGENT_FAILED,
                agent_id=task.spec.agent_id,
                payload={"role": task.spec.role, "turn": task.turn, "error": reason},
                dedupe_key=f"task:{task_id}:end",
            )
            self._open.pop(task_id)


# --- rating -> deterministic action mapping -----------------------------------------------

_RATING_TO_ACTION = {
    "buy": DecisionAction.BUY,
    "overweight": DecisionAction.BUY,
    "hold": DecisionAction.HOLD,
    "underweight": DecisionAction.SELL,
    "sell": DecisionAction.SELL,
}


def rating_to_action(rating: str | None) -> DecisionAction:
    """Unknown, missing or upstream-`REVIEW` ratings never silently become HOLD."""
    if not rating:
        return DecisionAction.REVIEW
    return _RATING_TO_ACTION.get(rating.strip().lower(), DecisionAction.REVIEW)


@dataclass
class EngineContext:
    run_id: str
    instrument: Instrument
    as_of: datetime
    trade_date: str  # exchange-local YYYY-MM-DD
    snapshots: list[MarketSnapshot]
    sink: EventSink
    work_dir: Any  # pathlib.Path for engine-private files


@dataclass
class EngineOutcome:
    rating: str | None
    final_report: str
    bear_case: str
    risk_case: str
    results: list[AgentResult]
    warnings: list[str] = field(default_factory=list)
    token_usage: dict[str, Any] | None = None
    coverage_gaps: list[str] = field(default_factory=list)  # data the engine could not get
    # Full sanitized report per agent (and both debate transcripts), for the analysis screen.
    reports: dict[str, str] = field(default_factory=dict)


class EngineNotConfiguredError(RuntimeError):
    code = "ENGINE_NOT_CONFIGURED"


class AnalysisEngine(Protocol):
    name: str
    demo: bool

    def version(self) -> str: ...

    def config_hash(self) -> str: ...

    def model_version(self) -> str: ...

    def check_ready(self) -> None:
        """Raise EngineNotConfiguredError with a safe message when it cannot run."""
        ...

    def run(self, ctx: EngineContext) -> EngineOutcome: ...


REPORT_MAX_CHARS = 30_000


def reports_from_state(state: dict[str, Any]) -> dict[str, str]:
    """Each agent's full report and the debate transcripts, redacted. Never messages/tool data."""
    reports: dict[str, str] = {}
    for spec in AGENT_CATALOG.values():
        if spec.report_key and spec.agent_id != "memory_log":
            text = str(state.get(spec.report_key, "") or "")
            if text.strip():
                reports[spec.agent_id] = redact_text(text, limit=REPORT_MAX_CHARS)
    for key, debate_key in (("investment_debate", "investment_debate_state"),
                            ("risk_debate", "risk_debate_state")):
        history = str((state.get(debate_key) or {}).get("history", "") or "")
        if history.strip():
            reports[key] = redact_text(history, limit=REPORT_MAX_CHARS)
    return reports


def outcome_from_state(
    projection: TradingAgentsProjection, rating: str | None, warnings: list[str] | None = None
) -> EngineOutcome:
    state = projection.final_state
    invest = state.get("investment_debate_state") or {}
    risk = state.get("risk_debate_state") or {}
    return EngineOutcome(
        rating=rating,
        final_report=str(state.get("final_trade_decision", "") or ""),
        bear_case=str(invest.get("bear_history", "") or ""),
        risk_case=str(risk.get("conservative_history", "") or ""),
        results=projection.results,
        warnings=warnings or [],
        reports=reports_from_state(state),
    )
