# Sprint 0 Report — Technical Validation / First Vertical Slice

**Date:** 2026-10-16 · **Status:** Implementation complete; **acceptance gate NOT yet passed**
(real LLM analysis blocked: no API key in this environment).

Legend: ✅ verified by executed test/command · ⚠️ implemented, unverified live · ❌ blocked / not done

## 1. Sprint 0 gate (IMPLEMENTATION_PLAN §9)
| Criterion | Status | Evidence |
|---|---|---|
| US 1 instrument real analysis (NVDA) | ❌ blocked | No `OPENAI_API_KEY`. Real path implemented; without a key the run ends `FAILED/ENGINE_NOT_CONFIGURED` (smoke test §4.6). `tests/live::test_real_tradingagents_run` skipped. |
| KR 1 instrument real analysis (005930) | ❌ blocked | Same LLM blocker. KR price data path verified live (§4.5); DART unverified (no key). |
| Agent event order, storage, replay | ✅ | e2e + unit tests; real server + separate worker smoke test (§4.6) |
| No account/order integration | ✅ | `tests/unit/test_no_live_orders.py`; `/health` → `live_orders:false` |

DEMO runs passed end-to-end, but they replay **synthetic** traces over **synthetic** fixtures and
are **not** analysis results.

## 2. Environment verified before implementation
| Item | Found |
|---|---|
| Repo state | 5 planning files only (CLAUDE.md, IMPLEMENTATION_PLAN.md, CODING_AI_PROMPT.md, PROJECT_PLAN.html, README.md); not a git repo |
| Toolchain | Python 3.13.7, uv 0.10.8, Node 22.19.0, npm 10.9.3, git 2.47.1 |
| Not available | Docker, PostgreSQL (`psql`), pnpm |
| API keys in env | none (LLM, DART, market data) |
| Isolation | Python deps only in `backend/.venv` (uv); Node deps only in `frontend/node_modules` |

## 3. TradingAgents verification (upstream clone in a scratch dir, never vendored)
- Release **v0.6.0** (2026-10-03), commit `1394a3f72aa4393e1a98f51b382434c4b4c2d972`,
  **Apache-2.0**, `requires-python >=3.11`; installs on Python 3.13 (langgraph 1.2.15,
  langchain-core 1.6.11, pandas 3.0.6, yfinance 1.7.0).
- Pinned in `backend/pyproject.toml` (`engine` extra) as a git URL at that commit; locked in `uv.lock`.
- Integration points used: `TradingAgentsGraph(selected_analysts, config, callbacks)`,
  `.create_run_state`, `.propagator.get_graph_args`, compiled `.graph.stream(stream_mode=["tasks","values"])`
  inside `dataflows.config.run_config_context` (the same wrapper upstream `stream_run` uses),
  `agents.rating.run_rating`. Upstream code is not patched.
- Why not `stream_run`: it collapses task *start* signals, which the UI needs for
  `agent.started`. Contract tests guard the lower-level usage.
- Graph nodes (verified by contract test against the installed package): Market/Sentiment/News/
  Fundamentals Analyst, Memory Log, Bull/Bear Researcher, Research Manager, Trader,
  Aggressive/Conservative/Neutral Analyst, Portfolio Manager.
- Ratings: Buy/Overweight/Hold/Underweight/Sell or `REVIEW` (unparseable). Mapping:
  Buy|Overweight→BUY, Hold→HOLD, Underweight|Sell→SELL, anything else→REVIEW (never HOLD).
- **Disabled on purpose:** `record_decision` is not called and the memory log is a fresh,
  per-run file, so upstream reflection on past decisions (a self-adapting loop) is off in the MVP.
- **Known limitation:** TradingAgents fetches its own tool data (Yahoo/SEC/etc.). Those calls are
  not captured as Stock Office snapshots; decisions from the real engine carry
  `ENGINE_DATA_NOT_SNAPSHOTTED`, and only Stock Office provider snapshots are cited as evidence.

## 4. Step-by-step test log (commands run from `backend/` unless noted)
### 4.1 Core env + domain import
`uv sync` → OK. Domain smoke: NVDA → USD/America/New_York/`NVDA`; 005930 → KRW/Asia/Seoul/`005930.KS`, DART corp `00126380`.
### 4.2 Unit tests (first pass)
`uv run pytest tests/unit -q` → **30 passed**.
Found while writing tests: appending after an interrupted (unterminated) JSONL line would corrupt
the log → fixed (`EventStore._drop_unterminated_tail`) and covered by a test.
### 4.3 Full deterministic suite + mutation sanity check
`uv run pytest -q` → **65 passed**. Two deliberate defects were injected, then reverted:
PIT guard disabled → 2 failures; unknown rating → HOLD → 2 failures. Restored → 65 passed.
Also fixed: an SSE close race (stream now ends on the terminal *event*, not on run status) and
resuming after the terminal event (closes immediately instead of idling).
### 4.4 Static checks + engine contract
`uv run ruff check src tests` → clean · `uv run mypy` (strict) → no issues in 25 files.
`uv sync --extra engine --extra live` then `uv run pytest tests/contract -q` → **5 passed** (37.8 s, mostly import time).
### 4.5 Live, read-only (`uv run pytest -m live tests/live -s -rs`) → 2 passed, 3 skipped
| Check | Result |
|---|---|
| Yahoo NVDA daily bars | 10 bars allowed, 0 excluded; latest 2026-10-15 |
| Yahoo 005930.KS daily bars | 8 allowed, **1 excluded by the point-in-time guard** (today's bar before KST close + 30 min) |
| OpenDART list.json | skipped — no key (parser unit-tested against documented shape only) |
| Real TradingAgents run NVDA / 005930 | skipped — no LLM key |
Raw provider responses are kept only in git-ignored `data/`.
### 4.6 Real server smoke (uvicorn + separate worker process)
`STOCK_OFFICE_WORKER_MODE=external uvicorn …` then `python -m stock_office.worker --once`:
- `/health` → `paper_only:true, live_orders:false`, pinned commit reported.
- SSE client connected **before** the worker ran; received **35 events** in seq order and closed on `run.completed`.
- `Last-Event-ID: 20` → resumed at seq 21.
- 005930 demo decision: `HOLD`, flags `COVERAGE_GAP, DEMO_NOT_ANALYSIS`, `PROPOSED_ONLY`.
- NVDA `engine=tradingagents` → `FAILED / ENGINE_NOT_CONFIGURED` ("OPENAI_API_KEY is not set"), 18 ms.
### 4.7 Frontend (from `frontend/`)
`npm run typecheck` OK · `npm test` → **3 passed** · `npm run build` OK (222.7 kB JS).
### 4.8 Final
`uv run pytest -q` → **70 passed, 5 deselected (live)**; ruff clean; mypy strict clean.

## 5. Measurements (actual vs. not measured)
| Metric | Value | Note |
|---|---|---|
| LLM cost / tokens per run | **not measured** | needs a key; `token_usage` is recorded via LangChain `UsageMetadataCallbackHandler` when a real run happens |
| Real analysis latency | **not measured** | — |
| DEMO run latency (005930, 35 events) | 810 ms | synthetic; dominated by file I/O (event store re-reads the log per append); not a performance claim |
| Deterministic suite | ~11 s | Windows 11, local |

## 6. Deviations from the plan (and why)
- **No PostgreSQL in Sprint 0**: not installed and the gate only requires JSON/JSONL storage.
  File repository mirrors the plan's tables (`run.json`, `events.jsonl`, `decision.json`,
  `outputs.json`, `snapshots/`). Migrate in Sprint 1.
- **KR data**: Yahoo `.KS` prices (read-only, unofficial) + OpenDART disclosures. KIS / legacy
  Kiwoom read-only providers were not built; legacy repos were not consulted or modified.
- **Frontend**: Sprint 0 dev console only (event-derived agent status). React Flow/Motion/ECharts are Sprint 2.
- `IMPLEMENTATION_PLAN.md` names the env template `env.example`; the repo uses `.env.example`.

## 7. Risks / open issues
1. Real-engine event contract is verified on node names and a LangGraph stream sample, **not** on a full real run.
2. Yahoo via yfinance is unofficial and unlicensed for redistribution; replace or license before any sharing.
3. TradingAgents' own tool data isn't snapshotted → evidence ↔ claim linkage is weak (§3).
4. OpenDART integration unverified live; `rcept_dt` gives only a date, so availability is conservatively set to end-of-day KST.
5. Event store is O(n²) per run (re-reads on append) and single-writer per run; fine for ~10² events, replace with PostgreSQL.
6. Starlette `TestClient` deprecation warning (`httpx` → `httpx2`) in the test env; harmless for now.

## 8. Next priorities
1. Provide `OPENAI_API_KEY` (or Anthropic/Google + `STOCK_OFFICE_TA_LLM_PROVIDER`) → run `pytest -m live` for NVDA and 005930; record latency/tokens/cost here.
2. Provide `STOCK_OFFICE_DART_API_KEY` → verify OpenDART live.
3. Capture TradingAgents tool calls as snapshots (wrap the data vendor router) for grounded evidence.
4. Sprint 1: PostgreSQL schema + migrations, queue, 3 instruments per market.

## 9. Addendum — cost profile & paid-test guard (2026-10-16)
- `STOCK_OFFICE_TA_COST_PROFILE`: `economy` (default) overrides upstream `max_tool_rounds` 20→6, `news_article_limit` 20→10 and `global_news_article_limit` 10→5. `standard` leaves upstream defaults unchanged. The profile and any `TRADINGAGENTS_*` env overrides feed `config_hash`; `model_version` names the profile and the overridden env keys (values are not published).
- Not changed in economy, on purpose: the deep model and reasoning effort (only 2 manager calls, and they decide the outcome) and `max_tokens` (a cap can truncate reasoning-model output into `REVIEW`).
- Real-LLM live tests now need `STOCK_OFFICE_ALLOW_PAID_TESTS=1` in addition to the key.
- Tests: `uv run pytest -q` → **77 passed**, 5 deselected (live) (+5 unit `test_cost_profile.py`, +2 contract: profile keys exist upstream and the graph builds under both profiles). ruff clean, mypy strict clean. Free live run: 2 passed, 3 skipped.
- Token savings are **not measured yet** (no LLM key). Plan: one `economy` and one `standard` run of the same instrument and date, recording tokens only.
