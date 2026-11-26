#!/usr/bin/env bash
# Build the Superset image, initialise metadata DB, create the admin, sync roles, start web. Requires: docker network 'ifnet', .env from init_env.sh
set -euo pipefail
cd "$(dirname "$0")/../docker"; set -a; . ../.env; set +a
# Superset image needs a Postgres driver + OIDC lib that the official image lacks. Fetch the wheels on a fresh clone (docker/wheels is gitignored).
if [ -z "$(ls wheels 2>/dev/null)" ]; then
  mkdir -p wheels
  "${PY:-python3}" -m pip download psycopg2-binary authlib joserfc --python-version 3.10 --platform manylinux2014_x86_64 --only-binary=:all: --no-deps -d wheels
fi
docker compose -f superset.compose.yml build
docker compose -f superset.compose.yml up -d ss-pg ss-redis; sleep 8
docker compose -f superset.compose.yml run --rm -e SS_ADMIN_PASSWORD="$SS_ADMIN_PASSWORD" --entrypoint "" superset sh -c \
 'superset db upgrade && superset fab create-admin --username admin --firstname Feasibility --lastname Admin --email admin@feasibility.invalid --password "$SS_ADMIN_PASSWORD" && superset init'
SS_PORTAL_ORIGINS="${SS_PORTAL_ORIGINS:-http://127.0.0.1:9000}" docker compose -f superset.compose.yml up -d superset
echo "waiting for Superset to answer..."
for i in $(seq 1 60); do [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8088/health)" = 200 ] && { echo "Superset is up: http://127.0.0.1:8088"; exit 0; }; sleep 4; done
echo "Superset did not come up in 4 minutes: docker logs if-superset"; exit 1
