# Stock Office — backend (Sprint 0)

FastAPI + background worker + `TradingAgentsAdapter`. **PAPER ONLY**: no broker, account or
order code exists; `STOCK_OFFICE_PAPER_ONLY=false` is rejected at startup.

## Requirements
- Python 3.11–3.13, [uv](https://docs.astral.sh/uv/) (verified: Python 3.13.7, uv 0.10.8, Windows 11)
- Optional: an LLM API key (for `engine=tradingagents`), an OpenDART key (KR disclosures)

## Setup
Everything is installed into the project virtualenv `backend/.venv`; nothing goes into the
system Python. Versions are locked in `uv.lock`.

```bash
cd backend
uv sync                              # core + dev tools
uv sync --extra engine --extra live  # + TradingAgents 0.6.0 @ 1394a3f, + yfinance
cp ../.env.example .env              # then fill keys; .env is git-ignored
```

## Run
```bash
# API (thread worker in-process, good for dev)
uv run uvicorn stock_office.api.app:app_factory --factory --port 8000

# API + separate worker process
STOCK_OFFICE_WORKER_MODE=external uv run uvicorn stock_office.api.app:app_factory --factory --port 8000
uv run python -m stock_office.worker            # or --once to drain the queue and exit

# Start a run and follow it
curl -XPOST localhost:8000/api/v1/analysis-runs -H 'content-type: application/json' \
     -d '{"instrument_id":"US:NASDAQ:NVDA","engine":"demo"}'
curl -N localhost:8000/api/v1/analysis-runs/<run_id>/events            # SSE (replay + live)
curl -N -H 'Last-Event-ID: 12' localhost:8000/api/v1/analysis-runs/<run_id>/events  # resume
curl localhost:8000/api/v1/analysis-runs/<run_id>/decision
```

`engine=demo` replays a **synthetic** trace over **synthetic** fixtures: every event and the
decision carry `demo: true` / `DEMO_NOT_ANALYSIS`. It is never an analysis result.
`engine=tradingagents` is the real path; without an LLM key the run ends
`FAILED / ENGINE_NOT_CONFIGURED` (by design, not faked).

## API (Sprint 0)
| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `paper_only`, `live_orders:false`, pinned engine version |
| GET | `/api/v1/instruments?q=&market=` | NVDA, 005930 only |
| POST | `/api/v1/analysis-runs` | `{instrument_id, as_of?, engine}` → 202 `{run_id, status:"QUEUED"}`; future `as_of` → 422 |
| GET | `/api/v1/analysis-runs[/{id}]` | run status, latency, snapshot ids, coverage gaps, token usage |
| GET | `/api/v1/analysis-runs/{id}/events` | SSE; `id:` = seq; resume via `Last-Event-ID` or `?after_seq=` |
| GET | `/api/v1/analysis-runs/{id}/outputs` | per-agent results |
| GET | `/api/v1/analysis-runs/{id}/decision` | proposal only (`execution:"PROPOSED_ONLY"`) |

Event types: `run.created`, `run.started`, `agent.started|completed|failed`, `debate.message`,
`decision.created`, `run.completed|failed`.

## Tests
```bash
uv run pytest                 # unit + contract + e2e, no network (contract needs --extra engine)
uv run pytest -m live -s      # network: Yahoo prices; DART / real LLM run if keys are set
uv run ruff check src tests && uv run mypy
```

| Folder | Scope |
|---|---|
| `tests/unit` | instruments, schemas, point-in-time, event store/SSE, projection, PAPER-ONLY guard |
| `tests/contract` | pinned TradingAgents: version, node names, rating contract, LangGraph stream shape |
| `tests/e2e` | HTTP API with DEMO engine: lifecycle, SSE resume, failure/missing data, look-ahead |
| `tests/live` | marked `live`, excluded by default |

## Layout
```
src/stock_office/
  config.py            settings (PAPER_ONLY enforced), pinned engine version
  domain/              Pydantic contracts, instrument ids (COUNTRY:EXCHANGE:SYMBOL)
  providers/           MarketDataProvider: fixture (DEMO), yahoo (read-only), dart (read-only)
  events/              JSONL store (monotonic seq, dedupe), sanitizer, SSE framing
  engine/              TradingAgentsAdapter projection, real engine, demo engine
  runs/                file repository (Sprint 0), run service (collect → PIT → engine → decision)
  api/app.py           FastAPI
  worker.py            background worker
```
