#!/usr/bin/env bash
# Start (or restart) the mini portal on http://127.0.0.1:9000 . Needs: portal/.venv, ../.env, Superset + Keycloak + data DB running.
cd "$(dirname "$0")"; pkill -f "uvicorn app:app" 2>/dev/null; sleep 1
mkdir -p data; nohup .venv/bin/uvicorn app:app --host 127.0.0.1 --port 9000 > data/portal.log 2>&1 &
for i in $(seq 1 20); do curl -s -o /dev/null http://127.0.0.1:9000/healthz && { echo "portal up: http://127.0.0.1:9000"; exit 0; }; sleep 0.5; done; echo "portal failed to start - see portal/data/portal.log"; exit 1
