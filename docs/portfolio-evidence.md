# Portfolio Evidence — Stock Office (draft)

Only **implemented and verified** items are listed as results. Planned work is labelled as
planned. There are no investment-performance claims: real analyses run daily, but their decisions
are unevaluated proposals, and no paper trading exists yet.

## Sprint 0 (2026-10-16) — implemented
| Feature | Code | Verification |
|---|---|---|
| Normalized contracts (Instrument, MarketSnapshot, AgentResult, InvestmentDecision, RunEvent) | [models.py](../backend/src/stock_office/domain/models.py) | `tests/unit/test_models.py` |
| US/KR instrument IDs (`COUNTRY:EXCHANGE:SYMBOL`), currency/timezone mapping | [instruments.py](../backend/src/stock_office/domain/instruments.py) | `tests/unit/test_instruments.py` |
| Point-in-time guard (`observed_at`/`available_at`/`ingested_at`) | [providers/base.py](../backend/src/stock_office/providers/base.py) | unit + e2e; live: excluded a not-yet-published KRX bar |
| TradingAgents v0.6.0 adapter: LangGraph task stream → ordered events | [engine/adapter.py](../backend/src/stock_office/engine/adapter.py) | 15 unit + 5 contract tests against the pinned package |
| Append-only event log, monotonic seq, idempotent appends, crash-tail recovery | [events/store.py](../backend/src/stock_office/events/store.py) | `tests/unit/test_event_store.py` |
| SSE replay/resume (`Last-Event-ID`, `after_seq`) with a separate worker process | [api/app.py](../backend/src/stock_office/api/app.py), [worker.py](../backend/src/stock_office/worker.py) | e2e + real uvicorn smoke (35 events, resume at seq 21) |
| Explicit failure states (FAILED / INSUFFICIENT_DATA / REVIEW) | [runs/service.py](../backend/src/stock_office/runs/service.py) | e2e failure/missing-data tests |
| PAPER-ONLY enforcement | [config.py](../backend/src/stock_office/config.py) | `tests/unit/test_no_live_orders.py` |
| Event-driven agent status reducer (frontend) | [runState.ts](../frontend/src/runState.ts) | vitest, 3 tests |

Test totals: backend 70 passed (unit/contract/e2e), live 2 passed / 3 skipped (missing keys);
frontend 3 passed. ruff + mypy strict clean. Details: [sprint-0-report.md](sprint-0-report.md).

## Sprint 2A (2026-10-16) — implemented
| Feature | Code | Verification |
|---|---|---|
| Isometric pixel-art office (Phaser 3 + Tiled map), camera pan/zoom | [OfficeScene.ts](../frontend/src/game/OfficeScene.ts), [office.tmj](../frontend/public/office/office.tmj) | Edge browser run, screenshots in `docs/screenshots/` |
| Event Adapter → deterministic Character State Machine | [eventAdapter.ts](../frontend/src/office/eventAdapter.ts), [stateMachine.ts](../frontend/src/office/stateMachine.ts) | 18 vitest tests incl. whole/chunked/duplicate/replay equality |
| Replay and live SSE with paced queue, debate dwell, catch-up | [replay.ts](../frontend/src/office/replay.ts) | tests + replays of real NVDA/005930 runs |
| Character Registry with generated CC0 placeholders | [registry.ts](../frontend/src/office/registry.ts), [gen_placeholder_art.py](../tools/gen_placeholder_art.py) | registry fallback tests |
| Measured frame rate | — | dev build 44–60 fps (mean ≈ 54); production build 57–62 fps (mean ≈ 61), 2026-10-19 |
| Korean reports/debate, plain-language narrator, auto mode, `/history` | [sprint-2a-report.md §6](sprint-2a-report.md) | unit tests + browser checks |

## Daily scheduled analysis on a private server (2026-10-16 deploy, verified 2026-10-19)
| Feature | Code | Verification |
|---|---|---|
| Exchange-calendar schedule (NVDA 17:00 ET after close, 005930 07:30 KST before open), one run per slot, paid-run cap | [schedule.py](../backend/src/stock_office/schedule.py), [worker.py](../backend/src/stock_office/worker.py) | unit tests; live runs below |
| Server deploy: systemd api/worker/web, loopback only, SSH-tunnel access | [deploy.md](deploy.md), [deploy.sh](../tools/deploy.sh) | services active since 2026-10-16 |

First scheduled runs (real engine, economy profile, `tradingagents-0.6.0@1394a3f`):

| Slot | Run | Latency | Decision | Cost (computed) |
|---|---|---|---|---|
| `US:NASDAQ:NVDA@2026-10-16` | `7dcf0bb672b84ee8` | 186 s | BUY / Overweight | ≈ $0.048 |
| `KR:KRX:005930@2026-10-19` | `afd91499c4df4ee0` | 176 s | SELL / Underweight | ≈ $0.046 |

Cost is stored `token_usage` × the per-token prices in [sprint-0-report.md §10](sprint-0-report.md) (not yet
reconciled with the OpenAI invoice). All 7 real server runs so far ≈ $0.31; projected ≈ $2/month for 2 instruments.
Both decisions carry `COVERAGE_GAP` and `ENGINE_DATA_NOT_SNAPSHOTTED`: they are proposals, not evidence of
performance.

## Not yet achieved (do not present as results)
- Per-run cost stored/displayed and a monthly budget stop (planned, Sprint R).
- Full snapshotting of the data the engine fetches itself (`ENGINE_DATA_NOT_SNAPSHOTTED`).
- PostgreSQL, Analysis Mode (React Flow), remaining 9 agent characters, paper trading, strategy comparison.

## Reusable artifacts for the write-up
- Agent event JSON: `GET /api/v1/analysis-runs/{id}/events` (DEMO runs must be shown labelled DEMO).
- Architecture: see `PROJECT_PLAN.html` §04; Sprint 0 implements API + worker + adapter + file storage.
