#!/usr/bin/env bash
# Phase 2 mini: append any MISSING secrets to the local gitignored .env (never committed).
set -euo pipefail
cd "$(dirname "$0")/.."
touch .env; chmod 600 .env
add() { grep -q "^$1=" .env || echo "$1=$2" >> .env; }
add INGEST_PW "$(openssl rand -hex 16)"
add KC_ADMIN_PASSWORD "Aa1-$(openssl rand -hex 10)"
add KC_CLIENT_SECRET "$(openssl rand -hex 24)"
add PORTAL_SESSION_SECRET "$(openssl rand -hex 32)"
add SVC_PASSWORD "Aa1-$(openssl rand -hex 12)"
add DEMO_PASSWORD "Demo-$(openssl rand -hex 6)-x9"
echo ".env updated"
