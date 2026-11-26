#!/usr/bin/env python3
"""Step 1: first-run setup (admin) + connect the READ-ONLY synthetic source. Idempotent-ish."""
from common import *; from mbapi import MB
import time, json
mb = MB()
c, props, _ = mb.call("GET", "/api/session/properties", token=None)
if not props.get("has-user-setup"):
    c, d, _ = mb.call("POST", "/api/setup", {
        "token": props["setup-token"],
        "user": {"first_name": "Feasibility", "last_name": "Admin", "email": "admin@feasibility.invalid", "password": ENV["MB_ADMIN_PASSWORD"], "site_name": "InsightFlow Feasibility"},
        "prefs": {"site_name": "InsightFlow Feasibility", "site_locale": "en", "allow_tracking": False}}, token=None)
    print("setup:", c, str(d)[:120])
mb.token = mb.login("admin@feasibility.invalid", ENV["MB_ADMIN_PASSWORD"]); print("admin session ok:", bool(mb.token))
c, dbs, _ = mb.call("GET", "/api/database"); items = dbs["data"] if isinstance(dbs, dict) else dbs
sample = [d for d in items if d.get("is_sample")]
for d in sample: print("delete sample db", d["id"], mb.call("DELETE", f"/api/database/{d['id']}")[0])
if not any(d["name"] == "clientdata_ro" for d in items):
    c, d, _ = mb.call("POST", "/api/database", {"name": "clientdata_ro", "engine": "postgres", "is_full_sync": True,
        "details": {"host": "if-data-pg", "port": 5432, "dbname": "clientdata", "user": "insightflow_ro", "password": ENV["DATA_PG_RO_PASSWORD"], "ssl": False, "schema-filters-type": "all"}})
    print("add db:", c, str(d)[:200])
c, dbs, _ = mb.call("GET", "/api/database"); items = dbs["data"] if isinstance(dbs, dict) else dbs
db = [d for d in items if d["name"] == "clientdata_ro"][0]
print("db id", db["id"], "details exposed to admin API:", json.dumps(db.get("details"))[:200])
for i in range(40):
    c, md, _ = mb.call("GET", f"/api/database/{db['id']}/metadata?include_hidden=true")
    tabs = [t for t in md.get("tables", [])]
    if len(tabs) >= 6: break
    time.sleep(3)
print("synced tables:", sorted(f"{t['schema']}.{t['name']}" for t in tabs))
(ROOT / "evidence" / "mb_state.json").write_text(json.dumps({"db_id": db["id"], "tables": {f"{t['schema']}": t["id"] for t in tabs}}))
