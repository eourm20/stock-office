# CEO app, step D: auto-approval, paper orders, portfolio (2026-10-19 – 10-20)

User goal: find out whether the AI committee would make or lose money, without the owner's judgment mixed
in. Owner decisions: during paper trading, **approve every request automatically** (switchable in ⚙); build
paper orders (D) before screener (B) and intraday monitoring (C); decide fills **after the close on the
day's daily bar** (C will refine to hourly bars); portfolio as a card on top of the inbox plus a detail page.
Added on 10-20: with auto-approval on, the approve/defer/reject buttons stay, but only record the **CEO's
opinion** beside the automatic approval, so the paper results still measure the model alone.

PAPER ONLY: nothing leaves the app. There is no securities-firm, account or order-sending code; the guard
test still enforces it.

## What changed
| Area | Change | Code |
|---|---|---|
| Storage | Migration 2: `company_settings`, `paper_cash` (KRW ledger, balance = sum), `paper_orders` (role entry/take_profit/stop/exit, status, active window, `idempotency_key` UNIQUE), `paper_fills` (one per order), `paper_positions`, `settle_runs` (one per market and session). Migration 3: `approvals.kind` (`decision`/`opinion`) | [db.py](../backend/src/stock_office/db.py) |
| Cost assumptions | KR commission 0.015 % each side, KR sell tax 0.20 %, US commission 0.1 %, FX spread 0.25 % each way, 5 bp slippage on stops and market exits. All in `Settings.paper_*`, shown as assumptions | [paper/costs.py](../backend/src/stock_office/paper/costs.py) |
| Fill rules (pure) | Entry: open ≤ limit → open, low ≤ limit → limit. Exit: gap below stop → open, gap above target → open, low touches stop → stop, high touches target → target; **both on one day → stop** (conservative); on the entry day only the stop is checked. No bar, stale bar or missing FX → no fill | [paper/fills.py](../backend/src/stock_office/paper/fills.py) |
| Book | Approval → `open_bracket` re-runs POLICY_V2 on the current account (cash, holdings, cash reserved by pending entries); entry limit order valid from the first session opening after the approval (no look-ahead into the bar) until the document's deadline; refusal → "[리스크 거절]" report. SELL meeting while holding → sell request → whole position at the next open. Fill → target + stop pair, one cancels the other | [paper/book.py](../backend/src/stock_office/paper/book.py) |
| Settlement | Per market after the close (KRX close + 40 min, NYSE close + 30 min, trading days only), oldest due session first; fills, cash, positions and inbox reports ("[체결]", "[청산]" with P&L) in one transaction; NAV snapshot per session (USD holdings at that day's USD/KRW). Late daily bar → retry every 10 min; once the next session opens it settles as NO_DATA and orders expire | [paper/settle.py](../backend/src/stock_office/paper/settle.py), [schedule.py](../backend/src/stock_office/schedule.py), [worker.py](../backend/src/stock_office/worker.py) |
| Inbox | Auto-approval as the request is filed (`auto:<id>` request id, shown as "자동"); one approval path for auto and CEO. CEO opinion on auto-approved requests until the deadline (defer can be changed, agree/object is final), never touches the book. DEMO meetings stay out of the book in production | [inbox.py](../backend/src/stock_office/inbox.py) |
| API | `GET /api/v1/portfolio`, `GET /api/v1/portfolio/activity`, `GET /api/v1/company/settings`, `POST /api/v1/company/auto-approve` (added to the guard test's named list); records carry `approval_auto`, `paper`, `ceo_opinion` | [app.py](../backend/src/stock_office/api/app.py) |
| UI | Inbox: portfolio card (NAV, return, holdings, cash weight). Approval document: paper order status, sell requests, "자동" stamp, opinion buttons (동의/보류/반대) under auto-approval; AI/policy badges kept on one line. `/portfolio`: NAV and return vs 10,000,000 KRW, cash, reserved, realized P&L, holdings (average, last close, P&L, distance to target/stop), pending orders, fills and exits with the rule used, cost assumptions, "모의투자 · 검증 전" labels. ⚙: auto-approval switch and cost assumptions. Records and minutes: "자동 승인 · 모의 체결 · CEO 반대". Office/inbox: settlement jobs in "다음 업무" no longer called "회의" | [app/portfolio/page.tsx](../frontend/src/app/portfolio/page.tsx), [app/inbox/[id]/page.tsx](../frontend/src/app/inbox/%5Bid%5D/page.tsx), [app/settings/page.tsx](../frontend/src/app/settings/page.tsx), [inbox/model.ts](../frontend/src/inbox/model.ts) |

## Tests
Backend **162 passed** (`uv run pytest`, no network), ruff and mypy (src) clean. New: fill rules
(entry limit, exit pair, entry day stop only, slippage on open exits), KRW and USD costs, approval → one
entry (repeated approvals never book twice), entry fill moves cash into a position and sets the exit pair,
target fill cancels the stop, both touched → stop, unreached limit expires and frees the reservation,
missing bar waits then settles without filling, USD fill at the rate with spread (waits without a rate),
SELL with/without a position, cash shortage → risk refusal, auto-approval off, DEMO kept out in
production, each closed session settled once (KR and US), CEO opinion (defer → reject, final after that,
order unchanged, closed after the deadline), e2e: auto-approved BUY filled after the close and shown in
`/api/v1/portfolio`.
A test that depended on the wall clock (it failed when run during Korean trading hours) was fixed on 10-20.

Frontend **46 passed** (`npx vitest run`), `tsc` clean, `next build` OK.

## Screens (iPhone width, DEMO seed data)
A scratch database was filled by DEMO meetings → auto-approval → settlement on **made-up daily bars**
(Samsung entry filled; NVDA entry filled then target hit; a new NVDA entry waiting). These numbers are
synthetic and show the screens only. In this seed DEMO meetings were allowed into the book; production
keeps them out, which is why the document still prints the DEMO note.
`ceo-d-inbox.png`, `ceo-d-portfolio.png`, `ceo-d-doc-opinion.png`, `ceo-d-settings.png`,
`ceo-d-records.png` in [screenshots/](screenshots/).

## Not done / limits
- Not deployed yet at the time of writing; the first real check is the first BUY meeting after deployment
  (auto-approval → entry → settlement that evening).
- Daily bars only: the order of intraday touches is unknown, hence "both touched → stop" and "entry day
  stop only". Hourly bars come with step C.
- No partial buys, short selling, rebalancing or benchmark chart (evaluation, step E).
- No performance claim: results are unvalidated paper results with assumed costs.
