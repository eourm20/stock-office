# CEO app, step A: inbox, office as CCTV, records (2026-10-19)

User goal: run the AI investment company as its **CEO** — receive approval documents, watch what each
department is doing like CCTV, read organised meeting minutes. Plan: `IMPLEMENTATION_PLAN.md` §3c
(order changed by the user: three-tab UX and inbox first; screener, intraday monitoring and paper orders
follow as steps B–D).

## What changed
| Area | Change | Code |
|---|---|---|
| Storage | SQLite `data/office.db` (WAL, append-only migrations): `inbox_items`, `plans`, `approvals` | [db.py](../backend/src/stock_office/db.py) |
| Approval plan | Deterministic parsing of the engine's labelled lines (`Entry Price`, `Stop Loss`, `Position Sizing`, `Price Target`, `Rating`, `Time Horizon`); reference price and ATR14 from the run's own stored bars; policy defaults for missing numbers (marked); validation (entry within 10% of the close, stop < entry < target, stop distance 1–25%); KRX tick rounding. Older runs read the trader's event summary and the decision rationale | [plan_extract.py](../backend/src/stock_office/plan_extract.py) |
| Asset allocator | `POLICY_V1`: min(10% × rating factor × AI multiplier, 1% risk ÷ stop distance, 20% per instrument, cash above 20%), 100,000 KRW minimum, each rule shown | [paper/allocator.py](../backend/src/stock_office/paper/allocator.py) |
| Inbox | One document per meeting (idempotent): BUY with a valid plan → approval request expiring at the next session close after the decision (exchange calendars); other outcomes → reports; failed checks → "검토 필요" (cannot be approved). Decisions approve/defer/reject with comment, repeated request ids return the same answer, expired → 409 and stays EXPIRED. Filing never fails a run. Backfill: `python -m stock_office.inbox` (past deadlines arrive as EXPIRED) | [inbox.py](../backend/src/stock_office/inbox.py), [service.py](../backend/src/stock_office/runs/service.py) |
| API | `GET /api/v1/inbox`, `GET /api/v1/inbox/{id}`, `POST …/decision`, `POST …/read`, `GET /api/v1/records`, `GET /api/v1/office/now` | [app.py](../backend/src/stock_office/api/app.py) |
| Guard test | State-changing routes listed by name; new check: no network imports in `paper/`; order/broker bans unchanged | [test_no_live_orders.py](../backend/tests/unit/test_no_live_orders.py) |
| UI | Bottom tabs 결재함 · 오피스 · 기록 + ⚙ 회사 운영. Inbox (summary strip, pending by deadline, reports, handled). Approval document (paper look, approval-line stamps, plan table with AI/policy badges, allocator lines, sticky approve/defer/reject + comment). Office CCTV (department monitor tiles, REC clock, live-only, idle shows the next job, "회의 소집"). Records by day with filters; minutes in company order. Old `/analysis/[runId]` and `/history` redirect | [app/page.tsx](../frontend/src/app/page.tsx), [app/inbox/[id]/page.tsx](../frontend/src/app/inbox/%5Bid%5D/page.tsx), [app/office/page.tsx](../frontend/src/app/office/page.tsx), [app/records/page.tsx](../frontend/src/app/records/page.tsx), [MinutesView.tsx](../frontend/src/analysis/MinutesView.tsx), [app/settings/page.tsx](../frontend/src/app/settings/page.tsx) |

## Real data check (local copy of stored runs, no paid call)
Backfill of the five real local meetings: NVDA 10/16 → "[결재] 엔비디아 매수 1주" (policy defaults, EXPIRED);
NVDA 10/16 (second, Korean) → AI-given entry $226.59 / stop $202.52, real USD/KRW 1,331.88 → "검토 필요":
the policy budget for this rating and multiplier (150,000 KRW) is below one share (~300,000 KRW). Open
policy question for the owner: fractional US shares in paper trading. Samsung SELL meetings → reports
("no position, long-only book").

## Tests
Backend **127 passed** (+17: plan extraction with fixtures copied from stored runs, allocator table incl. the
worked example, inbox expiry across KR/US calendars, DST and Chuseok, decision states, double tap, expiry
persistence, DEMO BUY → approval end to end, HOLD → report). ruff, mypy (src) clean. Bug found by the
tests and fixed: a refused late decision rolled back its own EXPIRED update.
Frontend **42 passed** (+5 inbox model: ordering, Korean deadline labels, money, stamps, day grouping),
`tsc` clean, `next build` OK. Browser (iPhone 13 emulation): inbox → document → approve with comment →
stamp; review document; minutes; office idle; settings. Fixed during the check: clock hydration mismatch,
repeated "대기", stamps wrapping, "0주 / 0원" on blocked plans.

## Follow-up: fractional US shares (POLICY_V2, same day, owner decision)
The owner buys US stocks in fractional quantities in their own securities app, so the allocator now sizes
US positions in steps of 0.0001 share (KRX stays whole shares). The stored NVDA case that was blocked
under V1 (budget 150,000 KRW < one share) now sizes to 0.4967 share. `Allocation.qty` is a Decimal;
titles and the UI print it without trailing zeros. Documents already filed keep their V1 record.
Tests: backend 128 passed (+1 real NVDA case, US fractional and KR whole-share variants); the guard test
caught the word "brokerage" in a new comment, which was reworded. Frontend 42 passed.
