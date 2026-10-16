# Stock Office

A personal AI investment-office simulator for US and Korean equities. An AI investment committee built on
[TradingAgents](https://github.com/TauricResearch/TradingAgents) analyzes a stock. Its **real**
multi-agent activity is stored as ordered events and replayed live. Decisions are evaluated only
through risk-gated **paper trading**.

> **PAPER ONLY.** There is no broker, account or order-execution code. Decisions are proposals,
> never orders. Nothing here is investment advice, and no performance is claimed.

## Status — Sprint 0 (2026-10-16)
| Area | State |
|---|---|
| TradingAgents v0.6.0 adapter (pinned `1394a3f`), event log, SSE replay/resume | ✅ implemented and tested |
| Point-in-time data guard, explicit `FAILED / REVIEW / INSUFFICIENT_DATA` | ✅ implemented and tested |
| Read-only prices for NVDA and Samsung Electronics (005930) | ✅ verified live (Yahoo) |
| OpenDART disclosures (KR) | ⚠️ implemented, not yet verified live (needs key) |
| **Real LLM analysis of NVDA / 005930** | ❌ not run yet: needs an LLM API key |
| PostgreSQL, committee UI, paper trading, strategy comparison | planned (Sprints 1–4) |

Tests: backend 70 passed (unit/contract/e2e) · frontend 3 passed. The `demo` engine replays
**synthetic** data, is labelled DEMO everywhere, and is never an analysis result.
Details are in [docs/sprint-0-report.md](docs/sprint-0-report.md).

## Quick start
Requires Python 3.11–3.13 with [uv](https://docs.astral.sh/uv/) and Node 22.

```bash
# backend (installs into backend/.venv only)
cd backend
uv sync --extra engine --extra live
cp ../.env.example .env        # fill in your own keys; .env is git-ignored
uv run uvicorn stock_office.api.app:app_factory --factory --port 8000

# frontend dev console (proxies /api to :8000)
cd ../frontend
npm install && npm run dev
```

API keys go in `backend/.env`:
- **Required:** an LLM key (`OPENAI_API_KEY` by default) to run real analysis.
- **Recommended:** `STOCK_OFFICE_DART_API_KEY` for Korean disclosures.
- **Optional:** `FRED_API_KEY` for macro data.

Never use brokerage or account keys.

```bash
cd backend
uv run pytest                  # deterministic suite, no network
uv run pytest -m live -s       # live checks; real analysis runs when keys are set
```

## Repository layout
| Path | Contents |
|---|---|
| [backend/](backend/README.md) | FastAPI API, background worker, TradingAgents adapter, providers, tests |
| [frontend/](frontend/) | Vite + React + TypeScript dev console (event-derived agent status) |
| [docs/](docs/) | Sprint reports and portfolio evidence (implemented features only) |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Scope, data/API contracts, sprint plan, progress log |
| [PROJECT_PLAN.html](PROJECT_PLAN.html) | Visual product blueprint (open in a browser) |
| [CLAUDE.md](CLAUDE.md), [CODING_AI_PROMPT.md](CODING_AI_PROMPT.md) | Operating rules and kickoff prompt for AI-assisted development |

## Principles
- Agent animation is driven only by stored engine events. Nothing is simulated as if it were real.
- Every data point records `observed_at`, `available_at` and `ingested_at`. Future data is never used.
- A missing rating or missing evidence becomes `REVIEW`. It never silently defaults to HOLD.
- Strategies are compared only on matched windows, capital and costs.
