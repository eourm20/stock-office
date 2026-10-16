"""DEMO engine: a scripted, LangGraph-shaped trace fed through the *real* projection.

Purpose: exercise event ordering, storage, replay and SSE without API keys. Every run it
produces is flagged `demo=true`; its output is synthetic and is never an analysis result.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .adapter import EngineContext, EngineOutcome, TradingAgentsProjection, outcome_from_state

DEMO_PREFIX = "DEMO (synthetic, not analysis): "


class DemoEngineFailure(RuntimeError):
    pass


class DemoEngine:
    name = "demo"
    demo = True

    def __init__(self, rating: str | None = "Hold", fail_at: str | None = None) -> None:
        self.rating = rating
        self.fail_at = fail_at

    def version(self) -> str:
        return "demo-trace-1"

    def config_hash(self) -> str:
        return f"demo-{self.rating}-{self.fail_at}"

    def model_version(self) -> str:
        return "demo-fixture (no model called)"

    def check_ready(self) -> None:
        return None

    def _trace(self, ctx: EngineContext) -> Iterator[tuple[str, Any]]:
        sym = ctx.instrument.id
        state: dict[str, Any] = {"company_of_interest": sym, "trade_date": ctx.trade_date}
        analysts = [("Market Analyst", "market_report"), ("News Analyst", "news_report"),
                    ("Fundamentals Analyst", "fundamentals_report"), ("Memory Log", "memory_note")]
        # Parallel analyst phase: all start, then finish.
        for i, (node, _) in enumerate(analysts):
            yield "tasks", {"id": f"a{i}", "name": node, "input": {}, "triggers": ["__start__"]}
        for i, (node, key) in enumerate(analysts):
            if node == self.fail_at:
                yield "tasks", {"id": f"a{i}", "name": node, "error": DemoEngineFailure("injected"),
                                "result": None, "interrupts": []}
                raise DemoEngineFailure(f"injected failure at {node}")
            text = f"{DEMO_PREFIX}{node} report for {sym} using {len(ctx.snapshots)} snapshots."
            state[key] = text
            yield "tasks", {"id": f"a{i}", "name": node, "error": None,
                            "result": {key: text}, "interrupts": []}
        yield "values", dict(state)

        sequence = [
            ("Bull Researcher", "investment", "Bull Analyst: " + DEMO_PREFIX + "upside case."),
            ("Bear Researcher", "investment", "Bear Analyst: " + DEMO_PREFIX + "downside case."),
            ("Research Manager", None, DEMO_PREFIX + "investment plan. Rating: Hold"),
            ("Trader", None, DEMO_PREFIX + "trader proposal."),
            ("Aggressive Analyst", "aggressive", DEMO_PREFIX + "aggressive view."),
            ("Conservative Analyst", "conservative", DEMO_PREFIX + "conservative view."),
            ("Neutral Analyst", "neutral", DEMO_PREFIX + "neutral view."),
        ]
        invest: dict[str, str] = {"bull_history": "", "bear_history": "", "current_response": ""}
        risk: dict[str, str] = {"conservative_history": ""}
        for i, (node, kind, text) in enumerate(sequence):
            yield "tasks", {"id": f"s{i}", "name": node, "input": {}, "triggers": []}
            if node == self.fail_at:
                yield "tasks", {"id": f"s{i}", "name": node, "error": DemoEngineFailure("injected"),
                                "result": None, "interrupts": []}
                raise DemoEngineFailure(f"injected failure at {node}")
            result: dict[str, Any]
            if kind == "investment":
                invest["current_response"] = text
                invest["bull_history" if node.startswith("Bull") else "bear_history"] += text
                result = {"investment_debate_state": dict(invest)}
            elif kind in ("aggressive", "conservative", "neutral"):
                risk[f"current_{kind}_response"] = text
                if kind == "conservative":
                    risk["conservative_history"] += text
                result = {"risk_debate_state": dict(risk)}
            elif node == "Research Manager":
                result = {"investment_plan": text}
            else:
                result = {"trader_investment_plan": text}
            state.update(result)
            yield "tasks", {"id": f"s{i}", "name": node, "error": None, "result": result,
                            "interrupts": []}

        final = (f"{DEMO_PREFIX}final decision. Rating: {self.rating}" if self.rating
                 else f"{DEMO_PREFIX}final decision without a rating label.")
        yield "tasks", {"id": "pm", "name": "Portfolio Manager", "input": {}, "triggers": []}
        state["final_trade_decision"] = final
        yield "tasks", {"id": "pm", "name": "Portfolio Manager", "error": None,
                        "result": {"final_trade_decision": final}, "interrupts": []}
        yield "values", dict(state)

    def run(self, ctx: EngineContext) -> EngineOutcome:
        projection = TradingAgentsProjection(run_id=ctx.run_id, sink=ctx.sink)
        try:
            for mode, chunk in self._trace(ctx):
                projection.consume(mode, chunk)
        except BaseException as exc:
            projection.abort_open_tasks(f"run aborted: {type(exc).__name__}")
            raise
        return outcome_from_state(projection, self.rating)
