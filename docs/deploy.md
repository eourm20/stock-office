# Running Stock Office on the server

**Server:** `quant-worker` (SSH alias; Oracle free tier, Ubuntu 22.04, 2 vCPU, 1 GB RAM + 1 GB swap).
**Exposure:** none. The UI (3000) and API (8000) listen on `127.0.0.1` only; the only public port is SSH.
You reach the office through an SSH tunnel.

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
ssh quant-worker
nano ~/stock-office/backend/.env      # set OPENAI_API_KEY, STOCK_OFFICE_DART_API_KEY, FRED_API_KEY
sudo systemctl restart stock-office-api stock-office-worker
```

Until the OpenAI key is set, scheduled analyses **wait** without being recorded as failures. A missed slot still
runs if the key arrives before the slot's deadline (the next market open).

## What runs
| Service | Command | Memory cap |
|---|---|---|
| `stock-office-api` | uvicorn on 127.0.0.1:8000, `WORKER_MODE=external` | 350 MB |
| `stock-office-worker` | `python -m stock_office.worker --schedule` (queue + daily schedule) | 750 MB |
| `stock-office-web` | Next.js standalone `node server.js` on 127.0.0.1:3000 | 300 MB |

Daily schedule (exchange calendars, holidays skipped; `STOCK_OFFICE_SCHEDULE_ENABLED=true` on the server):
- NVDA: 17:00 New York time after each NYSE session (≈ 06:00–07:00 KST next morning)
- Samsung (005930): 07:30 KST before each KRX session

Cost guard: at most `STOCK_OFFICE_MAX_PAID_RUNS_PER_DAY` (8) real-engine runs per rolling 24 h, manual and
scheduled together; further requests get HTTP 429. Expected spend for 2 instruments ≈ $2/month.

## Operate
```
ssh quant-worker 'systemctl status stock-office-api stock-office-worker stock-office-web --no-pager'
ssh quant-worker 'journalctl -u stock-office-worker -n 50 --no-pager'      # schedule and runs
tools/deploy.sh                                                             # redeploy HEAD (from Git Bash)
```
Data lives in `~/stock-office/backend/data` (JSON/JSONL until PostgreSQL in Sprint 1). Legacy services on this
server were masked on 2026-10-16 (see IMPLEMENTATION_PLAN §13).

## Why not Docker yet
On 1 GB RAM the Docker daemon and image builds (pandas, langchain) cost more than they give, and the server
cannot build images itself. Docker Compose is planned with PostgreSQL (Sprint 1) or a move to a larger Oracle
ARM instance (up to 4 OCPU / 24 GB, free tier).
