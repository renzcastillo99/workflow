#!/usr/bin/env python3
"""TC-17 on Metabase via the portal path: signed static-embed token, no session, 7 parallel card queries."""
from common import *; from mbapi import MB; import bench_lib as B
import json, hmac, hashlib, base64, time, urllib.request, urllib.error
admin = MB(); admin.token = admin.login("admin@feasibility.invalid", ENV["MB_ADMIN_PASSWORD"]); st = json.load(open(ROOT / "evidence/mb_state.json"))
b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def jwt(p):
    h = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()); pl = b64(json.dumps(p).encode())
    return f"{h}.{pl}." + b64(hmac.new(ENV["MB_EMBED_SECRET"].encode(), f"{h}.{pl}".encode(), hashlib.sha256).digest())
def card_calls(schema):
    s = st["content"][schema]; admin.call("PUT", f"/api/dashboard/{s['dashboard']}", {"enable_embedding": True, "embedding_params": {"date": "enabled", "branch": "enabled"}})
    tok = jwt({"resource": {"dashboard": s["dashboard"]}, "params": {}, "exp": int(time.time()) + 3000})
    def mk(k):
        def call(flt):
            qs = "" if not flt else f"?branch={urllib.request.quote(flt['branch'])}&date={flt['from']}~{flt['to']}"
            try:
                with urllib.request.urlopen(f"{admin.base}/api/embed/dashboard/{tok}/dashcard/{s['dashcards'][k]}/card/{s['cards'][k]}{qs}", timeout=120) as r: r.read(); return r.status in (200, 202)
            except Exception: return False
        return call
    return [mk(k) for k in ["Revenue", "Gross profit", "Margin", "Transactions", "Trend", "Branch", "Table"]]
out = {"engine": "metabase " + "v0.65.7.2 OSS", "environment": B.env_info(), "results": {}}
for schema in ["bench_100k", "bench_500k", "bench_1m", "bench_5m"]:
    cc = card_calls(schema); r = {}
    t, ok = B.dash_load(cc); r["first_load_ms (cold-ish: first touch since benchmark start)"] = round(t); 
    r["initial_dashboard_unfiltered"] = B.series(cc, 15, False)
    r["filter_change_branch+month"] = B.series(cc, 15, True)
    if schema in ("bench_1m", "bench_5m"): r["concurrency_20_users_x3_loads_filtered"] = B.concurrent(cc, 20, 3)
    out["results"][schema] = r; print(schema, json.dumps(r)); 
(EVID / "metabase_benchmark.json").write_text(json.dumps(out, indent=1))
