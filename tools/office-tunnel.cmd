@echo off
rem Opens a private SSH tunnel to the Stock Office server, then the office in the browser.
rem Nothing on the server is public: the UI (3000) and API (8000) listen on 127.0.0.1 only.
rem Close this window to disconnect.
echo Connecting to quant-worker (Ctrl+C or close the window to stop)...
start "" http://localhost:3000
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 3000:127.0.0.1:3000 -L 8000:127.0.0.1:8000 quant-worker
