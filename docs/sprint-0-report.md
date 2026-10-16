# Sprint 0 Report — Technical Validation / First Vertical Slice

**Date:** 2026-10-16 · **Status:** **Acceptance gate passed** for NVDA and 005930 (economy profile; see §10–11).
The original status line "gate NOT yet passed (no API key)" applied before the keys were added.

Legend: ✅ verified by executed test/command · ⚠️ implemented, unverified live · ❌ blocked / not done

## 1. Sprint 0 gate (IMPLEMENTATION_PLAN §9)
| Criterion | Status | Evidence |
|---|---|---|
| US 1 instrument real analysis (NVDA) | ✅ (economy profile) | Real run `641430f80ae149b9` COMPLETED in 163 s, 35 ordered events, 13 agents, 0 failed (§10). |
| KR 1 instrument real analysis (005930) | ✅ (economy profile) | Real run `0950497c54eb44b7` COMPLETED in 139 s, 35 events, 0 failed (§11). Caveat: no company news reached the News Analyst in that run; fixed afterwards (§11). |
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

## 10. First real runs and live verification (2026-10-16)
### Key checks (free)
- OpenAI key valid: `GET /v1/models` → 200, `gpt-6-sol` and `gpt-6-luna` listed. No tokens spent.
- **OpenDART verified live:** 005930 returned 15 disclosures over the last 30 days, all point-in-time allowed, Korean titles intact (UTF-8).
- Yahoo: NVDA 10 daily bars, 005930 9 daily bars.

### NVDA real analysis — run `641430f80ae149b9` (engine TradingAgents 0.6.0@1394a3f, profile `economy`)
| Item | Value |
|---|---|
| Status | COMPLETED; 13 agents started/completed, 0 failed; 5 debate messages; 35 events in seq order |
| Latency | 162.8 s total. Analysts run in parallel (~33–43 s); Research Manager → PM ≈ 2 min |
| Evidence | 22 Stock Office snapshots (Yahoo daily bars) |
| Decision | **BUY** (engine rating *Overweight*), `PROPOSED_ONLY`. Flags `ENGINE_DATA_NOT_SNAPSHOTTED`, `COVERAGE_GAP`* |
| Tokens, gpt-6-luna | input 81,422 (15,674 cached), output 15,797 (5,170 reasoning) |
| Tokens, gpt-6-sol | input 6,503, output 1,092 (344 reasoning) |
| **Cost (computed)** | luna ≈ $0.0146 + sol ≈ $0.0239 = **≈ $0.04 per run** |

Prices used, per 1M tokens: Sol $2 in / $10 out; Luna $0.10 in / $0.01 cached / $0.50 out. These come from secondary sources (2026-10) and have not been checked against OpenAI's pricing page.
The measurement is **~6–25× below the earlier pre-run estimate ($0.25–1)**: the deep model received only ~6.5K input tokens. At this rate, 2 instruments daily (~44 runs/month) ≈ $1.7/month. This is one sample; the next runs will confirm it.

This BUY/Overweight is a single, unevaluated model proposal. It is not a performance result or a signal, and nothing was executed.

\* The `COVERAGE_GAP` flag came from OpenDART "not covering" a US stock. That is not applicable, not a gap. **Fixed:** providers that do not apply to an instrument no longer count as gaps (new e2e test). Re-runs will not carry this flag.

### Coverage gaps observed inside the engine
- Polymarket (prediction markets, a News Analyst tool) returned **HTTP 451 (unavailable for legal reasons)** from this network, 3 queries. Upstream continued without it. These failures are not yet surfaced as events (TODO: route upstream tool failures into `coverage_gaps`).
- FRED key present; whether it was used in this run is not yet captured (same TODO).

### Viewing a run
`?run=<run_id>` in the dev console (`http://localhost:5173/?run=641430f80ae149b9`) replays any stored run, including debate text.

Tests after these changes: backend **78 passed** (+1 e2e), frontend 3 passed; ruff and mypy strict clean.

## 11. 005930 real run, issues found, fixes (2026-10-16)
### Run `0950497c54eb44b7` (KR:KRX:005930, profile `economy`)
| Item | Value |
|---|---|
| Status | COMPLETED; 13 agents started/completed, 0 failed; 5 debate messages; 35 ordered events |
| Latency | 139.2 s |
| Evidence | 34 snapshots: 19 Yahoo daily bars + 15 OpenDART disclosures |
| Decision | **SELL** (engine rating *Underweight*), `PROPOSED_ONLY`, flag `ENGINE_DATA_NOT_SNAPSHOTTED` |
| Tokens | luna in 105,177 (37,116 cached) / out 13,789; sol in 6,383 / out 979 |
| Cost (computed, same prices as §10) | luna ≈ $0.0141 + sol ≈ $0.0226 = **≈ $0.037** |

This is one model proposal, not a signal or a performance result. Nothing was executed.

An additional real run, `2f44b9a3dfe047f2` (005930), was started from the dev console at 07:26:01Z and completed (cost of the same order). One click was enough to start it; see issue 4.

### Issues found and fixed
| # | Issue | Fix | Verification |
|---|---|---|---|
| 1 | **Secret in logs:** httpx INFO logs every request URL, and OpenDART takes its key as a query parameter, so the worker log contained `crtfc_key=<key>`. Event payloads were already sanitized, but process logs were not. | New `logging_setup.install_log_redaction()` (worker and API): HTTP client loggers set to WARNING, plus a redaction filter on every handler. The affected local log file was deleted; no key in `backend/data`. | `tests/unit/test_log_redaction.py`; live check printed no request URLs |
| 2 | **No KR company news:** Yahoo has no news for `005930.KS`, so the News Analyst analysed without company news. Upstream only logged a warning. | Runtime-registered upstream vendor `stockoffice_dart`. For KR stocks the news chain is `yfinance,stockoffice_dart`: OpenDART disclosures for the same window, labelled as filings, not press news. Upstream files unchanged; the window is still clamped to the trade date. | contract test (routing via upstream `route_to_vendor`); live, no LLM: 3 disclosures returned for 2026-10-09..16 |
| 3 | **Engine-internal data failures invisible** (Polymarket HTTP 451, Yahoo "no news") | `collect_upstream_data_gaps()` records upstream WARNING logs during a run (redacted, deduplicated, ≤10) into `run.coverage_gaps` → `COVERAGE_GAP` flag | unit + e2e tests |
| 4 | One click in the dev console started a paid run | Confirmation dialog with a cost note for `engine=tradingagents` | frontend typecheck/build |

**Action recommended:** the OpenDART key appeared in a local log and in the development session transcript. Re-issue it at opendart.fss.or.kr (free) and update `backend/.env`.

Tests: backend **85 passed**, 5 deselected (live); ruff and mypy strict clean; frontend 3 passed and builds. The KR news fix is not yet exercised in a full LLM run.
