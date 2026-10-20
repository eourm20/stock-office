# Portfolio Evidence — Stock Office (draft, updated 2026-10-20)

Only **implemented and verified** items are listed as results; planned work is labelled as planned. There are
no investment-performance claims: the one-month mock-trading run on Kiwoom mock accounts started 2026-10-20 and
is not evaluated yet (criteria fixed in advance: `docs/evaluation-plan.md`).

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
| Paper book: auto-approval (CEO opinion recorded apart), POLICY_V2 re-check at approval, limit entries from the next session, fills decided on the day's bar after the close (both touched → stop), target/stop pair, KRW cash ledger, USD at that day's rate, idempotent orders and settlements | [paper/fills.py](../backend/src/stock_office/paper/fills.py), [paper/book.py](../backend/src/stock_office/paper/book.py), [paper/settle.py](../backend/src/stock_office/paper/settle.py), [paper/costs.py](../backend/src/stock_office/paper/costs.py) | unit + e2e (133 → 162 backend tests); screens with DEMO seed data (`docs/screenshots/ceo-d-*.png`); deployed 2026-10-20, no real fills yet |
| Research team (B): dated KOSPI200 (199) / NASDAQ-100 (101) snapshots, deterministic screener SCREEN_V1 (liquidity filter; trend, 3-month momentum rank, volume surge, 52-week high; volatility and overbought penalties) with written reasons, 25-stock watchlist, 3 focus meetings per market a day with held stocks first | [research/](../backend/src/stock_office/research/), [universe/](../backend/src/stock_office/universe/) | 4 unit tests; first live run 2026-10-20 (99 US stocks screened, 3 meetings) |
| Phone notifications: Web Push to the installed web app, four event types only (meeting started, meeting ended, approval request, desk orders), outbox with dedupe, quiet hours with one summary, known push services only | [notify.py](../backend/src/stock_office/notify.py), [sw.js](../frontend/public/sw.js), [push.ts](../frontend/src/lib/push.ts) | unit + e2e (162 → 173 backend tests); real subscription and delivery checked locally with Edge |
| Kiwoom 모의투자 read-only link (K1): mock server fixed in one module, account queries only, token renewal, paging, rate spacing; domestic and overseas snapshots | [kiwoom_mock/](../backend/src/stock_office/kiwoom_mock/) | unit tests with a fake HTTP server (no network); checked live against the mock server 2026-10-20 |
| Kiwoom mock desks (K2–K4, C): approved plans → regular-hours limit orders sized on the live mock account (POLICY_V3), pre-order check at the open (stop already broken or > 5% gap → held back), SENDING-before-request so no double order, fills from Kiwoom's own order history, deadline cancels, stop/target exits on the whole position, add-on buys merged into one position, −10% loss limit, intraday move (±3/5/10%) and DART filing reports, per-session account value with benchmark | [kiwoom_mock/desks.py](../backend/src/stock_office/kiwoom_mock/desks.py) | 18 tests against a fake Kiwoom server; deployed 2026-10-20; first real mock orders 2026-10-20 22:30 KST |
| No-real-orders guard (MOCK ONLY rule from 2026-10-20) | [test_no_live_orders.py](../backend/tests/unit/test_no_live_orders.py) | named state-changing routes; the real trading domain appears nowhere; the mock address lives in one file; order paths and API ids only in `kiwoom_mock/client.py` and `desks.py`; no network imports in `paper/` |
| Web app: two desks (국장/미장 switch), inbox with a summary-first approval document, office CCTV (Phaser, event-driven, deterministic state machine, shared boardroom), records, portfolio (Kiwoom account, performance vs benchmark, orders), settings, installable on iOS | [frontend/src/app/](../frontend/src/app/), [office/](../frontend/src/office/), [game/](../frontend/src/game/) | vitest 49; iPhone-size browser checks (screenshots in `docs/screenshots/`) |

## Measured
| What | Value | Source |
|---|---|---|
| Real committee run (economy profile) | ≈ 140–225 s, ≈ $0.04–0.05 | sprint-0, 2b reports |
| One-page briefing | ≈ $0.0014–0.0021 | sprint-2b report |
| Production frame rate (office) | 57–62 fps (mean ≈ 61) | sprint-2a report |
| Spend so far (October, as of 2026-10-20 evening) | $0.73 of a $7 budget (12 paid runs) | `/api/v1/budget` |
| Research screening (NASDAQ-100, Yahoo daily bars, ARM server) | ≈ 20 s for 101 stocks | worker log 2026-10-20 |

## Not yet achieved (do not present as results)
- Kiwoom mock order results (first orders 2026-10-20 22:30 KST) and the one-month evaluation (2026-10-20 ~ 11-19, criteria in `docs/evaluation-plan.md`).
- Learning from outcomes: off by design during the evaluation (decisions use fresh data but no reflection on past results).
- Any statement about investment returns. The first evaluation will use criteria fixed before the paper month.

## Reports
[sprint-0](sprint-0-report.md) · [sprint-2a](sprint-2a-report.md) · [sprint-2b](sprint-2b-report.md) ·
[CEO app step A](sprint-ceo-a-report.md) · [CEO app step D](sprint-ceo-d-report.md) · [deploy](deploy.md)
