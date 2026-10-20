"""Runtime settings. Secrets come from the environment / `.env` only and are never logged."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import find_dotenv, load_dotenv
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The pinned upstream engine this adapter was verified against.
TRADINGAGENTS_VERSION = "0.6.0"
TRADINGAGENTS_COMMIT = "1394a3f72aa4393e1a98f51b382434c4b4c2d972"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STOCK_OFFICE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    paper_only: bool = True
    data_dir: Path = Path("data")
    # "thread": the API process runs queued jobs on a background thread (dev default).
    # "external": the API only enqueues; `python -m stock_office.worker` executes.
    worker_mode: Literal["thread", "external"] = "thread"
    sse_poll_interval_s: float = 0.25
    # Browser origins allowed to call the API directly (the office UI streams SSE from it).
    cors_origins: str = "http://localhost:3000"

    # TradingAgents LLM settings (keys themselves are read by upstream from OPENAI_API_KEY etc.)
    ta_llm_provider: str = "openai"
    ta_deep_think_llm: str | None = None
    ta_quick_think_llm: str | None = None
    ta_analysts: str = "market,news,fundamentals"
    # Reports and debate text. Upstream keeps the machine-read "**Rating**:" line in English.
    ta_output_language: str = "Korean"
    # economy: dev/test default, trims low-risk levers only. standard: upstream defaults,
    # for acceptance and evaluation runs. Recorded in config_hash and model_version.
    ta_cost_profile: Literal["economy", "standard"] = "economy"
    # Polymarket answers HTTP 451 from Korea; when off, the tool reports "unavailable" at once
    # instead of making blocked requests.
    ta_prediction_markets: bool = False
    # Rounds of the bull/bear and the risk debates (upstream default 1; owner chose 2).
    ta_debate_rounds: int = 2

    # Daily automatic analysis (worker --schedule). Off unless explicitly enabled: it costs money.
    schedule_enabled: bool = False
    # Hard cap on real-engine runs (manual + scheduled) in any rolling 24 h.
    max_paid_runs_per_day: int = 8
    # Monthly LLM budget (Korea calendar month), a hard stop for every paid run. ≈ 10,000 KRW.
    monthly_budget_usd: Decimal = Decimal("7")

    # Paper book cost assumptions (shown as assumptions in ⚙ and on the portfolio screen).
    paper_kr_commission: Decimal = Decimal("0.00015")
    paper_kr_sell_tax: Decimal = Decimal("0.0020")
    paper_us_commission: Decimal = Decimal("0.001")
    paper_fx_spread: Decimal = Decimal("0.0025")
    paper_slippage: Decimal = Decimal("0.0005")

    # Phone notifications (Web Push to the installed web app). Keys come from
    # `python -m stock_office.notify keys` and live in the server .env only.
    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    # Contact for push services: "mailto:..." or a bare https origin (no path).
    vapid_subject: str = "https://stock-office.tail4755f0.ts.net"
    # Quiet hours, Korea time [start, end): notifications wait and arrive as one summary.
    notify_quiet_start: int = 23
    notify_quiet_end: int = 7

    dart_api_key: SecretStr | None = None
    # Official Naver Search API (Korean press headlines), read-only.
    naver_client_id: SecretStr | None = None
    naver_client_secret: SecretStr | None = None

    @field_validator("paper_only")
    @classmethod
    def _paper_only_is_mandatory(cls, value: bool) -> bool:
        if not value:
            raise ValueError("PAPER_ONLY cannot be disabled: Stock Office has no live-trading mode")
        return value


@lru_cache
def get_settings() -> Settings:
    # Export .env to os.environ (as upstream TradingAgents does on import) so provider keys and
    # TRADINGAGENTS_* overrides are visible before the engine is imported, e.g. for config_hash.
    load_dotenv(find_dotenv(usecwd=True), override=False)
    return Settings()
