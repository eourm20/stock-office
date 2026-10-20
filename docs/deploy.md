# Running Stock Office on the server

**Server (since 2026-10-19):** `stock-office` (SSH alias; Oracle Ampere A1, ARM64, Ubuntu 24.04, 4 OCPU, 24 GB RAM,
45 GB disk; Always-Free allowance, account is Pay-As-You-Go with a 0.01 SGD budget alert).
**Exposure:** none. The UI (3000) and API (8000) listen on `127.0.0.1` only; the only public port is SSH.
**Previous server** `quant-worker` (1 GB): Stock Office services stopped and disabled on 2026-10-19, files and data kept
for rollback (`sudo systemctl enable --now stock-office-api stock-office-worker stock-office-web` there, after stopping
the new ones, would revert). It left the tailnet; the new server took over the same name.
## Open it on your phone or PC (Tailscale, recommended)
Since 2026-10-19 the server is in the owner's Tailscale network (device `stock-office`). `tailscale serve`
publishes it **to that tailnet only** over HTTPS; nothing is exposed to the internet:

```
https://stock-office.tail4755f0.ts.net        /    -> 127.0.0.1:3000 (UI)
                                              /api -> 127.0.0.1:8000/api (FastAPI, SSE)
```

On the iPhone: Tailscale app connected → open the address in Safari → Share → "홈 화면에 추가". The page is an
installable web app (manifest, icons, full screen). On the HTTPS address the UI calls the API on the same origin;
on port 3000 (dev, SSH tunnel) it still calls port 8000 directly (`resolveApiBase` in `frontend/src/lib/api.ts`).

Server side (done once): Tailscale from its apt repo, `tailscale up --hostname=stock-office` (owner approved the
login link), `tailscale serve --bg 3000` and `tailscale serve --bg --set-path /api http://127.0.0.1:8000/api`
(owner enabled Serve/HTTPS for the tailnet). Check: `sudo tailscale serve status`. Turn off:
`sudo tailscale serve --https=443 off`.

## Open the office over an SSH tunnel (fallback)
Double-click `tools\office-tunnel.cmd` (or run the command below), then open http://localhost:3000.
Closing the window disconnects. Your PC does not need to stay on for the analyses to run.

```
ssh -N -L 3000:127.0.0.1:3000 -L 8000:127.0.0.1:8000 quant-worker
```

## API keys (once)
The server has its own `~/stock-office/backend/.env` (mode 600). The key lines are empty until you fill them:

```
ssh stock-office
nano ~/stock-office/backend/.env      # OPENAI_API_KEY, STOCK_OFFICE_DART_API_KEY,
                                      # STOCK_OFFICE_NAVER_CLIENT_ID / _SECRET, FRED_API_KEY
sudo systemctl restart stock-office-api stock-office-worker
```

Until the OpenAI key is set, scheduled analyses **wait** without being recorded as failures. A missed slot still
runs if the key arrives before the slot's deadline (the next market open).

## What runs
| Service | Command | Memory cap |
|---|---|---|
| `stock-office-api` | uvicorn on 127.0.0.1:8000, `WORKER_MODE=external` | 2 GB |
| `stock-office-worker` | `python -m stock_office.worker --schedule` (queue + daily schedule) | 6 GB |
| `stock-office-web` | Next.js standalone `node server.js` on 127.0.0.1:3000 | 2 GB |

Daily schedule (exchange calendars, holidays skipped; `STOCK_OFFICE_SCHEDULE_ENABLED=true` on the server):
- NVDA: 17:00 New York time after each NYSE session (≈ 06:00–07:00 KST next morning)
- Samsung (005930): 07:30 KST before each KRX session
- Paper settlement (same worker, trading days only): KRX close + 40 min (≈ 16:10 KST), NYSE close + 30 min
  (≈ 05:30–06:30 KST). Uses that session's daily bar from Yahoo; a missing bar is retried every 10 min until the
  next session opens, then the session is settled as NO_DATA and open orders expire. Nothing leaves the server.

Cost guard: at most `STOCK_OFFICE_MAX_PAID_RUNS_PER_DAY` (8) real-engine runs per rolling 24 h, manual and
scheduled together; further requests get HTTP 429. Expected spend for 2 instruments ≈ $2/month.

## Operate
```
ssh stock-office 'systemctl status stock-office-api stock-office-worker stock-office-web --no-pager'
ssh stock-office 'journalctl -u stock-office-worker -n 50 --no-pager'      # schedule and runs
tools/deploy.sh                                                             # redeploy HEAD (from Git Bash)
```
Data lives in `~/stock-office/backend/data` (JSON/JSONL until PostgreSQL in Sprint 1). Legacy services on this
server were masked on 2026-10-16 (see IMPLEMENTATION_PLAN §13).

## Why not Docker yet
On 1 GB RAM the Docker daemon and image builds (pandas, langchain) cost more than they give, and the server
cannot build images itself. Docker Compose is planned with PostgreSQL (Sprint 1) or a move to a larger Oracle
ARM instance (up to 4 OCPU / 24 GB, free tier).

## Migration log (2026-10-19)
1. Instance created by the owner (A1.Flex 4/24, Ubuntu 24.04). Claude added the SSH alias, installed uv + Python 3.13,
   Node 22, Tailscale, created the three systemd units (larger memory caps), copied `backend/data` (11 runs) and deployed.
2. The owner copied `backend/.env` server-to-server with `scp -3` (Claude never read it); size and mode checked only.
3. Cut-over away from schedule slots: old services stopped and disabled, old node logged out of Tailscale; new services
   started (health `worker_mode=external`, engine readiness OK, same next slots); owner removed the old device and renamed
   the new one to `stock-office` in the Tailscale admin; `tailscale serve` re-created; HTTPS checks 200 for `/`, `/office`,
   `/api/v1/office/summary`, `/api/v1/budget`, manifest. Budget and run history identical to the old server.

## Data on the server (`~/stock-office/backend/data`)
| Path | Contents |
|---|---|
| `runs/<run_id>/run.json`, `events.jsonl`, `decision.json` | the run, its ordered events and the decision |
| `runs/<run_id>/reports.json`, `briefing.json` | full redacted reports and debate transcripts; one-page AI summary |
| `runs/<run_id>/tool_results.json` | what the analysts' tools returned (redacted, ≤ 6,000 chars each; runs from 2026-10-20 on) |
| `runs/<run_id>/snapshots/` | provider data the run was given (prices, filings, news) with point-in-time stamps |
| `office.db` | SQLite: inbox documents, approval plans, CEO decisions and opinions; paper book (settings, KRW cash ledger, simulated orders and fills, positions, settled sessions). Migrations run on start (`PRAGMA user_version`, 3 since 2026-10-20); back it up before deploying a new migration |

File the inbox for runs that have no document yet (past deadlines arrive as EXPIRED):
`cd ~/stock-office/backend && .venv/bin/python -m stock_office.inbox`.
