#!/usr/bin/env bash
# Reset the mini demo to its starting state: live data = first 20,000 synthetic rows, portal DB re-seeded (users, assignments, history), portal restarted.
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/p2_01_db.sh >/dev/null
rm -f portal/data/portal.db portal/data/portal.db-wal portal/data/portal.db-shm
(cd portal && .venv/bin/python seed.py >/dev/null)
(cd scripts && python3 - <<'PY'
from common import *; from ssapi import SS
import json
ss = SS(); ss.login("admin", ENV["SS_ADMIN_PASSWORD"]); ds = json.load(open(ROOT / "evidence/p2_state.json"))["reports"]["sales-live"]["dataset_id"]
ss.call("PUT", f"/api/v1/dataset/{ds}", json={"cache_timeout": 60}); ss.call("POST", "/api/v1/cachekey/invalidate", json={"datasource_uids": [f"{ds}__table"]})
PY
)
# clear identity-provider brute-force lockouts left by earlier test runs (Keycloak admin API)
set -a; . ./.env; set +a
TOK=$(curl -s -d "client_id=admin-cli&username=kcadmin&password=$KC_ADMIN_PASSWORD&grant_type=password" http://127.0.0.1:8180/realms/master/protocol/openid-connect/token | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s -o /dev/null -w "keycloak lockouts cleared: HTTP %{http_code}\n" -X DELETE -H "Authorization: Bearer $TOK" http://127.0.0.1:8180/admin/realms/insightflow/attack-detection/brute-force/users
./portal/run.sh
