#!/usr/bin/env python3
"""TC-17 on Superset via the portal path: guest token (no session), 7 chart/data queries in parallel. force=True bypasses Redis cache (comparable to Metabase, no caching)."""
from common import *; from ssapi import SS; import bench_lib as B
import json, requests, datetime as dt, sys
admin = SS(); admin.login("admin", ENV["SS_ADMIN_PASSWORD"]); st = json.load(open(ROOT / "evidence/ss_state.json")); emb = json.load(open(ROOT / "evidence/_ss_emb.json"))["emb"]
for sch in ["bench_100k", "bench_500k", "bench_5m"]:
    if sch not in emb: emb[sch] = admin.call("POST", f"/api/v1/dashboard/{st['dashboards'][sch]}/embedded", json={"allowed_domains": []})[1]["result"]["uuid"]
json.dump({"emb": emb}, open(ROOT / "evidence/_ss_emb.json", "w"))
def token(sch): return admin.call("POST", "/api/v1/security/guest_token/", json={"user": {"username": "bench", "first_name": "b", "last_name": "b"}, "resources": [{"type": "dashboard", "id": emb[sch]}], "rls": []})[1]["token"]
METRIC = {k: [k] for k in ["revenue", "gross_profit", "margin", "transactions"]}
def card_calls(sch, force):
    holder = {"tok": token(sch), "t0": time.time()}
    def call_factory(metrics, columns):
        def call(flt):
            if time.time() - holder["t0"] > 240: holder.update(tok=token(sch), t0=time.time())
            filters = []
            if flt:
                end = (dt.date.fromisoformat(flt["to"]) + dt.timedelta(days=1)).isoformat()
                filters = [{"col": "branch", "op": "IN", "val": [flt["branch"]]}, {"col": "date", "op": "TEMPORAL_RANGE", "val": f"{flt['from']} : {end}"}]
            body = {"datasource": {"id": st["datasets"][sch], "type": "table"}, "form_data": {"dashboardId": st["dashboards"][sch]}, "force": force, "result_format": "json", "result_type": "full",
                    "queries": [{"metrics": metrics, "columns": columns, "filters": filters, "row_limit": 1000, "extras": {}, "orderby": []}]}
            try:
                r = requests.post(f"{admin.base}/api/v1/chart/data", json=body, headers={"X-GuestToken": holder["tok"]}, timeout=180); return r.status_code == 200
            except Exception: return False
        return call
    trend = [{"timeGrain": "P1M", "columnType": "BASE_AXIS", "sqlExpression": "date", "label": "date", "expressionType": "SQL"}]
    return [call_factory(["revenue"], []), call_factory(["gross_profit"], []), call_factory(["margin"], []), call_factory(["transactions"], []),
            call_factory(["revenue"], trend), call_factory(["revenue"], ["branch"]), call_factory(["revenue", "gross_profit", "margin", "transactions"], ["branch"])]
import time
out = {"engine": "superset 6.1.0 (gunicorn 4 workers x 8 threads, Redis cache)", "environment": B.env_info(), "results": {}}
for sch in ["bench_100k", "bench_500k", "bench_1m", "bench_5m"]:
    cc = card_calls(sch, True); r = {}
    t, ok = B.dash_load(cc); r["first_load_ms (cache bypassed)"] = round(t)
    r["initial_dashboard_unfiltered (cache bypassed)"] = B.series(cc, 15, False)
    r["filter_change_branch+month (cache bypassed)"] = B.series(cc, 15, True)
    if sch in ("bench_1m", "bench_5m"): r["concurrency_20_users_x3_loads_filtered (cache bypassed)"] = B.concurrent(cc, 20, 3)
    if sch in ("bench_1m", "bench_5m"):
        cw = card_calls(sch, False); B.dash_load(cw); B.series(cw, 15, True, seed=1)   # prime cache
        r["WARM CACHE initial_dashboard_unfiltered"] = B.series(cw, 15, False)
        r["WARM CACHE filter_change (same filter sequence as primed)"] = B.series(cw, 15, True, seed=1)
    out["results"][sch] = r; print(sch, json.dumps(r), flush=True)
    (EVID / "superset_benchmark.json").write_text(json.dumps(out, indent=1))
