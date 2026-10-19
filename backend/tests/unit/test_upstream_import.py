"""Importing TradingAgents must never pull keys from a `.env` into os.environ."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("tradingagents")

_PROBE = """
import os
from stock_office.config import Settings
from stock_office.engine.tradingagents_engine import TradingAgentsEngine
from stock_office.engine.adapter import EngineNotConfiguredError
engine = TradingAgentsEngine(Settings(_env_file=None))
try:
    engine.check_ready()
    print("READY")
except EngineNotConfiguredError:
    print("NOT_CONFIGURED")
print("KEY_IN_ENV" if os.environ.get("OPENAI_API_KEY") else "NO_KEY_IN_ENV")
"""


def test_engine_import_does_not_load_dotenv_keys(tmp_path: Path) -> None:
    # A fresh interpreter (the package is already imported in this one), started in a folder
    # whose .env holds a key: the upstream package would load it on import.
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-from-dotenv-should-not-load-0000\n",
                                   encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).resolve().parents[2] / "src"), env.get("PYTHONPATH", "")])
    out = subprocess.run([sys.executable, "-c", _PROBE], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=120, check=True).stdout
    assert out.split() == ["NOT_CONFIGURED", "NO_KEY_IN_ENV"], out
