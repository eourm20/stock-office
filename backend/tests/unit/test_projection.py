from typing import Any

import pytest

from stock_office.domain.models import AgentStatus, DecisionAction, EventType
from stock_office.engine.adapter import (
    AGENT_CATALOG,
    TradingAgentsProjection,
    rating_to_action,
    spec_for,
)


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[EventType, str | None, dict[str, Any]]] = []
        self.keys: set[str] = set()

    def __call__(self, type: EventType, *, agent_id: str | None = None,
                 payload: dict[str, Any] | None = None, dedupe_key: str | None = None) -> None:
        if dedupe_key in self.keys:
            return
        if dedupe_key:
            self.keys.add(dedupe_key)
        self.events.append((type, agent_id, payload or {}))


def start(task_id: str, name: str) -> dict[str, Any]:
    return {"id": task_id, "name": name, "input": {}, "triggers": []}


def done(task_id: str, name: str, result: Any = None, error: Any = None) -> dict[str, Any]:
    return {"id": task_id, "name": name, "result": result, "error": error, "interrupts": []}


def test_parallel_analysts_and_debate_projection() -> None:
    rec = Recorder()
    p = TradingAgentsProjection("r", rec)
    p.consume("tasks", start("1", "Market Analyst"))
    p.consume("tasks", start("2", "News Analyst"))
    p.consume("tasks", done("2", "News Analyst", {"news_report": "news ok",
                                                  "messages": ["tool call internals"]}))
    p.consume("tasks", done("1", "Market Analyst", {"market_report": "market ok"}))
    p.consume("tasks", start("3", "Bull Researcher"))
    p.consume("tasks", done("3", "Bull Researcher",
                            {"investment_debate_state": {"current_response": "Bull: up"}}))
    p.consume("tasks", start("4", "Conservative Analyst"))
    # Older LangGraph shape: list of (channel, value) pairs.
    p.consume("tasks", done("4", "Conservative Analyst",
                            [("risk_debate_state", {"current_conservative_response": "careful"})]))
    p.consume("values", {"final_trade_decision": "Rating: Buy"})

    kinds = [(t.value, a) for t, a, _ in rec.events]
    assert kinds == [
        ("agent.started", "market_analyst"), ("agent.started", "news_analyst"),
        ("agent.completed", "news_analyst"), ("agent.completed", "market_analyst"),
        ("agent.started", "bull_researcher"), ("debate.message", "bull_researcher"),
        ("agent.completed", "bull_researcher"), ("agent.started", "risk_conservative"),
        ("debate.message", "risk_conservative"), ("agent.completed", "risk_conservative"),
    ]
    assert rec.events[2][2]["summary"] == "news ok"
    assert all("messages" not in payload for _, _, payload in rec.events)
    assert rec.events[8][2]["text"] == "careful"
    assert p.final_state["final_trade_decision"] == "Rating: Buy"


def test_repeated_debate_turns_are_counted() -> None:
    rec = Recorder()
    p = TradingAgentsProjection("r", rec)
    for i in range(2):
        p.consume("tasks", start(f"b{i}", "Bull Researcher"))
        p.consume("tasks", done(f"b{i}", "Bull Researcher",
                                {"investment_debate_state": {"current_response": f"Bull {i}"}}))
    turns = [pl["turn"] for t, _, pl in rec.events if t is EventType.AGENT_STARTED]
    assert turns == [1, 2]


def test_failed_task_and_abort() -> None:
    rec = Recorder()
    p = TradingAgentsProjection("r", rec)
    p.consume("tasks", start("1", "Market Analyst"))
    p.consume("tasks", start("2", "News Analyst"))
    leak = RuntimeError("rate limit sk-ABCDEFGHIJKLMNOP")
    p.consume("tasks", done("1", "Market Analyst", error=leak))
    p.abort_open_tasks("run aborted: RuntimeError")
    failed = [(a, pl["error"]) for t, a, pl in rec.events if t is EventType.AGENT_FAILED]
    assert failed[0][0] == "market_analyst" and "sk-ABC" not in failed[0][1]
    assert failed[1] == ("news_analyst", "run aborted: RuntimeError")
    assert [r.status for r in p.results] == [AgentStatus.FAILED]


def test_dunder_and_unknown_nodes() -> None:
    rec = Recorder()
    p = TradingAgentsProjection("r", rec)
    p.consume("tasks", start("0", "__start__"))
    p.consume("tasks", start("1", "Macro Analyst"))  # a future upstream node
    assert [(t, a) for t, a, _ in rec.events] == [(EventType.AGENT_STARTED, "macro_analyst")]
    assert spec_for("Macro Analyst").phase == "unknown"


def test_duplicate_stream_chunks_are_idempotent() -> None:
    rec = Recorder()
    p = TradingAgentsProjection("r", rec)
    p.consume("tasks", start("1", "Trader"))
    p.consume("tasks", done("1", "Trader", {"trader_investment_plan": "plan"}))
    p.consume("tasks", done("1", "Trader", {"trader_investment_plan": "plan"}))  # replayed
    assert len(rec.events) == 2


@pytest.mark.parametrize("rating,action", [
    ("Buy", DecisionAction.BUY), ("Overweight", DecisionAction.BUY),
    ("Hold", DecisionAction.HOLD), ("Underweight", DecisionAction.SELL),
    ("Sell", DecisionAction.SELL), ("REVIEW", DecisionAction.REVIEW),
    (None, DecisionAction.REVIEW), ("", DecisionAction.REVIEW), ("Moon", DecisionAction.REVIEW),
])
def test_rating_mapping_never_defaults_to_hold(rating: str | None,
                                               action: DecisionAction) -> None:
    assert rating_to_action(rating) is action


def test_catalog_ids_unique() -> None:
    ids = [s.agent_id for s in AGENT_CATALOG.values()]
    assert len(ids) == len(set(ids))


class _Msg:
    def __init__(self, tool_calls: list[dict[str, Any]]) -> None:
        self.tool_calls = tool_calls


def test_tool_calls_inside_analyst_graph_publish_names_only() -> None:
    rec = Recorder()
    p = TradingAgentsProjection("r", rec)
    p.consume("tasks", start("A", "Market Analyst"))
    ns = ("Market Analyst:A",)
    secret_args = {"symbol": "NVDA", "api_key": "sk-should-never-appear-000000"}
    calls = [{"name": "get_stock_data", "args": secret_args, "id": "c1"},
             {"name": "get_indicators", "args": {"indicator": "rsi"}, "id": "c2"},
             {"name": "get_stock_data", "args": {}, "id": "c3"},
             {"name": "bad name; rm -rf", "args": {}, "id": "c4"}]
    p.consume("tasks", {"id": "t1", "name": "agent", "input": {}, "triggers": []}, ns)
    p.consume("tasks", {"id": "t2", "name": "tools", "triggers": [],
                        "input": {"messages": [_Msg(calls)]}}, ns)
    p.consume("tasks", {"id": "t2", "name": "tools", "triggers": [],
                        "input": {"messages": [_Msg(calls)]}}, ns)          # duplicate chunk
    p.consume("tasks", {"id": "t2", "name": "tools", "result": {}, "error": None}, ns)
    p.consume("values", {"messages": ["private"], "market_report": "draft"}, ns)
    p.consume("tasks", {"id": "t3", "name": "tools", "triggers": [],      # dict-shaped message
                        "input": {"messages": [{"tool_calls": [{"name": "get_indicators"}]}]}}, ns)
    p.consume("tasks", {"id": "t9", "name": "tools", "triggers": [],      # parent not running
                        "input": {"messages": [_Msg(calls)]}}, ("News Analyst:zzz",))
    p.consume("tasks", done("A", "Market Analyst", {"market_report": "final"}))

    tool_events = [(a, pl) for t, a, pl in rec.events if t is EventType.TOOL_CALLED]
    assert tool_events == [
        ("market_analyst", {"role": "Market Analyst", "turn": 1, "round": 1,
                            "tools": ["get_stock_data", "get_indicators", "other"]}),
        ("market_analyst", {"role": "Market Analyst", "turn": 1, "round": 2,
                            "tools": ["get_indicators"]}),
    ]
    assert "sk-should-never-appear" not in repr(rec.events)
    assert "rsi" not in repr(rec.events)
    # The analyst's private working state never becomes the run's final state.
    assert p.final_state == {}
    assert [t.value for t, _, _ in rec.events] == [
        "agent.started", "tool.called", "tool.called", "agent.completed"]


def test_reports_from_state_are_full_redacted_and_skip_internals() -> None:
    from stock_office.engine.adapter import REPORT_MAX_CHARS, reports_from_state

    long = "x" * 5000
    state = {"market_report": long, "news_report": "  ", "memory_note": "past",
             "final_trade_decision": "Rating: Buy api_key=sk-abcdefghijklmnop0000",
             "messages": ["internal"],
             "investment_debate_state": {"history": "Bull: a\nBear: b", "current_response": "b"},
             "risk_debate_state": {"history": ""}}
    reports = reports_from_state(state)
    assert set(reports) == {"market_analyst", "portfolio_manager", "investment_debate"}
    assert reports["market_analyst"] == long                      # not cut to the 600-char summary
    assert "sk-abcdefghijklmnop" not in reports["portfolio_manager"]
    assert len(reports_from_state({"market_report": "y" * (REPORT_MAX_CHARS + 50)})
               ["market_analyst"]) < REPORT_MAX_CHARS + 20
