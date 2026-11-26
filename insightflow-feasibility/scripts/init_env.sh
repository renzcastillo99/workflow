#!/usr/bin/env bash
# Generates a LOCAL, GITIGNORED .env with random synthetic-environment secrets.
# No credential is ever stored in source control. Re-running keeps existing values.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { echo ".env already exists - keeping it"; exit 0; }
r() { openssl rand -hex 16; }
cat > .env <<ENV
DATA_PG_ADMIN_PASSWORD=$(r)
DATA_PG_RO_PASSWORD=$(r)
MB_DB_PASSWORD=$(r)
MB_ADMIN_PASSWORD=Aa1-$(r)
MB_VIEWER_PASSWORD=Aa1-$(r)
MB_EMBED_SECRET=$(openssl rand -hex 32)
SS_DB_PASSWORD=$(r)
SS_ADMIN_PASSWORD=Aa1-$(r)
SS_VIEWER_PASSWORD=Aa1-$(r)
SUPERSET_SECRET_KEY=$(openssl rand -base64 42)
SS_GUEST_TOKEN_SECRET=$(openssl rand -hex 32)
ENV
chmod 600 .env
echo "created .env (gitignored, mode 600)"
