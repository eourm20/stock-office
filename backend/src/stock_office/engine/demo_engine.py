"""DEMO engine: a scripted, LangGraph-shaped trace fed through the *real* projection.

Purpose: exercise event ordering, storage, replay and SSE without API keys. Every run it
produces is flagged `demo=true`; its output is synthetic and is never an analysis result.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

from .adapter import EngineContext, EngineOutcome, TradingAgentsProjection, outcome_from_state

DEMO_PREFIX = "DEMO (합성 데이터, 실제 분석 아님): "
# Scripted tool rounds inside the analysts' own graphs (names only, like the real engine).
DEMO_TOOL_ROUNDS = {
    "Market Analyst": [["get_stock_data", "get_indicators"], ["get_verified_market_snapshot"]],
    "News Analyst": [["get_news", "get_global_news"]],
    "Fundamentals Analyst": [["get_fundamentals"], ["get_income_statement", "get_balance_sheet"]],
}
Chunk = tuple[tuple[str, ...], str, Any]


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

    def _trace(self, ctx: EngineContext) -> Iterator[Chunk]:
        sym = ctx.instrument.id
        state: dict[str, Any] = {"company_of_interest": sym, "trade_date": ctx.trade_date}
        analysts = [("Market Analyst", "market_report"), ("News Analyst", "news_report"),
                    ("Fundamentals Analyst", "fundamentals_report"), ("Memory Log", "memory_note")]
        # Parallel analyst phase: all start, then finish.
        for i, (node, _) in enumerate(analysts):
            yield (), "tasks", {"id": f"a{i}", "name": node, "input": {}, "triggers": ["__start__"]}
        for i, (node, _) in enumerate(analysts):
            ns = (f"{node}:a{i}",)
            for r, tools in enumerate(DEMO_TOOL_ROUNDS.get(node, [])):
                message = SimpleNamespace(tool_calls=[{"name": t, "args": {}} for t in tools])
                yield ns, "tasks", {"id": f"a{i}-tools{r}", "name": "tools",
                                    "input": {"messages": [message]}, "triggers": []}
                results = [SimpleNamespace(name=t, content=f"{DEMO_PREFIX}{t} 결과 (합성 데이터)")
                           for t in tools]
                yield ns, "tasks", {"id": f"a{i}-tools{r}", "name": "tools", "error": None,
                                    "result": {"messages": results}, "interrupts": []}
        for i, (node, key) in enumerate(analysts):
            if node == self.fail_at:
                yield (), "tasks", {"id": f"a{i}", "name": node,
                                    "error": DemoEngineFailure("injected"),
                                    "result": None, "interrupts": []}
                raise DemoEngineFailure(f"injected failure at {node}")
            text = f"{DEMO_PREFIX}{node} 보고서 — {sym}, 스냅샷 {len(ctx.snapshots)}건 사용."
            state[key] = text
            yield (), "tasks", {"id": f"a{i}", "name": node, "error": None,
                            "result": {key: text}, "interrupts": []}
        yield (), "values", dict(state)

        sequence = [
            ("Bull Researcher", "investment",
             "Bull Analyst: " + DEMO_PREFIX + "상승 근거를 제시합니다."),
            ("Bear Researcher", "investment",
             "Bear Analyst: " + DEMO_PREFIX + "하방 위험을 반박합니다."),
            ("Research Manager", None, DEMO_PREFIX + "투자 계획 정리. Rating: Hold"),
            ("Trader", None, DEMO_PREFIX + "트레이더 거래 제안."),
            ("Aggressive Analyst", "aggressive", DEMO_PREFIX + "공격적 관점."),
            ("Conservative Analyst", "conservative", DEMO_PREFIX + "보수적 관점."),
            ("Neutral Analyst", "neutral", DEMO_PREFIX + "중립적 관점."),
        ]
        invest: dict[str, str] = {"bull_history": "", "bear_history": "", "current_response": ""}
        risk: dict[str, str] = {"conservative_history": ""}
        for i, (node, kind, text) in enumerate(sequence):
            yield (), "tasks", {"id": f"s{i}", "name": node, "input": {}, "triggers": []}
            if node == self.fail_at:
                yield (), "tasks", {"id": f"s{i}", "name": node,
                                    "error": DemoEngineFailure("injected"),
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
            yield (), "tasks", {"id": f"s{i}", "name": node, "error": None, "result": result,
                            "interrupts": []}

        final = (f"{DEMO_PREFIX}최종 결정. Rating: {self.rating}" if self.rating
                 else f"{DEMO_PREFIX}등급 표기가 없는 최종 결정.")
        yield (), "tasks", {"id": "pm", "name": "Portfolio Manager", "input": {}, "triggers": []}
        state["final_trade_decision"] = final
        yield (), "tasks", {"id": "pm", "name": "Portfolio Manager", "error": None,
                        "result": {"final_trade_decision": final}, "interrupts": []}
        yield (), "values", dict(state)

    def run(self, ctx: EngineContext) -> EngineOutcome:
        projection = TradingAgentsProjection(run_id=ctx.run_id, sink=ctx.sink)
        try:
            for namespace, mode, chunk in self._trace(ctx):
                projection.consume(mode, chunk, namespace)
        except BaseException as exc:
            projection.abort_open_tasks(f"run aborted: {type(exc).__name__}")
            raise
        return outcome_from_state(projection, self.rating)
