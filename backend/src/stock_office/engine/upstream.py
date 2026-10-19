"""Import the pinned TradingAgents package without its import-time `.env` loading.

Upstream `tradingagents/__init__.py` runs `load_dotenv(find_dotenv(usecwd=True))`, which copies
keys from `backend/.env` into `os.environ` whenever the package is first imported. That bypasses
Stock Office's settings: a test that removed `OPENAI_API_KEY` on purpose got it back and made a
real, paid LLM call. `get_settings()` is the only place that exports `.env`; this keeps it so.
"""

from __future__ import annotations

import importlib
import sys
import threading
from types import ModuleType

_lock = threading.Lock()


def import_tradingagents() -> ModuleType:
    """Import (once) and return `tradingagents`; raises ImportError when it is not installed."""
    with _lock:
        module = sys.modules.get("tradingagents")
        if module is not None:
            return module
        import dotenv

        original = dotenv.load_dotenv

        def skip_dotenv(*_args: object, **_kwargs: object) -> bool:
            return False

        setattr(dotenv, "load_dotenv", skip_dotenv)  # noqa: B010 (temporary, restored below)
        try:
            imported: ModuleType = importlib.import_module("tradingagents")
        finally:
            dotenv.load_dotenv = original
        return imported
