#!/usr/bin/env bash
# Redeploy the committed code to the Stock Office server. Run from the repo root (Git Bash).
#   tools/deploy.sh [ssh-host]        (default: stock-office, the ARM server)
# Server .env and data/ are never touched. Avoid running near scheduled analyses
# (≈06:00 and 07:30 KST): restarting the worker aborts a run in progress.
set -euo pipefail
HOST="${1:-stock-office}"

if ! git diff --quiet HEAD -- backend frontend tools; then
  echo "Uncommitted changes in backend/frontend/tools: commit first (only HEAD is deployed)." >&2
  exit 1
fi

echo "== backend code ($(git rev-parse --short HEAD))"
git archive --format=tar HEAD backend tools | ssh "$HOST" 'tar -x -C ~/stock-office'
ssh "$HOST" 'cd ~/stock-office/backend && ~/.local/bin/uv sync --extra engine --extra live --no-dev -q'

echo "== frontend build (standalone, built locally)"
(cd frontend && rm -rf .next/standalone && npx next build >/dev/null)
ssh "$HOST" 'rm -rf ~/stock-office/web.new && mkdir -p ~/stock-office/web.new/.next'
tar -cf - -C frontend/.next/standalone . | ssh "$HOST" 'tar -xf - -C ~/stock-office/web.new'
tar -cf - -C frontend/.next static | ssh "$HOST" 'tar -xf - -C ~/stock-office/web.new/.next'
tar -cf - -C frontend public | ssh "$HOST" 'tar -xf - -C ~/stock-office/web.new'

echo "== switch and restart"
ssh "$HOST" 'cd ~/stock-office && rm -rf web.old && { [ -d web ] && mv web web.old || true; } && mv web.new web &&
  sudo -n systemctl restart stock-office-api stock-office-worker stock-office-web &&
  for i in $(seq 1 30); do curl -s -o /dev/null http://127.0.0.1:8000/health && break; sleep 2; done &&
  curl -s http://127.0.0.1:8000/health && echo &&
  curl -s -o /dev/null -w "web: HTTP %{http_code}\n" http://127.0.0.1:3000/'
echo "Done. Previous UI kept in ~/stock-office/web.old"
