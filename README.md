# Stock Office

A personal AI investment-office simulator for US and Korean equities. An AI investment committee built on
[TradingAgents](https://github.com/TauricResearch/TradingAgents) analyzes stocks every trading day. The owner
runs the company as its **CEO** from a phone-friendly web app with three tabs:

- **결재함 (inbox)** — approval documents drafted by the portfolio manager: conclusion, reasons, risks, an
  order plan whose numbers are marked *AI-given* or *policy default*, and the asset allocator's sizing
  (POLICY_V2). Approve, defer or reject; unanswered documents expire at the market close.
- **오피스 (office)** — a 2.5D pixel-art office that works like CCTV: department monitors and the live meeting,
  driven only by stored engine events. No replays.
- **기록 (records)** — meeting minutes: team reports, the bull/bear and risk debates as a chat, the decision and
  its approval, and attachments (sources, what the AI looked up, run facts).

> **MOCK ONLY.** No real-account orders, keys or account numbers. Approvals become simulated orders only through a
> deterministic risk policy: today in the app's own paper book; next (step K, planned) also on Kiwoom's 모의투자
> mock-trading server with mock accounts. Moving to real trading is not built and would be a separate decision.
> Nothing here is investment advice, and no performance is claimed.

## Status (2026-10-20)
| Area | State |
|---|---|
| Daily committee meetings on exchange calendars (NVDA, Samsung 005930), Korean reports, 2 debate rounds | ✅ running on the server |
| Data: Yahoo prices, OpenDART filings, Naver news headlines (KR), point-in-time guard, AI tool results stored | ✅ |
| CEO inbox, approval documents, POLICY_V2 allocator (fractional US shares), expiry, one-page AI briefing | ✅ |
| Office as CCTV, records of minutes, company settings, installable phone app (Tailscale only) | ✅ |
| Monthly LLM budget hard stop ($7 ≈ 10,000 KRW), paid-run cap | ✅ |
| Auto-approval (CEO opinion kept apart), paper orders settled on daily bars, KRW ledger, portfolio page (step D) | ✅ deployed 2026-10-20 (first real fills pending) |
| Shared boardroom in the office scene: both debates and their chairs meet there, from real events | ✅ deployed 2026-10-20 |
| Phone notifications (web push): meeting started, meeting ended, approval request; quiet hours | ✅ deployed 2026-10-20, received on iPhone |
| **Step K: Kiwoom 모의투자** — K1 read-only link to both mock accounts (domestic KRW, overseas USD) | ✅ deployed 2026-10-20 |
| Step K2–K4: mock orders with the same risk gate, fills read back, then the paper book is switched over | next |
| Intraday monitoring (C, also triggers K exits), research screener (B), investment policy statement | planned |
| **Step E: one month of mock trading** on the Kiwoom mock accounts, criteria fixed in advance | planned |

Tests: backend 185 passed (unit/contract/e2e, no network) · frontend 48 passed. Reports per step are in
[docs/](docs/); the current overview and remaining work are in [IMPLEMENTATION_PLAN.md §0](IMPLEMENTATION_PLAN.md).

## Tech stack
| Layer | Stack |
|---|---|
| Web app | Next.js 16, React 19, TypeScript, Tailwind CSS; Phaser 3 + Tiled (office); React Flow (committee graph) |
| Backend | FastAPI API, background worker (queue + daily schedule), SSE with replayable ordered events |
| Multi-agent | TradingAgents 0.6.0 (LangGraph), pinned `1394a3f`, behind `TradingAgentsAdapter` |
| Storage | Run records as JSON/JSONL files; office operations (inbox, plans, approvals, paper book) in SQLite |
| Server | Oracle Ampere A1 (ARM64), systemd, reachable only through the owner's Tailscale |

## Quick start
Requires Python 3.11–3.13 with [uv](https://docs.astral.sh/uv/) and Node 22.

```bash
# backend (installs into backend/.venv only)
cd backend
uv sync --extra engine --extra live
cp ../.env.example .env        # fill in your own keys; .env is git-ignored
uv run uvicorn stock_office.api.app:app_factory --factory --port 8000

# web app → http://localhost:3000
cd ../frontend
npm install && npm run dev     # calls the API at NEXT_PUBLIC_API_BASE (default http://localhost:8000)
```

Meeting minutes are at `http://localhost:3000/records/<run_id>`. The **DEMO** engine is free; the
real engine asks for confirmation because it costs money. To regenerate placeholder art and the
office map, run `uv run --no-project --with pillow python tools/gen_placeholder_art.py`. To swap a
character, edit `frontend/public/characters/registry.json`.

API keys go in `backend/.env`:
- **Required:** an LLM key (`OPENAI_API_KEY` by default) to run real analysis.
- **Recommended:** `STOCK_OFFICE_DART_API_KEY` for Korean disclosures, and
  `STOCK_OFFICE_NAVER_CLIENT_ID` / `STOCK_OFFICE_NAVER_CLIENT_SECRET` (Naver Search API) for Korean news.
- **Optional:** `FRED_API_KEY` for macro data.

Never use brokerage or account keys.

```bash
cd backend
uv run pytest                  # deterministic suite, no network
uv run pytest -m live -s       # live checks; real analysis runs when keys are set
```

## Server
Production runs on an Oracle ARM server with the daily schedule (NVDA after the US close, Samsung before the KRX
open). Nothing is public: the app is reachable only inside the owner's Tailscale network (phone home-screen app),
with an SSH tunnel as fallback. Setup, keys, operation and redeploys: [docs/deploy.md](docs/deploy.md).

## Repository layout
| Path | Contents |
|---|---|
| [backend/](backend/README.md) | FastAPI API, background worker, TradingAgents adapter, providers, tests |
| [frontend/](frontend/) | Next.js app: inbox, approval documents, office (Phaser), records, settings |
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
