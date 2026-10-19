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


@pytest.mark.parametrize("profile", ["economy", "standard"])
def test_cost_profile_keys_exist_upstream_and_graph_builds(
    profile: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tradingagents.default_config import build_default_config
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    from stock_office.engine.tradingagents_engine import COST_PROFILES

    upstream = build_default_config()
    assert set(COST_PROFILES[profile]) <= upstream.keys(), "profile key renamed upstream"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key-000000")
    engine = TradingAgentsEngine(
        Settings(data_dir=tmp_path, ta_cost_profile=profile, _env_file=None))  # type: ignore[call-arg]
    work = tmp_path / "runs" / "r1"
    work.mkdir(parents=True)
    config = engine.build_config(work)
    for key, value in COST_PROFILES[profile].items():
        assert config[key] == value
    TradingAgentsGraph(selected_analysts=engine.analysts, config=config)  # validates limits


def test_kr_news_vendor_routes_through_upstream(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """KR stocks: Yahoo first, then OpenDART disclosures; US stocks are unchanged."""
    from datetime import UTC, datetime

    from tradingagents.dataflows.config import run_config
    from tradingagents.dataflows.errors import VendorUnavailableError
    from tradingagents.dataflows.router import VENDOR_METHODS, route_to_vendor

    from stock_office.domain.instruments import get_instrument
    from stock_office.domain.models import MarketSnapshot
    from stock_office.engine.ta_extensions import KR_NEWS_VENDOR, register_kr_news_vendor
    from stock_office.providers.base import ProviderResult
    from stock_office.providers.dart import DartDisclosureProvider

    seen: list[tuple[str, str]] = []

    class StubDart(DartDisclosureProvider):
        def fetch_range(self, instrument, start, end):  # type: ignore[no-untyped-def]
            seen.append((start.isoformat(), end.isoformat()))
            snap = MarketSnapshot(
                id="dart-9", instrument_id=instrument.id, source="opendart", kind="disclosure",
                observed_at=datetime(2026, 10, 13, tzinfo=UTC),
                available_at=datetime(2026, 10, 13, 14, tzinfo=UTC),
                ingested_at=datetime(2026, 10, 16, tzinfo=UTC),
                payload={"rcept_no": "9", "report_nm": "분기보고서", "rcept_dt": "20261013"},
                payload_hash="h", source_url="https://dart.fss.or.kr/x")
            return ProviderResult(snapshots=[snap])

    def no_yahoo_news(*_: object) -> str:
        raise VendorUnavailableError("Yahoo Finance has no news articles tagged 005930.KS")

    monkeypatch.setitem(VENDOR_METHODS["get_news"], "yfinance", no_yahoo_news)
    register_kr_news_vendor(lambda: StubDart(api_key="k"))
    engine = TradingAgentsEngine(Settings(data_dir=tmp_path, dart_api_key="k",  # type: ignore[call-arg]
                                          _env_file=None))
    work = tmp_path / "runs" / "r1"
    work.mkdir(parents=True)
    kr = engine.build_config(work, get_instrument("KR:KRX:005930"))
    us = engine.build_config(work, get_instrument("US:NASDAQ:NVDA"))
    assert kr["tool_vendors"]["get_news"] == f"yfinance,{KR_NEWS_VENDOR}"
    assert "get_news" not in us.get("tool_vendors", {})
    with run_config(kr):
        text = route_to_vendor("get_news", "005930.KS", "2026-10-09", "2026-10-16")
    assert "OpenDART disclosures" in text and "분기보고서" in text
    assert seen == [("2026-10-09", "2026-10-16")]


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


def test_prediction_markets_off_answers_unavailable_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tradingagents.dataflows.config import run_config
    from tradingagents.dataflows.router import VENDOR_METHODS, route_to_vendor

    from stock_office.domain.instruments import get_instrument
    from stock_office.engine.ta_extensions import (
        PREDICTION_OFF_VENDOR,
        collect_upstream_data_gaps,
        register_prediction_markets_off,
    )

    def network_call(*_: object, **__: object) -> str:
        raise AssertionError("must not reach Polymarket")

    monkeypatch.setitem(VENDOR_METHODS["get_prediction_markets"], "polymarket", network_call)
    register_prediction_markets_off()
    engine = TradingAgentsEngine(Settings(data_dir=tmp_path, _env_file=None))  # type: ignore[call-arg]
    work = tmp_path / "runs" / "r1"
    work.mkdir(parents=True)
    config = engine.build_config(work, get_instrument("US:NASDAQ:NVDA"))
    assert config["tool_vendors"]["get_prediction_markets"] == PREDICTION_OFF_VENDOR
    with collect_upstream_data_gaps() as gaps, run_config(config):
        text = route_to_vendor("get_prediction_markets", "Fed rate cut", 6, None)
    assert "unavailable" in text.lower() or "DATA_UNAVAILABLE" in text
    # Switched off on purpose: the model is told "unavailable", and it is not a data gap.
    assert not any("451" in g or "prediction" in g.lower() for g in gaps.gaps)

    on = TradingAgentsEngine(Settings(data_dir=tmp_path, ta_prediction_markets=True,  # type: ignore[call-arg]
                                      _env_file=None))
    assert "get_prediction_markets" not in on.build_config(work).get("tool_vendors", {})
    assert on.config_hash() != engine.config_hash()


def test_subgraph_tool_stream_shape_feeds_tool_called() -> None:
    """With subgraphs=True the installed LangGraph tags analyst-internal tool tasks with the
    parent task id, and the tools task input carries the model's tool calls."""
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import ToolNode

    @tool
    def get_stock_data(symbol: str) -> str:
        """Stock data."""
        return "rows"

    # Functional form: the module's postponed annotations cannot see the local import.
    S = TypedDict("S", {"messages": Annotated[list[Any], add_messages], "market_report": str})  # noqa: UP013

    def agent(state: Any) -> dict[str, Any]:
        if len(state["messages"]) < 2:
            call = {"name": "get_stock_data", "args": {"symbol": "X"}, "id": "c1"}
            return {"messages": [AIMessage("", tool_calls=[call])]}
        return {"messages": [AIMessage("done")], "market_report": "ok"}

    sub = StateGraph(S)
    sub.add_node("agent", agent)
    sub.add_node("tools", ToolNode([get_stock_data]))
    sub.add_edge(START, "agent")
    sub.add_conditional_edges("agent", lambda s: "tools" if s["messages"][-1].tool_calls else END,
                              ["tools", END])
    sub.add_edge("tools", "agent")
    top = StateGraph(S)
    top.add_node("Market Analyst", sub.compile())
    top.add_edge(START, "Market Analyst")
    top.add_edge("Market Analyst", END)

    events: list[tuple[EventType, str | None, dict[str, Any] | None]] = []
    projection = TradingAgentsProjection(
        "r", lambda t, *, agent_id=None, payload=None, dedupe_key=None:
        events.append((t, agent_id, payload)))
    for namespace, mode, chunk in top.compile().stream(
            {"messages": [], "market_report": ""}, stream_mode=["tasks", "values"],
            subgraphs=True):
        projection.consume(mode, chunk, tuple(namespace))

    assert [(t, a) for t, a, _ in events] == [
        (EventType.AGENT_STARTED, "market_analyst"), (EventType.TOOL_CALLED, "market_analyst"),
        (EventType.AGENT_COMPLETED, "market_analyst")]
    assert events[1][2] == {"role": "Market Analyst", "turn": 1, "round": 1,
                            "tools": ["get_stock_data"]}
    assert projection.final_state["market_report"] == "ok"
    # The ToolNode's result messages are captured as evidence, with the tool's name.
    captured = [(r["tool"], r["content"]) for r in projection.tool_results]
    assert captured == [("get_stock_data", "rows")]


def test_upstream_analysts_run_tools_in_their_own_graph(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """tool.called relies on each analyst being a subgraph with a node named `tools`."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key-000000")  # client init only
    settings = Settings(data_dir=tmp_path, _env_file=None)  # type: ignore[call-arg]
    work = tmp_path / "runs" / "r1"
    work.mkdir(parents=True)
    graph = TradingAgentsGraph(selected_analysts=("market", "news", "fundamentals"),
                               config=TradingAgentsEngine(settings).build_config(work))
    nodes = set(graph.graph.get_graph(xray=1).nodes)
    for analyst in ("Market Analyst", "News Analyst", "Fundamentals Analyst"):
        assert f"{analyst}:tools" in nodes, sorted(nodes)
