#!/usr/bin/env bash
# Build the Superset image, initialise metadata DB, create the admin, sync roles, start web. Requires: docker network 'ifnet', .env from init_env.sh
set -euo pipefail
cd "$(dirname "$0")/../docker"; set -a; . ../.env; set +a
docker compose -f superset.compose.yml build
docker compose -f superset.compose.yml up -d ss-pg ss-redis; sleep 8
docker compose -f superset.compose.yml run --rm -e SS_ADMIN_PASSWORD="$SS_ADMIN_PASSWORD" --entrypoint "" superset sh -c \
 'superset db upgrade && superset fab create-admin --username admin --firstname Feasibility --lastname Admin --email admin@feasibility.invalid --password "$SS_ADMIN_PASSWORD" && superset init'
SS_PORTAL_ORIGINS="${SS_PORTAL_ORIGINS:-http://127.0.0.1:9000}" docker compose -f superset.compose.yml up -d superset
