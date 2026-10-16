"""Contract tests against the pinned TradingAgents package. No network, no LLM calls.

Run after `uv sync --extra engine`. Skipped when the optional package is absent.
"""

from __future__ import annotations

import inspect
import operator
from pathlib import Path
from typing import Annotated, Any, TypedDict

import pytest

from stock_office.config import TRADINGAGENTS_VERSION, Settings
from stock_office.domain.models import EventType
from stock_office.engine.adapter import AGENT_CATALOG, TradingAgentsProjection
from stock_office.engine.tradingagents_engine import TradingAgentsEngine

tradingagents = pytest.importorskip("tradingagents")
pytestmark = pytest.mark.engine


def test_pinned_version() -> None:
    assert tradingagents.__version__ == TRADINGAGENTS_VERSION


def test_integration_points_exist() -> None:
    from tradingagents.agents.rating import run_rating
    from tradingagents.dataflows.config import run_config_context
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    assert callable(run_rating) and callable(run_config_context)
    for name in ("create_run_state", "stream_run", "propagate"):
        assert hasattr(TradingAgentsGraph, name)
    params = inspect.signature(TradingAgentsGraph.__init__).parameters
    assert {"selected_analysts", "config", "callbacks"} <= params.keys()


def test_upstream_node_names_match_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch
                                           ) -> None:
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key-000000")  # client init only
    settings = Settings(data_dir=tmp_path, _env_file=None)  # type: ignore[call-arg]
    engine = TradingAgentsEngine(settings)
    work = tmp_path / "runs" / "r1"
    work.mkdir(parents=True)
    graph = TradingAgentsGraph(selected_analysts=("market", "social", "news", "fundamentals"),
                               config=engine.build_config(work))
    nodes = {n for n in graph.graph.get_graph().nodes if not n.startswith("__")}
    assert nodes == set(AGENT_CATALOG), f"upstream drift: {nodes ^ set(AGENT_CATALOG)}"
    # Memory log is isolated per run, so no prior decisions can be reflected.
    assert graph.config["memory_log_path"].startswith(str(work))


def test_upstream_rating_contract() -> None:
    from tradingagents.agents.rating import RATING_REVIEW, RATINGS_5_TIER, run_rating

    assert RATINGS_5_TIER == ("Buy", "Overweight", "Hold", "Underweight", "Sell")
    assert RATING_REVIEW == "REVIEW"
    assert run_rating({"final_trade_decision": "- **Rating**: Overweight\nbody"}) == "Overweight"
    assert run_rating({"final_trade_decision": "no label here"}) == "REVIEW"


class _S(TypedDict):
    market_report: str
    investment_debate_state: dict[str, Any]
    log: Annotated[list[str], operator.add]


def test_langgraph_tasks_stream_shape_feeds_projection() -> None:
    """The installed LangGraph emits the task start/finish shape the projection expects."""
    from langgraph.graph import END, START, StateGraph

    def market(_: _S) -> dict[str, Any]:
        return {"market_report": "ok", "log": ["m"]}

    def bull(_: _S) -> dict[str, Any]:
        return {"investment_debate_state": {"current_response": "Bull: yes"}, "log": ["b"]}

    g = StateGraph(_S)
    g.add_node("Market Analyst", market)
    g.add_node("Bull Researcher", bull)
    g.add_edge(START, "Market Analyst")
    g.add_edge("Market Analyst", "Bull Researcher")
    g.add_edge("Bull Researcher", END)
    compiled = g.compile()

    raw: list[tuple[str, Any]] = []
    events: list[tuple[EventType, str | None]] = []
    projection = TradingAgentsProjection(
        "r",
        lambda t, *, agent_id=None, payload=None, dedupe_key=None: events.append((t, agent_id)),
    )
    init = {"market_report": "", "investment_debate_state": {}, "log": []}
    for mode, chunk in compiled.stream(init, stream_mode=["tasks", "values"]):
        raw.append((mode, chunk))
        projection.consume(mode, chunk)

    starts = [c for m, c in raw if m == "tasks" and "input" in c]
    finishes = [c for m, c in raw if m == "tasks" and "result" in c]
    assert starts and {"id", "name", "input", "triggers"} <= starts[0].keys()
    assert finishes and {"id", "name", "error", "result"} <= finishes[0].keys()
    assert events == [
        (EventType.AGENT_STARTED, "market_analyst"), (EventType.AGENT_COMPLETED, "market_analyst"),
        (EventType.AGENT_STARTED, "bull_researcher"), (EventType.DEBATE_MESSAGE, "bull_researcher"),
        (EventType.AGENT_COMPLETED, "bull_researcher"),
    ]
    assert projection.final_state["market_report"] == "ok"
