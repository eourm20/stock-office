from pathlib import Path

import pytest
from pydantic import ValidationError

from stock_office.config import Settings
from stock_office.engine.tradingagents_engine import COST_PROFILES, TradingAgentsEngine


def _engine(tmp_path: Path, **kw: object) -> TradingAgentsEngine:
    return TradingAgentsEngine(Settings(data_dir=tmp_path, _env_file=None, **kw))  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _clean_upstream_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for key in [k for k in os.environ if k.startswith("TRADINGAGENTS_")]:
        monkeypatch.delenv(key)


def test_economy_is_the_default(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    assert engine.settings.ta_cost_profile == "economy"
    assert engine.model_version().endswith("/profile=economy")


def test_economy_trims_only_low_risk_levers() -> None:
    assert set(COST_PROFILES["economy"]) == {
        "max_tool_rounds", "news_article_limit", "global_news_article_limit"}
    assert COST_PROFILES["standard"] == {}
    # Upstream requires 2 * max_tool_rounds + 2 < max_recur_limit (default 100).
    assert 2 * COST_PROFILES["economy"]["max_tool_rounds"] + 2 < 100


def test_profiles_change_config_hash_and_model_version(tmp_path: Path) -> None:
    economy, standard = _engine(tmp_path), _engine(tmp_path, ta_cost_profile="standard")
    assert economy.config_hash() != standard.config_hash()
    assert standard.model_version().endswith("/profile=standard")
    assert economy._overrides()["max_tool_rounds"] == 6
    assert "max_tool_rounds" not in standard._overrides()


def test_unknown_profile_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _engine(tmp_path, ta_cost_profile="free")


def test_upstream_env_overrides_are_recorded(tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path)
    before = engine.config_hash()
    monkeypatch.setenv("TRADINGAGENTS_OPENAI_REASONING_EFFORT", "low")
    assert engine.config_hash() != before  # a silent env tweak cannot reuse the same hash
    assert engine.model_version().endswith(",env=OPENAI_REASONING_EFFORT")
    assert "low" not in engine.model_version()  # names only, values are not published
