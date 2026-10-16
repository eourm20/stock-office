# Portfolio Evidence — Stock Office (draft)

Only **implemented and verified** items are listed as results. Planned work is labelled as
planned. There are no investment-performance claims: no real analysis has run yet and no
paper trading exists.

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

## Not yet achieved (do not present as results)
- Real LLM analysis of NVDA / 005930 (blocked: no API key). Cost and latency not measured.
- OpenDART live verification.
- PostgreSQL, committee UI (React Flow/Motion), paper trading, strategy comparison.

## Reusable artifacts for the write-up
- Agent event JSON: `GET /api/v1/analysis-runs/{id}/events` (DEMO runs must be shown labelled DEMO).
- Architecture: see `PROJECT_PLAN.html` §04; Sprint 0 implements API + worker + adapter + file storage.
