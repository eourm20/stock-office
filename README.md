# Stock Office

A personal AI investment-office simulator for US and Korean equities. An AI investment committee built on
[TradingAgents](https://github.com/TauricResearch/TradingAgents) analyzes a stock. Its **real**
multi-agent activity is stored as ordered events and played out in a **2.5D isometric pixel-art
office**, where AI employees move between desks, analyze, debate and report. Decisions are
evaluated only through risk-gated **paper trading**.

> **PAPER ONLY.** There is no broker, account or order-execution code. Decisions are proposals,
> never orders. Nothing here is investment advice, and no performance is claimed.

## Status — Sprint 0 (2026-10-16)
| Area | State |
|---|---|
| TradingAgents v0.6.0 adapter (pinned `1394a3f`), event log, SSE replay/resume | ✅ implemented and tested |
| Point-in-time data guard, explicit `FAILED / REVIEW / INSUFFICIENT_DATA` | ✅ implemented and tested |
| Read-only prices for NVDA and Samsung Electronics (005930) | ✅ verified live (Yahoo) |
| OpenDART disclosures (KR), also used as KR company news for the engine | ✅ verified live |
| **Real LLM analysis of NVDA / 005930** | ✅ completed (≈140–165 s, ≈ $0.04 per run, economy profile) |
| Game-like office (Phaser 3 + Tiled), 4 placeholder characters, replay/live | ✅ Sprint 2A (see [report](docs/sprint-2a-report.md)) |
| Korean reports and debate, plain-language explanations, auto mode, decision cards, history page | ✅ |
| All 13 agents in the office, Analysis Mode, custom character upload | planned (Sprint 2B, 2C) |
| PostgreSQL, paper trading, strategy comparison | planned (Sprints 1, 3, 4) |

Tests: backend 86 passed (unit/contract/e2e) · frontend 18 passed. The `demo` engine replays
**synthetic** data, is labelled DEMO everywhere, and is never an analysis result.
Details are in [docs/sprint-0-report.md](docs/sprint-0-report.md).

## Tech stack
| Layer | Decided stack | Today |
|---|---|---|
| Office Mode (main screen) | Next.js, React, TypeScript, **Phaser 3**, Tiled Map Editor | ✅ first slice (Sprint 2A) |
| UI panels / other modes | Tailwind CSS, shadcn/ui, React Flow (Analysis Mode), ECharts (charts) | Tailwind ✅; shadcn/ui, React Flow, ECharts later |
| Characters | Character Registry (`agent_id → character_id → asset_id`); licensed placeholder pixel art first, user sprite sheets later | file registry + generated CC0 placeholders ✅; upload UI in Sprint 2C |
| Backend | FastAPI, background worker, SSE (replayable ordered events) | ✅ |
| Multi-agent | TradingAgents 0.6.0 (LangGraph) behind `TradingAgentsAdapter` | ✅ |
| Database | PostgreSQL | JSON/JSONL files until Sprint 1 |

## Quick start
Requires Python 3.11–3.13 with [uv](https://docs.astral.sh/uv/) and Node 22.

```bash
# backend (installs into backend/.venv only)
cd backend
uv sync --extra engine --extra live
cp ../.env.example .env        # fill in your own keys; .env is git-ignored
uv run uvicorn stock_office.api.app:app_factory --factory --port 8000

# office UI → http://localhost:3000  (dev console: /console)
cd ../frontend
npm install && npm run dev     # calls the API at NEXT_PUBLIC_API_BASE (default http://localhost:8000)
```

Open a stored run with `http://localhost:3000/?run=<run_id>`. The **DEMO** engine is free; the
real engine asks for confirmation because it costs money. To regenerate placeholder art and the
office map, run `uv run --no-project --with pillow python tools/gen_placeholder_art.py`. To swap a
character, edit `frontend/public/characters/registry.json`.

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
| [frontend/](frontend/) | Next.js office UI: Phaser scene, event adapter, character state machine, registry |
| [tools/](tools/) | Placeholder art, Tiled map and registry generator |
| [docs/](docs/) | Sprint reports and portfolio evidence (implemented features only) |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Scope, data/API contracts, sprint plan, progress log |
| [PROJECT_PLAN.html](PROJECT_PLAN.html) | Visual product blueprint (open in a browser) |
| [CLAUDE.md](CLAUDE.md) | Operating rules for AI-assisted development |

## Principles
- Agent animation is driven only by stored engine events. Nothing is simulated as if it were real.
- Every data point records `observed_at`, `available_at` and `ingested_at`. Future data is never used.
- A missing rating or missing evidence becomes `REVIEW`. It never silently defaults to HOLD.
- Strategies are compared only on matched windows, capital and costs.
