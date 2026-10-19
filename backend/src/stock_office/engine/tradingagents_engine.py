"""Real TradingAgents engine (optional `engine` extra). Requires an LLM provider API key.

Integration points used (v0.6.0): `TradingAgentsGraph.__init__`, `.create_run_state`,
`.propagator.get_graph_args`, `.graph.stream` (compiled LangGraph), `run_config_context`
(the same wrapper upstream `stream_run` uses), and `agents.rating.run_rating`.
`record_decision` is deliberately NOT called and the memory log is isolated per run, so
past-decision reflection (a self-adapting loop) stays disabled in the MVP.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from stock_office.config import TRADINGAGENTS_COMMIT, TRADINGAGENTS_VERSION, Settings
from stock_office.domain.models import Instrument, Market
from stock_office.engine.upstream import import_tradingagents
from stock_office.providers.dart import DartDisclosureProvider

from .adapter import (
    EngineContext,
    EngineNotConfiguredError,
    EngineOutcome,
    TradingAgentsProjection,
    outcome_from_state,
)
from .ta_extensions import (
    KR_NEWS_VENDOR,
    PREDICTION_OFF_VENDOR,
    collect_upstream_data_gaps,
    register_kr_news_vendor,
    register_prediction_markets_off,
)

_PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
}

# Upstream config overrides per cost profile. `economy` trims only levers with low expected
# quality impact on the analyst phase, where most tokens go. It deliberately leaves alone the
# deep model, reasoning effort (the 2 manager calls decide the outcome) and max_tokens (a cap
# can truncate a reasoning model's answer into an unparseable REVIEW). Token savings are
# measurable per run; quality equivalence is NOT established by single runs.
COST_PROFILES: dict[str, dict[str, Any]] = {
    "standard": {},
    "economy": {
        "max_tool_rounds": 6,             # upstream 20; a ceiling, rarely reached
        "news_article_limit": 10,         # upstream 20
        "global_news_article_limit": 5,   # upstream 10
    },
}

_UPSTREAM_ENV_PREFIX = "TRADINGAGENTS_"


def _upstream_env_overrides() -> dict[str, str]:
    """TRADINGAGENTS_* variables also change upstream config; they must be part of config_hash."""
    return {k: v for k, v in os.environ.items() if k.startswith(_UPSTREAM_ENV_PREFIX)}


class TradingAgentsEngine:
    name = "tradingagents"
    demo = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.analysts = tuple(a.strip() for a in settings.ta_analysts.split(",") if a.strip())

    def version(self) -> str:
        return f"tradingagents-{TRADINGAGENTS_VERSION}@{TRADINGAGENTS_COMMIT[:7]}"

    def _overrides(self) -> dict[str, Any]:
        overrides: dict[str, Any] = {
            "llm_provider": self.settings.ta_llm_provider,
            "output_language": self.settings.ta_output_language,
            "checkpoint_enabled": False,
            # Owner decision 2026-10-19: real back-and-forth (claim, rebuttal, counter-rebuttal)
            # in both debates instead of one statement each (upstream default 1).
            "max_debate_rounds": self.settings.ta_debate_rounds,
            "max_risk_discuss_rounds": self.settings.ta_debate_rounds,
        }
        if self.settings.ta_deep_think_llm:
            overrides["deep_think_llm"] = self.settings.ta_deep_think_llm
        if self.settings.ta_quick_think_llm:
            overrides["quick_think_llm"] = self.settings.ta_quick_think_llm
        overrides.update(COST_PROFILES[self.settings.ta_cost_profile])
        return overrides

    def config_hash(self) -> str:
        # Only a hash is stored, so env values (which may include endpoints) are never persisted.
        blob = json.dumps({"analysts": self.analysts, **self._overrides(),
                           "cost_profile": self.settings.ta_cost_profile,
                           "upstream_env": _upstream_env_overrides(),
                           "kr_news_vendor": KR_NEWS_VENDOR if self.kr_news_enabled else None,
                           "prediction_markets": self.settings.ta_prediction_markets,
                           "engine": self.version()}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def model_version(self) -> str:
        o = self._overrides()
        deep = o.get("deep_think_llm", "upstream-default")
        quick = o.get("quick_think_llm", "upstream-default")
        env = [k.removeprefix(_UPSTREAM_ENV_PREFIX) for k in sorted(_upstream_env_overrides())]
        env_note = f",env={'+'.join(env)}" if env else ""
        return (f"{self.version()}/{o['llm_provider']}:deep={deep},quick={quick}"
                f"/profile={self.settings.ta_cost_profile}{env_note}")

    def check_ready(self) -> None:
        try:
            import_tradingagents()
        except ImportError:
            raise EngineNotConfiguredError(
                "TradingAgents is not installed (uv sync --extra engine)"
            ) from None
        key_env = _PROVIDER_KEY_ENV.get(self.settings.ta_llm_provider)
        if key_env and not os.environ.get(key_env):
            raise EngineNotConfiguredError(f"{key_env} is not set for provider "
                                           f"{self.settings.ta_llm_provider!r}")

    @property
    def kr_news_enabled(self) -> bool:
        key = self.settings.dart_api_key
        return bool(key and key.get_secret_value().strip())

    def _dart_provider(self) -> DartDisclosureProvider:
        key = self.settings.dart_api_key
        return DartDisclosureProvider(api_key=key.get_secret_value() if key else None)

    def build_config(self, work_dir: Path, instrument: Instrument | None = None) -> dict[str, Any]:
        import_tradingagents()
        from tradingagents.default_config import build_default_config

        config: dict[str, Any] = build_default_config()
        config.update(self._overrides())
        if instrument is not None and instrument.market is Market.KR and self.kr_news_enabled:
            # Yahoo first; OpenDART disclosures when Yahoo has no company news for a KRX stock.
            config["tool_vendors"] = {**config.get("tool_vendors", {}),
                                      "get_news": f"yfinance,{KR_NEWS_VENDOR}"}
        if not self.settings.ta_prediction_markets:
            config["tool_vendors"] = {**config.get("tool_vendors", {}),
                                      "get_prediction_markets": PREDICTION_OFF_VENDOR}
        config["results_dir"] = str(work_dir / "ta_results")
        config["data_cache_dir"] = str(work_dir.parent.parent / "ta_cache")
        # Fresh, empty memory log per run: no reflection from earlier decisions leaks in.
        config["memory_log_path"] = str(work_dir / "ta_memory" / "trading_memory.md")
        return config

    def run(self, ctx: EngineContext) -> EngineOutcome:
        self.check_ready()
        from langchain_core.callbacks import UsageMetadataCallbackHandler
        from tradingagents.agents.rating import run_rating
        from tradingagents.dataflows.config import run_config_context
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        if self.kr_news_enabled:
            register_kr_news_vendor(self._dart_provider)
        if not self.settings.ta_prediction_markets:
            register_prediction_markets_off()
        usage = UsageMetadataCallbackHandler()
        graph = TradingAgentsGraph(
            selected_analysts=self.analysts,
            config=self.build_config(Path(ctx.work_dir), ctx.instrument),
            callbacks=[usage],
        )
        ticker = ctx.instrument.provider_symbols["yahoo"]
        init_state = graph.create_run_state(ticker, ctx.trade_date)
        args = graph.propagator.get_graph_args()
        args["stream_mode"] = ["tasks", "values"]
        args["subgraphs"] = True  # analysts' own graphs, for tool.called (names only)

        projection = TradingAgentsProjection(run_id=ctx.run_id, sink=ctx.sink)
        context = run_config_context(graph.config)
        with collect_upstream_data_gaps() as gaps:
            stream = context.run(graph.graph.stream, init_state, **args)
            try:
                while (step := context.run(next, stream, None)) is not None:
                    namespace, mode, chunk = step
                    projection.consume(mode, chunk, tuple(namespace))
            except BaseException as exc:
                projection.abort_open_tasks(f"run aborted: {type(exc).__name__}")
                raise
            finally:
                context.run(stream.close)

        # The engine fetches its own tool data. When its results were captured they are stored
        # with the run (tool_results.json); only if nothing was captured is the evidence partial.
        warnings = [] if projection.tool_results else [
            "ENGINE_DATA_NOT_SNAPSHOTTED: TradingAgents fetched its own tool data; "
            "only Stock Office provider snapshots are cited as evidence"]
        outcome = outcome_from_state(
            projection,
            run_rating(projection.final_state) if projection.final_state else None,
            warnings=warnings,
        )
        outcome.token_usage = {k: dict(v) for k, v in usage.usage_metadata.items()}
        outcome.coverage_gaps = list(gaps.gaps)
        return outcome
