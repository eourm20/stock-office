# Portfolio Evidence — Stock Office (draft, updated 2026-10-20)

Only **implemented and verified** items are listed as results; planned work is labelled as planned. There are
no investment-performance claims: real analyses run daily, but their decisions are unevaluated proposals, and
the paper book (step D) is new, with assumed costs and no evaluation yet.

## What exists
| Feature | Code | Verification |
|---|---|---|
| TradingAgents 0.6.0 adapter: LangGraph task stream → ordered events (incl. analysts' subgraphs → `tool.called`, names only) | [engine/adapter.py](../backend/src/stock_office/engine/adapter.py) | unit + contract tests against the pinned package; real runs |
| Append-only event log, monotonic seq, idempotent appends, SSE replay/resume | [events/store.py](../backend/src/stock_office/events/store.py), [api/app.py](../backend/src/stock_office/api/app.py) | unit + e2e |
| Point-in-time guard (`observed_at`/`available_at`/`ingested_at`), explicit FAILED/REVIEW/INSUFFICIENT_DATA | [providers/base.py](../backend/src/stock_office/providers/base.py), [runs/service.py](../backend/src/stock_office/runs/service.py) | unit + e2e |
| Data providers: Yahoo prices, OpenDART filings, Naver news headlines; KR news vendor for the engine | [providers/](../backend/src/stock_office/providers/), [engine/ta_extensions.py](../backend/src/stock_office/engine/ta_extensions.py) | unit/contract (no network) + live checks |
| Evidence: full redacted reports, AI tool results per run, one-page AI briefing (quick model, ≈ $0.002) | [adapter.py](../backend/src/stock_office/engine/adapter.py), [briefing.py](../backend/src/stock_office/briefing.py) | unit + e2e; real briefing checked |
| Daily schedule on exchange calendars; monthly LLM budget hard stop; paid-run cap | [schedule.py](../backend/src/stock_office/schedule.py), [budget.py](../backend/src/stock_office/budget.py) | unit; production since 2026-10-17 |
| CEO inbox: approval plans from labelled engine lines, POLICY_V2 allocator, expiry, decisions | [plan_extract.py](../backend/src/stock_office/plan_extract.py), [paper/allocator.py](../backend/src/stock_office/paper/allocator.py), [inbox.py](../backend/src/stock_office/inbox.py) | unit + e2e (127 → 133 backend tests) |
| Paper book: auto-approval (CEO opinion recorded apart), POLICY_V2 re-check at approval, limit entries from the next session, fills decided on the day's bar after the close (both touched → stop), target/stop pair, KRW cash ledger, USD at that day's rate, idempotent orders and settlements | [paper/fills.py](../backend/src/stock_office/paper/fills.py), [paper/book.py](../backend/src/stock_office/paper/book.py), [paper/settle.py](../backend/src/stock_office/paper/settle.py), [paper/costs.py](../backend/src/stock_office/paper/costs.py) | unit + e2e (133 → 162 backend tests); screens with DEMO seed data (`docs/screenshots/ceo-d-*.png`); not yet deployed |
| PAPER ONLY guard | [test_no_live_orders.py](../backend/tests/unit/test_no_live_orders.py) | named state-changing routes, no network imports in `paper/`, banned order/securities-firm words |
| Web app: inbox, approval document, office CCTV (Phaser, event-driven, deterministic state machine), records, settings, installable on iOS | [frontend/src/app/](../frontend/src/app/), [office/](../frontend/src/office/), [game/](../frontend/src/game/) | vitest 47 (incl. boardroom seating and meeting break-up from events); iPhone-size browser checks (screenshots in `docs/screenshots/`) |

## Measured
| What | Value | Source |
|---|---|---|
| Real committee run (economy profile) | ≈ 140–225 s, ≈ $0.04–0.05 | sprint-0, 2b reports |
| One-page briefing | ≈ $0.0014–0.0021 | sprint-2b report |
| Production frame rate (office) | 57–62 fps (mean ≈ 61) | sprint-2a report |
| Spend so far (October) | ≈ $0.3 of a $7 budget | `/api/v1/budget` |

## Not yet achieved (do not present as results)
- Paper results from real meetings (step D is implemented; the first real fills come after deployment); hourly-bar fills and intraday monitoring (C); screener (B).
- Any statement about investment returns. The first evaluation will use criteria fixed before the paper month.

## Reports
[sprint-0](sprint-0-report.md) · [sprint-2a](sprint-2a-report.md) · [sprint-2b](sprint-2b-report.md) ·
[CEO app step A](sprint-ceo-a-report.md) · [CEO app step D](sprint-ceo-d-report.md) · [deploy](deploy.md)
